"""Read-only CAP probe utilities for previewing monitored IQ files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


HEADER_LENGTH = 0x2C00
PREVIEW_PAIR_COUNT = 12
STAT_WINDOW_BYTES = 1024 * 1024


class CapProbeError(RuntimeError):
    """Raised when a CAP file cannot be probed safely."""


@dataclass(frozen=True)
class IQStatistics:
    """Summary statistics for one IQ sample window."""

    sample_count: int
    i_mean: float
    q_mean: float
    i_std: float
    q_std: float
    i_min: int
    i_max: int
    q_min: int
    q_max: int


@dataclass(frozen=True)
class CapProbeResult:
    """Structured preview data extracted from a CAP file."""

    path: Path
    file_size: int
    is_partial_capture: bool
    version: str
    header_length: int
    sample_rate_hz: float
    center_frequency_hz: float
    frame_sample_count: int
    block_size: int
    iq_pair_count: int
    statistics_window_pairs: int
    preview_pairs: list[tuple[int, int, int]]
    statistics: IQStatistics
    unresolved_fields: tuple[str, ...]


def probe_cap_file(path: Path) -> CapProbeResult:
    """Read verified CAP header fields and a small IQ preview window."""

    file_path = Path(path)
    if file_path.suffix.lower() != ".cap":
        raise CapProbeError("仅支持读取 .cap 文件。")
    if not file_path.exists():
        raise CapProbeError("文件不存在，无法执行导入预览。")

    file_size = file_path.stat().st_size
    if file_size <= HEADER_LENGTH:
        raise CapProbeError("文件长度不足，未达到有效 CAP 头部和 IQ 数据区。")
    if (file_size - HEADER_LENGTH) % 4 != 0:
        raise CapProbeError("文件大小与 IQ 对齐规则不符，无法按 I/Q 交织解析。")

    with file_path.open("rb") as handle:
        header = handle.read(HEADER_LENGTH)
        if len(header) < HEADER_LENGTH:
            raise CapProbeError("读取 CAP 头部失败。")

        version_bytes = header[0x0000:0x0008]
        version = version_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        if not version.startswith("B."):
            raise CapProbeError("文件头版本标记异常，不符合当前 CAP 预览规则。")

        sample_rate_hz = struct.unpack(">d", header[0x0010:0x0018])[0]
        center_frequency_hz = struct.unpack(">d", header[0x0018:0x0020])[0]
        frame_sample_count = struct.unpack(">I", header[0x0110:0x0114])[0]
        block_size = struct.unpack(">I", header[0x0114:0x0118])[0]

        iq_pair_count = (file_size - HEADER_LENGTH) // 4
        preview_bytes = handle.read(min(PREVIEW_PAIR_COUNT * 4, file_size - HEADER_LENGTH))
        preview_pairs = _decode_iq_pairs(preview_bytes)

        handle.seek(HEADER_LENGTH)
        statistics_window_bytes = min(file_size - HEADER_LENGTH, STAT_WINDOW_BYTES)
        statistics_bytes = handle.read(statistics_window_bytes)
        statistics = _build_statistics(statistics_bytes)

    unresolved_fields = (
        "0x0008 未确认参数",
        "0x0020 - 0x00FF 其他设备参数",
        "带宽/增益/时间戳编码方式待进一步验证",
    )
    return CapProbeResult(
        path=file_path,
        file_size=file_size,
        is_partial_capture=file_path.name.lower() == "head.cap",
        version=version,
        header_length=HEADER_LENGTH,
        sample_rate_hz=sample_rate_hz,
        center_frequency_hz=center_frequency_hz,
        frame_sample_count=frame_sample_count,
        block_size=block_size,
        iq_pair_count=iq_pair_count,
        statistics_window_pairs=statistics.sample_count,
        preview_pairs=[(index, i_value, q_value) for index, (i_value, q_value) in enumerate(preview_pairs)],
        statistics=statistics,
        unresolved_fields=unresolved_fields,
    )


def _decode_iq_pairs(data: bytes) -> list[tuple[int, int]]:
    """Decode a CAP IQ byte block as big-endian int16 I/Q pairs."""

    if not data:
        return []
    values = struct.unpack(">" + "h" * (len(data) // 2), data)
    return list(zip(values[0::2], values[1::2]))


def _build_statistics(data: bytes) -> IQStatistics:
    """Compute summary statistics for a limited IQ data window."""

    pairs = _decode_iq_pairs(data)
    if not pairs:
        raise CapProbeError("IQ 数据区为空，无法生成导入预览。")

    i_values = [i_value for i_value, _ in pairs]
    q_values = [q_value for _, q_value in pairs]
    sample_count = len(pairs)
    i_mean = sum(i_values) / sample_count
    q_mean = sum(q_values) / sample_count
    i_std = _population_std(i_values, i_mean)
    q_std = _population_std(q_values, q_mean)

    return IQStatistics(
        sample_count=sample_count,
        i_mean=i_mean,
        q_mean=q_mean,
        i_std=i_std,
        q_std=q_std,
        i_min=min(i_values),
        i_max=max(i_values),
        q_min=min(q_values),
        q_max=max(q_values),
    )


def _population_std(values: list[int], mean: float) -> float:
    """Return the population standard deviation for one value sequence."""

    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5
