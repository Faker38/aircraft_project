"""Shared workflow records used across dataset, training, and recognition pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SampleRecord:
    """One unified sample record used by the downstream workflow pages."""

    sample_id: str
    source_type: str
    raw_file_path: str
    sample_file_path: str
    label_type: str
    label_individual: str
    sample_rate_hz: float
    center_frequency_hz: float
    data_format: str
    sample_count: int
    device_id: str
    start_sample: int
    end_sample: int
    status: str = "已标注"
    source_name: str = ""

    @property
    def raw_file_name(self) -> str:
        """Return the source file name shown in compact tables."""

        return Path(self.raw_file_path).name

    @property
    def sample_file_name(self) -> str:
        """Return the generated sample file name."""

        return Path(self.sample_file_path).name

    @property
    def source_label(self) -> str:
        """Return one UI-friendly label for the sample source."""

        return {
            "local_preprocess": "预处理输出",
        }.get(self.source_type, "未知来源")


@dataclass(frozen=True)
class DatasetVersionRecord:
    """One dataset version summary used by dataset and training pages."""

    version_id: str
    task_type: str
    sample_count: int
    strategy: str
    created_at: str
    source_summary: str
    label_counts: dict[str, int] = field(default_factory=dict)
