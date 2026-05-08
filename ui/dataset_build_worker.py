"""后台工作线程：用于执行数据集版本生成。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import random
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from config import DATASETS_DIR
from services import DatasetVersionRecord, SampleRecord, create_dataset_version, write_dataset_manifest

SPLIT_RANDOM_SEED = 42
SPLIT_NAMES = ("train", "val", "test")
NPZ_SAMPLE_LENGTH = 4096
DEFAULT_NPZ_MAX_ITEMS = 1000


def collect_dataset_candidates(
    sample_records: list[SampleRecord],
    *,
    task_type: str,
) -> tuple[dict[str, int], list[str], dict[str, str], list[tuple[str, str]]]:
    """从样本记录中提取可生成数据集的候选集。"""

    label_counts: dict[str, int] = {}
    selected_sample_ids: list[str] = []
    label_values: dict[str, str] = {}
    sample_labels: list[tuple[str, str]] = []

    for record in sample_records:
        label_value = _unified_label(record)
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
    """按标签随机划分生成训练、验证、测试集合。"""

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
        _validate_label_split_capacity(label, records, train_ratio=train_ratio, test_ratio=test_ratio)
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

    return _unified_label(record)


def _unified_label(record: SampleRecord) -> str:
    """Return the single label used by the formal dataset flow."""

    return (record.label_type or record.label_individual).strip()


def _validate_label_split_capacity(
    label: str,
    records: list[SampleRecord],
    *,
    train_ratio: int,
    test_ratio: int,
) -> None:
    """Ensure each label can appear in both train and test when requested."""

    required = int(train_ratio > 0) + int(test_ratio > 0)
    if required > 1 and len(records) < required:
        raise ValueError(f"标签 {label} 样本数不足，无法同时进入训练集和测试集。")


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


def write_npz_dataset(
    *,
    version_id: str,
    selected_records: list[SampleRecord],
    label_values: dict[str, str],
    split_values: dict[str, str],
    max_items_per_npz: int,
) -> list[str]:
    """Write formal train/test NPZ files for one dataset version."""

    output_dir = DATASETS_DIR / version_id
    output_dir.mkdir(parents=True, exist_ok=True)
    max_items = max(1, int(max_items_per_npz or DEFAULT_NPZ_MAX_ITEMS))
    records_by_split: dict[str, list[SampleRecord]] = {split_name: [] for split_name in SPLIT_NAMES}
    for record in selected_records:
        split_name = split_values.get(record.sample_id, "train")
        if split_name in records_by_split:
            records_by_split[split_name].append(record)

    written_paths: list[str] = []
    for split_name in SPLIT_NAMES:
        split_records = sorted(records_by_split[split_name], key=lambda item: item.sample_id)
        if not split_records:
            continue
        for chunk_index, start in enumerate(range(0, len(split_records), max_items), start=1):
            chunk_records = split_records[start : start + max_items]
            file_name = f"{split_name}.npz" if len(split_records) <= max_items else f"{split_name}_part{chunk_index:03d}.npz"
            output_path = output_dir / file_name
            x_values = np.stack([_load_sample_as_iq_matrix(record.sample_file_path) for record in chunk_records])
            y_values = np.asarray([label_values[record.sample_id] for record in chunk_records])
            sample_ids = np.asarray([record.sample_id for record in chunk_records])
            file_ids = np.asarray([Path(record.raw_file_path).stem for record in chunk_records])
            source_paths = np.asarray([record.sample_file_path for record in chunk_records])
            np.savez_compressed(
                output_path,
                data=x_values,
                label=y_values,
                x=x_values,
                y=y_values,
                sample_ids=sample_ids,
                file_ids=file_ids,
                source_paths=source_paths,
            )
            written_paths.append(str(output_path))
    return written_paths


def _load_sample_as_iq_matrix(sample_file_path: str) -> np.ndarray:
    """Load one sample and normalize it to shape (2, 4096)."""

    path = Path(sample_file_path)
    if not path.exists():
        raise ValueError(f"样本文件不存在：{path}")
    array = np.load(path, allow_pickle=False)
    if hasattr(array, "files"):
        if "x" in array:
            array = array["x"]
        elif "data" in array:
            array = array["data"]
        else:
            raise ValueError(f"NPZ 样本缺少 data 或 x 字段：{path}")

    if np.iscomplexobj(array):
        flat = np.ravel(array)
        i_values = np.real(flat)
        q_values = np.imag(flat)
    else:
        numeric = np.asarray(array)
        if numeric.ndim >= 3:
            numeric = numeric.reshape(-1, *numeric.shape[-2:])
            numeric = numeric[0]
        if numeric.ndim == 2 and numeric.shape[0] == 2:
            i_values = numeric[0]
            q_values = numeric[1]
        elif numeric.ndim == 2 and numeric.shape[1] == 2:
            i_values = numeric[:, 0]
            q_values = numeric[:, 1]
        else:
            flat = np.ravel(numeric)
            i_values = flat
            q_values = np.zeros_like(flat)

    output = np.zeros((2, NPZ_SAMPLE_LENGTH), dtype=np.float32)
    i_array = np.asarray(i_values, dtype=np.float32).ravel()[:NPZ_SAMPLE_LENGTH]
    q_array = np.asarray(q_values, dtype=np.float32).ravel()[:NPZ_SAMPLE_LENGTH]
    output[0, : i_array.size] = i_array
    output[1, : q_array.size] = q_array
    return output


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
        max_items_per_npz: int = DEFAULT_NPZ_MAX_ITEMS,
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
        self.max_items_per_npz = max_items_per_npz

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
                self.failed.emit("没有可用样本，无法生成数据集。")
                return

            selected_sample_id_set = set(selected_sample_ids)
            selected_records = [record for record in self.sample_records if record.sample_id in selected_sample_id_set]
            source_types = {record.source_type for record in selected_records}
            if source_types == {"usrp_preprocess"}:
                source_summary = "IQ 预处理样本"
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
            self.progress_changed.emit(sample_total, max(sample_total, 1), "正在生成 NPZ")
            npz_paths = write_npz_dataset(
                version_id=self.version_id,
                selected_records=selected_records,
                label_values=label_values,
                split_values=split_values,
                max_items_per_npz=self.max_items_per_npz,
            )
            self.progress_changed.emit(sample_total, max(sample_total, 1), "正在生成 manifest")
            manifest_path = write_dataset_manifest(self.version_id)
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"数据集生成失败：{exc}")
            return

        self.finished.emit(
            {
                "record": record,
                "manifest_path": str(manifest_path) if manifest_path is not None else "",
                "npz_paths": npz_paths,
                "label_counts": label_counts,
                "sample_total": sample_total,
            }
        )
