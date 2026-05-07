"""External dataset import utilities for NPZ and MATLAB IQ files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import random
import re

import numpy as np

from config import DATASETS_DIR, SAMPLES_DIR
from services.database import (
    create_dataset_version,
    upsert_samples,
    write_dataset_manifest,
    DATASET_SPLIT_RANDOM_SEED,
)
from services.workflow_records import DatasetVersionRecord, SampleRecord


SAMPLE_LENGTH = 4096
SPLIT_NAMES = ("train", "val", "test")


class ExternalDatasetImportError(RuntimeError):
    """Raised when an external dataset cannot be imported."""


@dataclass(frozen=True)
class ExternalDatasetImportResult:
    """Summary returned after importing an external dataset directory."""

    version_record: DatasetVersionRecord
    manifest_path: str
    npz_paths: list[str]
    sample_count: int
    label_counts: dict[str, int]
    imported_file_count: int


@dataclass(frozen=True)
class _LoadedExternalSample:
    """One normalized external IQ sample before database persistence."""

    source_path: Path
    matrix: np.ndarray
    label: str
    device_id: str
    source_index: int
    explicit_split: str | None
    data_format: str


def import_external_dataset_directory(
    directory: str | Path,
    *,
    version_id: str,
    task_type: str,
    train_ratio: int,
    val_ratio: int,
    test_ratio: int,
    max_items_per_npz: int,
) -> ExternalDatasetImportResult:
    """Import one external dataset directory and register it as a dataset version."""

    source_dir = Path(directory).expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise ExternalDatasetImportError(f"数据集目录不存在：{source_dir}")
    if train_ratio + val_ratio + test_ratio != 100:
        raise ExternalDatasetImportError("训练集、验证集和测试集比例总和必须等于 100%。")

    source_files = _find_supported_source_files(source_dir)
    if not source_files:
        raise ExternalDatasetImportError("目录中没有可导入的 .npz 或 .mat 文件。")

    loaded_samples: list[_LoadedExternalSample] = []
    for path in source_files:
        relative_path = path.relative_to(source_dir)
        explicit_split = _infer_split(relative_path)
        if path.suffix.lower() == ".npz":
            loaded_samples.extend(_load_npz_samples(path, explicit_split=explicit_split))
        elif path.suffix.lower() == ".mat":
            loaded_samples.extend(_load_mat_samples(path, explicit_split=explicit_split))

    if not loaded_samples:
        raise ExternalDatasetImportError("没有解析到有效 IQ 样本。")

    split_values = _build_external_split_values(
        loaded_samples,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
    )
    records = _persist_external_samples(version_id, task_type, loaded_samples)
    sample_ids = [record.sample_id for record in records]
    label_values = {
        record.sample_id: (record.label_type if task_type == "类型识别" else record.label_individual)
        for record in records
    }
    label_counts: dict[str, int] = {}
    for sample_id in sample_ids:
        label = label_values[sample_id]
        label_counts[label] = label_counts.get(label, 0) + 1

    strategy = "外部导入原始划分" if any(sample.explicit_split for sample in loaded_samples) else "外部导入随机划分"
    version_record = DatasetVersionRecord(
        version_id=version_id,
        task_type=task_type,
        sample_count=len(records),
        strategy=strategy,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        source_summary="外部数据集",
        label_counts=label_counts,
    )

    upsert_samples(records)
    create_dataset_version(version_record, sample_ids, label_values, split_values)
    npz_paths = _write_dataset_npz_files(
        version_id=version_id,
        records=records,
        label_values=label_values,
        split_values=split_values,
        max_items_per_npz=max_items_per_npz,
    )
    manifest_path = write_dataset_manifest(version_id)
    return ExternalDatasetImportResult(
        version_record=version_record,
        manifest_path=str(manifest_path or ""),
        npz_paths=npz_paths,
        sample_count=len(records),
        label_counts=label_counts,
        imported_file_count=len(source_files),
    )


def _find_supported_source_files(source_dir: Path) -> list[Path]:
    """Return supported source files in stable order."""

    return sorted(
        [*source_dir.rglob("*.npz"), *source_dir.rglob("*.mat")],
        key=lambda item: str(item.relative_to(source_dir)).lower(),
    )


def _load_npz_samples(path: Path, *, explicit_split: str | None) -> list[_LoadedExternalSample]:
    """Load one external NPZ file with data/x and label/y style fields."""

    try:
        with np.load(path, allow_pickle=False) as payload:
            data_key = "data" if "data" in payload.files else ("x" if "x" in payload.files else "")
            if not data_key:
                raise ExternalDatasetImportError(f"NPZ 缺少 data 或 x 字段：{path.name}")
            label_key = "label" if "label" in payload.files else ("y" if "y" in payload.files else "")
            data = np.asarray(payload[data_key])
            labels = np.asarray(payload[label_key]) if label_key else np.asarray(_label_from_file_name(path))
    except ValueError as exc:
        raise ExternalDatasetImportError(f"NPZ 读取失败：{path.name}，{exc}") from exc

    matrices = _normalize_batch_to_iq_matrices(data, path)
    label_values = _normalize_labels(labels, len(matrices), fallback=_label_from_file_name(path))
    device_id = _device_id_from_file(path)
    return [
        _LoadedExternalSample(
            source_path=path,
            matrix=matrix,
            label=label_values[index],
            device_id=device_id,
            source_index=index,
            explicit_split=explicit_split,
            data_format="npz_iq_2x4096",
        )
        for index, matrix in enumerate(matrices)
    ]


def _load_mat_samples(path: Path, *, explicit_split: str | None) -> list[_LoadedExternalSample]:
    """Load one MATLAB v7.3 IQ file and slice it by time into 4096-point samples."""

    i_values, q_values = _read_mat_iq(path)
    sample_total = min(i_values.size, q_values.size) // SAMPLE_LENGTH
    if sample_total <= 0:
        raise ExternalDatasetImportError(f"MAT 文件长度不足：{path.name}")

    label = _label_from_file_name(path)
    device_id = _device_id_from_file(path)
    samples: list[_LoadedExternalSample] = []
    for index in range(sample_total):
        start = index * SAMPLE_LENGTH
        end = start + SAMPLE_LENGTH
        matrix = np.stack(
            [
                i_values[start:end].astype(np.float32, copy=False),
                q_values[start:end].astype(np.float32, copy=False),
            ]
        )
        samples.append(
            _LoadedExternalSample(
                source_path=path,
                matrix=matrix,
                label=label,
                device_id=device_id,
                source_index=index,
                explicit_split=explicit_split,
                data_format="mat_iq_2x4096",
            )
        )
    return samples


def _read_mat_iq(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read I/Q arrays from MATLAB files saved as HDF5 or classic MAT."""

    try:
        import h5py  # type: ignore

        with h5py.File(path, "r") as handle:
            keys = {key.lower(): key for key in handle.keys()}
            i_key = keys.get("i")
            q_key = keys.get("q")
            if i_key and q_key:
                return np.asarray(handle[i_key]).ravel(), np.asarray(handle[q_key]).ravel()
    except OSError:
        pass
    except ImportError as exc:
        raise ExternalDatasetImportError("MAT v7.3 文件需要安装 h5py。") from exc

    try:
        from scipy.io import loadmat  # type: ignore

        payload = loadmat(path)
        lower_keys = {key.lower(): key for key in payload if not key.startswith("__")}
        i_key = lower_keys.get("i")
        q_key = lower_keys.get("q")
        if i_key and q_key:
            return np.asarray(payload[i_key]).ravel(), np.asarray(payload[q_key]).ravel()
    except Exception as exc:  # pragma: no cover - fallback boundary
        raise ExternalDatasetImportError(f"MAT 读取失败：{path.name}，{exc}") from exc

    raise ExternalDatasetImportError(f"MAT 文件缺少 I/Q 字段：{path.name}")


