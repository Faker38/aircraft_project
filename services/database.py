"""本地 SQLite 数据库服务。

UI 层只调用这里的函数，不直接写 SQL。当前先采用轻量
CREATE TABLE IF NOT EXISTS，后续需要复杂升级时再引入迁移工具。
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from config import DATASETS_DIR, DB_DIR
from services.workflow_records import (
    DatasetItemRecord,
    DatasetVersionDetail,
    DatasetVersionRecord,
    LabelMappingRecord,
    RawFileRecord,
    SampleRecord,
    TrainedModelRecord,
)


DB_PATH = DB_DIR / "aircraft_project.sqlite3"
DATASET_SPLIT_RANDOM_SEED = 42

DEFAULT_LABEL_MAPPINGS: tuple[LabelMappingRecord, ...] = (
    LabelMappingRecord("usrp_2412M", "频点A", "", "USRP 演示频点 2412 MHz"),
    LabelMappingRecord("usrp_2437M", "频点B", "", "USRP 演示频点 2437 MHz"),
    LabelMappingRecord("usrp_2462M", "频点C", "", "USRP 演示频点 2462 MHz"),
)

USRP_AUTO_MAPPING_NOTE_PREFIX = "USRP 自动映射"


def init_database() -> None:
    """初始化数据库和核心表结构。"""

    DB_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                sample_rate_hz REAL NOT NULL DEFAULT 0,
                center_frequency_hz REAL NOT NULL DEFAULT 0,
                bandwidth_hz REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS preprocess_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_file_id INTEGER,
                started_at TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                candidate_segment_count INTEGER NOT NULL DEFAULT 0,
                detected_segment_count INTEGER NOT NULL DEFAULT 0,
                output_sample_count INTEGER NOT NULL DEFAULT 0,
                output_dir TEXT NOT NULL DEFAULT '',
                params_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(raw_file_id) REFERENCES raw_files(id)
            );

            CREATE TABLE IF NOT EXISTS samples (
                sample_id TEXT PRIMARY KEY,
                raw_file_id INTEGER,
                preprocess_task_id INTEGER,
                source_type TEXT NOT NULL,
                raw_file_path TEXT NOT NULL,
                sample_file_path TEXT NOT NULL,
                label_type TEXT NOT NULL DEFAULT '',
                label_individual TEXT NOT NULL DEFAULT '',
                sample_rate_hz REAL NOT NULL DEFAULT 0,
                center_frequency_hz REAL NOT NULL DEFAULT 0,
                data_format TEXT NOT NULL DEFAULT '',
                sample_count INTEGER NOT NULL DEFAULT 0,
                device_id TEXT NOT NULL DEFAULT '',
                start_sample INTEGER NOT NULL DEFAULT 0,
                end_sample INTEGER NOT NULL DEFAULT 0,
                snr_db REAL NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0,
                include_in_dataset INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT '待标注',
                source_name TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(raw_file_id) REFERENCES raw_files(id),
                FOREIGN KEY(preprocess_task_id) REFERENCES preprocess_tasks(id)
            );

            CREATE TABLE IF NOT EXISTS dataset_versions (
                version_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source_summary TEXT NOT NULL,
                label_counts_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS dataset_items (
                version_id TEXT NOT NULL,
                sample_id TEXT NOT NULL,
                label_value TEXT NOT NULL DEFAULT '',
                split TEXT NOT NULL DEFAULT 'train',
                created_at TEXT NOT NULL,
                PRIMARY KEY(version_id, sample_id),
                FOREIGN KEY(version_id) REFERENCES dataset_versions(version_id),
                FOREIGN KEY(sample_id) REFERENCES samples(sample_id)
            );

            CREATE TABLE IF NOT EXISTS trained_models (
                model_id TEXT PRIMARY KEY,
                dataset_version_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                model_kind TEXT NOT NULL,
                label_space_json TEXT NOT NULL DEFAULT '[]',
                artifact_path TEXT NOT NULL,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT '训练完成',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS label_mappings (
                device_id TEXT PRIMARY KEY,
                label_type TEXT NOT NULL DEFAULT '',
                label_individual TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);
            CREATE INDEX IF NOT EXISTS idx_samples_raw_file ON samples(raw_file_id);
            CREATE INDEX IF NOT EXISTS idx_dataset_items_version ON dataset_items(version_id);
            CREATE INDEX IF NOT EXISTS idx_trained_models_dataset_version ON trained_models(dataset_version_id);
            """
        )
        _ensure_column(conn, "dataset_items", "split", "TEXT NOT NULL DEFAULT 'train'")
        _migrate_trained_models_to_weak_version_reference(conn)
        _seed_default_label_mappings(conn)
        conn.execute("UPDATE samples SET status = '待标注' WHERE status = '待复核'")


