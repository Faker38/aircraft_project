"""后台工作线程：用于执行数据集版本生成。"""

from __future__ import annotations

from datetime import datetime
import random
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from services import DatasetVersionRecord, SampleRecord, create_dataset_version, write_dataset_manifest

SPLIT_RANDOM_SEED = 42
SPLIT_NAMES = ("train", "val", "test")


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
    sample_records: list[SampleRecord],
    *,
    task_type: str,
    strategy: str,
    train_ratio: int,
    val_ratio: int,
    test_ratio: int,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, str]:
    """按用户选择的真实策略生成训练、验证、测试划分。"""

    grouped: dict[str, list[SampleRecord]] = {}
    for record in sample_records:
        label = _label_for_task(record, task_type)
        if label:
            grouped.setdefault(label, []).append(record)

    split_values: dict[str, str] = {}
    total = sum(len(records) for records in grouped.values())
    processed = 0
    if progress_callback is not None:
        progress_callback(0, max(total, 1), "正在计算训练/验证/测试划分")

    rng = random.Random(SPLIT_RANDOM_SEED)
    for label, records in sorted(grouped.items(), key=lambda item: item[0]):
        if strategy == "按设备个体隔离":
            label_split_values = _build_device_isolated_split(
                label,
                records,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                test_ratio=test_ratio,
                rng=rng,
            )
        else:
            label_split_values = _build_stratified_random_split(
                records,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                test_ratio=test_ratio,
                rng=rng,
            )
        split_values.update(label_split_values)
        processed += len(records)

        if progress_callback is not None:
            progress_callback(processed, max(total, 1), "正在整理样本划分")

    return split_values


def _label_for_task(record: SampleRecord, task_type: str) -> str:
    """返回当前任务使用的标签字段。"""

    return record.label_type if task_type == "类型识别" else record.label_individual


def _build_stratified_random_split(
    records: list[SampleRecord],
    *,
    train_ratio: int,
    val_ratio: int,
    test_ratio: int,
    rng: random.Random,
) -> dict[str, str]:
    """在每个标签内随机分层划分，随机种子固定。"""

    sample_ids = [record.sample_id for record in sorted(records, key=lambda item: item.sample_id)]
    rng.shuffle(sample_ids)
    train_count, val_count, _ = calculate_split_counts(
        len(sample_ids),
        train_ratio,
        val_ratio,
        test_ratio,
    )
    split_values: dict[str, str] = {}
    for index, sample_id in enumerate(sample_ids):
        if index < train_count:
            split_values[sample_id] = "train"
        elif index < train_count + val_count:
            split_values[sample_id] = "val"
        else:
            split_values[sample_id] = "test"
    return split_values


def _build_device_isolated_split(
    label: str,
    records: list[SampleRecord],
    *,
    train_ratio: int,
    val_ratio: int,
    test_ratio: int,
    rng: random.Random,
) -> dict[str, str]:
    """按设备编号分组划分，保证同一设备不会跨 train/val/test。"""

    target_counts = calculate_split_counts(
        len(records),
        train_ratio,
        val_ratio,
        test_ratio,
    )
    active_targets = [
        (split_name, target_count)
        for split_name, target_count in zip(SPLIT_NAMES, target_counts)
        if target_count > 0
    ]
    grouped_by_device: dict[str, list[SampleRecord]] = {}
    for record in sorted(records, key=lambda item: item.sample_id):
        device_id = record.device_id.strip() or "未指定设备"
        grouped_by_device.setdefault(device_id, []).append(record)

    if len(grouped_by_device) < len(active_targets):
        raise ValueError(
            f"标签 {label} 只有 {len(grouped_by_device)} 个设备编号，"
            f"无法按设备个体隔离切出 {len(active_targets)} 个数据集合；"
            "请补充更多设备样本，或改用“按样本随机分层”。"
        )

    devices = sorted(grouped_by_device)
    rng.shuffle(devices)
    split_values: dict[str, str] = {}
    for split_index, (split_name, target_count) in enumerate(active_targets):
        is_last_split = split_index == len(active_targets) - 1
        remaining_slots = len(active_targets) - split_index - 1
        assigned_count = 0
        while devices and (
            is_last_split
            or not assigned_count
            or (assigned_count < target_count and len(devices) > remaining_slots)
        ):
            device_id = devices.pop(0)
            device_records = grouped_by_device[device_id]
            for record in device_records:
                split_values[record.sample_id] = split_name
            assigned_count += len(device_records)

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
                self.failed.emit("当前没有可用样本，无法生成数据集版本。请确认样本已标注、标签非空且处于纳入候选。")
                return

            selected_sample_id_set = set(selected_sample_ids)
            selected_records = [record for record in self.sample_records if record.sample_id in selected_sample_id_set]
            source_types = {record.source_type for record in selected_records}
            if source_types == {"usrp_preprocess"}:
                source_summary = "USRP演示样本"
            elif "usrp_preprocess" in source_types:
                source_summary = "混合预处理样本"
            else:
                source_summary = "预处理样本"

            split_values = build_split_values(
                selected_records,
                task_type=self.task_type,
                strategy=self.strategy,
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
                source_summary=source_summary,
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