def _normalize_batch_to_iq_matrices(data: np.ndarray, path: Path) -> list[np.ndarray]:
    """Normalize external arrays into a list of (2, 4096) matrices."""

    if data.ndim == 1 and np.iscomplexobj(data):
        data = data.reshape(1, -1)
    if data.ndim == 2:
        if data.shape[0] == 2 or data.shape[1] == 2:
            data = data.reshape(1, *data.shape)
        else:
            raise ExternalDatasetImportError(f"NPZ data 形状不支持：{path.name} -> {data.shape}")
    if data.ndim != 3:
        raise ExternalDatasetImportError(f"NPZ data 必须是三维数组：{path.name} -> {data.shape}")

    matrices: list[np.ndarray] = []
    for index in range(data.shape[0]):
        matrix = _normalize_one_matrix(data[index], f"{path.name}[{index}]")
        matrices.append(matrix)
    return matrices


def _normalize_one_matrix(array: np.ndarray, label: str) -> np.ndarray:
    """Normalize one array into shape (2, 4096)."""

    if np.iscomplexobj(array):
        flat = np.asarray(array).ravel()
        i_values = np.real(flat)
        q_values = np.imag(flat)
    elif array.ndim == 2 and array.shape[0] == 2:
        i_values = array[0]
        q_values = array[1]
    elif array.ndim == 2 and array.shape[1] == 2:
        i_values = array[:, 0]
        q_values = array[:, 1]
    else:
        raise ExternalDatasetImportError(f"样本形状不支持：{label} -> {array.shape}")

    output = np.zeros((2, SAMPLE_LENGTH), dtype=np.float32)
    i_array = np.asarray(i_values, dtype=np.float32).ravel()[:SAMPLE_LENGTH]
    q_array = np.asarray(q_values, dtype=np.float32).ravel()[:SAMPLE_LENGTH]
    output[0, : i_array.size] = i_array
    output[1, : q_array.size] = q_array
    return output


