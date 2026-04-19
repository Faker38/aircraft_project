"""Import helpers for RFUAV public IQ datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from services.workflow_records import SampleRecord


RFUAV_DATA_FORMAT = "complex_float32_iq"
FLOAT32_IQ_PAIR_BYTES = 8


class RFUAVImportError(RuntimeError):
    """Raised when an RFUAV dataset cannot be imported safely."""


class RFUAVImportCancelledError(RFUAVImportError):
    """Raised when an RFUAV import task is cancelled by the user."""


@dataclass(frozen=True)
class RFUAVIQFileInfo:
    """One IQ file entry discovered inside an RFUAV dataset directory."""

    name: str
    path: Path
    size_bytes: int


@dataclass(frozen=True)
class RFUAVDatasetProbe:
    """Metadata discovered from one RFUAV dataset directory."""

    dataset_root: Path
    drone_label: str
    serial_number: str
    data_type: str
    center_frequency_hz: float
    sample_rate_hz: float
    iq_files: list[RFUAVIQFileInfo]
    xml_path: Path


@dataclass(frozen=True)
class RFUAVImportResult:
    """Summary of one RFUAV import operation."""

    dataset_name: str
    dataset_root: Path
    imported_raw_file_count: int
    generated_sample_count: int
    label_type: str
    label_individual: str
    selected_file_name: str
    created_sample_paths: list[str]
    sample_records: list[SampleRecord]


def probe_rfuav_dataset(dataset_root: Path) -> RFUAVDatasetProbe:
    """Read one RFUAV dataset manifest without generating samples."""

    root = Path(dataset_root)
    if not root.exists() or not root.is_dir():
        raise RFUAVImportError("公开数据目录不存在，无法执行导入。")

    xml_files = sorted(root.glob("*.xml"))
    if not xml_files:
        raise RFUAVImportError("未找到 RFUAV 数据描述文件（*.xml）。")

    xml_path = xml_files[0]
    try:
        xml_root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        raise RFUAVImportError(f"公开数据 XML 解析失败：{exc}") from exc

    iq_paths = sorted(root.glob("*.iq"))
    if not iq_paths:
        raise RFUAVImportError("未找到 RFUAV IQ 数据文件（*.iq）。")

    iq_files = [
        RFUAVIQFileInfo(name=path.name, path=path, size_bytes=path.stat().st_size)
        for path in iq_paths
    ]

    drone_label = _read_required_text(xml_root, "Drone")
    serial_number = _read_required_text(xml_root, "SerialNumber")
    data_type = _read_required_text(xml_root, "DataType")
    center_frequency_hz = _read_required_float(xml_root, "CenterFrequency")
    sample_rate_hz = _read_required_float(xml_root, "SampleRate")

    return RFUAVDatasetProbe(
        dataset_root=root,
        drone_label=drone_label,
        serial_number=serial_number,
        data_type=data_type,
        center_frequency_hz=center_frequency_hz,
        sample_rate_hz=sample_rate_hz,
        iq_files=iq_files,
        xml_path=xml_path,
    )


def estimate_rfuav_sample_count(file_size_bytes: int, slice_length: int) -> int:
    """Estimate how many fixed-window samples one IQ file will yield."""

    if slice_length <= 0:
        return 0
    sample_bytes = slice_length * FLOAT32_IQ_PAIR_BYTES
    if sample_bytes <= 0:
        return 0
    return file_size_bytes // sample_bytes


def import_rfuav_dataset(
    dataset_root: Path,
    selected_iq_file: Path | str,
    slice_length: int,
    output_dir: Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
    cancel_checker: Callable[[], bool] | None = None,
) -> RFUAVImportResult:
    """Import one selected RFUAV IQ file into fixed-window sample files."""

    if slice_length <= 0:
        raise RFUAVImportError("切片长度必须大于 0。")

    probe = probe_rfuav_dataset(dataset_root)
    if probe.data_type.strip().lower() != "complex float":
        raise RFUAVImportError(f"当前仅支持 Complex Float，收到：{probe.data_type}")

    selected_info = _resolve_selected_iq_file(probe, selected_iq_file)
    total_windows = estimate_rfuav_sample_count(selected_info.size_bytes, slice_length)
    if total_windows <= 0:
        raise RFUAVImportError("未生成任何样本，请检查切片长度是否超过所选 IQ 文件长度。")

    dataset_name = _sanitize_token(probe.drone_label)
    device_id = f"{dataset_name}_{probe.serial_number}"
    run_token = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_root = Path(output_dir) / dataset_name / f"{selected_info.path.stem}_L{slice_length}_{run_token}"
    target_root.mkdir(parents=True, exist_ok=True)

    sample_records: list[SampleRecord] = []
    created_sample_paths: list[str] = []
    sample_bytes = slice_length * FLOAT32_IQ_PAIR_BYTES

    output_root = Path(output_dir)

    try:
        with selected_info.path.open("rb") as source:
            for window_index in range(total_windows):
                if cancel_checker is not None and cancel_checker():
                    raise RFUAVImportCancelledError("公开数据导入已取消。")

                chunk = source.read(sample_bytes)
                if len(chunk) < sample_bytes:
                    break

                sample_file_name = f"{selected_info.path.stem}_slice_{window_index:05d}.iq"
                sample_path = target_root / sample_file_name
                sample_path.write_bytes(chunk)
                created_sample_paths.append(str(sample_path))

                start_sample = window_index * slice_length
                end_sample = start_sample + slice_length - 1
                sample_records.append(
                    SampleRecord(
                        sample_id=f"rfuav_{window_index + 1:05d}",
                        source_type="rfuav_public",
                        raw_file_path=str(selected_info.path),
                        sample_file_path=str(sample_path),
                        label_type=dataset_name,
                        label_individual=device_id,
                        sample_rate_hz=probe.sample_rate_hz,
                        center_frequency_hz=probe.center_frequency_hz,
                        data_format=RFUAV_DATA_FORMAT,
                        sample_count=slice_length,
                        device_id=device_id,
                        start_sample=start_sample,
                        end_sample=end_sample,
                        status="已标注",
                        source_name=probe.drone_label,
                    )
                )

                if progress_callback is not None:
                    progress_callback(
                        window_index + 1,
                        total_windows,
                        f"正在切片 {selected_info.name} | {window_index + 1}/{total_windows}",
                    )
    except Exception:
        _cleanup_created_samples(created_sample_paths)
        _cleanup_empty_parent_dirs(target_root, output_root)
        raise

    if not sample_records:
        _cleanup_empty_parent_dirs(target_root, output_root)
        raise RFUAVImportError("未生成任何样本，请检查切片长度是否超过所选 IQ 文件长度。")

    return RFUAVImportResult(
        dataset_name=dataset_name,
        dataset_root=probe.dataset_root,
        imported_raw_file_count=1,
        generated_sample_count=len(sample_records),
        label_type=dataset_name,
        label_individual=device_id,
        selected_file_name=selected_info.name,
        created_sample_paths=created_sample_paths,
        sample_records=sample_records,
    )


def _resolve_selected_iq_file(probe: RFUAVDatasetProbe, selected_iq_file: Path | str) -> RFUAVIQFileInfo:
    """Return the IQ file info that matches the selected file."""

    selected_path = Path(selected_iq_file)
    for file_info in probe.iq_files:
        if file_info.path == selected_path or file_info.name == selected_path.name:
            return file_info
    raise RFUAVImportError("所选 IQ 文件不属于当前公开数据目录。")


def _cleanup_created_samples(created_sample_paths: list[str]) -> None:
    """Delete sample files created by one failed or cancelled import task."""

    for file_path in created_sample_paths:
        path = Path(file_path)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            continue


def _cleanup_empty_parent_dirs(target_root: Path, stop_root: Path) -> None:
    """Remove one now-empty output directory chain after cleanup."""

    current = target_root
    stop_root_resolved = stop_root.resolve()
    while True:
        try:
            current_resolved = current.resolve()
        except OSError:
            break
        if current_resolved == stop_root_resolved:
            break
        try:
            if current.exists() and not any(current.iterdir()):
                current.rmdir()
            else:
                break
        except OSError:
            break
        if current.parent == current:
            break
        current = current.parent


def _read_required_text(xml_root: ET.Element, tag: str) -> str:
    """Return one required text field from the dataset manifest."""

    node = xml_root.find(tag)
    text = node.text.strip() if node is not None and node.text else ""
    if not text:
        raise RFUAVImportError(f"公开数据 XML 缺少字段：{tag}")
    return text


def _read_required_float(xml_root: ET.Element, tag: str) -> float:
    """Return one required numeric field from the dataset manifest."""

    text = _read_required_text(xml_root, tag)
    try:
        return float(text)
    except ValueError as exc:
        raise RFUAVImportError(f"字段 {tag} 不是有效数值：{text}") from exc


def _sanitize_token(value: str) -> str:
    """Normalize one public label for file names and display tokens."""

    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", value.strip())
    return cleaned.strip("_") or "RFUAV_Sample"