def save_preprocess_result(config: Any, result: Any) -> None:
    """保存一次预处理任务及其产生的样本记录。"""

    init_database()
    now = _now_text()
    cap_info = result.cap_info
    with _connect() as conn:
        raw_file_id = _upsert_raw_file(
            conn,
            file_path=str(cap_info.path),
            sample_rate_hz=float(cap_info.sample_rate_hz),
            center_frequency_hz=float(cap_info.center_frequency_hz),
            bandwidth_hz=float(getattr(cap_info, "bandwidth_hz", 0.0)),
            now=now,
        )
        cursor = conn.execute(
            """
            INSERT INTO preprocess_tasks (
                raw_file_id, started_at, status, message, candidate_segment_count,
                detected_segment_count, output_sample_count, output_dir, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_file_id,
                now,
                "完成" if result.success else "失败",
                result.message,
                int(getattr(result, "candidate_segment_count", 0)),
                int(result.detected_segment_count),
                int(result.output_sample_count),
                result.sample_output_dir,
                json.dumps(_config_to_jsonable_dict(config), ensure_ascii=False),
            ),
        )
        task_id = int(cursor.lastrowid)
        _upsert_samples(conn, result.sample_records, raw_file_id=raw_file_id, preprocess_task_id=task_id, now=now)


def upsert_samples(records: list[SampleRecord]) -> None:
    """新增或更新样本记录。"""

    if not records:
        return
    init_database()
    now = _now_text()
    with _connect() as conn:
        records_by_path: dict[str, list[SampleRecord]] = {}
        raw_file_ids: dict[str, int] = {}

        for record in records:
            records_by_path.setdefault(record.raw_file_path, []).append(record)

        for file_path, grouped_records in records_by_path.items():
            first_record = grouped_records[0]
            raw_file_ids[file_path] = _upsert_raw_file(
                conn,
                file_path=file_path,
                sample_rate_hz=first_record.sample_rate_hz,
                center_frequency_hz=first_record.center_frequency_hz,
                bandwidth_hz=0.0,
                now=now,
            )

        for file_path, grouped_records in records_by_path.items():
            _upsert_samples(
                conn,
                grouped_records,
                raw_file_id=raw_file_ids[file_path],
                preprocess_task_id=None,
                now=now,
            )


def save_usrp_preprocess_result(result: Any) -> None:
    """保存一次 USRP IQ 演示预处理任务及其样本记录。"""

    init_database()
    now = _now_text()
    input_info = result.input_info
    with _connect() as conn:
        raw_file_id = _upsert_raw_file(
            conn,
            file_path=str(input_info.path),
            sample_rate_hz=float(input_info.sample_rate_hz),
            center_frequency_hz=float(input_info.center_frequency_hz),
            bandwidth_hz=float(input_info.bandwidth_hz),
            now=now,
        )
        params_payload = {
            "mode": "usrp_demo_preprocess",
            "metadata_path": str(input_info.metadata_path),
            "gain_db": float(input_info.gain_db),
            "duration_s": float(input_info.duration_s),
            "antenna": input_info.antenna,
            "iq_pair_count": int(input_info.iq_pair_count),
        }
        cursor = conn.execute(
            """
            INSERT INTO preprocess_tasks (
                raw_file_id, started_at, status, message, candidate_segment_count,
                detected_segment_count, output_sample_count, output_dir, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_file_id,
                now,
                "完成" if result.success else "失败",
                str(result.message),
                int(getattr(result, "candidate_segment_count", 0)),
                int(result.detected_segment_count),
                int(result.output_sample_count),
                str(result.sample_output_dir),
                json.dumps(params_payload, ensure_ascii=False),
            ),
        )
        task_id = int(cursor.lastrowid)
        _upsert_samples(conn, result.sample_records, raw_file_id=raw_file_id, preprocess_task_id=task_id, now=now)


def save_raw_capture_record(
    *,
    file_path: str,
    sample_rate_hz: float,
    center_frequency_hz: float,
    bandwidth_hz: float,
) -> None:
    """登记一条原始采集文件记录。"""

    init_database()
    with _connect() as conn:
        _upsert_raw_file(
            conn,
            file_path=file_path,
            sample_rate_hz=sample_rate_hz,
            center_frequency_hz=center_frequency_hz,
            bandwidth_hz=bandwidth_hz,
            now=_now_text(),
        )