def _normalize_labels(labels: np.ndarray, sample_count: int, *, fallback: str) -> list[str]:
    """Normalize scalar or per-sample labels into display-safe labels."""

    if labels.shape == ():
        return [_format_label_value(labels.item(), fallback=fallback)] * sample_count
    if labels.ndim == 2 and labels.shape[0] == sample_count and labels.shape[1] > 1:
        labels = np.argmax(labels, axis=1)
    flat = np.asarray(labels).ravel()
    if flat.size == 1:
        return [_format_label_value(flat[0], fallback=fallback)] * sample_count
    if flat.size != sample_count:
        raise ExternalDatasetImportError(f"标签数量 {flat.size} 与样本数量 {sample_count} 不一致。")
    return [_format_label_value(value, fallback=fallback) for value in flat]


def _format_label_value(value: object, *, fallback: str) -> str:
    """Convert one external label value into product-facing text."""

    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore").strip()
    else:
        text = str(value).strip()
    if text in {"", "None", "nan"}:
        return fallback
    if re.fullmatch(r"[-+]?\d+(\.0+)?", text):
        return f"类别{int(float(text))}"
    return text


def _infer_split(relative_path: Path) -> str | None:
    """Infer train/val/test split from folder or file names."""

    tokens = [part.lower() for part in relative_path.parts]
    joined = "/".join(tokens)
    if "train" in tokens or "训练" in joined:
        return "train"
    if "val" in tokens or "valid" in tokens or "验证" in joined:
        return "val"
    if "test" in tokens or "测试" in joined:
        return "test"
    stem = relative_path.stem.lower()
    if stem.startswith("train"):
        return "train"
    if stem.startswith(("val", "valid")):
        return "val"
    if stem.startswith("test"):
        return "test"
    return None


