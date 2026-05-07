"""Dataset page for processed-sample review, mapping maintenance, and dataset management."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QHeaderView,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import BASE_DIR
from services import (
    DatasetVersionRecord,
    LabelMappingRecord,
    OrphanFileRecord,
    SampleRecord,
    clear_processed_dataset_records,
    delete_label_mapping,
    delete_dataset_version,
    delete_orphan_local_paths,
    delete_sample,
    delete_samples_by_device,
    init_database,
    import_external_dataset_directory,
    ExternalDatasetImportError,
    list_dataset_versions,
    list_label_mappings,
    list_orphan_local_paths,
    list_samples,
    upsert_label_mapping,
    upsert_samples,
)
from ui.auto_label_worker import AutoLabelWorker
from ui.dataset_build_worker import DatasetBuildWorker, calculate_split_counts, collect_dataset_candidates
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class DatasetPage(QWidget):
    """Workflow page for processed-sample review, annotation, and dataset management."""

    sample_records_updated = Signal(object)
    dataset_versions_updated = Signal(object)

    SAMPLE_ID_COLUMN = 0
    SOURCE_COLUMN = 1
    RAW_FILE_COLUMN = 2
    DEVICE_COLUMN = 3
    SAMPLE_COUNT_COLUMN = 4
    SNR_COLUMN = 5
    SCORE_COLUMN = 6
    TYPE_COLUMN = 7
    INDIVIDUAL_COLUMN = 8
    INCLUDE_COLUMN = 9
    STATUS_COLUMN = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the dataset page."""

        super().__init__(parent)
        init_database()
        self._mapping_edit_row: int | None = None
        self._auto_label_thread: QThread | None = None
        self._auto_label_worker: AutoLabelWorker | None = None
        self._dataset_build_thread: QThread | None = None
        self._dataset_build_worker: DatasetBuildWorker | None = None
        self.sample_records: list[SampleRecord] = list_samples()
        self.dataset_versions: list[DatasetVersionRecord] = list_dataset_versions()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()
        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.mapping_metric = MetricCard("编号映射", "0", compact=True)
        self.sample_metric = MetricCard("已处理样本", "0", accent_color="#7CB98B", compact=True)
        self.pending_metric = MetricCard("待标注", "0", accent_color="#C59A63", compact=True)
        current_version = self.dataset_versions[-1].version_id if self.dataset_versions else "未生成"
        self.version_metric = MetricCard("数据集", current_version, accent_color="#5EA6D3", compact=True)
        metrics_row.addWidget(self.mapping_metric)
        metrics_row.addWidget(self.sample_metric)
        metrics_row.addWidget(self.pending_metric)
        metrics_row.addWidget(self.version_metric)
        content_layout.addLayout(metrics_row)

        content_layout.addWidget(self._build_sample_flow_card())

        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)
        mid_row.addWidget(self._build_mapping_card(), 2)
        mid_row.addWidget(self._build_sample_label_card(), 3)
        content_layout.addLayout(mid_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(14)
        bottom_row.addWidget(self._build_dataset_config_card(), 2)
        bottom_row.addWidget(self._build_dataset_result_card(), 3)
        content_layout.addLayout(bottom_row)

        content_layout.addWidget(self._build_history_card())
        self.maintenance_card = self._build_danger_zone_card()
        self.maintenance_card.setVisible(False)
        content_layout.addWidget(self.maintenance_card)
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._refresh_sample_table()
        self._refresh_history_table()
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self._sync_delete_device_samples_button()
        self._refresh_dataset_generation_controls()

    def get_sample_records(self) -> list[SampleRecord]:
        """Return the current downstream sample records."""

        return list(self.sample_records)

    def get_dataset_versions(self) -> list[DatasetVersionRecord]:
        """Return the current dataset versions."""

        return list(self.dataset_versions)

    def refresh_from_database(self, *, emit_signals: bool = True) -> None:
        """从 SQLite 重新加载映射、样本和版本，并刷新下游页面。"""

        self.sample_records = list_samples()
        self.dataset_versions = list_dataset_versions()
        self._reload_mapping_table()
        self._refresh_sample_table()
        self._refresh_history_table()
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self._refresh_dataset_generation_controls(update_status=False)
        self.version_metric.set_value(self.dataset_versions[-1].version_id if self.dataset_versions else "未生成")
        if emit_signals:
            self.sample_records_updated.emit(self.get_sample_records())
            self.dataset_versions_updated.emit(self.get_dataset_versions())

    def add_preprocess_records(self, records: list[SampleRecord]) -> None:
        """Append or update preprocess-generated sample records."""

        preprocess_records = [
            record for record in records if record.source_type in {"local_preprocess", "usrp_preprocess"}
        ]
        if not preprocess_records:
            return

        upsert_samples(preprocess_records)
        self.refresh_from_database(emit_signals=False)
        self.annotation_status_label.setText(
            f"已同步 {len(preprocess_records)} 条预处理候选样本，请继续完成或确认标注。"
        )
        self.sample_records_updated.emit(self.get_sample_records())

    def _build_sample_flow_card(self) -> SectionCard:
        """Create the simplified processed-sample workflow card."""

        section = SectionCard(
            "已处理样本",
            "",
            compact=True,
        )

        info_layout = QFormLayout()
        info_layout.setHorizontalSpacing(12)
        info_layout.setVerticalSpacing(10)

        self.processed_value = QLabel(str(len(self.sample_records)))
        self.processed_value.setObjectName("ValueLabel")
        self.ready_value = QLabel(str(sum(1 for record in self.sample_records if record.status == "已标注")))
        self.ready_value.setObjectName("ValueLabel")
        next_step_value = QLabel("数据集生成")
        next_step_value.setObjectName("ValueLabel")

        info_layout.addRow("样本数", self.processed_value)
        info_layout.addRow("已标注样本", self.ready_value)
        info_layout.addRow("下一步", next_step_value)

        section.body_layout.addLayout(info_layout)
        return section

    def _build_mapping_card(self) -> SectionCard:
        """Create the mapping maintenance card."""

        section = SectionCard(
            "编号映射",
            "",
            right_widget=StatusBadge("可编辑", "info", size="sm"),
            compact=True,
        )

        mapping_rows = list_label_mappings()
        self.mapping_table = QTableWidget(len(mapping_rows), 4)
        self.mapping_table.setHorizontalHeaderLabels(["设备编号", "类型标签", "个体标签", "备注"])
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mapping_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.mapping_table.setColumnWidth(0, 150)
        self.mapping_table.setColumnWidth(1, 110)
        self.mapping_table.setColumnWidth(2, 120)
        self.mapping_table.setColumnWidth(3, 180)
        configure_scrollable(self.mapping_table)
        self.mapping_table.itemSelectionChanged.connect(self._sync_mapping_form_from_selection)

        for row_index, record in enumerate(mapping_rows):
            row_data = [record.device_id, record.label_type, record.label_individual, record.note]
            for column, value in enumerate(row_data):
                self._set_table_value(self.mapping_table, row_index, column, value)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(10)

        self.mapping_device_input = QLineEdit()
        self.mapping_type_input = QLineEdit()
        self.mapping_individual_input = QLineEdit()
        self.mapping_note_input = QLineEdit()

        self.mapping_device_input.setPlaceholderText("例如 usrp_2412M")
        self.mapping_type_input.setPlaceholderText("例如 频点A")
        self.mapping_individual_input.setPlaceholderText("例如 频点A_001")
        self.mapping_note_input.setPlaceholderText("可选备注")

        form_layout.addRow("设备编号", self.mapping_device_input)
        form_layout.addRow("类型标签", self.mapping_type_input)
        form_layout.addRow("个体标签", self.mapping_individual_input)
        form_layout.addRow("备注", self.mapping_note_input)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.mapping_new_button = QPushButton("新增映射")
        self.mapping_new_button.clicked.connect(self._clear_mapping_form)

        self.mapping_save_button = QPushButton("保存映射")
        self.mapping_save_button.setObjectName("PrimaryButton")
        self.mapping_save_button.clicked.connect(self._save_mapping)

        self.mapping_delete_button = QPushButton("删除映射")
        self.mapping_delete_button.clicked.connect(self._delete_mapping)

        button_row.addWidget(self.mapping_new_button)
        button_row.addWidget(self.mapping_save_button)
        button_row.addWidget(self.mapping_delete_button)
        button_row.addStretch(1)

        self.mapping_status_label = QLabel("")
        self.mapping_status_label.setObjectName("MutedText")
        self.mapping_status_label.setWordWrap(True)

        section.body_layout.addWidget(self.mapping_table)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.mapping_status_label)
        return section

    def _reload_mapping_table(self) -> None:
        """从数据库刷新编号映射表。"""

        if not hasattr(self, "mapping_table"):
            return
        mapping_rows = list_label_mappings()
        self.mapping_table.blockSignals(True)
        self.mapping_table.setRowCount(len(mapping_rows))
        for row_index, record in enumerate(mapping_rows):
            row_data = [record.device_id, record.label_type, record.label_individual, record.note]
            for column, value in enumerate(row_data):
                self._set_table_value(self.mapping_table, row_index, column, value)
        self.mapping_table.blockSignals(False)
        self._mapping_edit_row = None
        self.mapping_metric.set_value(str(len(mapping_rows)))

    def _build_sample_label_card(self) -> SectionCard:
        """Create the sample annotation card."""

        section = SectionCard("样本标注", "", compact=True)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)

        self.type_radio = QRadioButton("类型识别")
        self.type_radio.setChecked(True)
        self.individual_radio = QRadioButton("个体识别")
        self.type_radio.toggled.connect(self._on_annotation_mode_changed)
        self.individual_radio.toggled.connect(self._on_annotation_mode_changed)

        mode_row.addWidget(self.type_radio)
        mode_row.addWidget(self.individual_radio)
        mode_row.addStretch(1)

        mode_hint = QLabel("")
        mode_hint.setObjectName("MutedText")
        mode_hint.setWordWrap(True)
        mode_hint.setVisible(False)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.device_filter = QComboBox()
        self.device_filter.currentIndexChanged.connect(self._apply_filters)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部状态", "待标注", "已标注", "已排除"])
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        self.delete_device_samples_button = QPushButton("删除设备样本")
        self.delete_device_samples_button.setObjectName("DangerButton")
        self.delete_device_samples_button.clicked.connect(self._delete_current_device_samples)

        filter_row.addWidget(QLabel("设备筛选"))
        filter_row.addWidget(self.device_filter)
        filter_row.addWidget(QLabel("标注状态"))
        filter_row.addWidget(self.status_filter)
        filter_row.addWidget(self.delete_device_samples_button)
        filter_row.addStretch(1)

        self.sample_table = QTableWidget(0, 11)
        self.sample_table.setHorizontalHeaderLabels(
            [
                "文件 ID",
                "来源类型",
                "来源文件",
                "设备编号",
                "样本点数",
                "SNR",
                "模型分数",
                "类型标签",
                "个体标签",
                "纳入数据集",
                "状态",
            ]
        )
        self.sample_table.horizontalHeader().setStretchLastSection(True)
        self.sample_table.verticalHeader().setVisible(False)
        self.sample_table.setAlternatingRowColors(True)
        self.sample_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sample_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sample_table.itemSelectionChanged.connect(self._sync_review_form_from_selection)
        self.sample_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.sample_table.setColumnWidth(self.SAMPLE_ID_COLUMN, 260)
        self.sample_table.setColumnWidth(self.SOURCE_COLUMN, 120)
        self.sample_table.setColumnWidth(self.RAW_FILE_COLUMN, 190)
        self.sample_table.setColumnWidth(self.DEVICE_COLUMN, 140)
        self.sample_table.setColumnWidth(self.SAMPLE_COUNT_COLUMN, 95)
        self.sample_table.setColumnWidth(self.SNR_COLUMN, 80)
        self.sample_table.setColumnWidth(self.SCORE_COLUMN, 95)
        self.sample_table.setColumnWidth(self.TYPE_COLUMN, 130)
        self.sample_table.setColumnWidth(self.INDIVIDUAL_COLUMN, 150)
        self.sample_table.setColumnWidth(self.INCLUDE_COLUMN, 90)
        self.sample_table.setColumnWidth(self.STATUS_COLUMN, 90)
        configure_scrollable(self.sample_table)

        review_title = QLabel("复核区")
        review_title.setObjectName("SectionTitle")

        review_hint = QLabel("")
        review_hint.setObjectName("MutedText")
        review_hint.setWordWrap(True)
        review_hint.setVisible(False)

        review_layout = QFormLayout()
        review_layout.setHorizontalSpacing(12)
        review_layout.setVerticalSpacing(10)

        self.review_sample_value = QLabel("未选择")
        self.review_sample_value.setObjectName("ValueLabel")
        self.review_device_value = QLabel("-")
        self.review_device_value.setObjectName("ValueLabel")

        self.review_type_input = QLineEdit()
        self.review_individual_input = QLineEdit()
        self.review_status_box = QComboBox()
        self.review_status_box.addItems(["待标注", "已标注", "已排除"])
        self.review_status_box.currentTextChanged.connect(self._on_review_status_changed)
        self.review_include_checkbox = QCheckBox("纳入数据集")
        self.review_include_checkbox.setChecked(True)
        self.review_include_checkbox.toggled.connect(self._on_include_toggled)
        self.review_type_input.setPlaceholderText("输入类型标签")
        self.review_individual_input.setPlaceholderText("输入个体标签")

        review_layout.addRow("文件 ID", self.review_sample_value)
        review_layout.addRow("设备编号", self.review_device_value)
        review_layout.addRow("类型标签", self.review_type_input)
        review_layout.addRow("个体标签", self.review_individual_input)
        review_layout.addRow("数据集候选", self.review_include_checkbox)
        include_hint = QLabel("")
        include_hint.setObjectName("MutedText")
        include_hint.setWordWrap(True)
        include_hint.setVisible(False)
        review_layout.addRow("", include_hint)
        review_layout.addRow("状态", self.review_status_box)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.auto_label_button = QPushButton("自动标注")
        self.auto_label_button.setObjectName("PrimaryButton")
        self.auto_label_button.clicked.connect(self._apply_auto_labeling)

        self.save_review_button = QPushButton("保存复核结果")
        self.save_review_button.clicked.connect(self._save_manual_review)

        self.delete_sample_button = QPushButton("删除选中样本")
        self.delete_sample_button.clicked.connect(self._delete_selected_sample)

        action_row.addWidget(self.auto_label_button)
        action_row.addWidget(self.save_review_button)
        action_row.addWidget(self.delete_sample_button)
        action_row.addStretch(1)

        self.auto_label_progress = QProgressBar()
        self.auto_label_progress.setRange(0, 100)
        self.auto_label_progress.setValue(0)
        self.auto_label_progress.setFormat("等待自动标注")

        self.annotation_status_label = QLabel("")
        self.annotation_status_label.setObjectName("MutedText")
        self.annotation_status_label.setWordWrap(True)

        section.body_layout.addLayout(mode_row)
        section.body_layout.addWidget(mode_hint)
        section.body_layout.addLayout(filter_row)
        section.body_layout.addWidget(self.sample_table)
        section.body_layout.addWidget(review_title)
        section.body_layout.addWidget(review_hint)
        section.body_layout.addLayout(review_layout)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.auto_label_progress)
        section.body_layout.addWidget(self.annotation_status_label)
        return section

    def _build_dataset_config_card(self) -> SectionCard:
        """Create the dataset build configuration card."""

        section = SectionCard(
            "数据集生成",
            "",
            compact=True,
        )

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self.dataset_type_radio = QRadioButton("类型识别")
        self.dataset_type_radio.setChecked(True)
        self.dataset_individual_radio = QRadioButton("个体识别")
        mode_row.addWidget(self.dataset_type_radio)
        mode_row.addWidget(self.dataset_individual_radio)
        mode_row.addStretch(1)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.train_ratio = QSpinBox()
        self.train_ratio.setRange(0, 100)
        self.train_ratio.setSuffix(" %")
        self.train_ratio.setValue(70)
        self.train_ratio.valueChanged.connect(self._refresh_dataset_generation_controls)

        self.val_ratio = QSpinBox()
        self.val_ratio.setRange(0, 100)
        self.val_ratio.setSuffix(" %")
        self.val_ratio.setValue(15)
        self.val_ratio.valueChanged.connect(self._refresh_dataset_generation_controls)

        self.test_ratio = QSpinBox()
        self.test_ratio.setRange(0, 100)
        self.test_ratio.setSuffix(" %")
        self.test_ratio.setValue(15)
        self.test_ratio.valueChanged.connect(self._refresh_dataset_generation_controls)

        self.strategy_box = QComboBox()
        self.strategy_box.addItems(["按样本随机分层", "按设备个体隔离"])
        self.strategy_box.currentIndexChanged.connect(self._refresh_dataset_generation_controls)
        self.dataset_type_radio.toggled.connect(self._refresh_dataset_generation_controls)
        self.dataset_individual_radio.toggled.connect(self._refresh_dataset_generation_controls)
        self.npz_limit_input = QSpinBox()
        self.npz_limit_input.setRange(1, 100000)
        self.npz_limit_input.setValue(1000)

        form_layout.addRow("训练集", self.train_ratio)
        form_layout.addRow("验证集", self.val_ratio)
        form_layout.addRow("测试集", self.test_ratio)
        form_layout.addRow("划分策略", self.strategy_box)
        form_layout.addRow("单包上限", self.npz_limit_input)

        action_row = QHBoxLayout()
        self.generate_button = QPushButton("生成数据集")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self._generate_dataset_version)
        self.generate_test_button = QPushButton("生成测试集")
        self.generate_test_button.clicked.connect(self._generate_test_dataset_version)
        self.import_external_button = QPushButton("导入数据集")
        self.import_external_button.clicked.connect(self._import_external_dataset_directory)
        action_row.addWidget(self.generate_button)
        action_row.addWidget(self.generate_test_button)
        action_row.addWidget(self.import_external_button)
        action_row.addStretch(1)

        self.dataset_build_progress = QProgressBar()
        self.dataset_build_progress.setRange(0, 100)
        self.dataset_build_progress.setValue(0)
        self.dataset_build_progress.setFormat("等待生成数据集")

        self.dataset_build_status_label = QLabel("")
        self.dataset_build_status_label.setObjectName("MutedText")
        self.dataset_build_status_label.setWordWrap(True)

        section.body_layout.addLayout(mode_row)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.dataset_build_progress)
        section.body_layout.addWidget(self.dataset_build_status_label)
        return section

    def _build_dataset_result_card(self) -> SectionCard:
        """Create the dataset split preview card."""

        section = SectionCard("划分结果", "", compact=True)
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["类别 / 个体", "训练集", "验证集", "测试集"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        configure_scrollable(self.result_table)
        section.body_layout.addWidget(self.result_table)
        return section

    def _build_history_card(self) -> SectionCard:
        """Create the dataset version history card."""

        section = SectionCard("数据集", "", compact=True)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(["数据集 ID", "任务类型", "样本数", "策略", "来源", "创建时间"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.history_table)
        section.body_layout.addWidget(self.history_table)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.delete_version_button = QPushButton("删除选中版本")
        self.delete_version_button.clicked.connect(self._delete_selected_dataset_version)
        action_row.addWidget(self.delete_version_button)
        action_row.addStretch(1)
        section.body_layout.addLayout(action_row)
        return section

    def _build_danger_zone_card(self) -> SectionCard:
        """创建数据库维护操作区。"""

        section = SectionCard(
            "数据维护",
            "",
            compact=True,
        )

        warning_label = QLabel("")
        warning_label.setObjectName("MutedText")
        warning_label.setWordWrap(True)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.clear_database_button = QPushButton("重置数据库")
        self.clear_database_button.setObjectName("DangerButton")
        self.clear_database_button.clicked.connect(self._clear_processed_dataset_database)
        self.orphan_cleanup_button = QPushButton("清理文件")
        self.orphan_cleanup_button.clicked.connect(self._preview_orphan_local_files)
        action_row.addWidget(self.clear_database_button)
        action_row.addWidget(self.orphan_cleanup_button)
        action_row.addStretch(1)

        section.body_layout.addWidget(warning_label)
        section.body_layout.addLayout(action_row)
        return section

    def _build_initial_sample_records(self) -> list[SampleRecord]:
        """Create the initial local sample list used by the current prototype."""

        mock_root = BASE_DIR / "data"
        return [
            SampleRecord(
                sample_id="1101",
                source_type="local_preprocess",
                raw_file_path=str(mock_root / "raw" / "20260415_213011.cap"),
                sample_file_path=str(mock_root / "samples" / "sample_1101.iq"),
                label_type="类别A",
                label_individual="类别A_001",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="batch_001",
                start_sample=0,
                end_sample=65535,
                status="已标注",
                source_name="预处理输出",
            ),
            SampleRecord(
                sample_id="1102",
                source_type="local_preprocess",
                raw_file_path=str(mock_root / "raw" / "20260415_213011.cap"),
                sample_file_path=str(mock_root / "samples" / "sample_1102.iq"),
                label_type="类别A",
                label_individual="类别A_001",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="batch_001",
                start_sample=65536,
                end_sample=131071,
                status="已标注",
                source_name="预处理输出",
            ),
            SampleRecord(
                sample_id="1103",
                source_type="local_preprocess",
                raw_file_path=str(mock_root / "raw" / "20260416_093205.cap"),
                sample_file_path=str(mock_root / "samples" / "sample_1103.iq"),
                label_type="类别B",
                label_individual="类别B_001",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="batch_002",
                start_sample=0,
                end_sample=65535,
                status="已标注",
                source_name="预处理输出",
            ),
            SampleRecord(
                sample_id="1104",
                source_type="local_preprocess",
                raw_file_path=str(mock_root / "raw" / "20260416_101155.cap"),
                sample_file_path=str(mock_root / "samples" / "sample_1104.iq"),
                label_type="",
                label_individual="",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="batch_003",
                start_sample=0,
                end_sample=65535,
                status="待标注",
                source_name="预处理输出",
            ),
        ]

    def _build_initial_dataset_versions(self) -> list[DatasetVersionRecord]:
        """Create the existing prototype dataset history."""

        return [
            DatasetVersionRecord(
                version_id="v001",
                task_type="类型识别",
                sample_count=1260,
                strategy="按样本随机分层",
                created_at="2026-04-09 18:22",
                source_summary="预处理样本",
                label_counts={"类别A": 685, "类别B": 460, "类别C": 882},
            ),
            DatasetVersionRecord(
                version_id="v002",
                task_type="个体识别",
                sample_count=980,
                strategy="按设备个体隔离",
                created_at="2026-04-13 20:06",
                source_summary="预处理样本",
                label_counts={"类别A_001": 312, "类别B_001": 276, "类别C_001": 392},
            ),
            DatasetVersionRecord(
                version_id="v003",
                task_type="类型识别",
                sample_count=1420,
                strategy="按样本随机分层",
                created_at="2026-04-16 16:10",
                source_summary="预处理样本",
                label_counts={"类别A": 685, "类别B": 460, "类别C": 882},
            ),
        ]

    def _refresh_sample_table(self) -> None:
        """Render the current unified sample records into the table."""

        current_sample_id = self.review_sample_value.text()
        self.sample_table.setRowCount(len(self.sample_records))
        for row_index, record in enumerate(self.sample_records):
            values = [
                record.sample_id,
                record.source_label,
                record.raw_file_name,
                record.device_id,
                str(record.sample_count),
                f"{record.snr_db:.2f}",
                f"{record.score:.4f}",
                record.label_type,
                record.label_individual,
                "是" if record.include_in_dataset else "否",
                record.status,
            ]
            for column, value in enumerate(values):
                self._set_table_value(self.sample_table, row_index, column, value)

        if current_sample_id and current_sample_id != "未选择":
            for row in range(self.sample_table.rowCount()):
                if self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN) == current_sample_id:
                    self.sample_table.selectRow(row)
                    break

    def _item_text(self, table: QTableWidget, row: int, column: int) -> str:
        """Return stripped text for one table cell."""

        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _set_table_value(self, table: QTableWidget, row: int, column: int, value: str) -> None:
        """Set one table cell value, creating the item if needed."""

        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        item.setText(value)
        item.setToolTip(value)
        left_align = (
            (table is getattr(self, "sample_table", None) and column in {self.SAMPLE_ID_COLUMN, self.RAW_FILE_COLUMN})
            or (table is getattr(self, "history_table", None) and column in {0, 4})
            or (table is getattr(self, "mapping_table", None) and column in {0, 3})
        )
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if left_align else Qt.AlignmentFlag.AlignCenter)
        )

    def _build_mapping_lookup(self) -> dict[str, dict[str, str]]:
        """Return a device-to-label mapping from the current mapping table."""

        mapping_lookup: dict[str, dict[str, str]] = {}
        for row in range(self.mapping_table.rowCount()):
            device_id = self._item_text(self.mapping_table, row, 0)
            if not device_id:
                continue
            mapping_lookup[device_id] = {
                "type": self._item_text(self.mapping_table, row, 1),
                "individual": self._item_text(self.mapping_table, row, 2),
                "note": self._item_text(self.mapping_table, row, 3),
            }
        return mapping_lookup

    def _clear_mapping_form(self) -> None:
        """Reset the mapping editor for a new row."""

        self._mapping_edit_row = None
        selection_model = self.mapping_table.selectionModel()
        self.mapping_table.blockSignals(True)
        self.mapping_table.clearSelection()
        if selection_model is not None:
            selection_model.clearCurrentIndex()
        self.mapping_table.blockSignals(False)
        self.mapping_device_input.clear()
        self.mapping_type_input.clear()
        self.mapping_individual_input.clear()
        self.mapping_note_input.clear()
        self.mapping_status_label.setText("请输入设备编号、类型标签和个体标签，然后保存映射。")

    def _sync_mapping_form_from_selection(self) -> None:
        """Load the selected mapping row into the editor."""

        row = self.mapping_table.currentRow()
        if row < 0:
            self._mapping_edit_row = None
            return

        self._mapping_edit_row = row
        self.mapping_device_input.setText(self._item_text(self.mapping_table, row, 0))
        self.mapping_type_input.setText(self._item_text(self.mapping_table, row, 1))
        self.mapping_individual_input.setText(self._item_text(self.mapping_table, row, 2))
        self.mapping_note_input.setText(self._item_text(self.mapping_table, row, 3))
        self.mapping_status_label.setText("已载入所选映射，可直接修改后保存。")

    def _save_mapping(self) -> None:
        """Create or update one mapping row from the editor inputs."""

        device_id = self.mapping_device_input.text().strip()
        type_label = self.mapping_type_input.text().strip()
        individual_label = self.mapping_individual_input.text().strip()
        note = self.mapping_note_input.text().strip()

        if not device_id or not type_label:
            self.mapping_status_label.setText("至少需要填写设备编号和类型标签。")
            return

        target_row = self._mapping_edit_row if self._mapping_edit_row is not None else -1
        for row in range(self.mapping_table.rowCount()):
            if row == target_row:
                continue
            if self._item_text(self.mapping_table, row, 0) == device_id:
                self.mapping_status_label.setText(f"设备编号 {device_id} 已存在，请直接选中原记录进行修改。")
                return

        mapping_record = LabelMappingRecord(
            device_id=device_id,
            label_type=type_label,
            label_individual=individual_label,
            note=note,
        )
        try:
            upsert_label_mapping(mapping_record)
        except Exception as exc:
            self.mapping_status_label.setText(f"映射保存失败：{exc}")
            return

        if target_row < 0:
            target_row = self.mapping_table.rowCount()
            self.mapping_table.insertRow(target_row)

        values = [device_id, type_label, individual_label, note]
        for column, value in enumerate(values):
            self._set_table_value(self.mapping_table, target_row, column, value)

        self._mapping_edit_row = target_row
        self.mapping_table.selectRow(target_row)
        self.mapping_status_label.setText(f"映射已保存：{device_id} -> {type_label} -> {individual_label or '待补充'}")
        self._sync_device_filter_options()
        self._apply_filters()
        self._refresh_annotation_metrics()

    def _delete_mapping(self) -> None:
        """Delete the selected mapping row."""

        row = self.mapping_table.currentRow()
        if row < 0:
            self.mapping_status_label.setText("请先选择要删除的映射。")
            return

        device_id = self._item_text(self.mapping_table, row, 0)
        try:
            delete_label_mapping(device_id)
        except Exception as exc:
            self.mapping_status_label.setText(f"映射删除失败：{exc}")
            return

        self.mapping_table.removeRow(row)
        self._mapping_edit_row = None
        self._clear_mapping_form()
        self.mapping_status_label.setText(f"已删除映射：{device_id}")
        self._sync_device_filter_options()
        self._apply_filters()
        self._refresh_annotation_metrics()

    def _on_annotation_mode_changed(self) -> None:
        """Refresh labels and controls when the annotation mode changes."""

        if self.individual_radio.isChecked():
            self.review_individual_input.setEnabled(True)
            self.annotation_status_label.setText("个体识别")
        else:
            self.review_individual_input.setEnabled(False)
            self.annotation_status_label.setText("类型识别")

        self._apply_filters()
        self._sync_review_form_from_selection()

    def _apply_auto_labeling(self) -> None:
        """在后台线程中执行自动标注，避免大样本场景卡住界面。"""

        if self._is_auto_labeling():
            return

        if not self.sample_records:
            self.annotation_status_label.setText("没有可标注样本。")
            return

        mapping_lookup = self._build_mapping_lookup()
        if not mapping_lookup:
            self.annotation_status_label.setText("映射表为空，正在清空所有样本标签并标记为待标注。")

        thread = QThread(self)
        worker = AutoLabelWorker(
            sample_records=self.sample_records,
            mapping_lookup=mapping_lookup,
            individual_mode=self.individual_radio.isChecked(),
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._on_auto_label_progress)
        worker.finished.connect(self._on_auto_label_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_auto_label_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_auto_label_worker)
        thread.finished.connect(thread.deleteLater)

        self._auto_label_thread = thread
        self._auto_label_worker = worker
        self._set_auto_labeling_state(True)
        self.auto_label_progress.setRange(0, max(len(self.sample_records), 1))
        self.auto_label_progress.setValue(0)
        self.auto_label_progress.setFormat("自动标注 %v / %m")
        self.annotation_status_label.setText(
            f"正在后台执行自动标注：0 / {len(self.sample_records)}。无映射命中的样本会被标记为待标注。"
        )
        thread.start()

    def _on_auto_label_progress(self, current: int, total: int, matched: int, pending: int) -> None:
        """在自动标注运行期间更新进度和状态文案。"""

        self.auto_label_progress.setRange(0, max(total, 1))
        self.auto_label_progress.setValue(current)
        self.annotation_status_label.setText(
            f"正在自动标注 {current} / {total} | 已命中 {matched} 条 | 待人工标注 {pending} 条"
        )

    def _on_auto_label_finished(self, updated_records: list[SampleRecord], summary: dict[str, int]) -> None:
        """自动标注完成后统一写库并刷新页面。"""

        try:
            upsert_samples(updated_records)
        except Exception as exc:
            self._set_auto_labeling_state(False)
            self.annotation_status_label.setText(f"自动标注完成，但数据库写入失败：{exc}")
            self.auto_label_progress.setFormat("自动标注失败")
            return

        self.sample_records = list(updated_records)
        self._refresh_sample_table()
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self._refresh_dataset_generation_controls(update_status=False)
        self._set_auto_labeling_state(False)
        self.auto_label_progress.setRange(0, max(summary.get("total", 0), 1))
        self.auto_label_progress.setValue(summary.get("total", 0))
        self.auto_label_progress.setFormat("自动标注完成")
        self.annotation_status_label.setText(
            f"自动标注完成：命中 {summary.get('matched', 0)} 条，"
            f"待人工标注 {summary.get('pending', 0)} 条，"
            f"更新 {summary.get('updated', 0)} 条。"
        )
        self.sample_records_updated.emit(self.get_sample_records())

    def _on_auto_label_failed(self, message: str) -> None:
        """自动标注失败时恢复控件并展示错误。"""

        self._set_auto_labeling_state(False)
        self.auto_label_progress.setFormat("自动标注失败")
        self.annotation_status_label.setText(message)

    def _clear_auto_label_worker(self) -> None:
        """在线程退出后清理自动标注 worker 引用。"""

        self._auto_label_thread = None
        self._auto_label_worker = None

    def _set_auto_labeling_state(self, running: bool) -> None:
        """根据自动标注运行状态统一启用或禁用相关控件。"""

        self.auto_label_button.setEnabled(not running)
        self.mapping_new_button.setEnabled(not running)
        self.mapping_save_button.setEnabled(not running)
        self.mapping_delete_button.setEnabled(not running)
        self.mapping_table.setEnabled(not running)
        self.mapping_device_input.setEnabled(not running)
        self.mapping_type_input.setEnabled(not running)
        self.mapping_individual_input.setEnabled(not running)
        self.mapping_note_input.setEnabled(not running)
        self.type_radio.setEnabled(not running)
        self.individual_radio.setEnabled(not running)
        self.device_filter.setEnabled(not running)
        self.status_filter.setEnabled(not running)
        self.sample_table.setEnabled(not running)
        self.review_type_input.setEnabled(not running)
        self.review_individual_input.setEnabled(not running and self.individual_radio.isChecked())
        self.review_status_box.setEnabled(not running)
        self.review_include_checkbox.setEnabled(not running and self.review_status_box.currentText() != "已排除")
        self.save_review_button.setEnabled(not running)
        self.delete_sample_button.setEnabled(not running)
        self.delete_device_samples_button.setEnabled(not running and self._current_device_for_bulk_delete() != "")
        self.generate_button.setEnabled(
            not running and self._split_ratio_total() == 100 and self._has_dataset_candidates_for_current_mode()
        )
        if hasattr(self, "generate_test_button"):
            self.generate_test_button.setEnabled(not running and self._has_dataset_candidates_for_current_mode())
        if hasattr(self, "import_external_button"):
            self.import_external_button.setEnabled(not running and not self._is_dataset_building())
        self.delete_version_button.setEnabled(not running)
        self.clear_database_button.setEnabled(not running)
        self.orphan_cleanup_button.setEnabled(not running and not self._is_dataset_building())

    def _is_auto_labeling(self) -> bool:
        """返回当前是否存在正在执行的自动标注任务。"""

        return self._auto_label_thread is not None

    def _on_review_status_changed(self, status_text: str) -> None:
        """根据标注状态同步“纳入候选”的可操作性。"""

        is_excluded = status_text == "已排除"
        self.review_include_checkbox.setEnabled(not is_excluded)
        if is_excluded:
            self.review_include_checkbox.blockSignals(True)
            self.review_include_checkbox.setChecked(False)
            self.review_include_checkbox.blockSignals(False)
            self._persist_include_state(False)

    def _on_include_toggled(self, checked: bool) -> None:
        """即时保存“纳入候选”状态。"""

        self._persist_include_state(checked)

    def _persist_include_state(self, include_in_dataset: bool) -> None:
        """把复核区勾选状态立即写回表格、内存记录和数据库。"""

        row = self.sample_table.currentRow()
        if row < 0:
            return
        if self._item_text(self.sample_table, row, self.STATUS_COLUMN) == "已排除":
            include_in_dataset = False

        self._set_table_value(self.sample_table, row, self.INCLUDE_COLUMN, "是" if include_in_dataset else "否")
        self._sync_sample_record_from_row(row)
        self._refresh_annotation_metrics()
        self._refresh_dataset_generation_controls(update_status=False)
        self.annotation_status_label.setText(
            f"样本 {self.review_sample_value.text()} 已更新：{'纳入数据集' if include_in_dataset else '不纳入数据集'}。"
        )
        self.sample_records_updated.emit(self.get_sample_records())

    def _delete_selected_sample(self) -> None:
        """从数据库删除当前选中的样本记录，不删除本地样本文件。"""

        row = self.sample_table.currentRow()
        if row < 0:
            self.annotation_status_label.setText("请先选择要删除的样本。")
            return

        sample_id = self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN)
        sample_file = self._record_for_row(row).sample_file_name if self._record_for_row(row) else ""
        if not sample_id:
            self.annotation_status_label.setText("样本记录无效，无法删除。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除样本",
            f"确认从数据库删除样本 {sample_id}？\n\n本操作不会删除本地 .npy 文件：{sample_file}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        delete_sample(sample_id)
        self.refresh_from_database(emit_signals=False)
        self.annotation_status_label.setText(f"已删除样本数据库记录：{sample_id}。本地样本文件未删除。")
        self.sample_records_updated.emit(self.get_sample_records())
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _current_device_for_bulk_delete(self) -> str:
        """返回批量删除设备样本的目标设备编号。"""

        selected_device = self.device_filter.currentText().strip() if hasattr(self, "device_filter") else ""
        if selected_device and selected_device != "全部设备":
            return selected_device
        row = self.sample_table.currentRow() if hasattr(self, "sample_table") else -1
        if row >= 0:
            return self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
        return ""

    def _sync_delete_device_samples_button(self) -> None:
        """刷新按设备批量删除按钮状态。"""

        if not hasattr(self, "delete_device_samples_button"):
            return
        self.delete_device_samples_button.setEnabled(
            not self._is_auto_labeling()
            and not self._is_dataset_building()
            and self._current_device_for_bulk_delete() != ""
        )

    def _delete_current_device_samples(self) -> None:
        """删除当前筛选设备的全部样本数据库记录，不删除本地文件。"""

        device_id = self._current_device_for_bulk_delete()
        if not device_id:
            self.annotation_status_label.setText("请先在设备筛选中选择一个设备，或选中某个样本行。")
            return

        match_count = sum(1 for record in self.sample_records if record.device_id == device_id)
        if match_count <= 0:
            self.annotation_status_label.setText(f"没有设备 {device_id} 的样本记录。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除设备样本",
            f"确认从数据库删除设备 {device_id} 的全部 {match_count} 条样本记录？\n\n"
            "本操作会清理相关数据集关联并重算版本摘要，但不会删除本地 .npy 文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        counts = delete_samples_by_device(device_id)
        self.refresh_from_database(emit_signals=False)
        self.annotation_status_label.setText(
            f"已删除设备 {device_id} 的样本记录 {counts.get('samples', 0)} 条，"
            f"数据集关联 {counts.get('dataset_items', 0)} 条；本地文件未删除。"
        )
        self.sample_records_updated.emit(self.get_sample_records())
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _delete_selected_dataset_version(self) -> None:
        """从数据库删除当前选中的数据集版本，不影响样本记录。"""

        row = self.history_table.currentRow()
        if row < 0:
            self.dataset_build_status_label.setText("请先选择要删除的数据集版本。")
            return

        version_id = self._item_text(self.history_table, row, 0)
        if not version_id:
            self.dataset_build_status_label.setText("数据集记录无效，无法删除。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除版本",
            f"确认从数据库删除数据集版本 {version_id}？\n\n本操作不会删除任何样本记录或本地文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        delete_dataset_version(version_id)
        self.dataset_versions = list_dataset_versions()
        self._refresh_history_table()
        self._refresh_dataset_generation_controls(update_status=False)
        self.version_metric.set_value(self.dataset_versions[-1].version_id if self.dataset_versions else "未生成")
        self.dataset_build_status_label.setText(
            f"已删除数据集版本：{version_id}。关联模型记录已保留，可继续用于识别；样本记录未删除。"
        )
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _clear_processed_dataset_database(self) -> None:
        """清空数据库记录，保留本地文件。"""

        reply = QMessageBox.warning(
            self,
            "确认重置数据库",
            "该操作会清空数据库中的原始记录、预处理任务、样本记录、数据集版本、版本关联和模型记录。\n\n"
            "不会删除本地 .iq、.json、.npy、.cap、manifest 或模型文件。\n\n"
            "该操作不可撤销，请确认是否继续。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.dataset_build_status_label.setText("已取消清空操作。")
            return

        confirm_text, accepted = QInputDialog.getText(
            self,
            "二次确认",
            "请输入“清空”以确认执行：",
            QLineEdit.EchoMode.Normal,
        )
        if not accepted or confirm_text.strip() != "清空":
            self.dataset_build_status_label.setText("已取消清空操作。")
            return

        counts = clear_processed_dataset_records()
        self.sample_records = list_samples()
        self.dataset_versions = list_dataset_versions()
        self._refresh_sample_table()
        self._refresh_history_table()
        self._refresh_dataset_generation_controls(update_status=False)
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self.version_metric.set_value("未生成")
        self.annotation_status_label.setText("数据库已重置。")
        self.dataset_build_status_label.setText(
            "已清空："
            f"原始记录 {counts.get('raw_files', 0)} 条，"
            f"预处理任务 {counts.get('preprocess_tasks', 0)} 条，"
            f"样本 {counts.get('samples', 0)} 条，"
            f"数据集版本 {counts.get('dataset_versions', 0)} 个，"
            f"版本关联 {counts.get('dataset_items', 0)} 条，"
            f"模型记录 {counts.get('trained_models', 0)} 条。"
        )
        self.sample_records_updated.emit(self.get_sample_records())
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _preview_orphan_local_files(self) -> None:
        """预览数据库无引用的本地运行文件，确认后再删除。"""

        orphan_records = list_orphan_local_paths()
        if not orphan_records:
            self.dataset_build_status_label.setText(
                "未发现孤立本地文件。扫描范围仅限 data/raw、data/samples、data/datasets、data/models。"
            )
            QMessageBox.information(
                self,
                "清理孤立文件",
                "未发现数据库无引用的本地运行文件或目录。",
            )
            return

        total_size = sum(record.size_bytes for record in orphan_records)
        detail_text = "\n".join(self._orphan_record_line(record) for record in orphan_records[:200])
        if len(orphan_records) > 200:
            detail_text += f"\n... 另有 {len(orphan_records) - 200} 项未展开。"

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("清理孤立文件")
        message.setText(
            f"发现 {len(orphan_records)} 项数据库无引用的本地文件或目录，合计约 {self._format_bytes(total_size)}。"
        )
        message.setInformativeText(
            "扫描范围：data/raw、data/samples、data/datasets、data/models。\n"
            "默认不会删除；点击删除后才会清理本地文件，且不会修改数据库记录。"
        )
        message.setDetailedText(detail_text)
        delete_button = message.addButton("删除这些孤立文件", QMessageBox.ButtonRole.DestructiveRole)
        close_button = message.addButton("仅预览，关闭", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(close_button)
        message.exec()

        if message.clickedButton() != delete_button:
            self.dataset_build_status_label.setText(
                f"已预览 {len(orphan_records)} 项孤立文件，未执行删除。"
            )
            return

        counts = delete_orphan_local_paths([record.path for record in orphan_records])
        self.dataset_build_status_label.setText(
            "孤立文件清理完成："
            f"已删除 {counts.get('deleted', 0)} 项，"
            f"已不存在 {counts.get('missing', 0)} 项，"
            f"跳过 {counts.get('skipped', 0)} 项，"
            f"失败 {counts.get('failed', 0)} 项。"
        )

    def _orphan_record_line(self, record: OrphanFileRecord) -> str:
        """返回孤立文件预览列表中的一行文本。"""

        kind = "目录" if record.is_dir else "文件"
        return (
            f"[{record.scope} / {kind}] {record.path} "
            f"({self._format_bytes(record.size_bytes)}) - {record.reason}"
        )

    def _format_bytes(self, size_bytes: int) -> str:
        """Format a byte count for compact UI text."""

        value = float(max(size_bytes, 0))
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024.0 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024.0
        return f"{value:.1f} GB"

    def _record_for_row(self, row: int) -> SampleRecord | None:
        """Return the backing sample record for one visible table row."""

        sample_id = self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN)
        if not sample_id:
            return None
        for record in self.sample_records:
            if record.sample_id == sample_id:
                return record
        return None

    def _sync_review_form_from_selection(self) -> None:
        """Load the selected sample into the manual review area."""

        row = self.sample_table.currentRow()
        if row < 0:
            self.review_sample_value.setText("未选择")
            self.review_device_value.setText("-")
            self.review_type_input.clear()
            self.review_individual_input.clear()
            self.review_include_checkbox.blockSignals(True)
            self.review_include_checkbox.setChecked(True)
            self.review_include_checkbox.blockSignals(False)
            self.review_status_box.setCurrentText("待标注")
            self.review_individual_input.setEnabled(self.individual_radio.isChecked())
            self._sync_delete_device_samples_button()
            return

        self.review_sample_value.setText(self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN))
        self.review_device_value.setText(self._item_text(self.sample_table, row, self.DEVICE_COLUMN))
        self.review_type_input.setText(self._item_text(self.sample_table, row, self.TYPE_COLUMN))
        self.review_individual_input.setText(self._item_text(self.sample_table, row, self.INDIVIDUAL_COLUMN))
        self.review_include_checkbox.blockSignals(True)
        self.review_include_checkbox.setChecked(self._item_text(self.sample_table, row, self.INCLUDE_COLUMN) != "否")
        self.review_include_checkbox.blockSignals(False)
        status_text = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待标注"
        self.review_status_box.setCurrentText(status_text)
        self.review_include_checkbox.setEnabled(status_text != "已排除")
        self.review_individual_input.setEnabled(self.individual_radio.isChecked())
        self._sync_delete_device_samples_button()

    def _save_manual_review(self) -> None:
        """Save manual corrections for the selected sample."""

        row = self.sample_table.currentRow()
        if row < 0:
            self.annotation_status_label.setText("请先选择一条样本，再保存复核结果。")
            return

        type_label = self.review_type_input.text().strip()
        individual_label = self.review_individual_input.text().strip()
        review_status = self.review_status_box.currentText().strip()
        include_in_dataset = self.review_include_checkbox.isChecked()
        if review_status == "已排除":
            include_in_dataset = False

        if review_status == "已标注" and not type_label:
            self.annotation_status_label.setText("状态为已标注时，至少需要填写类型标签。")
            return

        if review_status == "已标注" and self.individual_radio.isChecked() and not individual_label:
            self.annotation_status_label.setText("个体识别模式下，状态为已标注时需要填写个体标签。")
            return

        self._set_table_value(self.sample_table, row, self.TYPE_COLUMN, type_label)
        if self.individual_radio.isChecked():
            self._set_table_value(self.sample_table, row, self.INDIVIDUAL_COLUMN, individual_label)
        self._set_table_value(self.sample_table, row, self.INCLUDE_COLUMN, "是" if include_in_dataset else "否")
        self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, review_status)

        self._sync_sample_record_from_row(row)
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self._refresh_dataset_generation_controls(update_status=False)
        self.annotation_status_label.setText(f"样本 {self.review_sample_value.text()} 已保存：{review_status}。")
        self.sample_records_updated.emit(self.get_sample_records())

    def _sync_sample_record_from_row(self, row: int) -> None:
        """Write one edited table row back into the unified sample records."""

        sample_id = self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN)
        if not sample_id:
            return

        for index, record in enumerate(self.sample_records):
            if record.sample_id != sample_id:
                continue
            self.sample_records[index] = replace(
                record,
                label_type=self._item_text(self.sample_table, row, self.TYPE_COLUMN),
                label_individual=self._item_text(self.sample_table, row, self.INDIVIDUAL_COLUMN),
                include_in_dataset=self._item_text(self.sample_table, row, self.INCLUDE_COLUMN) != "否",
                status=self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待标注",
                device_id=self._item_text(self.sample_table, row, self.DEVICE_COLUMN),
            )
            upsert_samples([self.sample_records[index]])
            break

    def _apply_filters(self) -> None:
        """Filter the sample table by device and annotation status."""

        selected_device = self.device_filter.currentText()
        selected_status = self.status_filter.currentText()

        for row in range(self.sample_table.rowCount()):
            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            row_status = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待标注"

            visible = True
            if selected_device not in ("", "全部设备") and device_id != selected_device:
                visible = False
            if selected_status != "全部状态" and row_status != selected_status:
                visible = False

            self.sample_table.setRowHidden(row, not visible)

        current_row = self.sample_table.currentRow()
        if current_row >= 0 and self.sample_table.isRowHidden(current_row):
            selection_model = self.sample_table.selectionModel()
            self.sample_table.blockSignals(True)
            self.sample_table.clearSelection()
            if selection_model is not None:
                selection_model.clearCurrentIndex()
            self.sample_table.blockSignals(False)

        self._sync_review_form_from_selection()

    def _refresh_annotation_metrics(self) -> None:
        """Refresh the top metrics for mappings, samples, and pending reviews."""

        mapping_count = self.mapping_table.rowCount()
        pending_count = 0
        for row in range(self.sample_table.rowCount()):
            row_status = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待标注"
            if row_status == "待标注":
                pending_count += 1

        self.mapping_metric.set_value(str(mapping_count))
        self.sample_metric.set_value(str(self.sample_table.rowCount()))
        self.pending_metric.set_value(str(pending_count))
        if hasattr(self, "processed_value"):
            self.processed_value.setText(str(self.sample_table.rowCount()))
        if hasattr(self, "ready_value"):
            ready_count = sum(
                1
                for row in range(self.sample_table.rowCount())
                if self._item_text(self.sample_table, row, self.STATUS_COLUMN) == "已标注"
            )
            self.ready_value.setText(str(ready_count))

    def _sync_device_filter_options(self) -> None:
        """Refresh the device filter from sample rows and mapping rows."""

        current_text = self.device_filter.currentText() or "全部设备"
        device_ids: set[str] = set()

        for row in range(self.sample_table.rowCount()):
            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            if device_id:
                device_ids.add(device_id)

        for row in range(self.mapping_table.rowCount()):
            device_id = self._item_text(self.mapping_table, row, 0)
            if device_id:
                device_ids.add(device_id)

        options = ["全部设备", *sorted(device_ids)]
        self.device_filter.blockSignals(True)
        self.device_filter.clear()
        self.device_filter.addItems(options)
        index = self.device_filter.findText(current_text)
        self.device_filter.setCurrentIndex(index if index >= 0 else 0)
        self.device_filter.blockSignals(False)

    def _generate_dataset_version(self) -> None:
        """在后台线程中生成一个数据集版本。"""

        if self._is_dataset_building():
            return

        total_ratio = self._split_ratio_total()
        if total_ratio != 100:
            self.dataset_build_status_label.setText(f"划分比例总和为 {total_ratio}%，必须等于 100%。")
            self._refresh_dataset_generation_controls(update_status=False)
            return

        task_type = "类型识别" if self.dataset_type_radio.isChecked() else "个体识别"
        label_counts, selected_sample_ids, _, _ = collect_dataset_candidates(self.sample_records, task_type=task_type)

        if not label_counts:
            self.dataset_build_status_label.setText("没有可用样本，无法生成数据集。")
            return

        version_id = self._next_generated_version_id()
        thread = QThread(self)
        worker = DatasetBuildWorker(
            sample_records=self.sample_records,
            version_id=version_id,
            task_type=task_type,
            strategy=self.strategy_box.currentText(),
            train_ratio=self.train_ratio.value(),
            val_ratio=self.val_ratio.value(),
            test_ratio=self.test_ratio.value(),
            max_items_per_npz=self.npz_limit_input.value(),
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._on_dataset_build_progress)
        worker.finished.connect(self._on_dataset_build_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_dataset_build_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_dataset_build_worker)
        thread.finished.connect(thread.deleteLater)

        self._dataset_build_thread = thread
        self._dataset_build_worker = worker
        self._set_dataset_building_state(True)
        self.dataset_build_progress.setRange(0, max(len(selected_sample_ids), 1))
        self.dataset_build_progress.setValue(0)
        self.dataset_build_progress.setFormat("生成数据集 %v / %m")
        self.dataset_build_status_label.setText(
            f"正在生成数据集 {version_id}：共 {len(selected_sample_ids)} 条样本，请稍候。"
        )
        thread.start()

    def _generate_test_dataset_version(self) -> None:
        """生成仅包含测试集的数据集。"""

        self.train_ratio.blockSignals(True)
        self.val_ratio.blockSignals(True)
        self.test_ratio.blockSignals(True)
        self.train_ratio.setValue(0)
        self.val_ratio.setValue(0)
        self.test_ratio.setValue(100)
        self.train_ratio.blockSignals(False)
        self.val_ratio.blockSignals(False)
        self.test_ratio.blockSignals(False)
        self._refresh_dataset_generation_controls(update_status=False)
        self._generate_dataset_version()

    def _import_external_dataset_directory(self) -> None:
        """导入外部 NPZ/MAT 数据集目录。"""

        if self._is_dataset_building() or self._is_auto_labeling():
            return

        directory = QFileDialog.getExistingDirectory(
            self,
            "选择外部数据集目录",
            str(BASE_DIR.parent),
        )
        if not directory:
            return

        total_ratio = self._split_ratio_total()
        if total_ratio != 100:
            self.dataset_build_status_label.setText(f"划分比例总和为 {total_ratio}%，必须等于 100%。")
            self._refresh_dataset_generation_controls(update_status=False)
            return

        version_id = self._next_generated_version_id()
        task_type = "类型识别" if self.dataset_type_radio.isChecked() else "个体识别"
        self._set_dataset_building_state(True)
        self.dataset_build_progress.setRange(0, 0)
        self.dataset_build_progress.setFormat("正在导入数据集")
        self.dataset_build_status_label.setText(f"正在导入外部数据集 {version_id}。")
        try:
            result = import_external_dataset_directory(
                directory,
                version_id=version_id,
                task_type=task_type,
                train_ratio=self.train_ratio.value(),
                val_ratio=self.val_ratio.value(),
                test_ratio=self.test_ratio.value(),
                max_items_per_npz=self.npz_limit_input.value(),
            )
        except ExternalDatasetImportError as exc:
            self._set_dataset_building_state(False)
            self.dataset_build_progress.setRange(0, 100)
            self.dataset_build_progress.setValue(0)
            self.dataset_build_progress.setFormat("导入失败")
            self.dataset_build_status_label.setText(str(exc))
            return
        except Exception as exc:  # pragma: no cover - UI 入口保护
            self._set_dataset_building_state(False)
            self.dataset_build_progress.setRange(0, 100)
            self.dataset_build_progress.setValue(0)
            self.dataset_build_progress.setFormat("导入失败")
            self.dataset_build_status_label.setText(f"数据集导入失败：{exc}")
            return

        self.sample_records = list_samples()
        self.dataset_versions = list_dataset_versions()
        self.version_metric.set_value(result.version_record.version_id)
        self._reload_mapping_table()
        self._refresh_sample_table()
        self._refresh_history_table()
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self._set_dataset_building_state(False)
        self.dataset_build_progress.setRange(0, max(result.sample_count, 1))
        self.dataset_build_progress.setValue(result.sample_count)
        self.dataset_build_progress.setFormat("数据集导入完成")
        self.dataset_build_status_label.setText(
            f"数据集 {result.version_record.version_id} 已导入："
            f"{result.imported_file_count} 个文件，{result.sample_count} 条样本，"
            f"{len(result.label_counts)} 个标签。"
        )
        self.sample_records_updated.emit(self.get_sample_records())
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _split_ratio_total(self) -> int:
        """Return the current train/val/test ratio total."""

        return self.train_ratio.value() + self.val_ratio.value() + self.test_ratio.value()

    def _refresh_dataset_generation_controls(self, update_status: bool = True) -> None:
        """Refresh split preview, generation button state, and readiness hint."""

        total_ratio = self._split_ratio_total()
        is_valid = total_ratio == 100
        task_type = "类型识别" if self.dataset_type_radio.isChecked() else "个体识别"
        label_counts, selected_sample_ids, _, _ = collect_dataset_candidates(self.sample_records, task_type=task_type)
        device_split_warning = self._device_split_warning(task_type) if self.strategy_box.currentText() == "按设备个体隔离" else ""
        can_generate = (
            is_valid
            and bool(label_counts)
            and not device_split_warning
            and not self._is_dataset_building()
            and not self._is_auto_labeling()
        )
        self.generate_button.setEnabled(can_generate)
        if hasattr(self, "generate_test_button"):
            self.generate_test_button.setEnabled(
                bool(label_counts)
                and not device_split_warning
                and not self._is_dataset_building()
                and not self._is_auto_labeling()
            )
        if hasattr(self, "import_external_button"):
            self.import_external_button.setEnabled(not self._is_dataset_building() and not self._is_auto_labeling())
        if not is_valid:
            self.result_table.setRowCount(0)
            if update_status:
                self.dataset_build_status_label.setText(f"划分比例总和为 {total_ratio}%，必须等于 100%。")
            return

        self._refresh_dataset_result_table(label_counts)
        if not update_status:
            return
        if not label_counts:
            self.dataset_build_status_label.setText(
                "没有可用样本。"
            )
            return
        if device_split_warning:
            self.dataset_build_status_label.setText(device_split_warning)
            return
        self.dataset_build_status_label.setText(
            f"可生成{task_type}数据集：{len(label_counts)} 个标签，{len(selected_sample_ids)} 条样本。"
        )

    def _calculate_split_counts(self, total: int) -> tuple[int, int, int]:
        """Convert split percentages to concrete train/val/test counts."""

        return calculate_split_counts(
            total,
            self.train_ratio.value(),
            self.val_ratio.value(),
            self.test_ratio.value(),
        )

    def _next_generated_version_id(self) -> str:
        """Return the next dataset version ID for generated datasets."""

        generated_numbers: list[int] = []
        for record in self.dataset_versions:
            digits = "".join(char for char in record.version_id if char.isdigit())
            if digits:
                generated_numbers.append(int(digits))
        next_number = max(generated_numbers, default=0) + 1
        return f"v{next_number:03d}"

    def _refresh_dataset_result_table(self, label_counts: dict[str, int]) -> None:
        """Render the dataset split preview for one label-count dictionary."""

        rows = sorted(label_counts.items(), key=lambda item: item[0])
        self.result_table.setRowCount(len(rows))
        for row_index, (label, count) in enumerate(rows):
            train_count, val_count, test_count = self._calculate_split_counts(count)
            values = [label, str(train_count), str(val_count), str(test_count)]
            for column, value in enumerate(values):
                self._set_table_value(self.result_table, row_index, column, value)

    def _refresh_history_table(self) -> None:
        """Render the dataset version history table."""

        self.history_table.setRowCount(len(self.dataset_versions))
        for row_index, record in enumerate(self.dataset_versions):
            values = [
                record.version_id,
                record.task_type,
                str(record.sample_count),
                record.strategy,
                record.source_summary,
                record.created_at,
            ]
            for column, value in enumerate(values):
                self._set_table_value(self.history_table, row_index, column, value)

    def _on_dataset_build_progress(self, current: int, total: int, message: str) -> None:
        """在数据集生成期间更新进度和状态文案。"""

        self.dataset_build_progress.setRange(0, max(total, 1))
        self.dataset_build_progress.setValue(current)
        self.dataset_build_status_label.setText(f"{message} {current} / {total}")

    def _on_dataset_build_finished(self, payload: dict[str, object]) -> None:
        """数据集生成完成后统一刷新页面与下游联动。"""

        record = payload["record"]
        manifest_path = str(payload.get("manifest_path", ""))
        label_counts = dict(payload.get("label_counts", {}))

        self.dataset_versions = list_dataset_versions()
        self.version_metric.set_value(record.version_id)
        self._refresh_dataset_result_table(label_counts)
        self._refresh_history_table()
        self._set_dataset_building_state(False)
        self.dataset_build_progress.setRange(0, max(int(payload.get("sample_total", 0)), 1))
        self.dataset_build_progress.setValue(int(payload.get("sample_total", 0)))
        self.dataset_build_progress.setFormat("数据集生成完成")
        detail_text = f"标签数 {len(label_counts)}。"
        if record.task_type == "类型识别" and len(label_counts) > 1:
            detail_text = f"包含 {len(label_counts)} 个类型标签，可继续执行类型识别真实训练。"
        self.dataset_build_status_label.setText(
            f"数据集 {record.version_id} 已生成：{record.task_type} | 样本 {record.sample_count} 条 | "
            f"manifest {manifest_path or '未生成'} | {detail_text}"
        )
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _on_dataset_build_failed(self, message: str) -> None:
        """数据集生成失败时恢复控件并展示错误。"""

        self._set_dataset_building_state(False)
        self.dataset_build_progress.setFormat("数据集生成失败")
        self.dataset_build_status_label.setText(message)

    def _clear_dataset_build_worker(self) -> None:
        """在线程退出后清理数据集生成 worker 引用。"""

        self._dataset_build_thread = None
        self._dataset_build_worker = None

    def _set_dataset_building_state(self, running: bool) -> None:
        """根据数据集生成状态统一启用或禁用相关控件。"""

        task_type = "类型识别" if self.dataset_type_radio.isChecked() else "个体识别"
        device_split_warning = self._device_split_warning(task_type) if self.strategy_box.currentText() == "按设备个体隔离" else ""
        self.generate_button.setEnabled(
            not running
            and self._split_ratio_total() == 100
            and not self._is_auto_labeling()
            and self._has_dataset_candidates_for_current_mode()
            and not device_split_warning
        )
        if hasattr(self, "generate_test_button"):
            self.generate_test_button.setEnabled(
                not running
                and not self._is_auto_labeling()
                and self._has_dataset_candidates_for_current_mode()
                and not device_split_warning
            )
        if hasattr(self, "import_external_button"):
            self.import_external_button.setEnabled(not running and not self._is_auto_labeling())
        self.dataset_type_radio.setEnabled(not running)
        self.dataset_individual_radio.setEnabled(not running)
        self.train_ratio.setEnabled(not running)
        self.val_ratio.setEnabled(not running)
        self.test_ratio.setEnabled(not running)
        self.strategy_box.setEnabled(not running)
        self.npz_limit_input.setEnabled(not running)
        self.delete_version_button.setEnabled(not running)
        self.clear_database_button.setEnabled(not running)
        self.orphan_cleanup_button.setEnabled(not running and not self._is_auto_labeling())
        self.auto_label_button.setEnabled(not running and not self._is_auto_labeling())
        self.delete_device_samples_button.setEnabled(not running and self._current_device_for_bulk_delete() != "")

    def _is_dataset_building(self) -> bool:
        """返回当前是否存在正在执行的数据集生成任务。"""

        return self._dataset_build_thread is not None

    def _has_dataset_candidates_for_current_mode(self) -> bool:
        """Return whether current samples can generate the selected dataset type."""

        task_type = "类型识别" if self.dataset_type_radio.isChecked() else "个体识别"
        label_counts, _, _, _ = collect_dataset_candidates(self.sample_records, task_type=task_type)
        return bool(label_counts)

    def _device_split_warning(self, task_type: str) -> str:
        """检查按设备隔离划分是否具备足够设备数。"""

        grouped: dict[str, set[str]] = {}
        label_counts: dict[str, int] = {}
        use_type_label = task_type == "类型识别"
        for record in self.sample_records:
            label_value = record.label_type if use_type_label else record.label_individual
            if record.status != "已标注" or not record.include_in_dataset or not label_value:
                continue
            grouped.setdefault(label_value, set()).add(record.device_id.strip() or "未指定设备")
            label_counts[label_value] = label_counts.get(label_value, 0) + 1

        for label_value, device_ids in sorted(grouped.items()):
            split_counts = self._calculate_split_counts(label_counts.get(label_value, 0))
            required_groups = sum(1 for count in split_counts if count > 0)
            if len(device_ids) < required_groups:
                return (
                    f"按设备个体隔离需要每个标签至少 {required_groups} 个设备编号；"
                    f"标签 {label_value} 只有 {len(device_ids)} 个设备。"
                )
        return ""