def list_raw_files() -> list[RawFileRecord]:
    """读取全部原始采集文件数据库记录。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT file_path, file_name, sample_rate_hz, center_frequency_hz,
                   bandwidth_hz, created_at, updated_at
            FROM raw_files
            ORDER BY created_at, file_name
            """
        ).fetchall()
    return [
        RawFileRecord(
            file_path=row["file_path"],
            file_name=row["file_name"],
            sample_rate_hz=float(row["sample_rate_hz"]),
            center_frequency_hz=float(row["center_frequency_hz"]),
            bandwidth_hz=float(row["bandwidth_hz"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def upsert_usrp_label_mappings(records: list[SampleRecord]) -> int:
    """按 USRP 预处理样本自动补齐设备编号映射，不覆盖人工非空映射。"""

    usrp_records: dict[str, SampleRecord] = {}
    for record in records:
        if not record.device_id.startswith("usrp_") or not record.label_type:
            continue
        usrp_records[record.device_id] = record
    if not usrp_records:
        return 0

    init_database()
    now = _now_text()
    changed_count = 0
    with _connect() as conn:
        for device_id, record in sorted(usrp_records.items()):
            existing = conn.execute(
                """
                SELECT label_type, label_individual, note
                FROM label_mappings
                WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            label_individual = record.label_individual or f"{record.label_type}_001"
            note = f"{USRP_AUTO_MAPPING_NOTE_PREFIX}：{device_id}"
            should_update = existing is None
            if existing is not None:
                has_human_label = bool(existing["label_type"] or existing["label_individual"])
                is_auto_mapping = str(existing["note"] or "").startswith(USRP_AUTO_MAPPING_NOTE_PREFIX)
                should_update = (not has_human_label) or is_auto_mapping
            if not should_update:
                continue

            conn.execute(
                """
                INSERT INTO label_mappings (
                    device_id, label_type, label_individual, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    label_type = excluded.label_type,
                    label_individual = excluded.label_individual,
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (device_id, record.label_type, label_individual, note, now, now),
            )
            changed_count += 1
    return changed_count


def list_label_mappings() -> list[LabelMappingRecord]:
    """读取自动标注映射表。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT device_id, label_type, label_individual, note
            FROM label_mappings
            ORDER BY device_id
            """
        ).fetchall()
    return [
        LabelMappingRecord(
            device_id=row["device_id"],
            label_type=row["label_type"],
            label_individual=row["label_individual"],
            note=row["note"],
        )
        for row in rows
    ]


def upsert_label_mapping(record: LabelMappingRecord) -> None:
    """新增或更新一条自动标注映射。"""

    init_database()
    now = _now_text()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO label_mappings (
                device_id, label_type, label_individual, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                label_type = excluded.label_type,
                label_individual = excluded.label_individual,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (
                record.device_id,
                record.label_type,
                record.label_individual,
                record.note,
                now,
                now,
            ),
        )


def delete_label_mapping(device_id: str) -> None:
    """删除一条自动标注映射。"""

    init_database()
    with _connect() as conn:
        conn.execute("DELETE FROM label_mappings WHERE device_id = ?", (device_id,))


def get_workflow_overview_counts() -> dict[str, object]:
    """读取总览页使用的紧凑工作流指标。"""

    init_database()
    with _connect() as conn:
        raw_count = int(conn.execute("SELECT COUNT(*) FROM raw_files").fetchone()[0])
        sample_count = int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0])
        version_row = conn.execute(
            """
            SELECT version_id
            FROM dataset_versions
            ORDER BY created_at DESC, version_id DESC
            LIMIT 1
            """
        ).fetchone()
        model_row = conn.execute(
            """
            SELECT model_id
            FROM trained_models
            ORDER BY created_at DESC, model_id DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "raw_count": raw_count,
        "sample_count": sample_count,
        "current_version": version_row["version_id"] if version_row is not None else "未生成",
        "latest_model": model_row["model_id"] if model_row is not None else "未生成",
    }


def list_samples() -> list[SampleRecord]:
    """读取全部样本记录。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT sample_id, source_type, raw_file_path, sample_file_path, label_type,
                   label_individual, sample_rate_hz, center_frequency_hz, data_format,
                   sample_count, device_id, start_sample, end_sample, snr_db, score,
                   include_in_dataset, status, source_name
            FROM samples
            ORDER BY created_at, sample_id
            """
        ).fetchall()
    return [_sample_from_row(row) for row in rows]


def update_sample_label(
    sample_id: str,
    label_type: str,
    label_individual: str,
    status: str,
    include_in_dataset: bool,
) -> None:
    """更新单条样本的人工标注结果。"""

    init_database()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE samples
            SET label_type = ?, label_individual = ?, status = ?,
                include_in_dataset = ?, updated_at = ?
            WHERE sample_id = ?
            """,
            (label_type, label_individual, status, int(include_in_dataset), _now_text(), sample_id),
        )


def delete_sample(sample_id: str) -> None:
    """删除一条样本数据库记录，不删除本地样本文件。"""

    init_database()
    with _connect() as conn:
        _delete_samples_by_ids(conn, [sample_id])


def delete_samples_by_file_path(sample_file_path: str) -> dict[str, int]:
    """按生成样本文件路径删除样本记录和数据集关联，不删除本地 .npy 文件。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sample_id FROM samples WHERE sample_file_path = ?",
            (sample_file_path,),
        ).fetchall()
        return _delete_samples_by_ids(conn, [row["sample_id"] for row in rows])


def delete_samples_by_device(device_id: str) -> dict[str, int]:
    """按设备编号批量删除样本记录和数据集关联，不删除本地样本文件。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sample_id FROM samples WHERE device_id = ?",
            (device_id,),
        ).fetchall()
        return _delete_samples_by_ids(conn, [row["sample_id"] for row in rows])


def get_raw_file_delete_impact(file_path: str) -> dict[str, int]:
    """预估删除一条原始文件记录会影响的数据库记录数量。"""

    init_database()
    with _connect() as conn:
        return _raw_file_delete_impact(conn, file_path)


def delete_raw_file_record(file_path: str) -> dict[str, int]:
    """删除原始采集数据库记录及其派生样本关联，不删除本地原始文件。"""

    init_database()
    counts = _empty_raw_file_delete_counts()
    with _connect() as conn:
        raw_row = conn.execute(
            "SELECT id FROM raw_files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        raw_file_id = int(raw_row["id"]) if raw_row is not None else None
        sample_rows = _raw_file_sample_rows(conn, file_path, raw_file_id)
        sample_counts = _delete_samples_by_ids(conn, [row["sample_id"] for row in sample_rows])
        counts.update(sample_counts)

        if raw_file_id is not None:
            cursor = conn.execute("DELETE FROM preprocess_tasks WHERE raw_file_id = ?", (raw_file_id,))
            counts["preprocess_tasks"] = int(cursor.rowcount if cursor.rowcount != -1 else 0)
            cursor = conn.execute("DELETE FROM raw_files WHERE id = ?", (raw_file_id,))
            counts["raw_files"] = int(cursor.rowcount if cursor.rowcount != -1 else 0)
    return counts


def delete_dataset_version(version_id: str) -> None:
    """删除一个数据集版本记录，不影响样本表。"""

    init_database()
    with _connect() as conn:
        # 版本删除只移除版本和关联关系，样本本身继续保留。
        conn.execute("DELETE FROM dataset_items WHERE version_id = ?", (version_id,))
        conn.execute("DELETE FROM dataset_versions WHERE version_id = ?", (version_id,))


def clear_processed_dataset_records() -> dict[str, int]:
    """清空原始记录、预处理样本、数据集和模型记录，不删除本地文件。"""

    init_database()
    with _connect() as conn:
        counts = {
            "trained_models": int(conn.execute("SELECT COUNT(*) FROM trained_models").fetchone()[0]),
            "dataset_items": int(conn.execute("SELECT COUNT(*) FROM dataset_items").fetchone()[0]),
            "dataset_versions": int(conn.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()[0]),
            "samples": int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]),
            "preprocess_tasks": int(conn.execute("SELECT COUNT(*) FROM preprocess_tasks").fetchone()[0]),
            "raw_files": int(conn.execute("SELECT COUNT(*) FROM raw_files").fetchone()[0]),
        }
        # 清理数据库记录，不删除本地 .iq/.json/.cap/.npy/model 文件。
        conn.execute("DELETE FROM trained_models")
        conn.execute("DELETE FROM dataset_items")
        conn.execute("DELETE FROM dataset_versions")
        conn.execute("DELETE FROM samples")
        conn.execute("DELETE FROM preprocess_tasks")
        conn.execute("DELETE FROM raw_files")
    return counts


