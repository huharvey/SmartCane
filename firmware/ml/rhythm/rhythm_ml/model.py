from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, roc_auc_score

from .features import FEATURE_NAMES


Q_COLUMNS = tuple(f"q_{name}" for name in FEATURE_NAMES)
# SQI is kept as a firmware gate. Public bedside PPG and MAX30102 use different
# amplitude units, so fitting an SQI coefficient would learn a sensor mismatch.
MODEL_FEATURE_INDICES = (0, 1, 2, 3, 5)
MODEL_FEATURE_NAMES = tuple(FEATURE_NAMES[index] for index in MODEL_FEATURE_INDICES)


@dataclass(frozen=True)
class QuantizedModel:
    weights: np.ndarray
    bias: int
    score_scale: float
    af_threshold: float

    def probabilities_from_q(self, q_values: np.ndarray) -> np.ndarray:
        q = np.asarray(q_values, dtype=np.int32)
        logits = (q @ self.weights.astype(np.int32) + int(self.bias)) / float(
            self.score_scale
        )
        logits = np.clip(logits, -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-logits))


def stratified_subject_split(frame: pd.DataFrame, seed: int = 2026) -> dict[str, list[str]]:
    rng = np.random.default_rng(seed)
    split = {"train": [], "validation": [], "test": []}
    subject_labels = frame[["subject_id", "label"]].drop_duplicates()
    if subject_labels.groupby("subject_id")["label"].nunique().max() != 1:
        raise ValueError("a subject has more than one label")
    for label in (0, 1):
        subjects = sorted(subject_labels.loc[subject_labels["label"] == label, "subject_id"])
        if len(subjects) < 5:
            raise ValueError(f"label {label} has too few usable subjects: {len(subjects)}")
        rng.shuffle(subjects)
        test_count = max(1, int(round(len(subjects) * 0.20)))
        validation_count = max(1, int(round(len(subjects) * 0.20)))
        split["test"].extend(subjects[:test_count])
        split["validation"].extend(
            subjects[test_count : test_count + validation_count]
        )
        split["train"].extend(subjects[test_count + validation_count :])
    for key in split:
        split[key] = sorted(split[key])
    all_subjects = [subject for values in split.values() for subject in values]
    if len(all_subjects) != len(set(all_subjects)):
        raise AssertionError("subject leakage detected in split")
    return split


def _subset(frame: pd.DataFrame, subjects: Iterable[str]) -> pd.DataFrame:
    return frame[frame["subject_id"].isin(set(subjects))].copy()


