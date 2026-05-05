"""Runtime selection and warmup state for deployed three-stage inference."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import (
    THREE_STAGE_BINARY_MODEL_PATH,
    THREE_STAGE_DEVICE,
    THREE_STAGE_EXTRACTOR_MODE,
    THREE_STAGE_INDIVIDUAL_META_PATH,
    THREE_STAGE_INDIVIDUAL_MODEL_PATH,
    THREE_STAGE_TYPE_META_PATH,
    THREE_STAGE_TYPE_MODEL_PATH,
)
from services.three_stage_service import build_three_stage_config, run_three_stage_inference


@dataclass(frozen=True)
class ThreeStageRuntimeSelection:
    binary_model_path: str
    type_model_path: str
    type_metadata_path: str
    individual_model_path: str
    individual_metadata_path: str
    device: str = THREE_STAGE_DEVICE
    extractor_mode: str = THREE_STAGE_EXTRACTOR_MODE


_runtime_selection = ThreeStageRuntimeSelection(
    binary_model_path=str(THREE_STAGE_BINARY_MODEL_PATH),
    type_model_path=str(THREE_STAGE_TYPE_MODEL_PATH),
    type_metadata_path=str(THREE_STAGE_TYPE_META_PATH),
    individual_model_path=str(THREE_STAGE_INDIVIDUAL_MODEL_PATH),
    individual_metadata_path=str(THREE_STAGE_INDIVIDUAL_META_PATH if THREE_STAGE_INDIVIDUAL_META_PATH.exists() else ""),
)


def get_three_stage_runtime_selection() -> ThreeStageRuntimeSelection:
    return _runtime_selection


def set_three_stage_runtime_selection(selection: ThreeStageRuntimeSelection) -> None:
    global _runtime_selection
    _runtime_selection = selection


def warmup_three_stage_runtime(sample_file_path: str) -> dict[str, object]:
    config = build_three_stage_config(
        sample_file_path,
        binary_model_path=_runtime_selection.binary_model_path,
        type_model_path=_runtime_selection.type_model_path,
        type_metadata_path=_runtime_selection.type_metadata_path or None,
        individual_model_path=_runtime_selection.individual_model_path,
        individual_metadata_path=_runtime_selection.individual_metadata_path or None,
        device=_runtime_selection.device,
        extractor_mode=_runtime_selection.extractor_mode,
    )
    return run_three_stage_inference(config)


def resolve_three_stage_warmup_sample() -> str:
    candidates = [
        Path(r"D:\pythonProject10\success_three_stage"),
        Path(r"D:\pythonProject10"),
    ]
    mat_files: list[Path] = []
    for base_dir in candidates:
        if not base_dir.exists():
            continue
        mat_files.extend(sorted(base_dir.glob("*.mat")))
    if not mat_files:
        raise FileNotFoundError("No local .mat file found for three-stage warmup.")
    best = min(mat_files, key=lambda path: (path.stat().st_size, path.name.lower()))
    return str(best.resolve())


def validate_three_stage_selection(selection: ThreeStageRuntimeSelection) -> None:
    required_paths = [
        ("binary_model_path", selection.binary_model_path),
        ("type_model_path", selection.type_model_path),
        ("type_metadata_path", selection.type_metadata_path),
        ("individual_model_path", selection.individual_model_path),
    ]
    for field_name, raw_path in required_paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"{field_name} not found: {path}")
    if selection.individual_metadata_path:
        meta_path = Path(selection.individual_metadata_path).expanduser()
        if not meta_path.exists():
            raise FileNotFoundError(f"individual_metadata_path not found: {meta_path}")