def create_dataset_version(
    record: DatasetVersionRecord,
    sample_ids: list[str],
    label_values: dict[str, str],
    split_values: dict[str, str] | None = None,
) -> None:
    """保存一个数据集版本及其样本关联。"""

    init_database()
    split_values = split_values or {}
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO dataset_versions (
                version_id, task_type, sample_count, strategy, created_at,
                source_summary, label_counts_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.version_id,
                record.task_type,
                record.sample_count,
                record.strategy,
                record.created_at,
                record.source_summary,
                json.dumps(record.label_counts, ensure_ascii=False),
            ),
        )
        conn.execute("DELETE FROM dataset_items WHERE version_id = ?", (record.version_id,))
        created_at = _now_text()
        rows = [
            (
                record.version_id,
                sample_id,
                label_values.get(sample_id, ""),
                split_values.get(sample_id, "train"),
                created_at,
            )
            for sample_id in sample_ids
        ]
        conn.executemany(
            """
            INSERT INTO dataset_items (version_id, sample_id, label_value, split, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def list_dataset_versions() -> list[DatasetVersionRecord]:
    """读取全部数据集版本。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT version_id, task_type, sample_count, strategy, created_at,
                   source_summary, label_counts_json
            FROM dataset_versions
            ORDER BY created_at, version_id
            """
        ).fetchall()

    records: list[DatasetVersionRecord] = []
    for row in rows:
        try:
            label_counts = json.loads(row["label_counts_json"] or "{}")
        except json.JSONDecodeError:
            label_counts = {}
        records.append(
            DatasetVersionRecord(
                version_id=row["version_id"],
                task_type=row["task_type"],
                sample_count=int(row["sample_count"]),
                strategy=row["strategy"],
                created_at=row["created_at"],
                source_summary=row["source_summary"],
                label_counts={str(key): int(value) for key, value in label_counts.items()},
            )
        )
    return records


def list_dataset_items(version_id: str) -> list[DatasetItemRecord]:
    """读取一个数据集版本下的真实样本清单。"""

    init_database()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                di.version_id,
                di.sample_id,
                di.label_value,
                di.split,
                s.source_type,
                s.raw_file_path,
                s.sample_file_path,
                s.label_type,
                s.label_individual,
                s.sample_rate_hz,
                s.center_frequency_hz,
                s.device_id,
                s.sample_count
            FROM dataset_items di
            JOIN samples s ON s.sample_id = di.sample_id
            WHERE di.version_id = ?
            ORDER BY di.split, di.sample_id
            """,
            (version_id,),
        ).fetchall()

    items: list[DatasetItemRecord] = []
    for row in rows:
        sample_path = Path(row["sample_file_path"])
        items.append(
            DatasetItemRecord(
                version_id=row["version_id"],
                sample_id=row["sample_id"],
                source_type=row["source_type"],
                raw_file_path=row["raw_file_path"],
                sample_file_path=str(sample_path),
                label_value=row["label_value"],
                label_type=row["label_type"],
                label_individual=row["label_individual"],
                split=row["split"],
                source_file=Path(row["raw_file_path"]).name,
                sample_rate_hz=float(row["sample_rate_hz"]),
                center_frequency_hz=float(row["center_frequency_hz"]),
                sample_count=int(row["sample_count"]),
                device_id=row["device_id"],
                file_exists=sample_path.exists(),
            )
        )
    return items


