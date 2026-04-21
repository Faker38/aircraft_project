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

from config import DB_DIR
from services.workflow_records import DatasetVersionRecord, SampleRecord


DB_PATH = DB_DIR / "aircraft_project.sqlite3"


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
                created_at TEXT NOT NULL,
                PRIMARY KEY(version_id, sample_id),
                FOREIGN KEY(version_id) REFERENCES dataset_versions(version_id),
                FOREIGN KEY(sample_id) REFERENCES samples(sample_id)
            );

            CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);
            CREATE INDEX IF NOT EXISTS idx_samples_raw_file ON samples(raw_file_id);
            CREATE INDEX IF NOT EXISTS idx_dataset_items_version ON dataset_items(version_id);
            """
        )


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
        for record in records:
            raw_file_id = _upsert_raw_file(
                conn,
                file_path=record.raw_file_path,
                sample_rate_hz=record.sample_rate_hz,
                center_frequency_hz=record.center_frequency_hz,
                bandwidth_hz=0.0,
                now=now,
            )
            _upsert_samples(conn, [record], raw_file_id=raw_file_id, preprocess_task_id=None, now=now)


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


def create_dataset_version(record: DatasetVersionRecord, sample_ids: list[str], label_values: dict[str, str]) -> None:
    """保存一个数据集版本及其样本关联。"""

    init_database()
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
        for sample_id in sample_ids:
            conn.execute(
                """
                INSERT INTO dataset_items (version_id, sample_id, label_value, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (record.version_id, sample_id, label_values.get(sample_id, ""), _now_text()),
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
    """写入或更新原始 CAP 文件记录，并返回主键。"""

    file_name = Path(file_path).name
    conn.execute(
        """
        INSERT INTO raw_files (
            file_path, file_name, sample_rate_hz, center_frequency_hz,
            bandwidth_hz, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            sample_rate_hz = excluded.sample_rate_hz,
            center_frequency_hz = excluded.center_frequency_hz,
            bandwidth_hz = excluded.bandwidth_hz,
            updated_at = excluded.updated_at
        """,
        (file_path, file_name, sample_rate_hz, center_frequency_hz, bandwidth_hz, now, now),
    )
    row = conn.execute("SELECT id FROM raw_files WHERE file_path = ?", (file_path,)).fetchone()
    return int(row["id"])


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
                record.status,
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
        status=row["status"],
        source_name=row["source_name"],
    )


def _config_to_jsonable_dict(config: Any) -> dict[str, Any]:
    """把预处理配置对象转换为 JSON 友好的字典。"""

    raw_dict = asdict(config) if hasattr(config, "__dataclass_fields__") else dict(config)
    return {key: str(value) if isinstance(value, Path) else value for key, value in raw_dict.items()}


def _now_text() -> str:
    """返回统一格式的本地时间字符串。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