def _xy(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    q = frame.loc[:, Q_COLUMNS].to_numpy(dtype=np.float64)
    x = q[:, MODEL_FEATURE_INDICES] / 127.0
    y = frame["label"].to_numpy(dtype=np.int8)
    return x, y


def _subject_balanced_weights(frame: pd.DataFrame) -> np.ndarray:
    counts = frame.groupby("subject_id")["subject_id"].transform("count").to_numpy()
    weights = 1.0 / counts.astype(np.float64)
    return weights / np.mean(weights)


def binary_metrics(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict:
    y = np.asarray(labels, dtype=np.int8)
    p = np.asarray(probabilities, dtype=np.float64)
    prediction = (p >= threshold).astype(np.int8)
    tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
    sensitivity = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = (
        2.0 * precision * sensitivity / (precision + sensitivity)
        if precision + sensitivity
        else 0.0
    )
    accuracy = (tp + tn) / max(1, tp + tn + fp + fn)
    balanced = 0.5 * (sensitivity + specificity)
    normal_precision = tn / (tn + fn) if tn + fn else 0.0
    normal_f1 = (
        2.0 * normal_precision * specificity / (normal_precision + specificity)
        if normal_precision + specificity
        else 0.0
    )
    auc = float(roc_auc_score(y, p)) if np.unique(y).size == 2 else None
    return {
        "threshold": float(threshold),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
        "accuracy": float(accuracy),
        "sensitivity": float(sensitivity),
        "specificity": float(specificity),
        "precision": float(precision),
        "f1": float(f1),
        "normal_precision": float(normal_precision),
        "normal_recall": float(specificity),
        "normal_f1": float(normal_f1),
        "macro_f1": float(0.5 * (f1 + normal_f1)),
        "balanced_accuracy": float(balanced),
        "roc_auc": auc,
    }


def subject_metrics(frame: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> dict:
    scored = frame[["subject_id", "label"]].copy()
    scored["probability_af"] = probabilities
    subjects = (
        scored.groupby("subject_id", as_index=False)
        .agg(label=("label", "first"), probability_af=("probability_af", "median"))
        .sort_values("subject_id")
    )
    result = binary_metrics(
        subjects["label"].to_numpy(),
        subjects["probability_af"].to_numpy(),
        threshold,
    )
    result["subject_count"] = int(len(subjects))
    return result


def consensus_subject_metrics(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
    consecutive_windows: int = 3,
) -> dict:
    """Evaluate the same repeated-window alert rule used by the firmware."""
    scored = frame[["subject_id", "label", "window_end_s"]].copy()
    scored["probability_af"] = probabilities
    subject_rows: list[dict] = []
    non_af_hours = 0.0
    false_alert_episodes = 0
    for subject_id, group in scored.sort_values(
        ["subject_id", "window_end_s"]
    ).groupby("subject_id", sort=True):
        run = 0
        maximum_run = 0
        first_alert_at_s = None
        alert_episodes = 0
        for row in group.itertuples(index=False):
            if float(row.probability_af) >= threshold:
                run += 1
                maximum_run = max(maximum_run, run)
                if run >= consecutive_windows and first_alert_at_s is None:
                    first_alert_at_s = float(row.window_end_s)
                if run == consecutive_windows:
                    alert_episodes += 1
            else:
                run = 0
        subject_rows.append(
            {
                "subject_id": subject_id,
                "label": int(group["label"].iloc[0]),
                "predicted_af": int(maximum_run >= consecutive_windows),
                "maximum_consecutive_af_windows": int(maximum_run),
                "first_alert_at_s": first_alert_at_s,
                "alert_episodes": int(alert_episodes),
            }
        )
        if int(group["label"].iloc[0]) == 0:
            non_af_hours += float(group["window_end_s"].max()) / 3600.0
            false_alert_episodes += alert_episodes
    subjects = pd.DataFrame(subject_rows)
    result = binary_metrics(
        subjects["label"].to_numpy(),
        subjects["predicted_af"].to_numpy(dtype=np.float64),
        0.5,
    )
    result["threshold"] = float(threshold)
    result["consecutive_windows"] = int(consecutive_windows)
    result["subject_count"] = int(len(subjects))
    result["subjects"] = subject_rows
    result["false_alert_episodes"] = int(false_alert_episodes)
    result["non_af_hours"] = float(non_af_hours)
    result["false_alerts_per_hour"] = (
        float(false_alert_episodes / non_af_hours) if non_af_hours > 0.0 else None
    )
    return result


def _fit(frame: pd.DataFrame, regularization_c: float, seed: int) -> LogisticRegression:
    x, y = _xy(frame)
    model = LogisticRegression(
        C=regularization_c,
        class_weight="balanced",
        max_iter=5000,
        random_state=seed,
        solver="liblinear",
    )
    model.fit(x, y, sample_weight=_subject_balanced_weights(frame))
    return model


def _select_model(
    train: pd.DataFrame, validation: pd.DataFrame, seed: int
) -> tuple[float, float, list[dict]]:
    candidates: list[dict] = []
    for regularization_c in (0.01, 0.1, 1.0, 10.0, 100.0):
        model = _fit(train, regularization_c, seed)
        x_validation, y_validation = _xy(validation)
        probabilities = model.predict_proba(x_validation)[:, 1]
        # Firmware regards confidence below 0.60 as inconclusive.  Keeping the
        # AF threshold at or above that value prevents a low-probability AF
        # decision from being immediately discarded by the runtime gate.
        for threshold in np.arange(0.60, 0.851, 0.025):
            windows = binary_metrics(y_validation, probabilities, float(threshold))
            subjects = subject_metrics(validation, probabilities, float(threshold))
            consensus = consensus_subject_metrics(
                validation, probabilities, float(threshold)
            )
            candidates.append(
                {
                    "regularization_c": regularization_c,
                    "threshold": float(threshold),
                    "window": windows,
                    "subject": subjects,
                    "consensus_subject": consensus,
                }
            )
    candidates.sort(
        key=lambda item: (
            item["consensus_subject"]["balanced_accuracy"],
            item["consensus_subject"]["sensitivity"],
            item["consensus_subject"]["specificity"],
            # When event-level performance is tied, prefer the more
            # conservative threshold.  It reduces sustained false alarms
            # without sacrificing any validation-subject detections.
            item["threshold"],
            item["subject"]["balanced_accuracy"],
            item["window"]["balanced_accuracy"],
        ),
        reverse=True,
    )
    best = candidates[0]
    return (
        float(best["regularization_c"]),
        float(best["threshold"]),
        candidates,
    )


def quantize_logistic_model(
    model: LogisticRegression, af_threshold: float
) -> QuantizedModel:
    coefficients = np.zeros(6, dtype=np.float64)
    coefficients[list(MODEL_FEATURE_INDICES)] = model.coef_[0]
    max_coefficient = max(1e-9, float(np.max(np.abs(coefficients))))
    score_scale = min(8192.0, math.floor(0.98 * 127.0 * 127.0 / max_coefficient))
    score_scale = max(128.0, score_scale)
    weights = np.rint(coefficients * score_scale / 127.0).astype(np.int32)
    if np.max(np.abs(weights)) > 127:
        raise ValueError("INT8 weight overflow")
    bias = int(round(float(model.intercept_[0]) * score_scale))
    return QuantizedModel(
        weights=weights.astype(np.int8),
        bias=bias,
        score_scale=float(score_scale),
        af_threshold=float(af_threshold),
    )


def _split_summary(frame: pd.DataFrame, split: dict[str, list[str]]) -> dict:
    summary = {}
    for name, subjects in split.items():
        subset = _subset(frame, subjects)
        summary[name] = {
            "subjects": subjects,
            "subject_count": len(subjects),
            "window_count": int(len(subset)),
            "af_subjects": int(subset.loc[subset["label"] == 1, "subject_id"].nunique()),
            "normal_subjects": int(
                subset.loc[subset["label"] == 0, "subject_id"].nunique()
            ),
        }
    return summary


def train_and_evaluate(frame: pd.DataFrame, seed: int = 2026) -> tuple[QuantizedModel, dict, pd.DataFrame]:
    split = stratified_subject_split(frame, seed)
    train = _subset(frame, split["train"])
    validation = _subset(frame, split["validation"])
    test = _subset(frame, split["test"])
    regularization_c, threshold, candidates = _select_model(train, validation, seed)

    development = pd.concat([train, validation], ignore_index=True)
    float_model = _fit(development, regularization_c, seed)
    quantized = quantize_logistic_model(float_model, threshold)

    predictions = test[["subject_id", "label", "window_end_s"]].copy()
    x_test, y_test = _xy(test)
    q_test = test.loc[:, Q_COLUMNS].to_numpy(dtype=np.uint8)
    float_probability = float_model.predict_proba(x_test)[:, 1]
    quantized_probability = quantized.probabilities_from_q(q_test)
    predictions["float_probability_af"] = float_probability
    predictions["int8_probability_af"] = quantized_probability
    predictions["float_prediction"] = (float_probability >= threshold).astype(np.int8)
    predictions["int8_prediction"] = (quantized_probability >= threshold).astype(np.int8)
    agreement = float(
        np.mean(predictions["float_prediction"] == predictions["int8_prediction"])
    )

    metrics = {
        "model_kind": "subject-independent binary logistic regression",
        "class_mapping": {"0": "NORMAL", "1": "AF"},
        "feature_names": list(FEATURE_NAMES),
        "fitted_feature_names": list(MODEL_FEATURE_NAMES),
        "sqi_policy": "firmware gate only; exported SQI coefficient is zero",
        "seed": seed,
        "split": _split_summary(frame, split),
        "selection": {
            "regularization_c": regularization_c,
            "af_threshold": threshold,
            "best_validation_window": candidates[0]["window"],
            "best_validation_subject": candidates[0]["subject"],
            "best_validation_consensus_subject": candidates[0]["consensus_subject"],
        },
        "float_test": {
            "window": binary_metrics(y_test, float_probability, threshold),
            "subject": subject_metrics(test, float_probability, threshold),
        },
        "int8_test": {
            "window": binary_metrics(y_test, quantized_probability, threshold),
            "subject": subject_metrics(test, quantized_probability, threshold),
            "consensus_subject": consensus_subject_metrics(
                test, quantized_probability, threshold
            ),
            "prediction_agreement_with_float": agreement,
            "maximum_probability_error": float(
                np.max(np.abs(float_probability - quantized_probability))
            ),
        },
        "quantization": {
            "weights": [int(value) for value in quantized.weights],
            "bias": quantized.bias,
            "score_scale": quantized.score_scale,
            "af_threshold": quantized.af_threshold,
        },
    }
    subject_test = metrics["int8_test"]["consensus_subject"]
    metrics["course_acceptance"] = {
        "criteria": {
            "subject_sensitivity_min": 0.80,
            "subject_specificity_min": 0.75,
            "subject_balanced_accuracy_min": 0.78,
            "float_int8_agreement_min": 0.99,
            "false_alerts_per_non_af_hour_max": 0.5,
        },
        "passed_public_test": bool(
            subject_test["sensitivity"] >= 0.80
            and subject_test["specificity"] >= 0.75
            and subject_test["balanced_accuracy"] >= 0.78
            and agreement >= 0.99
            and subject_test["false_alerts_per_hour"] is not None
            and subject_test["false_alerts_per_hour"] <= 0.5
        ),
        "medical_claim_allowed": False,
    }
    return quantized, metrics, predictions


def write_model_header(model: QuantizedModel, output: Path) -> None:
    weights = ", ".join(str(int(value)) for value in model.weights)
    content = f"""#pragma once

// Generated by ml/rhythm/run_training.py from subject-independent,
// ECG-referenced MIMIC PERform AF data. Do not edit by hand.
namespace RhythmModel {{
constexpr unsigned int MODEL_VERSION = 1;
constexpr unsigned int FEATURE_COUNT = 6;
// Input order: IBI CV, RMSSD/mean IBI, pNN50, max IBI jump/mean,
// signal quality (gate only, zero weight), heart-rate out-of-range score.
constexpr signed char WEIGHTS[FEATURE_COUNT] = {{{weights}}};
constexpr int BIAS = {model.bias};
constexpr float SCORE_SCALE = {model.score_scale:.1f}f;
constexpr float AF_THRESHOLD = {model.af_threshold:.6f}f;
constexpr unsigned int MODEL_BYTES = sizeof(WEIGHTS) + sizeof(BIAS) +
                                     sizeof(SCORE_SCALE) + sizeof(AF_THRESHOLD);
}}  // namespace RhythmModel
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def save_metrics(metrics: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