def get_dataset_version_detail(version_id: str) -> DatasetVersionDetail | None:
    """读取训练页需要的数据集版本详情。"""

    version = next((record for record in list_dataset_versions() if record.version_id == version_id), None)
    if version is None:
        return None

    items = list_dataset_items(version_id)
    manifest_path = DATASETS_DIR / version_id / "manifest.json"
    return DatasetVersionDetail(
        version=version,
        items=items,
        manifest_path=str(manifest_path),
        missing_file_count=sum(1 for item in items if not item.file_exists),
        empty_label_count=sum(1 for item in items if not item.label_value),
    )


def write_dataset_manifest(version_id: str) -> Path | None:
    """把数据集版本详情导出为训练入口可读取的 manifest。"""

    detail = get_dataset_version_detail(version_id)
    if detail is None:
        return None

    manifest_path = Path(detail.manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version_id": detail.version.version_id,
        "task_type": detail.version.task_type,
        "strategy": detail.version.strategy,
        "sample_count": detail.version.sample_count,
        "source_summary": detail.version.source_summary,
        "label_counts": detail.version.label_counts,
        "split_random_seed": DATASET_SPLIT_RANDOM_SEED,
        "split_summary": _build_manifest_split_summary(detail.items),
        "missing_file_count": detail.missing_file_count,
        "empty_label_count": detail.empty_label_count,
        "items": [
            {
                "sample_id": item.sample_id,
                "source_type": item.source_type,
                "raw_file_path": item.raw_file_path,
                "sample_file_path": item.sample_file_path,
                "label_value": item.label_value,
                "label_type": item.label_type,
                "label_individual": item.label_individual,
                "split": item.split,
                "source_file": item.source_file,
                "sample_rate_hz": item.sample_rate_hz,
                "center_frequency_hz": item.center_frequency_hz,
                "device_id": item.device_id,
                "sample_count": item.sample_count,
                "file_exists": item.file_exists,
            }
            for item in detail.items
        ],
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _build_manifest_split_summary(items: list[DatasetItemRecord]) -> dict[str, dict[str, object]]:
    """生成 manifest 中的划分摘要，便于训练页和人工复核。"""

    summary: dict[str, dict[str, object]] = {}
    for item in items:
        split_bucket = summary.setdefault(item.split, {"sample_count": 0, "label_counts": {}, "device_count": 0})
        split_bucket["sample_count"] = int(split_bucket["sample_count"]) + 1
        label_counts = split_bucket["label_counts"]
        if isinstance(label_counts, dict):
            label_counts[item.label_value] = int(label_counts.get(item.label_value, 0)) + 1

    for split, split_bucket in summary.items():
        devices = {item.device_id for item in items if item.split == split and item.device_id}
        split_bucket["device_count"] = len(devices)
    return summary


def save_trained_model(record: TrainedModelRecord) -> None:
    """写入或更新一条训练模型记录。"""

    init_database()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO trained_models (
                model_id, dataset_version_id, task_type, model_kind, label_space_json,
                artifact_path, metrics_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.model_id,
                record.dataset_version_id,
                record.task_type,
                record.model_kind,
                json.dumps(record.label_space, ensure_ascii=False),
                record.artifact_path,
                json.dumps(record.metrics, ensure_ascii=False),
                record.status,
                record.created_at,
            ),
        )


