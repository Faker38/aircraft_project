"""类型识别模型批量测试服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import csv
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from config import EVALUATIONS_DIR
from services.model_service import FEATURE_NAMES, ModelServiceError, extract_iq_features, load_trained_model
from services.workflow_records import ModelEvaluationResult, TrainedModelRecord, TrainingMetricRow


def evaluate_type_model(
    model_id: str,
    manifest_csv_path: str,
    *,
    progress_callback: Callable[[int, str, str], None] | None = None,
) -> ModelEvaluationResult:
    """对一个外部标注测试集执行批量评估。"""

    bundle = load_trained_model(model_id)
    model_record: TrainedModelRecord = bundle["record"]
    payload = bundle["payload"]
    model = payload["model"]
    label_space = [str(value) for value in payload.get("label_space", model_record.label_space)]

    manifest_path = Path(manifest_csv_path)
    if not manifest_path.exists():
        raise ModelServiceError(f"测试清单不存在：{manifest_path}")
    if manifest_path.suffix.lower() != ".csv":
        raise ModelServiceError("模型测试清单必须为 .csv 文件。")

    _emit_progress(progress_callback, 5, "正在读取测试清单", f"[Stage] 正在读取测试清单：{manifest_path}")
    rows = _load_manifest_rows(manifest_path)
    if not rows:
        raise ModelServiceError("当前测试清单没有可评估的样本。")

    missing_paths = [row["sample_file_path"] for row in rows if not Path(row["sample_file_path"]).exists()]
    if missing_paths:
        raise ModelServiceError(f"当前测试清单有 {len(missing_paths)} 个样本文件不存在，请先修正路径。")
    empty_labels = [row["sample_id"] for row in rows if not row["label_type"]]
    if empty_labels:
        raise ModelServiceError(f"当前测试清单有 {len(empty_labels)} 条样本标签为空。")
    outside_labels = sorted({row["label_type"] for row in rows if row["label_type"] not in label_space})
    if outside_labels:
        raise ModelServiceError(f"测试清单中存在不在模型标签空间内的标签：{', '.join(outside_labels)}")

    features: list[np.ndarray] = []
    truth_labels: list[str] = []
    sample_total = len(rows)
    _emit_progress(progress_callback, 10, "正在提取测试特征", f"[Stage] 开始提取测试特征，共 {sample_total} 条样本。")
    for index, row in enumerate(rows, start=1):
        if index == 1 or index % 500 == 0 or index == sample_total:
            _emit_progress(
                progress_callback,
                min(70, 10 + int(index / max(sample_total, 1) * 60)),
                "正在提取测试特征",
                f"[Stage] 正在提取测试特征：{index}/{sample_total}",
            )
        features.append(extract_iq_features(row["sample_file_path"]))
        truth_labels.append(row["label_type"])

    x_eval = np.vstack(features)
    y_true = np.asarray(truth_labels, dtype=object)
    _emit_progress(progress_callback, 75, "正在执行批量推理", "[Stage] 测试特征提取完成，开始执行批量预测。")
    y_pred = model.predict(x_eval)
    accuracy = float(accuracy_score(y_true, y_pred))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    matrix = confusion_matrix(y_true, y_pred, labels=label_space)
    report = classification_report(y_true, y_pred, labels=label_space, output_dict=True, zero_division=0)

    metric_rows: list[TrainingMetricRow] = []
    for label in label_space:
        label_report = report.get(label, {})
        metric_rows.append(
            TrainingMetricRow(
                label=label,
                precision=float(label_report.get("precision", 0.0)),
                recall=float(label_report.get("recall", 0.0)),
                f1=float(label_report.get("f1-score", 0.0)),
                support=int(label_report.get("support", 0)),
            )
        )

    run_id = f"eval_{model_record.model_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = EVALUATIONS_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    metrics_csv_path = output_dir / "metrics.csv"

    _emit_progress(progress_callback, 90, "正在写入测试报告", f"[Stage] 批量推理完成，正在写入测试报告：{output_dir}")
    report_payload = {
        "run_id": run_id,
        "model_id": model_record.model_id,
        "dataset_version_id": model_record.dataset_version_id,
        "manifest_csv_path": str(manifest_path),
        "sample_count": sample_total,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "label_space": label_space,
        "feature_count": len(FEATURE_NAMES),
        "confusion_matrix": matrix.tolist(),
        "created_at": _now_text(),
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with metrics_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "precision", "recall", "f1", "support"])
        for row in metric_rows:
            writer.writerow([row.label, f"{row.precision:.6f}", f"{row.recall:.6f}", f"{row.f1:.6f}", row.support])

    logs = [
        f"[Start] 开始模型测试 | 模型 {model_record.model_id}",
        f"[Info] 测试清单：{manifest_path}",
        f"[Info] 测试样本数：{sample_total}",
        f"[Info] 标签空间：{' / '.join(label_space)}",
        f"[Done] 正确率：{accuracy * 100:.2f}% | 宏平均 F1：{macro_f1:.4f}",
        f"[Done] 报告文件：{report_path}",
        f"[Done] 指标文件：{metrics_csv_path}",
    ]
    _emit_progress(progress_callback, 100, "测试完成", logs[-3])

    return ModelEvaluationResult(
        model_record=model_record,
        manifest_csv_path=str(manifest_path),
        report_path=str(report_path),
        metrics_csv_path=str(metrics_csv_path),
        sample_count=sample_total,
        accuracy=accuracy,
        macro_f1=macro_f1,
        confusion_matrix=matrix.tolist(),
        metric_rows=metric_rows,
        logs=logs,
        label_space=label_space,
    )


def _load_manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    """读取并校验外部测试集 CSV。"""

    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {name.strip() for name in (reader.fieldnames or []) if name}
        required = {"sample_id", "sample_file_path", "label_type"}
        missing = sorted(required - fieldnames)
        if missing:
            raise ModelServiceError(f"测试清单缺少必要字段：{', '.join(missing)}")

        rows: list[dict[str, str]] = []
        for raw_row in reader:
            sample_path_text = (raw_row.get("sample_file_path") or "").strip()
            if sample_path_text:
                sample_path = Path(sample_path_text)
                if not sample_path.is_absolute():
                    sample_path = (manifest_path.parent / sample_path).resolve()
            else:
                sample_path = Path("")
            rows.append(
                {
                    "sample_id": (raw_row.get("sample_id") or "").strip(),
                    "sample_file_path": str(sample_path),
                    "label_type": (raw_row.get("label_type") or "").strip(),
                }
            )
        return rows


def _emit_progress(
    progress_callback: Callable[[int, str, str], None] | None,
    percent: int,
    stage_text: str,
    log_text: str,
) -> None:
    """向训练页发出模型测试阶段消息。"""

    if progress_callback is None:
        return
    progress_callback(int(percent), stage_text, log_text)


def _now_text() -> str:
    """返回统一时间文本。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