def _build_external_split_values(
    samples: list[_LoadedExternalSample],
    *,
    train_ratio: int,
    val_ratio: int,
    test_ratio: int,
) -> dict[str, str]:
    """Build split values for imported external samples."""

    explicit_samples = [sample for sample in samples if sample.explicit_split]
    if explicit_samples and len(explicit_samples) == len(samples):
        return {_sample_id_for(sample): str(sample.explicit_split) for sample in samples}
    if explicit_samples:
        raise ExternalDatasetImportError("外部数据集不能混用显式 train/test 目录和未划分文件。")

    grouped: dict[str, list[_LoadedExternalSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.label, []).append(sample)

    rng = random.Random(DATASET_SPLIT_RANDOM_SEED)
    split_values: dict[str, str] = {}
    for label, label_samples in sorted(grouped.items(), key=lambda item: item[0]):
        shuffled = sorted(label_samples, key=_sample_id_for)
        rng.shuffle(shuffled)
        train_count, val_count, _ = _calculate_split_counts(
            len(shuffled),
            train_ratio,
            val_ratio,
            test_ratio,
        )
        for index, sample in enumerate(shuffled):
            if index < train_count:
                split = "train"
            elif index < train_count + val_count:
                split = "val"
            else:
                split = "test"
            split_values[_sample_id_for(sample)] = split
    return split_values


def _calculate_split_counts(total: int, train_ratio: int, val_ratio: int, test_ratio: int) -> tuple[int, int, int]:
    """Convert ratios to exact counts."""

    if total <= 0:
        return 0, 0, 0
    counts = [int(round(total * train_ratio / 100)), int(round(total * val_ratio / 100)), int(round(total * test_ratio / 100))]
    diff = total - sum(counts)
    order = [2, 1, 0]
    index = 0
    while diff != 0:
        target = order[index % len(order)]
        if diff > 0:
            counts[target] += 1
            diff -= 1
        elif counts[target] > 0:
            counts[target] -= 1
            diff += 1
        index += 1
    return counts[0], counts[1], counts[2]


def _persist_external_samples(
    version_id: str,
    task_type: str,
    samples: list[_LoadedExternalSample],
) -> list[SampleRecord]:
    """Write normalized sample npy files and return database records."""

    output_dir = SAMPLES_DIR / "external_import" / version_id
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[SampleRecord] = []
    for sample in samples:
        sample_id = _sample_id_for(sample)
        output_path = output_dir / f"{sample_id}.npy"
        np.save(output_path, sample.matrix.astype(np.float32, copy=False))
        if task_type == "个体识别":
            label_type = _label_from_file_name(sample.source_path)
            label_individual = sample.label
        else:
            label_type = sample.label
            label_individual = sample.device_id
        records.append(
            SampleRecord(
                sample_id=sample_id,
                source_type="external_dataset",
                raw_file_path=str(sample.source_path),
                sample_file_path=str(output_path),
                label_type=label_type,
                label_individual=label_individual,
                sample_rate_hz=0.0,
                center_frequency_hz=0.0,
                data_format=sample.data_format,
                sample_count=SAMPLE_LENGTH,
                device_id=sample.device_id,
                start_sample=sample.source_index * SAMPLE_LENGTH,
                end_sample=(sample.source_index + 1) * SAMPLE_LENGTH - 1,
                include_in_dataset=True,
                status="已标注",
                source_name="外部数据集",
            )
        )
    return records


def _write_dataset_npz_files(
    *,
    version_id: str,
    records: list[SampleRecord],
    label_values: dict[str, str],
    split_values: dict[str, str],
    max_items_per_npz: int,
) -> list[str]:
    """Write train/val/test NPZ files using data/label and x/y aliases."""

    output_dir = DATASETS_DIR / version_id
    output_dir.mkdir(parents=True, exist_ok=True)
    max_items = max(1, int(max_items_per_npz or 1000))
    grouped: dict[str, list[SampleRecord]] = {split: [] for split in SPLIT_NAMES}
    for record in records:
        split = split_values.get(record.sample_id, "train")
        if split in grouped:
            grouped[split].append(record)

    written: list[str] = []
    for split in SPLIT_NAMES:
        split_records = sorted(grouped[split], key=lambda item: item.sample_id)
        if not split_records:
            continue
        for chunk_index, start in enumerate(range(0, len(split_records), max_items), start=1):
            chunk = split_records[start : start + max_items]
            file_name = f"{split}.npz" if len(split_records) <= max_items else f"{split}_part{chunk_index:03d}.npz"
            output_path = output_dir / file_name
            matrices = np.stack([np.load(record.sample_file_path, allow_pickle=False) for record in chunk]).astype(np.float32)
            labels = np.asarray([label_values[record.sample_id] for record in chunk])
            sample_ids = np.asarray([record.sample_id for record in chunk])
            file_ids = np.asarray([Path(record.raw_file_path).stem for record in chunk])
            source_paths = np.asarray([record.sample_file_path for record in chunk])
            np.savez_compressed(
                output_path,
                data=matrices,
                label=labels,
                x=matrices,
                y=labels,
                sample_ids=sample_ids,
                file_ids=file_ids,
                source_paths=source_paths,
            )
            written.append(str(output_path))
    return written


def _sample_id_for(sample: _LoadedExternalSample) -> str:
    """Build a stable sample id for one external sample."""

    digest = hashlib.sha1(str(sample.source_path).encode("utf-8")).hexdigest()[:8]
    return f"ext_{_safe_token(sample.source_path.stem)}_{digest}_{sample.source_index + 1:05d}"


def _device_id_from_file(path: Path) -> str:
    """Infer file-group id from source file name."""

    return _safe_token(path.stem)


def _label_from_file_name(path: Path) -> str:
    """Infer a readable label from file name prefix."""

    token = path.stem.split("_", 1)[0].strip()
    return token or path.stem


def _safe_token(value: str) -> str:
    """Return a filesystem and id safe token preserving common label characters."""

    token = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip(), flags=re.UNICODE)
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "external"
