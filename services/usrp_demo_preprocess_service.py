"""USRP IQ preprocessing.

This module bridges UHD ``rx_samples_to_file`` output into the existing
dataset/training/recognition workflow without changing the CAP algorithm path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

import numpy as np

from config import RAW_DATA_DIR, SAMPLES_DIR
from services.cap_probe import IQStatistics, PREVIEW_PAIR_COUNT, STAT_WINDOW_BYTES
from services.workflow_records import SampleRecord


DEFAULT_USRP_DEMO_SLICE_LENGTH = 8192
DEFAULT_USRP_DEMO_MAX_SEGMENTS = 120
USRP_DEMO_SOURCE_TYPE = "usrp_preprocess"
USRP_DEMO_SOURCE_NAME = "IQ 预处理输出"

FREQUENCY_LABELS_MHZ: dict[int, str] = {
    2412: "频点A",
    2437: "频点B",
    2462: "频点C",
}


class USRPDemoPreprocessError(RuntimeError):
    """Raised when USRP preprocessing cannot continue safely."""


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
    """Configuration for converting one USRP IQ capture into samples."""

    input_file_path: str
    slice_length: int
    energy_threshold_db: float
    sample_output_dir: str
    max_segments: int = DEFAULT_USRP_DEMO_MAX_SEGMENTS


@dataclass(frozen=True)
class USRPDemoPreprocessResult:
    """USRP preprocessing result consumed by the Qt page."""

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
    """Return the default output directory for USRP IQ samples."""

    return SAMPLES_DIR / "usrp_iq_output"


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
        raise USRPDemoPreprocessError("IQ 预处理仅支持 .iq 文件。")
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
    """Convert a UHD IQ capture into labeled samples for downstream pages."""

    input_info = preview_usrp_iq_file(config.input_file_path)
    slice_length = max(1024, int(config.slice_length))
    max_segments = max(1, int(config.max_segments))
    output_dir = Path(config.sample_output_dir or default_usrp_demo_output_dir())
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = np.memmap(input_info.path, dtype="<i2", mode="r")
    if raw.size % 2 != 0:
        raise USRPDemoPreprocessError("USRP IQ 文件不是合法的 I/Q 交织序列。")
    iq_pairs = raw.reshape(-1, 2)
    window_count = int(iq_pairs.shape[0] // slice_length)
    if window_count <= 0:
        raise USRPDemoPreprocessError("USRP IQ 文件长度不足，无法按设定切片长度生成样本。")

    window_stats = _score_windows(iq_pairs, window_count, slice_length)
    power_values = np.asarray([item["power_db"] for item in window_stats], dtype=np.float64)
    median_power_db = float(np.median(power_values)) if power_values.size else -120.0
    threshold_db = median_power_db + float(config.energy_threshold_db)

    candidates = [
        item
        for item in window_stats
        if item["power_db"] >= threshold_db and item["rms"] > 0.0 and item["clip_pct"] <= 1.0
    ]
    if not candidates:
        candidates = sorted(window_stats, key=lambda item: item["power_db"], reverse=True)[: min(max_segments, 12)]

    selected = sorted(candidates, key=lambda item: item["power_db"], reverse=True)[:max_segments]
    selected = sorted(selected, key=lambda item: item["index"])

    label = suggest_usrp_demo_label(input_info.center_frequency_hz)
    records: list[SampleRecord] = []
    segments: list[dict[str, Any]] = []
    safe_stem = _slugify(input_info.path.stem)
    device_id = f"usrp_{int(round(input_info.center_frequency_hz / 1_000_000))}M"

    for ordinal, item in enumerate(selected, start=1):
        start_sample = int(item["index"] * slice_length)
        end_sample = int(start_sample + slice_length)
        sample_iq = iq_pairs[start_sample:end_sample].astype(np.float32, copy=True)
        complex_iq = (sample_iq[:, 0] + 1j * sample_iq[:, 1]).astype(np.complex64, copy=False)
        segment_id = f"usrp_{ordinal:04d}"
        output_path = output_dir / f"{safe_stem}_{segment_id}.npy"
        np.save(output_path, complex_iq, allow_pickle=False)

        duration_ms = slice_length / max(input_info.sample_rate_hz, 1.0) * 1000.0
        snr_db = float(item["power_db"] - median_power_db)
        score = float(item["power_db"])
        segments.append(
            {
                "segment_id": segment_id,
                "start_sample": start_sample,
                "end_sample": end_sample,
                "duration_ms": duration_ms,
                "center_freq_hz": input_info.center_frequency_hz,
                "bandwidth_hz": input_info.bandwidth_hz,
                "snr_db": snr_db,
                "score": score,
                "output_file_path": str(output_path),
                "status": "已保存",
            }
        )
        records.append(
            SampleRecord(
                sample_id=f"usrp_{safe_stem}_{segment_id}",
                source_type=USRP_DEMO_SOURCE_TYPE,
                raw_file_path=str(input_info.path),
                sample_file_path=str(output_path),
                label_type=label,
                label_individual=f"{label}_001",
                sample_rate_hz=input_info.sample_rate_hz,
                center_frequency_hz=input_info.center_frequency_hz,
                data_format="complex64_npy",
                sample_count=int(complex_iq.size),
                device_id=device_id,
                start_sample=start_sample,
                end_sample=end_sample,
                snr_db=snr_db,
                score=score,
                include_in_dataset=True,
                status="已标注",
                source_name=USRP_DEMO_SOURCE_NAME,
            )
        )

    logs = [
        f"[Start] IQ 预处理：{input_info.path.name}",
        f"[Info] 采样率 {input_info.sample_rate_hz / 1_000_000:.3f} MHz，中心频率 {input_info.center_frequency_hz / 1_000_000:.3f} MHz。",
        f"[Info] 切片长度 {slice_length}，候选窗口 {window_count}，能量阈值 {threshold_db:.2f} dB。",
        f"[Info] 标签建议：{label}。",
        f"[Done] 已保存 {len(records)} 条 IQ 样本：{output_dir}",
    ]
    return USRPDemoPreprocessResult(
        success=bool(records),
        message=f"IQ 预处理完成，已生成 {len(records)} 条样本。",
        input_info=input_info,
        detected_segment_count=len(records),
        candidate_segment_count=window_count,
        output_sample_count=len(records),
        sample_output_dir=str(output_dir),
        segments=segments,
        logs=logs,
        sample_records=records,
    )


def suggest_usrp_demo_label(center_frequency_hz: float) -> str:
    """Return the label for the nearest configured frequency."""

    mhz = int(round(float(center_frequency_hz) / 1_000_000))
    nearest = min(FREQUENCY_LABELS_MHZ, key=lambda value: abs(value - mhz))
    if abs(nearest - mhz) <= 3:
        return FREQUENCY_LABELS_MHZ[nearest]
    return f"频点{mhz}M"


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise USRPDemoPreprocessError(f"USRP 元数据 JSON 无法解析：{path}") from exc
    if not isinstance(payload, dict):
        raise USRPDemoPreprocessError("USRP 元数据 JSON 格式异常。")
    return payload


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


def _score_windows(iq_pairs: np.ndarray, window_count: int, slice_length: int) -> list[dict[str, float]]:
    stats: list[dict[str, float]] = []
    for index in range(window_count):
        start = index * slice_length
        end = start + slice_length
        window = iq_pairs[start:end].astype(np.float32, copy=False)
        complex_iq = window[:, 0] + 1j * window[:, 1]
        amplitude = np.abs(complex_iq).astype(np.float64, copy=False)
        power = float(np.mean(np.square(amplitude)))
        rms = float(np.sqrt(power))
        power_db = float(10.0 * np.log10(power + 1e-12))
        clip_count = int(np.count_nonzero((np.abs(window[:, 0]) >= 32760) | (np.abs(window[:, 1]) >= 32760)))
        stats.append(
            {
                "index": float(index),
                "rms": rms,
                "power_db": power_db,
                "clip_pct": clip_count / max(slice_length, 1) * 100.0,
            }
        )
    return stats


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value.strip())
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_").lower() or datetime.now().strftime("usrp_%Y%m%d_%H%M%S")
