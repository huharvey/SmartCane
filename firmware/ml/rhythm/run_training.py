from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from rhythm_ml.dataset import load_or_build_public_features
from rhythm_ml.local_replay import replay_capture_directory
from rhythm_ml.model import save_metrics, train_and_evaluate, write_model_header


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and verify the SmartCane AF rhythm-screening candidate."
    )
    parser.add_argument("--af-zip", required=True, type=Path)
    parser.add_argument("--non-af-zip", required=True, type=Path)
    parser.add_argument("--local-captures", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/latest"))
    parser.add_argument("--rebuild-features", action="store_true")
    parser.add_argument("--seed", type=int, default=2026)
    return parser.parse_args()


def _percent(value: float | None) -> str:
    return "不可用" if value is None else f"{100.0 * value:.1f}%"


def _write_report(output: Path, metrics: dict, local: dict | None) -> None:
    public = metrics["int8_test"]
    subject = public["subject"]
    consensus = public["consensus_subject"]
    window = public["window"]
    acceptance = metrics["course_acceptance"]
    public_result = "通过" if acceptance["passed_public_test"] else "未通过"
    local_result = "尚未执行"
    if local is not None:
        local_result = "通过" if local["passed_no_new_serious_alerts"] else "未通过"
    ready = bool(
        acceptance["passed_public_test"]
        and local is not None
        and local["passed_no_new_serious_alerts"]
    )
    lines = [
        "# 智能拐杖异常节律候选模型训练报告",
        "",
        "> 本模型只用于课程项目的异常节律筛查，不能诊断房颤，也不能替代心电图和医生判断。",
        "",
        "## 本次结论",
        "",
        f"- MIMIC PERform 独立受试者测试：**{public_result}**",
        f"- P001～P043 正常/伪影短程回放：**{local_result}**",
        f"- 是否可以进入实物短程回归：**{'可以' if ready else '暂不可以'}**",
        "- `RHYTHM_MODEL_CALIBRATED`：仍须保持 `false`，直到烧录后完成 2～3 组实物静止测试。",
        "",
        "## 数据划分",
        "",
        "按受试者划分训练、验证和测试集合，同一人的窗口不会跨集合，避免数据泄漏。",
        "",
        f"公开数据共提取 {metrics['dataset']['total_windows']} 个可用窗口；"
        f"因峰值不足、长间隔或窗口末端心搏过期而丢弃 "
        f"{metrics['dataset']['discarded_windows']} 个（"
        f"{_percent(metrics['dataset']['discarded_window_fraction'])}）。",
        "",
        "| 集合 | 受试者 | 窗口 |",
        "|---|---:|---:|",
    ]
    for name, title in (("train", "训练"), ("validation", "验证"), ("test", "独立测试")):
        item = metrics["split"][name]
        lines.append(f"| {title} | {item['subject_count']} | {item['window_count']} |")
    lines.extend(
        [
            "",
            "## 独立测试结果（INT8 候选模型）",
            "",
            "| 粒度 | 灵敏度 | 特异度 | 平衡准确率 | AUC |",
            "|---|---:|---:|---:|---:|",
            f"| 固件连续3窗口告警/受试者 | {_percent(consensus['sensitivity'])} | {_percent(consensus['specificity'])} | {_percent(consensus['balanced_accuracy'])} | {consensus['roc_auc'] if consensus['roc_auc'] is not None else '不可用'} |",
            f"| 窗口概率中位数/受试者（辅助） | {_percent(subject['sensitivity'])} | {_percent(subject['specificity'])} | {_percent(subject['balanced_accuracy'])} | {subject['roc_auc'] if subject['roc_auc'] is not None else '不可用'} |",
            f"| 15秒窗口 | {_percent(window['sensitivity'])} | {_percent(window['specificity'])} | {_percent(window['balanced_accuracy'])} | {window['roc_auc'] if window['roc_auc'] is not None else '不可用'} |",
            "",
            f"按固件连续三窗口规则，独立非房颤数据中的假告警率为 "
            f"{consensus['false_alerts_per_hour']:.3f} 次/小时。",
            "",
            f"浮点模型与 INT8 模型分类一致率：{_percent(public['prediction_agreement_with_float'])}。",
            "",
            "## 本地 P001～P043 回放",
            "",
        ]
    )
    if local is None:
        lines.append("未提供 `--local-captures`，因此尚未执行。")
    else:
        lines.extend(
            [
                f"- 找到文件：{local['file_count']} 个",
                f"- 实际有固件推理点的文件：{local['replayed_file_count']} 个",
                f"- 通过质量门控的推理窗口：{local['gated_inference_count']} 个",
                f"- 原始 AF-like 窗口：{local['af_like_windows']} 个",
                f"- 连续 3 窗口形成的 `SUSPECTED_AF`：{local['suspected_af_windows']} 个",
                "",
                "这些记录没有同步 ECG 房颤金标准，只能用于确认正常和伪影场景没有新增严重假报警。",
            ]
        )
    lines.extend(
        [
            "",
            "## 后续必须完成",
            "",
            "1. 只有公开独立测试与本地软件回放都通过，才把生成的头文件作为候选模型接入固件。",
            "2. 编译并烧录，记录模型字节数、RAM、Flash 和推理耗时。",
            "3. 实物重新采 2～3 组 30～60 秒正常静止 PPG，最终状态应为 `NORMAL`，且无新增严重假报警。",
            "4. 全部通过后，才把 `RHYTHM_MODEL_CALIBRATED` 改为 `true`。",
            "",
        ]
    )
    (output / "TRAINING_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    feature_csv = output / "public_features.csv"
    manifest_path = output / "dataset_manifest.json"
    frame = load_or_build_public_features(
        args.af_zip,
        args.non_af_zip,
        feature_csv,
        manifest_path,
        rebuild=args.rebuild_features,
    )
    model, metrics, predictions = train_and_evaluate(frame, seed=args.seed)
    metrics["dataset"] = json.loads(manifest_path.read_text(encoding="utf-8"))
    write_model_header(model, output / "RhythmModel.generated.h")
    predictions.to_csv(output / "public_test_predictions.csv", index=False)

    local_summary = None
    if args.local_captures:
        replay, local_summary = replay_capture_directory(args.local_captures, model)
        replay.to_csv(output / "local_replay.csv", index=False)
        (output / "local_replay_summary.json").write_text(
            json.dumps(local_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    metrics["local_replay"] = local_summary
    metrics["candidate_ready_for_hardware_regression"] = bool(
        metrics["course_acceptance"]["passed_public_test"]
        and local_summary is not None
        and local_summary["passed_no_new_serious_alerts"]
    )
    save_metrics(metrics, output / "metrics.json")
    _write_report(output, metrics, local_summary)

    print(f"[done] output: {output}")
    print(
        "[result] public_test={} local_replay={} hardware_candidate={}".format(
            metrics["course_acceptance"]["passed_public_test"],
            None if local_summary is None else local_summary["passed_no_new_serious_alerts"],
            metrics["candidate_ready_for_hardware_regression"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
