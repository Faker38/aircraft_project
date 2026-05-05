"""CAP probe helpers for previewing headers and decoding complex IQ."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

import numpy as np


HEADER_LENGTH = 0x200
PREVIEW_PAIR_COUNT = 12
STAT_WINDOW_BYTES = 1024 * 1024


class CapProbeError(RuntimeError):
    """Raised when a CAP file cannot be parsed safely."""


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
    """Structured CAP preview metadata used by the UI and preprocess layer."""

    path: Path
    file_size: int
    is_partial_capture: bool
    version: str
    header_length: int
    bandwidth_hz: float
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
    """Read the CAP header and a small IQ preview window."""

    file_path = Path(path)
    if file_path.suffix.lower() != ".cap":
        raise CapProbeError("Only .cap files are supported.")
    if not file_path.exists():
        raise CapProbeError("CAP file does not exist.")

    file_size = file_path.stat().st_size
    if file_size <= HEADER_LENGTH:
        raise CapProbeError("CAP file is shorter than the fixed header.")
    if (file_size - HEADER_LENGTH) % 4 != 0:
        raise CapProbeError("CAP payload is not aligned to int16 IQ pairs.")

    with file_path.open("rb") as handle:
        header = handle.read(HEADER_LENGTH)
        if len(header) < HEADER_LENGTH:
            raise CapProbeError("Failed to read the CAP header.")

        version_bytes = header[0x0000:0x0008]
        version = version_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        if not version.startswith("B."):
            raise CapProbeError("CAP version marker is not recognized.")

        bandwidth_hz = struct.unpack(">d", header[0x0010:0x0018])[0]
        sample_rate_hz = bandwidth_hz * 1.28
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
        "0x0008 parameter meaning is still unconfirmed",
        "0x0020-0x00FF device-specific fields still need validation",
        "bandwidth, gain, and time-encoding assumptions should be cross-checked on more samples",
    )
    return CapProbeResult(
        path=file_path,
        file_size=file_size,
        is_partial_capture=file_path.name.lower() == "head.cap",
        version=version,
        header_length=HEADER_LENGTH,
        bandwidth_hz=bandwidth_hz,
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


def load_cap_complex_iq(path: Path) -> np.ndarray:
    """Load the CAP payload as one complex64 IQ sequence."""

    file_path = Path(path)
    if file_path.suffix.lower() != ".cap":
        raise CapProbeError("Only .cap files are supported.")
    if not file_path.exists():
        raise CapProbeError("CAP file does not exist.")

    file_size = file_path.stat().st_size
    payload_size = file_size - HEADER_LENGTH
    if payload_size <= 0:
        raise CapProbeError("CAP payload is empty.")
    if payload_size % 4 != 0:
        raise CapProbeError("CAP payload is not aligned to int16 IQ pairs.")

    with file_path.open("rb") as handle:
        handle.seek(HEADER_LENGTH)
        payload = handle.read()

    iq_int16 = np.frombuffer(payload, dtype=">i2")
    if iq_int16.size % 2 != 0:
        raise CapProbeError("CAP payload does not contain complete IQ pairs.")

    i_values = iq_int16[0::2].astype(np.float32, copy=False)
    q_values = iq_int16[1::2].astype(np.float32, copy=False)
    return (i_values + 1j * q_values).astype(np.complex64, copy=False)


def _decode_iq_pairs(data: bytes) -> list[tuple[int, int]]:
    """Decode interleaved big-endian int16 IQ pairs."""

    if not data:
        return []
    values = struct.unpack(">" + "h" * (len(data) // 2), data)
    return list(zip(values[0::2], values[1::2]))


def _build_statistics(data: bytes) -> IQStatistics:
    """Compute statistics for one IQ data window."""

    pairs = _decode_iq_pairs(data)
    if not pairs:
        raise CapProbeError("CAP IQ payload window is empty.")

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
    """Compute the population standard deviation for one list of values."""

    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5
