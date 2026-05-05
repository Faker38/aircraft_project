"""Three-stage drone inference service wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any
from collections.abc import Callable
import time

import numpy as np
from scipy.signal import butter, filtfilt, welch

from config import (
    THREE_STAGE_ARTIFACTS_DIR,
    THREE_STAGE_BINARY_MODEL_PATH,
    THREE_STAGE_DEVICE,
    THREE_STAGE_EXTRACTOR_MODE,
    THREE_STAGE_INDIVIDUAL_META_PATH,
    THREE_STAGE_INDIVIDUAL_MODEL_PATH,
    THREE_STAGE_SCRIPT_PATH,
    THREE_STAGE_TYPE_META_PATH,
    THREE_STAGE_TYPE_MODEL_PATH,
)


class ThreeStageServiceError(RuntimeError):
    """Raised when the three-stage backend cannot be executed safely."""


@dataclass(frozen=True)
class ThreeStageInferenceConfig:
    """Inputs needed to run the deployed three-stage inference pipeline."""

    input_path: str
    device: str = THREE_STAGE_DEVICE
    extractor_mode: str = THREE_STAGE_EXTRACTOR_MODE
    binary_model_path: str = str(THREE_STAGE_BINARY_MODEL_PATH)
    type_model_path: str = str(THREE_STAGE_TYPE_MODEL_PATH)
    type_metadata_path: str = str(THREE_STAGE_TYPE_META_PATH)
    individual_model_path: str = str(THREE_STAGE_INDIVIDUAL_MODEL_PATH)
    individual_metadata_path: str = str(THREE_STAGE_INDIVIDUAL_META_PATH)
    min_bw_mhz: float = 12.0
    max_bw_mhz: float = 35.0
    drone_threshold: float = 0.50


THREE_STAGE_FS_HZ = 80e6
THREE_STAGE_DEFAULT_SHIFT_HZ = 23e6
THREE_STAGE_DEFAULT_WINDOW_LEN = 4000
THREE_STAGE_DEFAULT_GAP = 8000
_MAT_PREPROCESS_CACHE: dict[tuple[str, float, float, str], dict[str, Any]] = {}


def default_three_stage_config(input_path: str) -> ThreeStageInferenceConfig:
    """Build a config using the repository default artifacts."""

    return ThreeStageInferenceConfig(input_path=input_path)


def build_three_stage_config(
    input_path: str,
    *,
    binary_model_path: str | None = None,
    type_model_path: str | None = None,
    type_metadata_path: str | None = None,
    individual_model_path: str | None = None,
    individual_metadata_path: str | None = None,
    device: str | None = None,
    extractor_mode: str | None = None,
    min_bw_mhz: float | None = None,
    max_bw_mhz: float | None = None,
    drone_threshold: float | None = None,
) -> ThreeStageInferenceConfig:
    """Build a three-stage config that can override the default local artifact paths."""

    return ThreeStageInferenceConfig(
        input_path=input_path,
        device=device or THREE_STAGE_DEVICE,
        extractor_mode=extractor_mode or THREE_STAGE_EXTRACTOR_MODE,
        binary_model_path=binary_model_path or str(THREE_STAGE_BINARY_MODEL_PATH),
        type_model_path=type_model_path or str(THREE_STAGE_TYPE_MODEL_PATH),
        type_metadata_path=type_metadata_path or str(THREE_STAGE_TYPE_META_PATH),
        individual_model_path=individual_model_path or str(THREE_STAGE_INDIVIDUAL_MODEL_PATH),
        individual_metadata_path=individual_metadata_path or str(THREE_STAGE_INDIVIDUAL_META_PATH),
        min_bw_mhz=float(min_bw_mhz) if min_bw_mhz is not None else 12.0,
        max_bw_mhz=float(max_bw_mhz) if max_bw_mhz is not None else 35.0,
        drone_threshold=float(drone_threshold) if drone_threshold is not None else 0.50,
    )


def run_three_stage_inference(config: ThreeStageInferenceConfig) -> dict[str, Any] | list[dict[str, Any]]:
    """Run the deployed three-stage pipeline on one file or a directory."""

    engine = _load_engine(
        binary_model_path=Path(config.binary_model_path),
        type_model_path=Path(config.type_model_path),
        type_metadata_path=Path(config.type_metadata_path) if config.type_metadata_path else None,
        individual_model_path=Path(config.individual_model_path),
        individual_metadata_path=Path(config.individual_metadata_path) if config.individual_metadata_path else None,
        device=config.device,
        extractor_mode=config.extractor_mode,
    )

    input_path = Path(config.input_path).expanduser().resolve()
    if input_path.is_file():
        if input_path.suffix.lower() == ".mat":
            return engine.infer_mat_file(
                input_path,
                min_bw_mhz=float(config.min_bw_mhz),
                max_bw_mhz=float(config.max_bw_mhz),
                drone_threshold=float(config.drone_threshold),
            )
        if input_path.suffix.lower() == ".npy":
            return _infer_npy_file(engine, input_path, config)
        _ensure_supported_input(input_path)

    if input_path.is_dir():
        results: list[dict[str, Any]] = []
        for file_path in sorted(input_path.rglob("*.mat")):
            results.append(
                engine.infer_mat_file(
                    file_path,
                    min_bw_mhz=float(config.min_bw_mhz),
                    max_bw_mhz=float(config.max_bw_mhz),
                    drone_threshold=float(config.drone_threshold),
                )
            )
        for file_path in sorted(input_path.rglob("*.npy")):
            results.append(_infer_npy_file(engine, file_path, config))
        return results

    raise ThreeStageServiceError(f"Input path does not exist: {input_path}")


def run_three_stage_inference_streaming(
    config: ThreeStageInferenceConfig,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run three-stage inference and emit a partial result after the type stage."""

    engine = _load_engine(
        binary_model_path=Path(config.binary_model_path),
        type_model_path=Path(config.type_model_path),
        type_metadata_path=Path(config.type_metadata_path) if config.type_metadata_path else None,
        individual_model_path=Path(config.individual_model_path),
        individual_metadata_path=Path(config.individual_metadata_path) if config.individual_metadata_path else None,
        device=config.device,
        extractor_mode=config.extractor_mode,
    )

    input_path = Path(config.input_path).expanduser().resolve()
    if not input_path.is_file():
        raise ThreeStageServiceError("Streaming three-stage inference currently supports one file only.")
    if input_path.suffix.lower() == ".mat":
        return _infer_mat_file_streaming(
            engine,
            input_path,
            config,
            progress_callback=progress_callback,
        )
    if input_path.suffix.lower() == ".npy":
        return _infer_npy_file_streaming(
            engine,
            input_path,
            config,
            progress_callback=progress_callback,
        )
    _ensure_supported_input(input_path)
    raise ThreeStageServiceError(f"Unsupported input path: {input_path}")


