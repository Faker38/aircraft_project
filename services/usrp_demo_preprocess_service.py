"""USRP IQ preprocessing aligned with the success_three_stage candidate extractor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
from scipy.signal import resample_poly

from config import RAW_DATA_DIR, SAMPLES_DIR
from services.cap_probe import IQStatistics, PREVIEW_PAIR_COUNT, STAT_WINDOW_BYTES
from services.three_stage_service import (
    THREE_STAGE_FS_HZ,
    ThreeStageServiceError,
    extract_candidate_bursts_from_complex_iq,
)
from services.workflow_records import SampleRecord


DEFAULT_USRP_DEMO_SLICE_LENGTH = 4096
DEFAULT_USRP_DEMO_MAX_SEGMENTS = 120
USRP_DEMO_SOURCE_TYPE = "usrp_preprocess"
USRP_DEMO_SOURCE_NAME = "USRP 三阶段对齐预处理"


class USRPDemoPreprocessError(RuntimeError):
    """Raised when USRP IQ preprocessing cannot continue safely."""


@dataclass(frozen=True)
class USRPDemoPreprocessInfo:
    """Read-only preview information for one USRP IQ capture."""

    path: Path
    metadata_path: Path
    file_size: int
    sample_rate_hz: float
    center_frequency_hz: float
    bandwidth_hz: float
    gain_db: float
    duration_s: float
    antenna: str
    iq_pair_count: int
    statistics_window_pairs: int
    preview_pairs: list[tuple[int, int, int]]
    statistics: IQStatistics
    metadata: dict[str, Any]


@dataclass(frozen=True)
class USRPDemoPreprocessConfig:
    """Configuration for converting one USRP IQ capture into aligned candidate samples."""

    input_file_path: str
    slice_length: int
    energy_threshold_db: float
    sample_output_dir: str
    max_segments: int = DEFAULT_USRP_DEMO_MAX_SEGMENTS


@dataclass(frozen=True)
class USRPDemoPreprocessResult:
    """USRP IQ preprocessing result consumed by the Qt page."""

    success: bool
    message: str
    input_info: USRPDemoPreprocessInfo
    detected_segment_count: int
    candidate_segment_count: int
    output_sample_count: int
    sample_output_dir: str
    segments: list[dict[str, Any]]
    logs: list[str]
    sample_records: list[SampleRecord]


def default_usrp_demo_output_dir() -> Path:
    """Return the default output directory for aligned USRP samples."""

    return SAMPLES_DIR / "usrp_demo_output"


def list_usrp_iq_captures(raw_dir: Path | None = None) -> list[Path]:
    """Return IQ files with a sibling JSON metadata file."""

    root = Path(raw_dir or RAW_DATA_DIR)
    if not root.exists():
        return []
    return sorted(
        (path for path in root.glob("*.iq") if path.with_suffix(".json").exists()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def preview_usrp_iq_file(path: str | Path) -> USRPDemoPreprocessInfo:
    """Read metadata and a small IQ preview window from a UHD capture."""

    iq_path = Path(path)
    if iq_path.suffix.lower() != ".iq":
        raise USRPDemoPreprocessError("USRP 预处理仅支持 .iq 文件。")
    if not iq_path.exists():
        raise USRPDemoPreprocessError("USRP IQ 文件不存在。")
    if iq_path.stat().st_size <= 0 or iq_path.stat().st_size % 4 != 0:
        raise USRPDemoPreprocessError("USRP IQ 文件大小不符合 int16 I/Q 对齐规则。")

    metadata_path = iq_path.with_suffix(".json")
    if not metadata_path.exists():
        raise USRPDemoPreprocessError("未找到同名 .json 元数据文件。")

    metadata = _read_metadata(metadata_path)
    iq_pair_count = iq_path.stat().st_size // 4
    statistics_pairs = min(iq_pair_count, STAT_WINDOW_BYTES // 4)
    preview_pairs_count = min(iq_pair_count, PREVIEW_PAIR_COUNT)

    values = np.fromfile(iq_path, dtype="<i2", count=max(statistics_pairs * 2, preview_pairs_count * 2))
    if values.size < 2:
        raise USRPDemoPreprocessError("USRP IQ 数据区为空。")

    pairs = values[: statistics_pairs * 2].reshape(-1, 2)
    statistics = _build_statistics(pairs)
    preview_pairs = [
        (index, int(i_value), int(q_value))
        for index, (i_value, q_value) in enumerate(values[: preview_pairs_count * 2].reshape(-1, 2))
    ]

    return USRPDemoPreprocessInfo(
        path=iq_path,
        metadata_path=metadata_path,
        file_size=iq_path.stat().st_size,
        sample_rate_hz=float(metadata.get("sample_rate_hz", 0.0)),
        center_frequency_hz=float(metadata.get("center_frequency_hz", 0.0)),
        bandwidth_hz=float(metadata.get("bandwidth_hz", 0.0)),
        gain_db=float(metadata.get("gain_db", 0.0)),
        duration_s=float(metadata.get("duration_s", 0.0)),
        antenna=str(metadata.get("antenna", "")),
        iq_pair_count=iq_pair_count,
        statistics_window_pairs=statistics.sample_count,
        preview_pairs=preview_pairs,
        statistics=statistics,
        metadata=metadata,
    )


def run_usrp_demo_preprocess(config: USRPDemoPreprocessConfig) -> USRPDemoPreprocessResult:
    """Convert a UHD IQ capture into candidate samples using the three-stage-aligned extractor."""

    input_info = preview_usrp_iq_file(config.input_file_path)
    slice_length = max(1024, int(config.slice_length))
    max_segments = max(1, int(config.max_segments))
    output_dir = Path(config.sample_output_dir or default_usrp_demo_output_dir())
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_complex_iq = _load_usrp_complex_iq(input_info.path)
    logs = [
        f"[Start] USRP 三阶段对齐预处理：{input_info.path.name}",
        f"[Info] 输入采样率 {input_info.sample_rate_hz / 1_000_000:.3f} MHz，中心频率 {input_info.center_frequency_hz / 1_000_000:.3f} MHz。",
        f"[Info] 切片长度 {slice_length}，最大候选输出 {max_segments}。",
    ]

    try:
        aligned_iq = _align_iq_for_three_stage(raw_complex_iq, input_info.sample_rate_hz, logs)
        bursts = extract_candidate_bursts_from_complex_iq(
            aligned_iq,
            sample_rate_hz=THREE_STAGE_FS_HZ,
            slice_len=slice_length,
        )
    except (ThreeStageServiceError, ValueError, OSError) as exc:
        raise USRPDemoPreprocessError(str(exc)) from exc

    selected_bursts = bursts[:max_segments]
    safe_stem = _slugify(input_info.path.stem)
    device_id = _slugify(input_info.path.stem) or datetime.now().strftime("usrp_%Y%m%d_%H%M%S")
    records: list[SampleRecord] = []
    segments: list[dict[str, Any]] = []

    for ordinal, burst in enumerate(selected_bursts, start=1):
        pure_iq = np.asarray(burst.get("pure_iq"))
        if pure_iq.size == 0:
            continue

        segment_id = f"usrp_{ordinal:04d}"
        output_path = output_dir / f"{safe_stem}_{segment_id}.npy"
        np.save(output_path, pure_iq.astype(np.complex64, copy=False), allow_pickle=False)

        start_sample = int(burst.get("start_idx", 0))
        end_sample = int(burst.get("end_idx", 0))
        bandwidth_hz = float(burst.get("bandwidth_hz", 0.0))
        slice_count = int(burst.get("slice_count", 0))
        duration_ms = pure_iq.size / max(THREE_STAGE_FS_HZ, 1.0) * 1000.0
        score = float(slice_count)
        center_frequency_hz = float(input_info.center_frequency_hz + burst.get("center_freq_offset_hz", 0.0))

        segments.append(
            {
                "segment_id": segment_id,
                "start_sample": start_sample,
                "end_sample": end_sample,
                "duration_ms": duration_ms,
                "center_freq_hz": center_frequency_hz,
                "bandwidth_hz": bandwidth_hz,
                "snr_db": 0.0,
                "score": score,
                "output_file_path": str(output_path),
                "status": "aligned_candidate",
            }
        )
        records.append(
            SampleRecord(
                sample_id=f"usrp_{safe_stem}_{segment_id}",
                source_type=USRP_DEMO_SOURCE_TYPE,
                raw_file_path=str(input_info.path),
                sample_file_path=str(output_path),
                label_type="",
                label_individual="",
                sample_rate_hz=THREE_STAGE_FS_HZ,
                center_frequency_hz=center_frequency_hz,
                data_format="complex64_npy",
                sample_count=int(pure_iq.size),
                device_id=device_id,
                start_sample=start_sample,
                end_sample=end_sample,
                snr_db=0.0,
                score=score,
                include_in_dataset=True,
                status="待标注",
                source_name=USRP_DEMO_SOURCE_NAME,
            )
        )
        logs.append(
            f"[Burst] {segment_id}: slices={slice_count}, samples={pure_iq.size}, bw={bandwidth_hz / 1e6:.2f} MHz"
        )

    if records:
        message = f"USRP 三阶段对齐预处理完成，已生成 {len(records)} 条候选样本。"
        logs.append(f"[Done] 已保存 {len(records)} 条三阶段对齐候选样本到 {output_dir}")
    else:
        message = "未提取到符合三阶段规则的候选信号段。"
        logs.append(f"[Done] {message}")

    return USRPDemoPreprocessResult(
        success=bool(records),
        message=message,
        input_info=input_info,
        detected_segment_count=len(records),
        candidate_segment_count=len(selected_bursts),
        output_sample_count=len(records),
        sample_output_dir=str(output_dir),
        segments=segments,
        logs=logs,
        sample_records=records,
    )


def suggest_usrp_demo_label(center_frequency_hz: float) -> str:
    """Compatibility hook kept for existing imports."""

    return f"{int(round(float(center_frequency_hz) / 1_000_000))}M"


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise USRPDemoPreprocessError(f"USRP 元数据 JSON 无法解析：{path}") from exc
    if not isinstance(payload, dict):
        raise USRPDemoPreprocessError("USRP 元数据 JSON 格式异常。")
    return payload


def _load_usrp_complex_iq(path: Path) -> np.ndarray:
    raw = np.fromfile(path, dtype="<i2")
    if raw.size == 0 or raw.size % 2 != 0:
        raise USRPDemoPreprocessError("USRP IQ 文件不是合法的 I/Q 交织序列。")
    iq_pairs = raw.reshape(-1, 2).astype(np.float32, copy=False)
    return (iq_pairs[:, 0] + 1j * iq_pairs[:, 1]).astype(np.complex64, copy=False)


def _align_iq_for_three_stage(iq: np.ndarray, source_rate_hz: float, logs: list[str]) -> np.ndarray:
    if source_rate_hz <= 0:
        raise USRPDemoPreprocessError("USRP 元数据中的采样率无效。")
    if abs(source_rate_hz - THREE_STAGE_FS_HZ) <= 1.0:
        logs.append("[Info] 输入 IQ 已经匹配三阶段 80 MHz 采样率。")
        return iq.astype(np.complex64, copy=False)

    ratio = Fraction(THREE_STAGE_FS_HZ / source_rate_hz).limit_denominator(512)
    logs.append(
        f"[Info] 将 IQ 从 {source_rate_hz / 1e6:.3f} MHz 重采样到 {THREE_STAGE_FS_HZ / 1e6:.1f} MHz，比例 {ratio.numerator}/{ratio.denominator}。"
    )
    real = resample_poly(iq.real.astype(np.float32, copy=False), ratio.numerator, ratio.denominator)
    imag = resample_poly(iq.imag.astype(np.float32, copy=False), ratio.numerator, ratio.denominator)
    return (real + 1j * imag).astype(np.complex64, copy=False)


def _build_statistics(pairs: np.ndarray) -> IQStatistics:
    if pairs.size == 0:
        raise USRPDemoPreprocessError("USRP IQ 数据区为空，无法生成预览统计。")
    i_values = pairs[:, 0].astype(np.float64, copy=False)
    q_values = pairs[:, 1].astype(np.float64, copy=False)
    return IQStatistics(
        sample_count=int(pairs.shape[0]),
        i_mean=float(np.mean(i_values)),
        q_mean=float(np.mean(q_values)),
        i_std=float(np.std(i_values)),
        q_std=float(np.std(q_values)),
        i_min=int(np.min(i_values)),
        i_max=int(np.max(i_values)),
        q_min=int(np.min(q_values)),
        q_max=int(np.max(q_values)),
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_").lower() or datetime.now().strftime("usrp_%Y%m%d_%H%M%S")
