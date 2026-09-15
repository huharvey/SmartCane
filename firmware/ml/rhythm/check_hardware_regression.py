from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


EXPECTED_MODEL_BYTES = 18


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the final 2-3 SmartCane normal/still PPG captures."
    )
    parser.add_argument("--captures", required=True, type=Path)
    parser.add_argument("--trials", nargs="+", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/latest/HARDWARE_RESULT.md")
    )
    return parser.parse_args()


def _trial_id(path: Path, frame: pd.DataFrame) -> str:
    if "trial_id" in frame and frame["trial_id"].notna().any():
        return str(frame.loc[frame["trial_id"].notna(), "trial_id"].iloc[0]).upper()
    match = re.search(r"(P\d{3})", path.name, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _inference_rows(frame: pd.DataFrame) -> pd.DataFrame:
    count = pd.to_numeric(frame["rhythm_inference_count"], errors="coerce").fillna(0)
    changed = count.ne(count.shift(fill_value=count.iloc[0])) & count.gt(0)
    return frame.loc[changed].copy()


def main() -> int:
    args = parse_args()
    requested = {item.upper() for item in args.trials}
    files = [
        path
        for path in args.captures.rglob("*.csv")
        if path.name.lower() != "trials.csv"
    ]
    found: dict[str, tuple[Path, pd.DataFrame]] = {}
    for path in files:
        frame = pd.read_csv(path, low_memory=False)
        trial_id = _trial_id(path, frame)
        if trial_id in requested:
            found[trial_id] = (path, frame)

    summaries: list[dict] = []
    all_times: list[float] = []
    for trial_id in sorted(requested):
        if trial_id not in found:
            summaries.append({"trial_id": trial_id, "passed": False, "reason": "未找到 CSV"})
            continue
        path, frame = found[trial_id]
        required = {
            "t_ms",
            "rhythm_state",
            "rhythm_inference_us",
            "rhythm_inference_count",
            "rhythm_model_bytes",
        }
        if not required.issubset(frame.columns):
            summaries.append({"trial_id": trial_id, "passed": False, "reason": "CSV 字段不完整"})
            continue
        time_ms = pd.to_numeric(frame["t_ms"], errors="coerce").dropna()
        duration_s = float((time_ms.max() - time_ms.min()) / 1000.0)
        inferences = _inference_rows(frame)
        inference_us = pd.to_numeric(
            inferences["rhythm_inference_us"], errors="coerce"
        ).dropna()
        model_bytes = set(
            pd.to_numeric(inferences["rhythm_model_bytes"], errors="coerce")
            .dropna()
            .astype(int)
        )
        states = inferences["rhythm_state"].fillna("").astype(str).str.upper().tolist()
        final_state = states[-1] if states else "NO_INFERENCE"
        reasons: list[str] = []
        if duration_s < 30.0:
            reasons.append("记录短于30秒")
        if len(inferences) < 3:
            reasons.append("有效推理少于3次")
        if "SUSPECTED_AF" in states:
            reasons.append("出现SUSPECTED_AF")
        if final_state != "NORMAL":
            reasons.append(f"最终状态为{final_state}")
        if model_bytes != {EXPECTED_MODEL_BYTES}:
            reasons.append(f"模型字节数为{sorted(model_bytes)}，应为{EXPECTED_MODEL_BYTES}")
        all_times.extend(float(value) for value in inference_us)
        summaries.append(
            {
                "trial_id": trial_id,
                "file": str(path.resolve()),
                "duration_s": duration_s,
                "inference_count": int(len(inferences)),
                "final_state": final_state,
                "suspected_af_count": states.count("SUSPECTED_AF"),
                "model_bytes": sorted(model_bytes),
                "passed": not reasons,
                "reason": "；".join(reasons) if reasons else "通过",
            }
        )

    passed = len(summaries) >= 2 and all(item["passed"] for item in summaries)
    performance = None
    if all_times:
        values = np.asarray(all_times, dtype=np.float64)
        performance = {
            "samples": int(values.size),
            "mean_us": float(values.mean()),
            "p95_us": float(np.percentile(values, 95)),
            "max_us": float(values.max()),
        }

    lines = [
        "# 候选节律模型实物短程回归结果",
        "",
        f"总体结论：**{'通过' if passed else '未通过'}**",
        "",
        "| 试验 | 时长(s) | 推理次数 | 最终状态 | SUSPECTED_AF | 模型字节 | 结论 |",
        "|---|---:|---:|---|---:|---|---|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['trial_id']} | {item.get('duration_s', 0):.1f} | "
            f"{item.get('inference_count', 0)} | {item.get('final_state', '—')} | "
            f"{item.get('suspected_af_count', 0)} | {item.get('model_bytes', '—')} | "
            f"{item['reason']} |"
        )
    lines.extend(["", "## 推理耗时", ""])
    if performance:
        lines.append(
            f"样本 {performance['samples']} 次，平均 {performance['mean_us']:.1f} μs，"
            f"P95 {performance['p95_us']:.1f} μs，最大 {performance['max_us']:.1f} μs。"
        )
    else:
        lines.append("没有可统计的推理耗时。")
    lines.extend(
        [
            "",
            "## 是否修改标定开关",
            "",
            (
                "本次满足短程课程验收条件，可以人工复核 CSV 后将 "
                "`RHYTHM_MODEL_CALIBRATED` 改为 `true`。"
                if passed
                else "不要修改 `RHYTHM_MODEL_CALIBRATED`，先按失败原因重新采集或排查。"
            ),
            "",
            "> 通过也只代表课程原型验证，不代表医疗器械认证或房颤诊断能力。",
            "",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    json_path = args.output.with_suffix(".json")
    json_path.write_text(
        json.dumps(
            {"passed": passed, "trials": summaries, "performance": performance},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"hardware regression: {'PASS' if passed else 'FAIL'}")
    print(args.output.resolve())
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
