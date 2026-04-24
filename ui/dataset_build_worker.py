"""后台工作线程：用于执行数据集版本生成。"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from services import DatasetVersionRecord, SampleRecord, create_dataset_version, write_dataset_manifest


def collect_dataset_candidates(
    sample_records: list[SampleRecord],
    *,
    task_type: str,
) -> tuple[dict[str, int], list[str], dict[str, str], list[tuple[str, str]]]:
    """从样本记录中提取可生成数据集的候选集。"""

    use_type_label = task_type == "类型识别"
    label_counts: dict[str, int] = {}
    selected_sample_ids: list[str] = []
    label_values: dict[str, str] = {}
    sample_labels: list[tuple[str, str]] = []

    for record in sample_records:
        label_value = record.label_type if use_type_label else record.label_individual
        if record.status != "已标注" or not record.include_in_dataset or not label_value:
            continue
        label_counts[label_value] = label_counts.get(label_value, 0) + 1
        selected_sample_ids.append(record.sample_id)
        label_values[record.sample_id] = label_value
        sample_labels.append((record.sample_id, label_value))

    return label_counts, selected_sample_ids, label_values, sample_labels


def calculate_split_counts(total: int, train_ratio: int, val_ratio: int, test_ratio: int) -> tuple[int, int, int]:
    """把比例转换成具体的 train / val / test 样本数。"""

    if total <= 0:
        return 0, 0, 0

    ratios = [train_ratio / 100, val_ratio / 100, test_ratio / 100]
    counts = [int(round(total * ratio)) for ratio in ratios]
    diff = total - sum(counts)
    adjust_order = [2, 1, 0]
    adjust_index = 0
    while diff != 0:
        target_index = adjust_order[adjust_index % len(adjust_order)]
        if diff > 0:
            counts[target_index] += 1
            diff -= 1
        elif counts[target_index] > 0:
            counts[target_index] -= 1
            diff += 1
        adjust_index += 1
    return counts[0], counts[1], counts[2]


def build_split_values(
    sample_labels: list[tuple[str, str]],
    *,
    train_ratio: int,
    val_ratio: int,
    test_ratio: int,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, str]:
    """按标签内顺序生成训练、验证、测试划分。"""

    grouped: dict[str, list[str]] = {}
    for sample_id, label in sample_labels:
        grouped.setdefault(label, []).append(sample_id)

    split_values: dict[str, str] = {}
    total = len(sample_labels)
    processed = 0
    if progress_callback is not None:
        progress_callback(0, max(total, 1), "正在计算训练/验证/测试划分")

    for sample_ids in grouped.values():
        train_count, val_count, test_count = calculate_split_counts(
            len(sample_ids),
            train_ratio,
            val_ratio,
            test_ratio,
        )

        for index, sample_id in enumerate(sample_ids):
            if index < train_count:
                split_values[sample_id] = "train"
            elif index < train_count + val_count:
                split_values[sample_id] = "val"
            elif index < train_count + val_count + test_count:
                split_values[sample_id] = "test"
            processed += 1

        if progress_callback is not None:
            progress_callback(processed, max(total, 1), "正在整理样本划分")

    return split_values


class DatasetBuildWorker(QObject):
    """把一次数据集版本生成任务放到 UI 线程之外执行。"""

    progress_changed = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        sample_records: list[SampleRecord],
        version_id: str,
        task_type: str,
        strategy: str,
        train_ratio: int,
        val_ratio: int,
        test_ratio: int,
    ) -> None:
        """保存本次数据集生成所需的输入参数。"""

        super().__init__()
        self.sample_records = list(sample_records)
        self.version_id = version_id
        self.task_type = task_type
        self.strategy = strategy
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio

    @Slot()
    def run(self) -> None:
        """在线程中完成候选收集、写库和 manifest 生成。"""

        try:
            label_counts, selected_sample_ids, label_values, sample_labels = collect_dataset_candidates(
                self.sample_records,
                task_type=self.task_type,
            )
            sample_total = len(selected_sample_ids)
            self.progress_changed.emit(0, max(sample_total, 1), "正在收集可生成样本")
            if not label_counts:
                self.failed.emit("当前没有可用的已标注样本，无法生成数据集版本。")
                return

            split_values = build_split_values(
                sample_labels,
                train_ratio=self.train_ratio,
                val_ratio=self.val_ratio,
                test_ratio=self.test_ratio,
                progress_callback=self.progress_changed.emit,
            )

            record = DatasetVersionRecord(
                version_id=self.version_id,
                task_type=self.task_type,
                sample_count=sum(label_counts.values()),
                strategy=self.strategy,
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                source_summary="预处理样本",
                label_counts=label_counts,
            )
            self.progress_changed.emit(sample_total, max(sample_total, 1), "正在写入数据库")
            create_dataset_version(record, selected_sample_ids, label_values, split_values)
            self.progress_changed.emit(sample_total, max(sample_total, 1), "正在生成 manifest")
            manifest_path = write_dataset_manifest(self.version_id)
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"数据集生成失败：{exc}")
            return

        self.finished.emit(
            {
                "record": record,
                "manifest_path": str(manifest_path) if manifest_path is not None else "",
                "label_counts": label_counts,
                "sample_total": sample_total,
            }
        )