def extract_candidate_bursts_from_complex_iq(
    iq: np.ndarray,
    *,
    sample_rate_hz: float = THREE_STAGE_FS_HZ,
    slice_len: int = 4096,
) -> list[dict[str, Any]]:
    """Mirror the batch-compatible MAT burst extractor on an in-memory IQ stream."""

    z_raw = _ensure_complex_iq(iq)
    if z_raw.size < slice_len:
        return []

    if abs(float(sample_rate_hz) - THREE_STAGE_FS_HZ) > 1.0:
        raise ThreeStageServiceError(
            f"Three-stage aligned preprocessing expects {THREE_STAGE_FS_HZ / 1e6:.1f} MHz IQ, "
            f"got {float(sample_rate_hz) / 1e6:.3f} MHz."
        )

    t_total = np.arange(z_raw.size, dtype=np.float64) / THREE_STAGE_FS_HZ
    z_shifted = (z_raw * np.exp(-1j * 2 * np.pi * THREE_STAGE_DEFAULT_SHIFT_HZ * t_total)).astype(
        np.complex64,
        copy=False,
    )

    b_pre, a_pre = butter(5, 15e6 / (0.5 * THREE_STAGE_FS_HZ), btype="low")
    z_filtered_pre = filtfilt(b_pre, a_pre, z_shifted).astype(np.complex64, copy=False)
    power = np.abs(z_filtered_pre) ** 2
    p_sum = np.cumsum(np.insert(power, 0, 0.0))
    win_energy = p_sum[THREE_STAGE_DEFAULT_WINDOW_LEN:] - p_sum[:-THREE_STAGE_DEFAULT_WINDOW_LEN]
    if win_energy.size == 0:
        return []

    noise_floor = float(np.percentile(win_energy, 5))
    signal_peak = float(np.percentile(win_energy, 95))
    if signal_peak < noise_floor * 1.5:
        return []

    threshold = noise_floor + (signal_peak - noise_floor) * 0.15
    active_idx = np.where(win_energy > threshold)[0]
    if active_idx.size == 0:
        return []

    bursts: list[dict[str, Any]] = []
    breaks = np.where(np.diff(active_idx) > THREE_STAGE_DEFAULT_GAP)[0]
    start_pointer = 0
    for break_index in list(breaks) + [int(active_idx.size - 1)]:
        s_idx = int(active_idx[start_pointer])
        e_idx = int(active_idx[break_index] + THREE_STAGE_DEFAULT_WINDOW_LEN)
        start_pointer = break_index + 1
        if e_idx - s_idx < slice_len:
            continue

        seg_raw = z_raw[s_idx:e_idx]
        f_psd, psd = welch(seg_raw, fs=THREE_STAGE_FS_HZ, nperseg=1024, return_onesided=False)
        f_psd = np.fft.fftshift(f_psd)
        psd = np.fft.fftshift(psd)
        psd_db = 10 * np.log10(psd + 1e-12)

        valid_mask = (f_psd >= 5e6) & (f_psd <= 38e6)
        valid_f = f_psd[valid_mask]
        valid_psd = psd[valid_mask]
        valid_psd_db = psd_db[valid_mask]
        if valid_psd.size == 0:
            continue

        cumulative_power = np.cumsum(valid_psd)
        total_power = float(cumulative_power[-1])
        if total_power <= 0.0:
            continue

        normalized_power = cumulative_power / total_power
        left_idx = min(int(np.searchsorted(normalized_power, 0.05)), valid_f.size - 1)
        right_idx = min(int(np.searchsorted(normalized_power, 0.95)), valid_f.size - 1)
        obw_hz = float(valid_f[right_idx] - valid_f[left_idx])
        center_hz = float((valid_f[right_idx] + valid_f[left_idx]) / 2)

        obw_psd_db = valid_psd_db[left_idx : right_idx + 1]
        if obw_psd_db.size == 0:
            continue
        prominence = float(np.max(obw_psd_db) - np.median(obw_psd_db))
        if not (10e6 <= obw_hz <= 30e6 and prominence < 14):
            continue

        pure_iq = _extract_pure_burst_with_bandpass(
            z_raw=z_raw,
            s_idx=s_idx,
            e_idx=e_idx,
            center_hz=center_hz,
            bandwidth_hz=obw_hz,
            sample_rate_hz=THREE_STAGE_FS_HZ,
        )
        slice_count = int(pure_iq.size // slice_len)
        if slice_count <= 0:
            continue

        bursts.append(
            {
                "burst_idx": len(bursts),
                "start_idx": s_idx,
                "end_idx": e_idx,
                "center_freq_offset_hz": center_hz,
                "bandwidth_hz": obw_hz,
                "slice_count": slice_count,
                "pure_iq": pure_iq[: slice_count * slice_len].astype(np.complex64, copy=False),
            }
        )

    return bursts


@lru_cache(maxsize=4)
def _load_engine(
    *,
    binary_model_path: Path,
    type_model_path: Path,
    type_metadata_path: Path | None,
    individual_model_path: Path,
    individual_metadata_path: Path | None,
    device: str,
    extractor_mode: str,
) -> Any:
    module = _load_inference_module()
    engine_cls = getattr(module, "ThreeStageRFInference", None)
    if not callable(engine_cls):
        raise ThreeStageServiceError("The deployed three-stage script does not expose ThreeStageRFInference.")

    if not binary_model_path.exists():
        raise ThreeStageServiceError(f"Binary model not found: {binary_model_path}")
    if not type_model_path.exists():
        raise ThreeStageServiceError(f"Type model not found: {type_model_path}")
    if not individual_model_path.exists():
        raise ThreeStageServiceError(f"Individual model not found: {individual_model_path}")
    if type_metadata_path is not None and not type_metadata_path.exists():
        raise ThreeStageServiceError(f"Type metadata not found: {type_metadata_path}")
    if individual_metadata_path is not None and not individual_metadata_path.exists():
        individual_metadata_path = None

    return engine_cls(
        binary_model_path=binary_model_path,
        type_model_path=type_model_path,
        type_metadata_path=type_metadata_path,
        individual_model_path=individual_model_path,
        individual_metadata_path=individual_metadata_path,
        device=device,
        extractor_mode=extractor_mode,
    )


def _load_inference_module() -> ModuleType:
    """Dynamically load the deployed three-stage inference script."""

    if not THREE_STAGE_SCRIPT_PATH.exists():
        raise ThreeStageServiceError(f"Three-stage script not found: {THREE_STAGE_SCRIPT_PATH}")

    spec = spec_from_file_location("deployed_three_stage_inference", THREE_STAGE_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ThreeStageServiceError("Unable to load the deployed three-stage inference module.")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_supported_input(path: Path) -> None:
    raise ThreeStageServiceError("Three-stage backend currently supports .mat raw files and .npy IQ samples only.")


def _infer_npy_file(engine: Any, input_path: Path, config: ThreeStageInferenceConfig) -> dict[str, Any]:
    """Run three-stage classification on one existing IQ sample."""

    raw = np.load(input_path, allow_pickle=False)
    iq = _ensure_complex_iq(raw)
    slice_len = 4096
    total_slices = int(iq.size // slice_len)
    if total_slices <= 0:
        raise ThreeStageServiceError(f"Sample is shorter than one 4096-point slice: {input_path}")

    iq = iq[: total_slices * slice_len].reshape(total_slices, slice_len)
    raw_iq_slices = np.stack([iq.real, iq.imag], axis=1).astype(np.float32, copy=False)

    binary_results = engine.batch_binary_infer([raw_iq_slices], float(config.drone_threshold))
    binary_result = binary_results[0] if binary_results else {
        "is_drone": False,
        "drone_score_p80": 0.0,
        "slice_count": total_slices,
    }
    burst_result: dict[str, Any] = {
        "burst_idx": 0,
        "start_idx": 0,
        "end_idx": int(total_slices * slice_len),
        "center_freq_offset_hz": 0.0,
        "bandwidth_hz": 0.0,
        "slice_count": total_slices,
        "binary_result": binary_result,
    }

    accepted_bursts = 1 if binary_result.get("is_drone") else 0
    overall_type_result: dict[str, Any] | None = None
    overall_individual_result: dict[str, Any] | None = None

    if binary_result.get("is_drone"):
        flat_segments = [segment for segment in raw_iq_slices]
        type_probs, type_stage_sec = engine._build_stage_probs(flat_segments, engine.type_stage)
        individual_probs, individual_stage_sec = engine._build_stage_probs(flat_segments, engine.individual_stage)
        if type_probs is not None:
            type_summary = engine._summarize_stage_probs(type_probs, engine.type_stage["class_names"])
            burst_result["type_result"] = {"total_slices": total_slices, **type_summary}
            overall_type_result = {"total_slices": len(type_probs), **type_summary}
        if individual_probs is not None:
            individual_summary = engine._summarize_stage_probs(individual_probs, engine.individual_stage["class_names"])
            burst_result["individual_result"] = {"total_slices": total_slices, **individual_summary}
            overall_individual_result = {"total_slices": len(individual_probs), **individual_summary}
    else:
        type_stage_sec = 0.0
        individual_stage_sec = 0.0

    return {
        "status": "success" if accepted_bursts else "no_drone_detected",
        "detected_candidate_bursts": 1,
        "accepted_drone_bursts": accepted_bursts,
        "overall_type_result": overall_type_result,
        "overall_individual_result": overall_individual_result,
        "file": str(input_path),
        "burst_results": [burst_result],
        "stats": {
            "candidate_bursts": 1,
            "candidate_slices": total_slices,
            "accepted_drone_bursts": accepted_bursts,
            "type_input_slices": total_slices if accepted_bursts else 0,
            "individual_input_slices": total_slices if accepted_bursts else 0,
        },
        "timings": {
            "preprocess_sec": 0.0,
            "binary_stage_sec": 0.0,
            "type_stage_sec": float(type_stage_sec),
            "individual_stage_sec": float(individual_stage_sec),
            "postprocess_overhead_sec": 0.0,
            "total_sec": float(type_stage_sec + individual_stage_sec),
        },
    }


def _infer_npy_file_streaming(
    engine: Any,
    input_path: Path,
    config: ThreeStageInferenceConfig,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run three-stage classification on one IQ sample and emit a partial type-stage result."""

    raw = np.load(input_path, allow_pickle=False)
    iq = _ensure_complex_iq(raw)
    slice_len = 4096
    total_slices = int(iq.size // slice_len)
    if total_slices <= 0:
        raise ThreeStageServiceError(f"Sample is shorter than one 4096-point slice: {input_path}")

    start_time = time.perf_counter()
    iq = iq[: total_slices * slice_len].reshape(total_slices, slice_len)
    raw_iq_slices = np.stack([iq.real, iq.imag], axis=1).astype(np.float32, copy=False)

    binary_results = engine.batch_binary_infer([raw_iq_slices], float(config.drone_threshold))
    binary_result = binary_results[0] if binary_results else {
        "is_drone": False,
        "drone_score_p80": 0.0,
        "slice_count": total_slices,
    }
    burst_result: dict[str, Any] = {
        "burst_idx": 0,
        "start_idx": 0,
        "end_idx": int(total_slices * slice_len),
        "center_freq_offset_hz": 0.0,
        "bandwidth_hz": 0.0,
        "slice_count": total_slices,
        "binary_result": binary_result,
    }

    accepted_bursts = 1 if binary_result.get("is_drone") else 0
    overall_type_result: dict[str, Any] | None = None
    overall_individual_result: dict[str, Any] | None = None
    type_stage_sec = 0.0
    individual_stage_sec = 0.0

    if binary_result.get("is_drone"):
        flat_segments = [segment for segment in raw_iq_slices]
        type_probs, type_stage_sec, shared_payload = _build_shared_stage_probs(engine, flat_segments)
        if type_probs is not None:
            type_summary = engine._summarize_stage_probs(type_probs, engine.type_stage["class_names"])
            burst_result["type_result"] = {"total_slices": total_slices, **type_summary}
            overall_type_result = {"total_slices": len(type_probs), **type_summary}

        partial_result = {
            "status": "success",
            "detected_candidate_bursts": 1,
            "accepted_drone_bursts": accepted_bursts,
            "overall_type_result": overall_type_result,
            "overall_individual_result": None,
            "file": str(input_path),
            "burst_results": [burst_result.copy()],
            "stats": {
                "candidate_bursts": 1,
                "candidate_slices": total_slices,
                "accepted_drone_bursts": accepted_bursts,
                "type_input_slices": total_slices,
                "individual_input_slices": total_slices,
            },
            "timings": {
                "preprocess_sec": 0.0,
                "binary_stage_sec": 0.0,
                "type_stage_sec": float(type_stage_sec),
                "individual_stage_sec": 0.0,
                "postprocess_overhead_sec": 0.0,
                "total_sec": float(time.perf_counter() - start_time),
            },
        }
        if progress_callback is not None:
            progress_callback({"kind": "three_stage_partial", "raw_result": partial_result})

        if engine._stage_cfg_key(engine.type_stage) == engine._stage_cfg_key(engine.individual_stage):
            individual_probs, individual_stage_sec = _run_individual_from_shared_features(engine, shared_payload)
        else:
            individual_probs, individual_stage_sec = engine._build_stage_probs(flat_segments, engine.individual_stage)
        if individual_probs is not None:
            individual_summary = engine._summarize_stage_probs(individual_probs, engine.individual_stage["class_names"])
            burst_result["individual_result"] = {"total_slices": total_slices, **individual_summary}
            overall_individual_result = {"total_slices": len(individual_probs), **individual_summary}

    result = {
        "status": "success" if accepted_bursts else "no_drone_detected",
        "detected_candidate_bursts": 1,
        "accepted_drone_bursts": accepted_bursts,
        "overall_type_result": overall_type_result,
        "overall_individual_result": overall_individual_result,
        "file": str(input_path),
        "burst_results": [burst_result],
        "stats": {
            "candidate_bursts": 1,
            "candidate_slices": total_slices,
            "accepted_drone_bursts": accepted_bursts,
            "type_input_slices": total_slices if accepted_bursts else 0,
            "individual_input_slices": total_slices if accepted_bursts else 0,
        },
        "timings": {
            "preprocess_sec": 0.0,
            "binary_stage_sec": 0.0,
            "type_stage_sec": float(type_stage_sec),
            "individual_stage_sec": float(individual_stage_sec),
            "postprocess_overhead_sec": 0.0,
            "total_sec": float(time.perf_counter() - start_time),
        },
    }
    return result


def _build_shared_stage_probs(
    engine: Any,
    flat_segments: list[np.ndarray],
) -> tuple[np.ndarray | None, float, Any | None]:
    """Reuse one STFT feature tensor for both type and individual stages when configs match."""

    if not flat_segments:
        return None, 0.0, None

    if engine._stage_cfg_key(engine.type_stage) != engine._stage_cfg_key(engine.individual_stage):
        type_probs, type_stage_sec = engine._build_stage_probs(flat_segments, engine.type_stage)
        return type_probs, type_stage_sec, None

    shared_start = time.perf_counter()
    feats = [engine._compute_stft_scipy(np.asarray(seg, dtype=np.float32), engine.type_stage) for seg in flat_segments]
    feats_tensor = np.stack(feats, axis=0)
    feats_tensor = _to_stage_tensor(engine, feats_tensor)

    type_start = time.perf_counter()
    with _stage_no_grad():
        type_probs = _stage_softmax_numpy(engine.type_stage["model"], feats_tensor)
    type_stage_sec = time.perf_counter() - type_start

    shared_elapsed = time.perf_counter() - shared_start
    shared_feat_sec = max(0.0, shared_elapsed - type_stage_sec)
    type_stage_sec += shared_feat_sec
    return type_probs, type_stage_sec, feats_tensor


def _run_individual_from_shared_features(
    engine: Any,
    feats_tensor: Any,
) -> tuple[np.ndarray | None, float]:
    """Run the individual stage on an already prepared shared feature tensor."""

    if feats_tensor is None:
        return None, 0.0
    individual_start = time.perf_counter()
    with _stage_no_grad():
        individual_probs = _stage_softmax_numpy(engine.individual_stage["model"], feats_tensor)
    individual_stage_sec = time.perf_counter() - individual_start
    return individual_probs, individual_stage_sec


def _to_stage_tensor(engine: Any, feats_array: np.ndarray) -> Any:
    import torch

    return torch.tensor(feats_array, dtype=torch.float32).to(engine.device)


def _stage_softmax_numpy(model: Any, feats_tensor: Any) -> np.ndarray:
    import torch

    return torch.softmax(model(feats_tensor), dim=1).cpu().numpy()


def _stage_no_grad():
    import torch

    return torch.no_grad()


def _infer_mat_file_streaming(
    engine: Any,
    input_path: Path,
    config: ThreeStageInferenceConfig,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one MAT inference and emit a partial result right after the type stage."""

    module = _load_inference_module()
    extractor = getattr(module, "extract_candidate_bursts_from_mat", None)
    slice_len = int(getattr(module, "SLICE_LEN", 4096))
    if not callable(extractor):
        raise ThreeStageServiceError("The deployed three-stage script does not expose extract_candidate_bursts_from_mat.")

    t0 = time.perf_counter()
    cache_key = (
        str(input_path),
        float(config.min_bw_mhz),
        float(config.max_bw_mhz),
        str(engine.extractor_mode),
    )
    cached = _MAT_PREPROCESS_CACHE.get(cache_key)
    if cached is None:
        bursts = extractor(
            input_path,
            engine.device,
            extractor_mode=engine.extractor_mode,
            min_bw_mhz=float(config.min_bw_mhz),
            max_bw_mhz=float(config.max_bw_mhz),
            slice_len=slice_len,
        )
        _MAT_PREPROCESS_CACHE[cache_key] = {
            "bursts": bursts,
            "slice_len": slice_len,
        }
    else:
        bursts = cached["bursts"]
    t1 = time.perf_counter()

    all_iq = [b["raw_iq_slices"] for b in bursts]
    binary_start = time.perf_counter()
    binary_results = engine.batch_binary_infer(all_iq, float(config.drone_threshold))
    binary_stage_sec = time.perf_counter() - binary_start

    accepted_iq: list[np.ndarray] = []
    accepted_indices: list[int] = []
    burst_results: list[dict[str, Any]] = []
    for i, (burst, res) in enumerate(zip(bursts, binary_results)):
        burst_result = {**burst, "binary_result": res}
        burst_result.pop("raw_iq_slices", None)
        if res["is_drone"]:
            accepted_iq.append(burst["raw_iq_slices"])
            accepted_indices.append(i)
        burst_results.append(burst_result)

    flat_segments = [seg for slices in accepted_iq for seg in slices]
    type_stage_sec = 0.0
    individual_stage_sec = 0.0
    type_probs = None
    individual_probs = None

    if flat_segments:
        type_probs, type_stage_sec, shared_payload = _build_shared_stage_probs(engine, flat_segments)
        cursor = 0
        for idx in accepted_indices:
            cnt = burst_results[idx]["slice_count"]
            if type_probs is not None:
                type_summary = engine._summarize_stage_probs(type_probs[cursor : cursor + cnt], engine.type_stage["class_names"])
                burst_results[idx]["type_result"] = {"total_slices": cnt, **type_summary}
            cursor += cnt

        accepted_bursts = [b for b in burst_results if b.get("binary_result", {}).get("is_drone")]
        overall_type_result = None
        if type_probs is not None:
            overall_type_result = {
                "total_slices": len(type_probs),
                **engine._summarize_stage_probs(type_probs, engine.type_stage["class_names"]),
            }
        candidate_slices = sum(b["slice_count"] for b in bursts) if bursts else 0
        accepted_slices = len(flat_segments)
        partial_result = {
            "status": "success" if accepted_bursts else "no_drone_detected",
            "detected_candidate_bursts": len(bursts),
            "accepted_drone_bursts": len(accepted_bursts),
            "overall_type_result": overall_type_result,
            "overall_individual_result": None,
            "file": str(input_path),
            "burst_results": [dict(item) for item in burst_results],
            "stats": {
                "candidate_bursts": len(bursts),
                "candidate_slices": candidate_slices,
                "accepted_drone_bursts": len(accepted_bursts),
                "type_input_slices": accepted_slices,
                "individual_input_slices": accepted_slices,
            },
            "timings": {
                "preprocess_sec": float(t1 - t0),
                "binary_stage_sec": float(binary_stage_sec),
                "type_stage_sec": float(type_stage_sec),
                "individual_stage_sec": 0.0,
                "postprocess_overhead_sec": 0.0,
                "total_sec": float(time.perf_counter() - t0),
            },
        }
        if progress_callback is not None:
            progress_callback({"kind": "three_stage_partial", "raw_result": partial_result})

        if engine._stage_cfg_key(engine.type_stage) == engine._stage_cfg_key(engine.individual_stage):
            individual_probs, individual_stage_sec = _run_individual_from_shared_features(engine, shared_payload)
        else:
            individual_probs, individual_stage_sec = engine._build_stage_probs(flat_segments, engine.individual_stage)
        cursor = 0
        for idx in accepted_indices:
            cnt = burst_results[idx]["slice_count"]
            if individual_probs is not None:
                individual_summary = engine._summarize_stage_probs(
                    individual_probs[cursor : cursor + cnt],
                    engine.individual_stage["class_names"],
                )
                burst_results[idx]["individual_result"] = {"total_slices": cnt, **individual_summary}
            cursor += cnt

    t_end = time.perf_counter()
    accepted_bursts = [b for b in burst_results if b.get("binary_result", {}).get("is_drone")]
    overall_type_result = None
    if type_probs is not None:
        overall_type_result = {"total_slices": len(type_probs), **engine._summarize_stage_probs(type_probs, engine.type_stage["class_names"])}
    overall_individual_result = None
    if individual_probs is not None:
        overall_individual_result = {
            "total_slices": len(individual_probs),
            **engine._summarize_stage_probs(individual_probs, engine.individual_stage["class_names"]),
        }
    candidate_slices = sum(b["slice_count"] for b in bursts) if bursts else 0
    accepted_slices = len(flat_segments)

    return {
        "status": "success" if accepted_bursts else "no_drone_detected",
        "detected_candidate_bursts": len(bursts),
        "accepted_drone_bursts": len(accepted_bursts),
        "overall_type_result": overall_type_result,
        "overall_individual_result": overall_individual_result,
        "file": str(input_path),
        "burst_results": burst_results,
        "stats": {
            "candidate_bursts": len(bursts),
            "candidate_slices": candidate_slices,
            "accepted_drone_bursts": len(accepted_bursts),
            "type_input_slices": accepted_slices,
            "individual_input_slices": accepted_slices,
        },
        "timings": {
            "preprocess_sec": float(t1 - t0),
            "binary_stage_sec": float(binary_stage_sec),
            "type_stage_sec": float(type_stage_sec),
            "individual_stage_sec": float(individual_stage_sec),
            "postprocess_overhead_sec": float(max(0.0, (t_end - t1) - binary_stage_sec - type_stage_sec - individual_stage_sec)),
            "total_sec": float(t_end - t0),
        },
    }


def _ensure_complex_iq(raw: np.ndarray) -> np.ndarray:
    flat = np.asarray(raw).reshape(-1)
    if np.iscomplexobj(flat):
        return flat.astype(np.complex64, copy=False)
    if flat.size % 2 != 0:
        raise ThreeStageServiceError("Current sample is not a valid complex IQ sequence.")
    real = flat[0::2].astype(np.float32, copy=False)
    imag = flat[1::2].astype(np.float32, copy=False)
    return (real + 1j * imag).astype(np.complex64, copy=False)


def _extract_pure_burst_with_bandpass(
    *,
    z_raw: np.ndarray,
    s_idx: int,
    e_idx: int,
    center_hz: float,
    bandwidth_hz: float,
    sample_rate_hz: float,
    margin_mhz: float = 2.0,
) -> np.ndarray:
    """Apply the same bandpass-plus-baseband-shift step used in success_three_stage."""

    z_seg = z_raw[s_idx:e_idx].astype(np.complex64, copy=False)
    bandwidth_with_margin = min(bandwidth_hz + (margin_mhz * 1e6), sample_rate_hz * 0.45)
    lowcut = max(center_hz - (bandwidth_with_margin / 2.0), 1e5)
    highcut = min(center_hz + (bandwidth_with_margin / 2.0), (sample_rate_hz / 2.0) - 1e5)

    if lowcut < highcut:
        nyquist = 0.5 * sample_rate_hz
        try:
            b, a = butter(5, [lowcut / nyquist, highcut / nyquist], btype="band")
            z_filtered = filtfilt(b, a, z_seg).astype(np.complex64, copy=False)
        except ValueError:
            z_filtered = z_seg
    else:
        z_filtered = z_seg

    t_seg = np.arange(z_filtered.size, dtype=np.float64) / sample_rate_hz
    return (z_filtered * np.exp(-1j * 2 * np.pi * center_hz * t_seg)).astype(np.complex64, copy=False)
