"""预处理适配层：负责把 Qt 页面和仓库内预处理脚本桥接起来。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re
from types import ModuleType
from typing import Any

import numpy as np

from config import BASE_DIR, PREPROCESS_MODEL_PATH, PREPROCESS_MODELS_DIR, SAMPLES_DIR
from services.cap_probe import CapProbeError, CapProbeResult, probe_cap_file
from services.workflow_records import SampleRecord


INTERNAL_PREPROCESS_DIR = BASE_DIR / "preprocess_integration"
LEGACY_PREPROCESS_DIR = BASE_DIR.parent / "预处理对接"
PREPROCESS_SCRIPT_NAME = "reprocess_classify_model1_0420.py"
DEFAULT_MODEL_CANDIDATES = (
    "best_model_1_detect_v2.pth",
    "best_model_1_detect_v2 (1).pth",
)


class PreprocessAdapterError(RuntimeError):
    """当外部预处理集成无法安全执行时抛出。"""


@dataclass(frozen=True)
class PreprocessRunConfig:
    """前端页面传给适配层的预处理请求参数。"""

    input_file_path: str
    slice_length: int
    energy_threshold_db: float
    noise_floor_dbm: float
    min_bandwidth_mhz: float
    min_duration_ms: float
    enable_bandpass: bool
    sample_output_dir: str
    model_weights_path: str
    ai_confidence_threshold: float


@dataclass(frozen=True)
class PreprocessRunResult:
    """适配层整理后的预处理结果，供 Qt 页面直接消费。"""

    success: bool
    message: str
    cap_info: CapProbeResult
    detected_segment_count: int
    candidate_segment_count: int  # 新增候选段数
    output_sample_count: int
    sample_output_dir: str
    segments: list[dict[str, Any]]
    logs: list[str]
    sample_records: list[SampleRecord]


def default_preprocess_output_dir() -> Path:
    """返回预处理任务默认使用的样本输出目录。"""

    return SAMPLES_DIR / "preprocess_output"


def resolve_default_model_weights_path() -> Path:
    """返回当前可用的模型权重路径。

    优先查找仓库内目录；如果权重还未迁入仓库，则兼容旧的外部联调目录。
    """

    if PREPROCESS_MODEL_PATH.exists():
        return PREPROCESS_MODEL_PATH

    for preprocess_dir in _candidate_preprocess_dirs():
        for candidate_name in DEFAULT_MODEL_CANDIDATES:
            candidate = preprocess_dir / candidate_name
            if candidate.exists():
                return candidate

        available = sorted(preprocess_dir.glob("*.pth"))
        if available:
            return available[0]

    available_model_weights = sorted(PREPROCESS_MODELS_DIR.glob("*.pth"))
    if available_model_weights:
        return available_model_weights[0]
    raise PreprocessAdapterError("未找到可用的预处理模型权重文件。")


def run_preprocess(config: PreprocessRunConfig) -> PreprocessRunResult:
    """执行外部预处理脚本，并把返回结果整理成页面可用结构。"""

    input_path = Path(config.input_file_path)
    if input_path.suffix.lower() != ".cap":
        raise PreprocessAdapterError("预处理输入必须为 .cap 文件。")
    if not input_path.exists():
        raise PreprocessAdapterError("预处理输入文件不存在。")

    # 先用项目内 CAP 探针验证头字段，确保页面和算法遵循同一口径。
    cap_info = probe_cap_file(input_path)
    module = _load_preprocess_module()
    run_inference_api = getattr(module, "run_inference_api", None)
    if not callable(run_inference_api):
        raise PreprocessAdapterError("外部预处理脚本未提供可调用的 run_inference_api。")

    # 输出目录和权重路径在进入算法前先做一次兜底校验，避免线程里直接崩。
    output_dir = Path(config.sample_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = Path(config.model_weights_path) if config.model_weights_path else resolve_default_model_weights_path()
    if not model_path.exists():
        raise PreprocessAdapterError(f"预处理模型权重不存在：{model_path}")

    raw_result = run_inference_api(
        input_file_path=str(input_path),
        slice_length=config.slice_length,
        energy_threshold_db=config.energy_threshold_db,
        noise_floor_dbm=config.noise_floor_dbm,
        enable_bandpass=config.enable_bandpass,
        sample_output_dir=str(output_dir),
        min_bandwidth_mhz=config.min_bandwidth_mhz,
        min_duration_ms=config.min_duration_ms,
        model_weights_path=str(model_path),
        ai_confidence_threshold=config.ai_confidence_threshold,
    )
    if not isinstance(raw_result, dict):
        raise PreprocessAdapterError("预处理脚本返回格式异常，预期为 JSON 兼容字典。")

    required_keys = {
        "success",
        "message",
        "detected_segment_count",
        "candidate_segment_count",
        "output_sample_count",
        "segments",
        "logs",
    }
    missing_keys = sorted(required_keys - set(raw_result.keys()))
    if missing_keys:
        raise PreprocessAdapterError(f"预处理脚本缺少返回字段：{', '.join(missing_keys)}")

    segments = _normalize_segments(raw_result.get("segments", []))
    sample_records = _build_sample_records(input_path, cap_info, segments)
    return PreprocessRunResult(
        success=bool(raw_result.get("success")),
        message=str(raw_result.get("message", "")),
        cap_info=cap_info,
        detected_segment_count=int(raw_result.get("detected_segment_count", 0)),
        candidate_segment_count=int(raw_result.get("candidate_segment_count", 0)),
        output_sample_count=int(raw_result.get("output_sample_count", 0)),
        sample_output_dir=str(output_dir),
        segments=segments,
        logs=[str(item) for item in raw_result.get("logs", [])],
        sample_records=sample_records,
    )


def _load_preprocess_module() -> ModuleType:
    """从预处理目录动态加载算法脚本。

    当前优先使用仓库内脚本；若尚未完全迁移，兼容旧外部目录。
    """

    preprocess_script_path = _resolve_preprocess_script_path()

    module_name = "external_preprocess_0420"
    spec = spec_from_file_location(module_name, preprocess_script_path)
    if spec is None or spec.loader is None:
        raise PreprocessAdapterError("无法加载预处理脚本模块。")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_segments(raw_segments: Any) -> list[dict[str, Any]]:
    """把外部脚本返回的片段结果整理成统一字典列表。"""

    if not isinstance(raw_segments, list):
        raise PreprocessAdapterError("预处理脚本的 segments 字段必须为列表。")

    normalized_segments: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        normalized_segments.append(
            {
                "segment_id": str(item.get("segment_id", "")),
                "start_sample": int(item.get("start_sample", 0)),
                "end_sample": int(item.get("end_sample", 0)),
                "duration_ms": float(item.get("duration_ms", 0.0)),
                "center_freq_hz": float(item.get("center_freq_hz", 0.0)),
                "bandwidth_hz": float(item.get("bandwidth_hz", 0.0)),
                "snr_db": float(item.get("snr_db", 0.0)),
                "score": float(item.get("score", 0.0)),
                "output_file_path": str(item.get("output_file_path", "")),
                "status": str(item.get("status", "")),
            }
        )
    return normalized_segments


def _build_sample_records(
    input_path: Path,
    cap_info: CapProbeResult,
    segments: list[dict[str, Any]],
) -> list[SampleRecord]:
    """把已保存的候选片段转换成统一的样本记录。"""

    records: list[SampleRecord] = []
    for index, segment in enumerate(segments, start=1):
        sample_path = Path(str(segment.get("output_file_path", "")))
        if not sample_path.exists():
            continue

        # 只要算法已经落盘候选段，就进入数据集管理页等待人工标注；
        # 模型判定结果只作为参考，不再阻止样本进入后续流程。
        sample_count = _sample_count_from_file(sample_path)
        segment_stem = _slugify(sample_path.stem or f"segment_{index:03d}")
        sample_id = f"pp_{_slugify(input_path.stem)}_{segment_stem}"
        center_frequency_hz = float(segment.get("center_freq_hz") or cap_info.center_frequency_hz)

        records.append(
            SampleRecord(
                sample_id=sample_id,
                source_type="local_preprocess",
                raw_file_path=str(input_path),
                sample_file_path=str(sample_path),
                label_type="",
                label_individual="",
                sample_rate_hz=cap_info.sample_rate_hz,
                center_frequency_hz=center_frequency_hz,
                data_format="complex64_npy",
                sample_count=sample_count,
                device_id=input_path.stem,
                start_sample=int(segment.get("start_sample", 0)),
                end_sample=int(segment.get("end_sample", 0)),
                snr_db=float(segment.get("snr_db", 0.0)),
                score=float(segment.get("score", 0.0)),
                include_in_dataset=True,
                status="待标注",
                source_name="预处理输出",
            )
        )
    return records


def _sample_count_from_file(path: Path) -> int:
    """返回一个输出样本文件对应的样本点数。"""

    if path.suffix.lower() == ".npy":
        data = np.load(path, mmap_mode="r")
        if data.shape:
            return int(data.shape[0])
        return int(data.size)
    return 0


def _slugify(value: str) -> str:
    """生成稳定的标识片段，用于构造样本 ID。"""

    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_").lower()


def _candidate_preprocess_dirs() -> tuple[Path, ...]:
    """返回可用于查找预处理脚本和权重的目录集合。"""

    return (
        INTERNAL_PREPROCESS_DIR,
        LEGACY_PREPROCESS_DIR,
    )


def _resolve_preprocess_script_path() -> Path:
    """返回当前应加载的预处理脚本路径。"""

    for preprocess_dir in _candidate_preprocess_dirs():
        candidate = preprocess_dir / PREPROCESS_SCRIPT_NAME
        if candidate.exists():
            return candidate
    searched = "、".join(str(path / PREPROCESS_SCRIPT_NAME) for path in _candidate_preprocess_dirs())
    raise PreprocessAdapterError(f"未找到预处理脚本：{searched}")
