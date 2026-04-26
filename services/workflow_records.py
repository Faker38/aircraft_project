"""跨数据集、训练和识别页面共享的工作流记录结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SampleRecord:
    """后续流程页面统一使用的样本记录。"""

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
    snr_db: float = 0.0
    score: float = 0.0
    include_in_dataset: bool = True
    status: str = "待标注"
    source_name: str = ""

    @property
    def raw_file_name(self) -> str:
        """返回紧凑表格里展示的源文件名。"""

        return Path(self.raw_file_path).name

    @property
    def sample_file_name(self) -> str:
        """返回生成后的样本文件名。"""

        return Path(self.sample_file_path).name

    @property
    def source_label(self) -> str:
        """返回适合界面展示的样本来源标签。"""

        return {
            "local_preprocess": "预处理输出",
        }.get(self.source_type, "未知来源")


@dataclass(frozen=True)
class DatasetVersionRecord:
    """数据集页和训练页共用的数据集版本摘要。"""

    version_id: str
    task_type: str
    sample_count: int
    strategy: str
    created_at: str
    source_summary: str
    label_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetItemRecord:
    """数据集版本中一条可训练样本记录。"""

    version_id: str
    sample_id: str
    sample_file_path: str
    label_value: str
    label_type: str
    label_individual: str
    split: str
    source_file: str
    sample_count: int
    file_exists: bool


@dataclass(frozen=True)
class DatasetVersionDetail:
    """训练页消费的数据集版本详情。"""

    version: DatasetVersionRecord
    items: list[DatasetItemRecord]
    manifest_path: str
    missing_file_count: int
    empty_label_count: int


@dataclass(frozen=True)
class TrainedModelRecord:
    """训练完成后写入数据库的模型记录。"""

    model_id: str
    dataset_version_id: str
    task_type: str
    model_kind: str
    label_space: list[str] = field(default_factory=list)
    artifact_path: str = ""
    metrics: dict[str, object] = field(default_factory=dict)
    status: str = "训练完成"
    created_at: str = ""

    @property
    def accuracy_text(self) -> str:
        """返回适合界面展示的精度文本。"""

        value = self.metrics.get("test_accuracy")
        if value is None:
            return "-"
        return f"{float(value) * 100:.1f}%"

    @property
    def macro_f1_text(self) -> str:
        """返回适合界面展示的宏平均 F1 文本。"""

        value = self.metrics.get("test_macro_f1")
        if value is None:
            return "-"
        return f"{float(value):.3f}"

    @property
    def validation_accuracy_text(self) -> str:
        """返回适合界面展示的验证集精度文本。"""

        value = self.metrics.get("val_accuracy")
        if value is None:
            return "-"
        return f"{float(value) * 100:.1f}%"

    @property
    def random_state_text(self) -> str:
        """返回适合界面展示的随机种子文本。"""

        value = self.metrics.get("random_state")
        return str(value) if value is not None else "-"

    @property
    def n_estimators_text(self) -> str:
        """返回适合界面展示的树数量文本。"""

        value = self.metrics.get("n_estimators")
        return str(value) if value is not None else "-"

    @property
    def max_depth_text(self) -> str:
        """返回适合界面展示的最大深度文本。"""

        value = self.metrics.get("max_depth")
        if value in (None, 0, "0"):
            return "不限"
        return str(value)


@dataclass(frozen=True)
class TrainingMetricRow:
    """训练结果表格中的一行分类指标。"""

    label: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True)
class TrainingRunResult:
    """一次真实训练完成后返回给训练页的统一结果。"""

    model_record: TrainedModelRecord
    manifest_path: str
    split_counts: dict[str, int] = field(default_factory=dict)
    label_counts: dict[str, int] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    metric_rows: list[TrainingMetricRow] = field(default_factory=list)
    confusion_matrix: list[list[int]] = field(default_factory=list)
    feature_count: int = 0


@dataclass(frozen=True)
class PredictionResult:
    """识别页展示的一次预测结果。"""

    model_record: TrainedModelRecord
    predicted_label: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelEvaluationResult:
    """训练页中一次批量模型测试的统一结果。"""

    model_record: TrainedModelRecord
    manifest_csv_path: str
    report_path: str
    metrics_csv_path: str
    sample_count: int
    accuracy: float
    macro_f1: float
    confusion_matrix: list[list[int]] = field(default_factory=list)
    metric_rows: list[TrainingMetricRow] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    label_space: list[str] = field(default_factory=list)