def list_trained_models(task_type: str | None = None) -> list[TrainedModelRecord]:
    """读取全部已登记的训练模型记录。"""

    init_database()
    query = """
        SELECT model_id, dataset_version_id, task_type, model_kind, label_space_json,
               artifact_path, metrics_json, status, created_at
        FROM trained_models
    """
    params: tuple[object, ...] = ()
    if task_type:
        query += " WHERE task_type = ?"
        params = (task_type,)
    query += " ORDER BY created_at DESC, model_id DESC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_trained_model_from_row(row) for row in rows]


def get_trained_model(model_id: str) -> TrainedModelRecord | None:
    """按模型编号读取一条训练模型记录。"""

    init_database()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT model_id, dataset_version_id, task_type, model_kind, label_space_json,
                   artifact_path, metrics_json, status, created_at
            FROM trained_models
            WHERE model_id = ?
            """,
            (model_id,),
        ).fetchone()
    if row is None:
        return None
    return _trained_model_from_row(row)


def delete_trained_model(model_id: str) -> None:
    """删除一条模型数据库记录，不删除本地模型文件。"""

    init_database()
    with _connect() as conn:
        conn.execute("DELETE FROM trained_models WHERE model_id = ?", (model_id,))


def _empty_raw_file_delete_counts() -> dict[str, int]:
    """返回原始文件删除影响统计的默认结构。"""

    return {
        "raw_files": 0,
        "preprocess_tasks": 0,
        "samples": 0,
        "dataset_items": 0,
        "dataset_versions_deleted": 0,
        "dataset_versions_updated": 0,
    }


def _raw_file_delete_impact(conn: sqlite3.Connection, file_path: str) -> dict[str, int]:
    """计算删除原始文件记录前的数据库影响范围。"""

    counts = _empty_raw_file_delete_counts()
    raw_row = conn.execute(
        "SELECT id FROM raw_files WHERE file_path = ?",
        (file_path,),
    ).fetchone()
    raw_file_id = int(raw_row["id"]) if raw_row is not None else None
    counts["raw_files"] = 1 if raw_file_id is not None else 0
    if raw_file_id is not None:
        counts["preprocess_tasks"] = int(
            conn.execute("SELECT COUNT(*) FROM preprocess_tasks WHERE raw_file_id = ?", (raw_file_id,)).fetchone()[0]
        )

    sample_ids = [row["sample_id"] for row in _raw_file_sample_rows(conn, file_path, raw_file_id)]
    counts["samples"] = len(sample_ids)
    if not sample_ids:
        return counts

    placeholders = ", ".join("?" for _ in sample_ids)
    counts["dataset_items"] = int(
        conn.execute(
            f"SELECT COUNT(*) FROM dataset_items WHERE sample_id IN ({placeholders})",
            tuple(sample_ids),
        ).fetchone()[0]
    )
    version_rows = conn.execute(
        f"SELECT DISTINCT version_id FROM dataset_items WHERE sample_id IN ({placeholders})",
        tuple(sample_ids),
    ).fetchall()
    for row in version_rows:
        version_id = row["version_id"]
        remaining_count = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM dataset_items
                WHERE version_id = ? AND sample_id NOT IN ({placeholders})
                """,
                (version_id, *sample_ids),
            ).fetchone()[0]
        )
        if remaining_count <= 0:
            counts["dataset_versions_deleted"] += 1
        else:
            counts["dataset_versions_updated"] += 1
    return counts


def _raw_file_sample_rows(
    conn: sqlite3.Connection,
    file_path: str,
    raw_file_id: int | None,
) -> list[sqlite3.Row]:
    """读取一个原始文件关联的样本行，兼容 raw_file_id 缺失的旧记录。"""

    if raw_file_id is None:
        return conn.execute(
            "SELECT sample_id FROM samples WHERE raw_file_path = ?",
            (file_path,),
        ).fetchall()
    return conn.execute(
        """
        SELECT sample_id
        FROM samples
        WHERE raw_file_id = ? OR raw_file_path = ?
        """,
        (raw_file_id, file_path),
    ).fetchall()


def _delete_samples_by_ids(conn: sqlite3.Connection, sample_ids: list[str]) -> dict[str, int]:
    """删除样本和数据集关联，并刷新受影响版本摘要。"""

    unique_ids = [sample_id for sample_id in dict.fromkeys(sample_ids) if sample_id]
    counts = {
        "samples": 0,
        "dataset_items": 0,
        "dataset_versions_deleted": 0,
        "dataset_versions_updated": 0,
    }
    if not unique_ids:
        return counts

    placeholders = ", ".join("?" for _ in unique_ids)
    version_rows = conn.execute(
        f"SELECT DISTINCT version_id FROM dataset_items WHERE sample_id IN ({placeholders})",
        tuple(unique_ids),
    ).fetchall()
    version_ids = [row["version_id"] for row in version_rows]

    cursor = conn.execute(
        f"DELETE FROM dataset_items WHERE sample_id IN ({placeholders})",
        tuple(unique_ids),
    )
    counts["dataset_items"] = int(cursor.rowcount if cursor.rowcount != -1 else 0)
    cursor = conn.execute(
        f"DELETE FROM samples WHERE sample_id IN ({placeholders})",
        tuple(unique_ids),
    )
    counts["samples"] = int(cursor.rowcount if cursor.rowcount != -1 else 0)

    summary_counts = _refresh_dataset_version_summaries(conn, version_ids)
    counts.update(summary_counts)
    return counts


