"""后台工作线程：用于执行数据集页自动标注。"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from services import SampleRecord


def build_auto_labeled_records(
    sample_records: list[SampleRecord],
    mapping_lookup: dict[str, dict[str, str]],
    *,
    individual_mode: bool,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
) -> tuple[list[SampleRecord], dict[str, int]]:
    """根据当前映射表批量生成新的样本标注结果。"""

    total = len(sample_records)
    matched = 0
    pending = 0
    updated = 0
    updated_records: list[SampleRecord] = []

    if progress_callback is not None:
        progress_callback(0, total, matched, pending)

    for index, record in enumerate(sample_records, start=1):
        new_record = record
        mapping = (
            mapping_lookup.get(record.device_id)
            if record.source_type in {"local_preprocess", "usrp_preprocess"}
            else None
        )

        if mapping is None:
            new_record = replace(
                record,
                label_type="",
                label_individual="",
                status="待标注",
            )
            pending += 1
        else:
            mapped_label = (mapping.get("type", "") or mapping.get("individual", "")).strip()
            mapped_status = "已标注" if mapped_label else "待标注"
            new_record = replace(
                record,
                label_type=mapped_label,
                label_individual=mapped_label,
                status=mapped_status,
            )
            if mapped_status == "已标注":
                matched += 1
            else:
                pending += 1

        if new_record != record:
            updated += 1
        updated_records.append(new_record)

        if progress_callback is not None and (index == total or index % 200 == 0):
            progress_callback(index, total, matched, pending)

    summary = {
        "total": total,
        "matched": matched,
        "pending": pending,
        "updated": updated,
    }
    return updated_records, summary


class AutoLabelWorker(QObject):
    """把大批量自动标注放到 UI 线程之外执行。"""

    progress_changed = Signal(int, int, int, int)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        sample_records: list[SampleRecord],
        mapping_lookup: dict[str, dict[str, str]],
        individual_mode: bool,
    ) -> None:
        """保存本次自动标注所需的数据快照。"""

        super().__init__()
        self.sample_records = list(sample_records)
        self.mapping_lookup = dict(mapping_lookup)
        self.individual_mode = individual_mode

    @Slot()
    def run(self) -> None:
        """在线程中执行自动标注并回传结果。"""

        try:
            updated_records, summary = build_auto_labeled_records(
                self.sample_records,
                self.mapping_lookup,
                individual_mode=self.individual_mode,
                progress_callback=self.progress_changed.emit,
            )
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"自动标注执行失败：{exc}")
            return

        self.finished.emit(updated_records, summary)
