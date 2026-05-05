"""Preprocess adapter that keeps CAP preprocessing aligned with success_three_stage."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import re
from typing import Any

import numpy as np
from scipy.signal import resample_poly

from config import SAMPLES_DIR
from services.cap_probe import CapProbeResult, load_cap_complex_iq, probe_cap_file
from services.three_stage_service import (
    THREE_STAGE_FS_HZ,
    ThreeStageServiceError,
    extract_candidate_bursts_from_complex_iq,
)
from services.workflow_records import SampleRecord


class PreprocessAdapterError(RuntimeError):
    """Raised when the preprocess layer cannot complete safely."""


@dataclass(frozen=True)
class PreprocessRunConfig:
    """UI-facing CAP preprocess request parameters."""

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
    """Normalized CAP preprocess result consumed by the Qt page."""

    success: bool
    message: str
    cap_info: CapProbeResult
    detected_segment_count: int
    candidate_segment_count: int
    output_sample_count: int
    sample_output_dir: str
    segments: list[dict[str, Any]]
    logs: list[str]
    sample_records: list[SampleRecord]


def default_preprocess_output_dir() -> Path:
    """Return the default output directory for CAP preprocess samples."""

    return SAMPLES_DIR / "preprocess_output"


def resolve_default_model_weights_path() -> Path:
    """Compatibility hook for the old UI field. CAP preprocess no longer needs a model weight file."""

    return Path()


def run_preprocess(config: PreprocessRunConfig) -> PreprocessRunResult:
    """Run CAP preprocessing with the same candidate burst extraction used by success_three_stage."""

    input_path = Path(config.input_file_path)
    if input_path.suffix.lower() != ".cap":
        raise PreprocessAdapterError("Preprocess input must be a .cap file.")
    if not input_path.exists():
        raise PreprocessAdapterError("Preprocess input file does not exist.")

    cap_info = probe_cap_file(input_path)
    output_dir = Path(config.sample_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logs = [
        "CAP preprocessing uses the success_three_stage batch-compatible burst extractor.",
        f"Slice length: {config.slice_length}",
        "Legacy threshold fields are kept in the UI for compatibility and are not used by this CAP path.",
    ]

    try:
        raw_iq = load_cap_complex_iq(input_path)
        aligned_iq = _align_iq_for_three_stage(raw_iq, float(cap_info.sample_rate_hz), logs)
        bursts = extract_candidate_bursts_from_complex_iq(
            aligned_iq,
            sample_rate_hz=THREE_STAGE_FS_HZ,
            slice_len=int(config.slice_length),
        )
    except (ThreeStageServiceError, OSError, ValueError) as exc:
        raise PreprocessAdapterError(str(exc)) from exc

    segments = _save_three_stage_segments(
        bursts=bursts,
        input_path=input_path,
        output_dir=output_dir,
        sample_rate_hz=THREE_STAGE_FS_HZ,
        logs=logs,
    )
    sample_records = _build_sample_records(input_path, cap_info, segments, sample_rate_hz=THREE_STAGE_FS_HZ)

    if segments:
        message = "三阶段对齐预处理完成。"
        logs.append(f"Saved {len(segments)} aligned candidate burst samples.")
    else:
        message = "未提取到符合三阶段规则的候选信号段。"
        logs.append(message)

    return PreprocessRunResult(
        success=bool(segments),
        message=message,
        cap_info=cap_info,
        detected_segment_count=len(segments),
        candidate_segment_count=len(segments),
        output_sample_count=len(segments),
        sample_output_dir=str(output_dir),
        segments=segments,
        logs=logs,
        sample_records=sample_records,
    )


def _save_three_stage_segments(
    *,
    bursts: list[dict[str, Any]],
    input_path: Path,
    output_dir: Path,
    sample_rate_hz: float,
    logs: list[str],
) -> list[dict[str, Any]]:
    """Persist aligned candidate bursts as complex IQ .npy files."""

    segments: list[dict[str, Any]] = []
    for burst in bursts:
        pure_iq = np.asarray(burst.get("pure_iq"))
        if pure_iq.size == 0:
            continue

        burst_idx = int(burst.get("burst_idx", len(segments)))
        output_name = f"{input_path.stem}_burst_{burst_idx:03d}.npy"
        output_path = output_dir / output_name
        np.save(output_path, pure_iq.astype(np.complex64, copy=False), allow_pickle=False)

        duration_ms = (float(pure_iq.size) / sample_rate_hz) * 1000.0 if sample_rate_hz > 0 else 0.0
        bandwidth_hz = float(burst.get("bandwidth_hz", 0.0))
        slice_count = int(burst.get("slice_count", 0))
        segments.append(
            {
                "segment_id": f"burst_{burst_idx:03d}",
                "start_sample": int(burst.get("start_idx", 0)),
                "end_sample": int(burst.get("end_idx", 0)),
                "duration_ms": duration_ms,
                "center_freq_hz": float(burst.get("center_freq_offset_hz", 0.0)),
                "bandwidth_hz": bandwidth_hz,
                "snr_db": 0.0,
                "score": float(slice_count),
                "output_file_path": str(output_path),
                "status": "aligned_candidate",
            }
        )
        logs.append(
            f"{output_name}: slices={slice_count}, samples={pure_iq.size}, bw={bandwidth_hz / 1e6:.2f} MHz"
        )
    return segments


def _build_sample_records(
    input_path: Path,
    cap_info: CapProbeResult,
    segments: list[dict[str, Any]],
    *,
    sample_rate_hz: float,
) -> list[SampleRecord]:
    """Convert extracted candidate bursts into sample records."""

    records: list[SampleRecord] = []
    for index, segment in enumerate(segments, start=1):
        sample_path = Path(str(segment.get("output_file_path", "")))
        if not sample_path.exists():
            continue

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
                sample_rate_hz=sample_rate_hz,
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
                source_name="三阶段对齐预处理",
            )
        )
    return records


def _sample_count_from_file(path: Path) -> int:
    """Return the IQ sample count for one saved .npy file."""

    if path.suffix.lower() == ".npy":
        data = np.load(path, mmap_mode="r", allow_pickle=False)
        if data.shape:
            return int(data.shape[0])
        return int(data.size)
    return 0


def _slugify(value: str) -> str:
    """Generate a stable identifier fragment."""

    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_").lower()


def _align_iq_for_three_stage(iq: np.ndarray, source_rate_hz: float, logs: list[str]) -> np.ndarray:
    """Resample CAP IQ so the downstream extractor sees the expected three-stage rate."""

    if source_rate_hz <= 0:
        raise PreprocessAdapterError("CAP sample rate is invalid.")
    if abs(source_rate_hz - THREE_STAGE_FS_HZ) <= 1.0:
        logs.append("Input IQ already matches the three-stage 80 MHz sample rate.")
        return iq.astype(np.complex64, copy=False)

    ratio = Fraction(THREE_STAGE_FS_HZ / source_rate_hz).limit_denominator(512)
    logs.append(
        f"Resampling IQ from {source_rate_hz / 1e6:.3f} MHz to {THREE_STAGE_FS_HZ / 1e6:.1f} MHz "
        f"with ratio {ratio.numerator}/{ratio.denominator}."
    )
    real = resample_poly(iq.real.astype(np.float32, copy=False), ratio.numerator, ratio.denominator)
    imag = resample_poly(iq.imag.astype(np.float32, copy=False), ratio.numerator, ratio.denominator)
    return (real + 1j * imag).astype(np.complex64, copy=False)