def _refresh_dataset_version_summaries(conn: sqlite3.Connection, version_ids: list[str]) -> dict[str, int]:
    """重算样本删除后受影响的数据集版本摘要，空版本直接移除。"""

    counts = {"dataset_versions_deleted": 0, "dataset_versions_updated": 0}
    for version_id in dict.fromkeys(version_ids):
        rows = conn.execute(
            """
            SELECT label_value, COUNT(*) AS sample_count
            FROM dataset_items
            WHERE version_id = ?
            GROUP BY label_value
            """,
            (version_id,),
        ).fetchall()
        if not rows:
            cursor = conn.execute("DELETE FROM dataset_versions WHERE version_id = ?", (version_id,))
            counts["dataset_versions_deleted"] += int(cursor.rowcount if cursor.rowcount != -1 else 0)
            continue

        label_counts = {str(row["label_value"]): int(row["sample_count"]) for row in rows}
        sample_count = sum(label_counts.values())
        conn.execute(
            """
            UPDATE dataset_versions
            SET sample_count = ?, label_counts_json = ?
            WHERE version_id = ?
            """,
            (sample_count, json.dumps(label_counts, ensure_ascii=False), version_id),
        )
        counts["dataset_versions_updated"] += 1
    return counts


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """创建一次短生命周期 SQLite 连接。"""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 当前项目是单机桌面联调工具，关闭 rollback journal 可避开部分 Windows
    # 目录权限/占用导致的 journal 写入失败；后续正式版可切回 WAL。
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _upsert_raw_file(
    conn: sqlite3.Connection,
    file_path: str,
    sample_rate_hz: float,
    center_frequency_hz: float,
    bandwidth_hz: float,
    now: str,
) -> int:
    """写入或更新原始文件记录，并返回主键。"""

    file_name = Path(file_path).name
    conn.execute(
        """
        INSERT INTO raw_files (
            file_path, file_name, sample_rate_hz, center_frequency_hz,
            bandwidth_hz, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            sample_rate_hz = CASE
                WHEN excluded.sample_rate_hz > 0 THEN excluded.sample_rate_hz
                ELSE raw_files.sample_rate_hz
            END,
            center_frequency_hz = CASE
                WHEN excluded.center_frequency_hz > 0 THEN excluded.center_frequency_hz
                ELSE raw_files.center_frequency_hz
            END,
            bandwidth_hz = CASE
                WHEN excluded.bandwidth_hz > 0 THEN excluded.bandwidth_hz
                ELSE raw_files.bandwidth_hz
            END,
            updated_at = excluded.updated_at
        """,
        (file_path, file_name, sample_rate_hz, center_frequency_hz, bandwidth_hz, now, now),
    )
    row = conn.execute("SELECT id FROM raw_files WHERE file_path = ?", (file_path,)).fetchone()
    return int(row["id"])


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    """在轻量原型阶段为旧数据库补齐新增列。"""

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(row["name"] == column_name for row in rows):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def _seed_default_label_mappings(conn: sqlite3.Connection) -> None:
    """首次初始化时写入 USRP 演示频点映射。"""

    seeded = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'default_label_mappings_seeded'"
    ).fetchone()
    if seeded is not None and seeded["value"] == "1":
        return

    now = _now_text()
    conn.executemany(
        """
        INSERT OR IGNORE INTO label_mappings (
            device_id, label_type, label_individual, note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                record.device_id,
                record.label_type,
                record.label_individual,
                record.note,
                now,
                now,
            )
            for record in DEFAULT_LABEL_MAPPINGS
        ],
    )
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('default_label_mappings_seeded', '1')"
    )


def _upsert_samples(
    conn: sqlite3.Connection,
    records: list[SampleRecord],
    raw_file_id: int | None,
    preprocess_task_id: int | None,
    now: str,
) -> None:
    """批量写入或更新样本记录。"""

    for record in records:
        conn.execute(
            """
            INSERT INTO samples (
                sample_id, raw_file_id, preprocess_task_id, source_type,
                raw_file_path, sample_file_path, label_type, label_individual,
                sample_rate_hz, center_frequency_hz, data_format, sample_count,
                device_id, start_sample, end_sample, snr_db, score,
                include_in_dataset, status, source_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sample_id) DO UPDATE SET
                raw_file_id = excluded.raw_file_id,
                preprocess_task_id = COALESCE(excluded.preprocess_task_id, samples.preprocess_task_id),
                source_type = excluded.source_type,
                raw_file_path = excluded.raw_file_path,
                sample_file_path = excluded.sample_file_path,
                label_type = excluded.label_type,
                label_individual = excluded.label_individual,
                sample_rate_hz = excluded.sample_rate_hz,
                center_frequency_hz = excluded.center_frequency_hz,
                data_format = excluded.data_format,
                sample_count = excluded.sample_count,
                device_id = excluded.device_id,
                start_sample = excluded.start_sample,
                end_sample = excluded.end_sample,
                snr_db = excluded.snr_db,
                score = excluded.score,
                include_in_dataset = excluded.include_in_dataset,
                status = excluded.status,
                source_name = excluded.source_name,
                updated_at = excluded.updated_at
            """,
            (
                record.sample_id,
                raw_file_id,
                preprocess_task_id,
                record.source_type,
                record.raw_file_path,
                record.sample_file_path,
                record.label_type,
                record.label_individual,
                record.sample_rate_hz,
                record.center_frequency_hz,
                record.data_format,
                record.sample_count,
                record.device_id,
                record.start_sample,
                record.end_sample,
                record.snr_db,
                record.score,
                int(record.include_in_dataset),
                _normalize_sample_status(record.status),
                record.source_name,
                now,
                now,
            ),
        )


def _sample_from_row(row: sqlite3.Row) -> SampleRecord:
    """把数据库行转换为页面统一样本记录。"""

    return SampleRecord(
        sample_id=row["sample_id"],
        source_type=row["source_type"],
        raw_file_path=row["raw_file_path"],
        sample_file_path=row["sample_file_path"],
        label_type=row["label_type"],
        label_individual=row["label_individual"],
        sample_rate_hz=float(row["sample_rate_hz"]),
        center_frequency_hz=float(row["center_frequency_hz"]),
        data_format=row["data_format"],
        sample_count=int(row["sample_count"]),
        device_id=row["device_id"],
        start_sample=int(row["start_sample"]),
        end_sample=int(row["end_sample"]),
        snr_db=float(row["snr_db"]),
        score=float(row["score"]),
        include_in_dataset=bool(row["include_in_dataset"]),
        status=_normalize_sample_status(row["status"]),
        source_name=row["source_name"],
    )


def _trained_model_from_row(row: sqlite3.Row) -> TrainedModelRecord:
    """把数据库行转换为统一的训练模型记录。"""

    try:
        label_space = json.loads(row["label_space_json"] or "[]")
    except json.JSONDecodeError:
        label_space = []
    try:
        metrics = json.loads(row["metrics_json"] or "{}")
    except json.JSONDecodeError:
        metrics = {}

    return TrainedModelRecord(
        model_id=row["model_id"],
        dataset_version_id=row["dataset_version_id"],
        task_type=row["task_type"],
        model_kind=row["model_kind"],
        label_space=[str(value) for value in label_space],
        artifact_path=row["artifact_path"],
        metrics=metrics if isinstance(metrics, dict) else {},
        status=row["status"],
        created_at=row["created_at"],
    )


def _config_to_jsonable_dict(config: Any) -> dict[str, Any]:
    """把预处理配置对象转换为 JSON 友好的字典。"""

    raw_dict = asdict(config) if hasattr(config, "__dataclass_fields__") else dict(config)
    return {key: str(value) if isinstance(value, Path) else value for key, value in raw_dict.items()}


def _now_text() -> str:
    """返回统一格式的本地时间字符串。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_sample_status(status: str) -> str:
    """把历史状态归并到当前三态模型。"""

    if status in {"待标注", "已标注", "已排除"}:
        return status
    if status == "待复核":
        return "待标注"
    return "待标注"


def _migrate_trained_models_to_weak_version_reference(conn: sqlite3.Connection) -> None:
    """把 trained_models 从强外键升级为弱版本引用。"""

    foreign_keys = conn.execute("PRAGMA foreign_key_list(trained_models)").fetchall()
    if not any(row[2] == "dataset_versions" for row in foreign_keys):
        return

    conn.executescript(
        """
        ALTER TABLE trained_models RENAME TO trained_models_old;

        CREATE TABLE trained_models (
            model_id TEXT PRIMARY KEY,
            dataset_version_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            model_kind TEXT NOT NULL,
            label_space_json TEXT NOT NULL DEFAULT '[]',
            artifact_path TEXT NOT NULL,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT '训练完成',
            created_at TEXT NOT NULL
        );

        INSERT INTO trained_models (
            model_id, dataset_version_id, task_type, model_kind,
            label_space_json, artifact_path, metrics_json, status, created_at
        )
        SELECT
            model_id, dataset_version_id, task_type, model_kind,
            label_space_json, artifact_path, metrics_json, status, created_at
        FROM trained_models_old;

        DROP TABLE trained_models_old;

        CREATE INDEX IF NOT EXISTS idx_trained_models_dataset_version ON trained_models(dataset_version_id);
        """
    )
