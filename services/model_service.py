"""类型识别真实训练与推理服务。"""

from __future__ import annotations

from collections.abc import Callable
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from config import MODELS_DIR
from services.database import get_dataset_version_detail, get_trained_model, save_trained_model, write_dataset_manifest
from services.workflow_records import PredictionResult, TrainingMetricRow, TrainingRunResult, TrainedModelRecord


FEATURE_NAMES: tuple[str, ...] = (
    "i_mean",
    "i_std",
    "q_mean",
    "q_std",
    "amplitude_mean",
    "amplitude_std",
    "amplitude_max",
    "power_mean",
    "power_std",
    "amplitude_diff_mean",
    "spectrum_peak",
    "spectrum_mean",
    "spectrum_std",
    "spectral_entropy",
)


class ModelServiceError(RuntimeError):
    """训练或推理阶段的统一业务异常。"""


class TrainingCancelled(ModelServiceError):
    """用于标记一次协作式训练取消。"""


def train_type_model(
    version_id: str,
    *,
    model_name: str | None = None,
    n_estimators: int = 300,
    max_depth: int = 24,
    random_state: int = 42,
    progress_callback: Callable[[str, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> TrainingRunResult:
    """基于一个类型识别数据集版本训练真实模型。"""

    detail = get_dataset_version_detail(version_id)
    if detail is None:
        raise ModelServiceError(f"未找到数据集版本：{version_id}")
    if detail.version.task_type != "类型识别":
        raise ModelServiceError("请选择可训练的数据集版本。")
    if not detail.items:
        raise ModelServiceError("数据集版本没有可训练样本。")
    if detail.missing_file_count:
        raise ModelServiceError(f"版本中有 {detail.missing_file_count} 个样本文件不存在，请先修正样本路径。")
    if detail.empty_label_count:
        raise ModelServiceError(f"版本中有 {detail.empty_label_count} 条样本标签为空，请先回到数据集页补齐。")

    _emit_train_progress(
        progress_callback,
        "正在读取数据集版本",
        f"[Stage] 已读取数据集版本 {version_id}，开始准备 manifest 与训练输入。",
    )
    _raise_if_cancelled(cancel_check, "训练已停止：在读取数据集版本后取消。")

    # 训练前重新写一份 manifest，确保训练页和服务层看到的是同一版样本清单。
    manifest_path = write_dataset_manifest(version_id)
    if manifest_path is None:
        raise ModelServiceError("数据集 manifest 生成失败，无法继续训练。")

    _emit_train_progress(
        progress_callback,
        "正在统计标签与划分",
        f"[Stage] 已生成 manifest，开始统计标签分布与数据划分：{manifest_path}",
    )
    _raise_if_cancelled(cancel_check, "训练已停止：在 manifest 生成后取消。")

    label_counts = Counter(item.label_value for item in detail.items if item.label_value)
    if len(label_counts) < 2:
        raise ModelServiceError("模型训练至少需要两类标签，请先补齐样本标注。")

    split_counts = Counter(item.split for item in detail.items)
    for split_name in ("train", "val", "test"):
        if split_counts.get(split_name, 0) <= 0:
            raise ModelServiceError(f"版本缺少 {split_name} 集样本，请先调整数据集划分。")

    training_domain = _build_training_domain(detail.items)
    logs = [
        f"[Start] 开始训练类型识别模型 | 数据集版本 {version_id}",
        f"[Info] Manifest: {manifest_path}",
        f"[Info] 标签数: {len(label_counts)} | 标签分布: {dict(label_counts)}",
        f"[Info] 数据划分: train={split_counts.get('train', 0)} / val={split_counts.get('val', 0)} / test={split_counts.get('test', 0)}",
        f"[Info] 训练适用域: 来源={training_domain.get('source_types', [])} / "
        f"中心频率={_format_range(training_domain.get('center_frequency_hz_range'))} Hz / "
        f"采样率={_format_range(training_domain.get('sample_rate_hz_range'))} Hz",
        f"[Info] 训练参数: random_state={int(random_state)} / n_estimators={int(n_estimators)} / max_depth={_format_max_depth(max_depth)}",
        "[Info] 相同版本、参数与随机种子下，训练结果可重复。",
    ]

    split_features: dict[str, list[np.ndarray]] = {"train": [], "val": [], "test": []}
    split_labels: dict[str, list[str]] = {"train": [], "val": [], "test": []}
    _emit_train_progress(
        progress_callback,
        "正在提取样本特征",
        f"[Stage] 开始提取 IQ 特征，共 {len(detail.items)} 条样本。",
    )
    for index, item in enumerate(detail.items, start=1):
        if index == 1 or index % 1000 == 0 or index == len(detail.items):
            _emit_train_progress(
                progress_callback,
                "正在提取样本特征",
                f"[Stage] 正在提取 IQ 特征：{index}/{len(detail.items)}",
            )
        _raise_if_cancelled(cancel_check, f"训练已停止：特征提取已处理 {index - 1} 条样本。")
        features = extract_iq_features(item.sample_file_path)
        split_features[item.split].append(features)
        split_labels[item.split].append(item.label_value)

    x_train = np.vstack(split_features["train"])
    x_val = np.vstack(split_features["val"])
    x_test = np.vstack(split_features["test"])
    y_train = np.asarray(split_labels["train"], dtype=object)
    y_val = np.asarray(split_labels["val"], dtype=object)
    y_test = np.asarray(split_labels["test"], dtype=object)

    if len(set(y_train.tolist())) < 2:
        raise ModelServiceError("训练集内实际可用标签不足两类，无法完成真实训练。")

    resolved_max_depth = None if int(max_depth) <= 0 else int(max_depth)
    _emit_train_progress(
        progress_callback,
        "正在训练随机森林",
        f"[Stage] 特征提取完成，开始拟合 RandomForest：trees={int(n_estimators)} / max_depth={_format_max_depth(max_depth)} / seed={int(random_state)}",
    )
    _raise_if_cancelled(cancel_check, "训练已停止：在进入随机森林拟合前取消。")
    clf = RandomForestClassifier(
        n_estimators=int(n_estimators),
        max_depth=resolved_max_depth,
        random_state=int(random_state),
        # 固定单进程，避免 Windows 下 joblib 并行权限问题。
        n_jobs=1,
        class_weight="balanced_subsample",
    )
    clf.fit(x_train, y_train)
    _raise_if_cancelled(cancel_check, "训练已停止：随机森林拟合已完成，结果不会保存。")

    _emit_train_progress(
        progress_callback,
        "正在评估模型",
        "[Stage] 随机森林拟合完成，开始计算验证集、测试集指标与混淆矩阵。",
    )
    _raise_if_cancelled(cancel_check, "训练已停止：在模型评估前取消。")
    y_val_pred = clf.predict(x_val)
    y_test_pred = clf.predict(x_test)
    label_space = [str(label) for label in clf.classes_]
    val_accuracy = float(accuracy_score(y_val, y_val_pred))
    test_accuracy = float(accuracy_score(y_test, y_test_pred))
    test_macro_f1 = float(f1_score(y_test, y_test_pred, average="macro", zero_division=0))
    matrix = confusion_matrix(y_test, y_test_pred, labels=label_space)
    report = classification_report(y_test, y_test_pred, labels=label_space, output_dict=True, zero_division=0)

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

    model_id = _build_model_id(model_name or f"rf_type_{version_id}")
    model_dir = MODELS_DIR / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "model.joblib"
    metadata_path = model_dir / "metadata.json"

    _emit_train_progress(
        progress_callback,
        "正在写入模型文件",
        f"[Stage] 评估完成，开始写入模型与元数据：{model_path}",
    )
    _raise_if_cancelled(cancel_check, "训练已停止：在写入模型文件前取消。")
    model_payload = {
        "model_id": model_id,
        "dataset_version_id": version_id,
        "task_type": "类型识别",
        "model_kind": "RandomForest",
        "feature_names": list(FEATURE_NAMES),
        "label_space": label_space,
        "trained_at": _now_text(),
        "training_domain": training_domain,
        "training_config": {
            "random_state": int(random_state),
            "n_estimators": int(n_estimators),
            "max_depth": resolved_max_depth,
        },
        "model": clf,
    }
    joblib.dump(model_payload, model_path)

    metrics_payload: dict[str, Any] = {
        "val_accuracy": val_accuracy,
        "test_accuracy": test_accuracy,
        "test_macro_f1": test_macro_f1,
        "feature_count": len(FEATURE_NAMES),
        "split_counts": {key: int(value) for key, value in split_counts.items()},
        "label_counts": {key: int(value) for key, value in label_counts.items()},
        "confusion_matrix": matrix.tolist(),
        "training_domain": training_domain,
        "random_state": int(random_state),
        "n_estimators": int(n_estimators),
        "max_depth": resolved_max_depth,
    }
    metadata_payload: dict[str, Any] = {
        "model_id": model_id,
        "dataset_version_id": version_id,
        "task_type": "类型识别",
        "model_kind": "RandomForest",
        "label_space": label_space,
        "feature_names": list(FEATURE_NAMES),
        "training_domain": training_domain,
        "training_config": {
            "random_state": int(random_state),
            "n_estimators": int(n_estimators),
            "max_depth": resolved_max_depth,
        },
        "metrics": metrics_payload,
        "metric_rows": [
            {
                "label": row.label,
                "precision": row.precision,
                "recall": row.recall,
                "f1": row.f1,
                "support": row.support,
            }
            for row in metric_rows
        ],
    }
    metadata_path.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if cancel_check is not None and cancel_check():
        for path in (model_path, metadata_path):
            if path.exists():
                path.unlink()
        raise TrainingCancelled("训练已停止：模型文件写入后收到取消请求，产物已丢弃。")

    model_record = TrainedModelRecord(
        model_id=model_id,
        dataset_version_id=version_id,
        task_type="类型识别",
        model_kind="RandomForest",
        label_space=label_space,
        artifact_path=str(model_path),
        metrics=metrics_payload,
        status="训练完成",
        created_at=_now_text(),
    )
    save_trained_model(model_record)

    logs.extend(
        [
            f"[Info] 特征维度: {len(FEATURE_NAMES)}",
            f"[Info] 验证集精度: {val_accuracy * 100:.2f}%",
            f"[Done] 测试集精度: {test_accuracy * 100:.2f}% | 宏平均 F1: {test_macro_f1:.4f}",
            f"[Done] 模型文件: {model_path}",
            f"[Done] 元数据文件: {metadata_path}",
        ]
    )
    return TrainingRunResult(
        model_record=model_record,
        manifest_path=str(manifest_path),
        split_counts={key: int(value) for key, value in split_counts.items()},
        label_counts={key: int(value) for key, value in label_counts.items()},
        logs=logs,
        metric_rows=metric_rows,
        confusion_matrix=matrix.tolist(),
        feature_count=len(FEATURE_NAMES),
    )


def load_trained_model(model_id: str) -> dict[str, Any]:
    """加载一个已经训练完成的类型识别模型。"""

    record = get_trained_model(model_id)
    if record is None:
        raise ModelServiceError(f"未找到模型记录：{model_id}")

    artifact_path = Path(record.artifact_path)
    if not artifact_path.exists():
        raise ModelServiceError(f"模型文件不存在：{artifact_path}")

    payload = joblib.load(artifact_path)
    if not isinstance(payload, dict) or "model" not in payload:
        raise ModelServiceError("模型文件内容无效，无法用于识别。")
    return {"record": record, "payload": payload}


def predict_type_sample(model_id: str, sample_file_path: str) -> PredictionResult:
    """使用一个已训练模型对单条样本执行类型识别。"""

    bundle = load_trained_model(model_id)
    record = bundle["record"]
    payload = bundle["payload"]
    model = payload["model"]

    sample_path = Path(sample_file_path)
    if not sample_path.exists():
        raise ModelServiceError(f"样本文件不存在：{sample_path}")

    features = extract_iq_features(sample_path).reshape(1, -1)
    predicted_label = str(model.predict(features)[0])

    probabilities: dict[str, float] = {}
    confidence = 1.0
    if hasattr(model, "predict_proba"):
        prob_values = model.predict_proba(features)[0]
        classes = [str(value) for value in getattr(model, "classes_", record.label_space)]
        probabilities = {label: float(prob) for label, prob in zip(classes, prob_values)}
        confidence = max(probabilities.values(), default=0.0)

    return PredictionResult(
        model_record=record,
        predicted_label=predicted_label,
        confidence=float(confidence),
        probabilities=probabilities,
    )


def _emit_train_progress(
    progress_callback: Callable[[str, str], None] | None,
    stage_text: str,
    log_text: str,
) -> None:
    """向训练页发出阶段性进度消息。"""

    if progress_callback is None:
        return
    progress_callback(stage_text, log_text)


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None, message: str) -> None:
    """在训练关键阶段检查是否已收到取消请求。"""

    if cancel_check is None:
        return
    if cancel_check():
        raise TrainingCancelled(message)


def _format_max_depth(max_depth: int | None) -> str:
    """把最大深度转换为适合日志展示的文本。"""

    if max_depth is None or int(max_depth) <= 0:
        return "不限"
    return str(int(max_depth))


def _build_training_domain(items: list[Any]) -> dict[str, Any]:
    """汇总模型训练样本的来源、频率和采样率适用范围。"""

    source_types = sorted({str(getattr(item, "source_type", "")) for item in items if getattr(item, "source_type", "")})
    device_ids = sorted({str(getattr(item, "device_id", "")) for item in items if getattr(item, "device_id", "")})
    center_frequencies = [
        float(getattr(item, "center_frequency_hz", 0.0))
        for item in items
        if float(getattr(item, "center_frequency_hz", 0.0) or 0.0) > 0.0
    ]
    sample_rates = [
        float(getattr(item, "sample_rate_hz", 0.0))
        for item in items
        if float(getattr(item, "sample_rate_hz", 0.0) or 0.0) > 0.0
    ]
    return {
        "source_types": source_types,
        "device_count": len(device_ids),
        "center_frequency_hz_range": _range_payload(center_frequencies),
        "sample_rate_hz_range": _range_payload(sample_rates),
    }


def _range_payload(values: list[float]) -> dict[str, float] | None:
    """把数值列表压缩为 min/max 范围。"""

    if not values:
        return None
    return {"min": float(min(values)), "max": float(max(values))}


def _format_range(value: object) -> str:
    """把适用域范围转成日志里的紧凑文本。"""

    if not isinstance(value, dict):
        return "-"
    return f"{float(value.get('min', 0.0)):.0f}-{float(value.get('max', 0.0)):.0f}"


def extract_iq_features(sample_file_path: str | Path) -> np.ndarray:
    """从一条 IQ 样本文件提取稳定、轻量的机器学习特征。"""

    sample_path = Path(sample_file_path)
    if not sample_path.exists():
        raise ModelServiceError(f"样本文件不存在：{sample_path}")

    raw = np.load(sample_path, allow_pickle=False)
    iq = _ensure_complex_iq(raw)
    if iq.size == 0:
        raise ModelServiceError(f"样本内容为空：{sample_path}")

    real = iq.real.astype(np.float64, copy=False)
    imag = iq.imag.astype(np.float64, copy=False)
    amplitude = np.abs(iq).astype(np.float64, copy=False)
    power = np.square(amplitude, dtype=np.float64)
    amplitude_diff = np.diff(amplitude) if amplitude.size > 1 else np.asarray([0.0], dtype=np.float64)

    spectrum = np.abs(np.fft.fft(iq)).astype(np.float64, copy=False)
    spectrum = spectrum[: max(1, spectrum.size // 2)] if spectrum.size > 1 else spectrum
    spectrum_sum = float(np.sum(spectrum))
    if spectrum_sum <= 0.0:
        spectral_entropy = 0.0
    else:
        normalized = spectrum / spectrum_sum
        spectral_entropy = float(-np.sum(normalized * np.log2(normalized + 1e-12)))
        if normalized.size > 1:
            spectral_entropy /= float(np.log2(normalized.size))

    features = np.asarray(
        [
            np.mean(real),
            np.std(real),
            np.mean(imag),
            np.std(imag),
            np.mean(amplitude),
            np.std(amplitude),
            np.max(amplitude),
            np.mean(power),
            np.std(power),
            np.mean(np.abs(amplitude_diff)),
            np.max(spectrum),
            np.mean(spectrum),
            np.std(spectrum),
            spectral_entropy,
        ],
        dtype=np.float64,
    )
    return np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)


def _ensure_complex_iq(raw: np.ndarray) -> np.ndarray:
    """把不同形态的样本数组统一转换为一维复数 IQ 序列。"""

    flat = np.asarray(raw).reshape(-1)
    if np.iscomplexobj(flat):
        return flat.astype(np.complex128, copy=False)
    if flat.size % 2 != 0:
        raise ModelServiceError("样本不是合法的复数 IQ 序列。")
    real = flat[0::2].astype(np.float64, copy=False)
    imag = flat[1::2].astype(np.float64, copy=False)
    return real + 1j * imag


def _build_model_id(raw_name: str) -> str:
    """生成可落盘、可入库的模型编号。"""

    illegal_chars = set('<>:"/\\|?*\r\n\t')
    cleaned_chars = [
        "_" if char.isspace() or char in illegal_chars else char
        for char in raw_name.strip()
    ]
    base_name = re.sub(r"_+", "_", "".join(cleaned_chars)).strip(" ._-") or "rf_type_model"
    return f"{base_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _now_text() -> str:
    """返回统一时间文本。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
