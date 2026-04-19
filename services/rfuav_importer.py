"""Import helpers for RFUAV public IQ datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from services.workflow_records import SampleRecord


RFUAV_DATA_FORMAT = "complex_float32_iq"
FLOAT32_IQ_PAIR_BYTES = 8


class RFUAVImportError(RuntimeError):
    """Raised when an RFUAV dataset cannot be imported safely."""


@dataclass(frozen=True)
class RFUAVDatasetProbe:
    """Metadata discovered from one RFUAV dataset directory."""

    dataset_root: Path
    drone_label: str
    serial_number: str
    data_type: str
    center_frequency_hz: float
    sample_rate_hz: float
    iq_files: list[Path]
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

    iq_files = sorted(root.glob("*.iq"))
    if not iq_files:
        raise RFUAVImportError("未找到 RFUAV IQ 数据文件（*.iq）。")

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


def import_rfuav_dataset(
    dataset_root: Path,
    slice_length: int,
    output_dir: Path,
) -> RFUAVImportResult:
    """Import one RFUAV public dataset into fixed-window sample files."""

    if slice_length <= 0:
        raise RFUAVImportError("切片长度必须大于 0。")

    probe = probe_rfuav_dataset(dataset_root)
    if probe.data_type.strip().lower() != "complex float":
        raise RFUAVImportError(f"当前仅支持 Complex Float，收到：{probe.data_type}")

    dataset_name = _sanitize_token(probe.drone_label)
    device_id = f"{dataset_name}_{probe.serial_number}"
    target_root = Path(output_dir) / dataset_name
    target_root.mkdir(parents=True, exist_ok=True)

    sample_records: list[SampleRecord] = []
    sample_bytes = slice_length * FLOAT32_IQ_PAIR_BYTES
    sample_index = 1

    for raw_file in probe.iq_files:
        raw_size = raw_file.stat().st_size
        if raw_size < sample_bytes:
            continue

        valid_windows = raw_size // sample_bytes
        with raw_file.open("rb") as source:
            for window_index in range(valid_windows):
                chunk = source.read(sample_bytes)
                if len(chunk) < sample_bytes:
                    break

                sample_file_name = f"{raw_file.stem}_slice_{window_index:05d}.iq"
                sample_path = target_root / sample_file_name
                sample_path.write_bytes(chunk)

                start_sample = window_index * slice_length
                end_sample = start_sample + slice_length - 1
                sample_records.append(
                    SampleRecord(
                        sample_id=f"rfuav_{sample_index:05d}",
                        source_type="rfuav_public",
                        raw_file_path=str(raw_file),
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
                sample_index += 1

    if not sample_records:
        raise RFUAVImportError("未生成任何样本，请检查切片长度是否超过原始数据长度。")

    return RFUAVImportResult(
        dataset_name=dataset_name,
        dataset_root=probe.dataset_root,
        imported_raw_file_count=len(probe.iq_files),
        generated_sample_count=len(sample_records),
        label_type=dataset_name,
        label_individual=device_id,
        sample_records=sample_records,
    )


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
