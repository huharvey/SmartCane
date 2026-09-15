from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .features import FEATURE_NAMES, MIN_IBI_COUNT, feature_vector, quantize_features
from .model import Q_COLUMNS, QuantizedModel


WINDOW_MS = 15_000
MIN_SIGNAL_QUALITY = 0.70
MIN_MODEL_CONFIDENCE = 0.60
ALERT_CONSECUTIVE_WINDOWS = 3


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def _trial_id(path: Path, frame: pd.DataFrame) -> str:
    if "trial_id" in frame and frame["trial_id"].notna().any():
        return str(frame.loc[frame["trial_id"].notna(), "trial_id"].iloc[0])
    match = re.search(r"(P\d{3})", path.name, flags=re.IGNORECASE)
    return match.group(1).upper() if match else path.stem


def _inference_endpoints(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the first row of each real firmware inference counter value."""
    if "rhythm_inference_count" not in frame:
        return pd.DataFrame()
    count = pd.to_numeric(frame["rhythm_inference_count"], errors="coerce").fillna(0)
    changed = count.ne(count.shift(fill_value=count.iloc[0])) & count.gt(0)
    return frame.loc[changed].copy()


def replay_file(path: Path, model: QuantizedModel) -> tuple[list[dict], dict]:
    required = {
        "t_ms",
        "beat_accepted",
        "ibi_ms",
        "sqi",
        "hr_bpm",
        "finger",
        "rhythm_inference_count",
    }
    frame = pd.read_csv(path, low_memory=False)
    if not required.issubset(frame.columns):
        return [], {
            "file": str(path),
            "trial_id": _trial_id(path, frame),
            "status": "SKIPPED_SCHEMA",
            "inference_count": 0,
            "af_like_windows": 0,
            "suspected_af_windows": 0,
        }

    trial_id = _trial_id(path, frame)
    label = str(frame["label"].dropna().iloc[0]) if "label" in frame and frame["label"].notna().any() else ""
    expected = (
        str(frame["expected_state"].dropna().iloc[0])
        if "expected_state" in frame and frame["expected_state"].notna().any()
        else ""
    )
    frame["t_ms"] = pd.to_numeric(frame["t_ms"], errors="coerce")
    frame["ibi_ms"] = pd.to_numeric(frame["ibi_ms"], errors="coerce")
    frame["sqi"] = pd.to_numeric(frame["sqi"], errors="coerce")
    frame["hr_bpm"] = pd.to_numeric(frame["hr_bpm"], errors="coerce")
    frame["beat_accepted"] = _as_bool(frame["beat_accepted"])
    frame["finger"] = _as_bool(frame["finger"])
    endpoints = _inference_endpoints(frame)

    rows: list[dict] = []
    consecutive_af = 0
    for _, endpoint in endpoints.iterrows():
        end_ms = float(endpoint["t_ms"])
        beats = frame.loc[
            frame["beat_accepted"]
            & frame["ibi_ms"].notna()
            & frame["t_ms"].gt(end_ms - WINDOW_MS)
            & frame["t_ms"].le(end_ms),
            "ibi_ms",
        ].to_numpy(dtype=np.float64)
        sqi = float(endpoint["sqi"]) if np.isfinite(endpoint["sqi"]) else 0.0
        finger = bool(endpoint["finger"])
        gate_passed = finger and sqi >= MIN_SIGNAL_QUALITY and beats.size >= MIN_IBI_COUNT
        probability = np.nan
        raw_af = False
        state = "INCONCLUSIVE"
        q = np.zeros(6, dtype=np.uint8)

        if gate_passed:
            values = feature_vector(beats, signal_quality=sqi)
            q = quantize_features(values)
            probability = float(model.probabilities_from_q(q.reshape(1, -1))[0])
            predicted_af = probability >= model.af_threshold
            confidence = probability if predicted_af else 1.0 - probability
            if confidence < MIN_MODEL_CONFIDENCE:
                consecutive_af = 0
                state = "INCONCLUSIVE"
            elif predicted_af:
                raw_af = True
                consecutive_af += 1
                state = (
                    "SUSPECTED_AF"
                    if consecutive_af >= ALERT_CONSECUTIVE_WINDOWS
                    else "IRREGULAR"
                )
            else:
                consecutive_af = 0
                state = "NORMAL"
        else:
            consecutive_af = 0

        row = {
            "file": str(path),
            "trial_id": trial_id,
            "label": label,
            "expected_state": expected,
            "t_ms": int(end_ms),
            "beat_count": int(beats.size),
            "sqi": sqi,
            "gate_passed": bool(gate_passed),
            "probability_af": probability,
            "raw_af_like": bool(raw_af),
            "replayed_state": state,
        }
        row.update({column: int(value) for column, value in zip(Q_COLUMNS, q)})
        rows.append(row)

    summary = {
        "file": str(path),
        "trial_id": trial_id,
        "label": label,
        "expected_state": expected,
        "status": "REPLAYED" if rows else "NO_FIRMWARE_INFERENCE",
        "inference_count": len(rows),
        "gated_inference_count": sum(bool(row["gate_passed"]) for row in rows),
        "af_like_windows": sum(bool(row["raw_af_like"]) for row in rows),
        "suspected_af_windows": sum(row["replayed_state"] == "SUSPECTED_AF" for row in rows),
    }
    return rows, summary


def replay_capture_directory(
    capture_directory: Path, model: QuantizedModel
) -> tuple[pd.DataFrame, dict]:
    capture_directory = Path(capture_directory)
    files = sorted(
        path
        for path in capture_directory.rglob("*.csv")
        if path.name.lower() != "trials.csv"
    )
    if not files:
        raise FileNotFoundError(f"no capture CSV files below {capture_directory}")

    rows: list[dict] = []
    file_summaries: list[dict] = []
    for position, path in enumerate(files, start=1):
        print(f"[local replay] {position}/{len(files)} {path.name}", flush=True)
        file_rows, summary = replay_file(path, model)
        rows.extend(file_rows)
        file_summaries.append(summary)

    replay = pd.DataFrame(rows)
    serious_alerts = sum(item["suspected_af_windows"] for item in file_summaries)
    summary = {
        "capture_directory": str(capture_directory.resolve()),
        "file_count": len(files),
        "replayed_file_count": sum(item["status"] == "REPLAYED" for item in file_summaries),
        "inference_count": sum(item["inference_count"] for item in file_summaries),
        "gated_inference_count": sum(
            item.get("gated_inference_count", 0) for item in file_summaries
        ),
        "af_like_windows": sum(item["af_like_windows"] for item in file_summaries),
        "suspected_af_windows": serious_alerts,
        "passed_no_new_serious_alerts": serious_alerts == 0,
        "files": file_summaries,
        "interpretation": (
            "These captures are normal/artifact regression data, not ECG-labelled AF test data."
        ),
    }
    return replay, summary
