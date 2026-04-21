"""Dataset page for processed-sample review, mapping maintenance, and dataset management."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
    SampleRecord,
    create_dataset_version,
    init_database,
    list_dataset_versions,
    list_samples,
    upsert_samples,
)
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
        self.version_metric = MetricCard("当前版本", current_version, accent_color="#5EA6D3", compact=True)
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
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._refresh_sample_table()
        self._refresh_history_table()
        latest_label_counts = self.dataset_versions[-1].label_counts if self.dataset_versions else {}
        self._refresh_dataset_result_table(latest_label_counts)
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()

    def get_sample_records(self) -> list[SampleRecord]:
        """Return the current downstream sample records."""

        return list(self.sample_records)

    def get_dataset_versions(self) -> list[DatasetVersionRecord]:
        """Return the current dataset versions."""

        return list(self.dataset_versions)

    def add_preprocess_records(self, records: list[SampleRecord]) -> None:
        """Append or update preprocess-generated sample records."""

        preprocess_records = [record for record in records if record.source_type == "local_preprocess"]
        if not preprocess_records:
            return

        upsert_samples(preprocess_records)
        self.sample_records = list_samples()
        self._refresh_sample_table()
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self.annotation_status_label.setText(
            f"已同步 {len(preprocess_records)} 条预处理候选样本，请继续完成手动标注。"
        )
        self.sample_records_updated.emit(self.get_sample_records())

    def _build_sample_flow_card(self) -> SectionCard:
        """Create the simplified processed-sample workflow card."""

        section = SectionCard(
            "已处理样本",
            "本页只围绕预处理输出样本展开，按“样本复核 -> 标签确认 -> 生成数据集”推进。",
            right_widget=StatusBadge("主流程", "info", size="sm"),
            compact=True,
        )

        info_layout = QFormLayout()
        info_layout.setHorizontalSpacing(12)
        info_layout.setVerticalSpacing(10)

        self.processed_value = QLabel(str(len(self.sample_records)))
        self.processed_value.setObjectName("ValueLabel")
        self.ready_value = QLabel(str(sum(1 for record in self.sample_records if record.status == "已标注")))
        self.ready_value.setObjectName("ValueLabel")
        next_step_value = QLabel("标签确认 -> 数据集生成")
        next_step_value.setObjectName("ValueLabel")

        info_layout.addRow("当前样本数", self.processed_value)
        info_layout.addRow("已标注样本", self.ready_value)
        info_layout.addRow("当前下一步", next_step_value)

        hint_label = QLabel("当前页面不再包含公开数据导入入口，后续统一对接你们自己的预处理输出样本。")
        hint_label.setObjectName("MutedText")
        hint_label.setWordWrap(True)

        section.body_layout.addLayout(info_layout)
        section.body_layout.addWidget(hint_label)
        return section

    def _build_mapping_card(self) -> SectionCard:
        """Create the mapping maintenance card."""

        section = SectionCard(
            "编号映射",
            "人工只需维护 设备编号 -> 类型标签 -> 个体标签 的对应关系。",
            right_widget=StatusBadge("可编辑", "info", size="sm"),
            compact=True,
        )

        self.mapping_table = QTableWidget(3, 4)
        self.mapping_table.setHorizontalHeaderLabels(["设备编号", "类型标签", "个体标签", "备注"])
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mapping_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.mapping_table)
        self.mapping_table.itemSelectionChanged.connect(self._sync_mapping_form_from_selection)

        mapping_rows = [
            ["drone_001", "DJI_Mavic3", "mavic3_001", "甲方样机 A"],
            ["drone_003", "Autel_EVO", "autel_003", "Autel 目标机"],
            ["drone_007", "FPV_Racing", "fpv_007", "竞速穿越机"],
        ]
        for row_index, row_data in enumerate(mapping_rows):
            for column, value in enumerate(row_data):
                self.mapping_table.setItem(row_index, column, QTableWidgetItem(value))

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(10)

        self.mapping_device_input = QLineEdit()
        self.mapping_type_input = QLineEdit()
        self.mapping_individual_input = QLineEdit()
        self.mapping_note_input = QLineEdit()

        self.mapping_device_input.setPlaceholderText("例如 drone_001")
        self.mapping_type_input.setPlaceholderText("例如 DJI_Mavic3")
        self.mapping_individual_input.setPlaceholderText("例如 mavic3_001")
        self.mapping_note_input.setPlaceholderText("可选备注")

        form_layout.addRow("设备编号", self.mapping_device_input)
        form_layout.addRow("类型标签", self.mapping_type_input)
        form_layout.addRow("个体标签", self.mapping_individual_input)
        form_layout.addRow("备注", self.mapping_note_input)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        new_button = QPushButton("新增映射")
        new_button.clicked.connect(self._clear_mapping_form)

        save_button = QPushButton("保存映射")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_mapping)

        delete_button = QPushButton("删除映射")
        delete_button.clicked.connect(self._delete_mapping)

        button_row.addWidget(new_button)
        button_row.addWidget(save_button)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)

        self.mapping_status_label = QLabel("维护好映射表后，预处理输出样本可按设备编号自动回填标签。")
        self.mapping_status_label.setObjectName("MutedText")
        self.mapping_status_label.setWordWrap(True)

        section.body_layout.addWidget(self.mapping_table)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.mapping_status_label)
        return section

    def _build_sample_label_card(self) -> SectionCard:
        """Create the sample annotation card."""

        section = SectionCard("样本标注", "围绕已处理样本完成标签确认与人工复核。", compact=True)

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

        mode_hint = QLabel("预处理输出样本建议先维护映射，再执行自动标注；只有异常样本才需要人工复核。")
        mode_hint.setObjectName("MutedText")
        mode_hint.setWordWrap(True)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.device_filter = QComboBox()
        self.device_filter.currentIndexChanged.connect(self._apply_filters)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部状态", "待标注", "待复核", "已标注"])
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        filter_row.addWidget(QLabel("设备筛选"))
        filter_row.addWidget(self.device_filter)
        filter_row.addWidget(QLabel("标注状态"))
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch(1)

        self.sample_table = QTableWidget(0, 11)
        self.sample_table.setHorizontalHeaderLabels(
            [
                "样本 ID",
                "来源类型",
                "来源文件",
                "设备编号",
                "样本点数",
                "SNR",
                "模型分数",
                "类型标签",
                "个体标签",
                "纳入",
                "状态",
            ]
        )
        self.sample_table.horizontalHeader().setStretchLastSection(True)
        self.sample_table.verticalHeader().setVisible(False)
        self.sample_table.setAlternatingRowColors(True)
        self.sample_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sample_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sample_table.itemSelectionChanged.connect(self._sync_review_form_from_selection)
        configure_scrollable(self.sample_table)

        review_title = QLabel("复核区")
        review_title.setObjectName("SectionTitle")

        review_hint = QLabel("点击样本行后，在这里做少量修正。通常只需要处理未匹配到映射的样本。")
        review_hint.setObjectName("MutedText")
        review_hint.setWordWrap(True)

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
        self.review_status_box.addItems(["待标注", "待复核", "已标注"])
        self.review_include_checkbox = QCheckBox("纳入数据集")
        self.review_include_checkbox.setChecked(True)
        self.review_type_input.setPlaceholderText("输入类型标签")
        self.review_individual_input.setPlaceholderText("输入个体标签")

        review_layout.addRow("样本 ID", self.review_sample_value)
        review_layout.addRow("设备编号", self.review_device_value)
        review_layout.addRow("类型标签", self.review_type_input)
        review_layout.addRow("个体标签", self.review_individual_input)
        review_layout.addRow("是否纳入", self.review_include_checkbox)
        review_layout.addRow("状态", self.review_status_box)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        auto_button = QPushButton("自动标注")
        auto_button.setObjectName("PrimaryButton")
        auto_button.clicked.connect(self._apply_auto_labeling)

        save_review_button = QPushButton("保存复核结果")
        save_review_button.clicked.connect(self._save_manual_review)

        action_row.addWidget(auto_button)
        action_row.addWidget(save_review_button)
        action_row.addStretch(1)

        self.annotation_status_label = QLabel("当前模式：类型识别。自动标注仅作用于预处理输出样本。")
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
        section.body_layout.addWidget(self.annotation_status_label)
        return section

    def _build_dataset_config_card(self) -> SectionCard:
        """Create the dataset build configuration card."""

        section = SectionCard(
            "数据集生成",
            "根据当前已处理样本生成数据集版本，并衔接训练与识别模块。",
            right_widget=StatusBadge("版本管理", "info", size="sm"),
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
        self.train_ratio.setRange(10, 90)
        self.train_ratio.setSuffix(" %")
        self.train_ratio.setValue(70)

        self.val_ratio = QSpinBox()
        self.val_ratio.setRange(5, 45)
        self.val_ratio.setSuffix(" %")
        self.val_ratio.setValue(15)

        self.test_ratio = QSpinBox()
        self.test_ratio.setRange(5, 45)
        self.test_ratio.setSuffix(" %")
        self.test_ratio.setValue(15)

        self.strategy_box = QComboBox()
        self.strategy_box.addItems(["按样本随机分层", "按设备个体隔离"])

        form_layout.addRow("训练集", self.train_ratio)
        form_layout.addRow("验证集", self.val_ratio)
        form_layout.addRow("测试集", self.test_ratio)
        form_layout.addRow("划分策略", self.strategy_box)

        action_row = QHBoxLayout()
        generate_button = QPushButton("生成数据集")
        generate_button.setObjectName("PrimaryButton")
        generate_button.clicked.connect(self._generate_dataset_version)
        action_row.addWidget(generate_button)
        action_row.addStretch(1)

        self.dataset_build_status_label = QLabel("当前仅基于预处理输出样本生成新版本，后续统一接真实样本测试。")
        self.dataset_build_status_label.setObjectName("MutedText")
        self.dataset_build_status_label.setWordWrap(True)

        section.body_layout.addLayout(mode_row)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.dataset_build_status_label)
        return section

    def _build_dataset_result_card(self) -> SectionCard:
        """Create the dataset split preview card."""

        section = SectionCard("划分结果", "显示当前版本的类别或个体样本数。", compact=True)
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

        section = SectionCard("历史版本", "显示已生成数据集与来源。", compact=True)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(["版本号", "任务类型", "训练样本", "策略", "来源", "创建时间"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        configure_scrollable(self.history_table)
        section.body_layout.addWidget(self.history_table)
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
                label_type="DJI_Mavic3",
                label_individual="mavic3_001",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="drone_001",
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
                label_type="DJI_Mavic3",
                label_individual="mavic3_001",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="drone_001",
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
                label_type="FPV_Racing",
                label_individual="fpv_007",
                sample_rate_hz=10_000_000.0,
                center_frequency_hz=2_440_000_000.0,
                data_format="complex_float32_iq",
                sample_count=65536,
                device_id="drone_007",
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
                device_id="drone_003",
                start_sample=0,
                end_sample=65535,
                status="待复核",
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
                label_counts={"DJI_Mavic3": 685, "Autel_EVO": 460, "FPV_Racing": 882},
            ),
            DatasetVersionRecord(
                version_id="v002",
                task_type="个体识别",
                sample_count=980,
                strategy="按设备个体隔离",
                created_at="2026-04-13 20:06",
                source_summary="预处理样本",
                label_counts={"mavic3_001": 312, "autel_003": 276, "fpv_007": 392},
            ),
            DatasetVersionRecord(
                version_id="v003",
                task_type="类型识别",
                sample_count=1420,
                strategy="按样本随机分层",
                created_at="2026-04-16 16:10",
                source_summary="预处理样本",
                label_counts={"DJI_Mavic3": 685, "Autel_EVO": 460, "FPV_Racing": 882},
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
            self.annotation_status_label.setText("当前模式：个体识别。自动标注会同时回填类型标签和个体标签。")
        else:
            self.review_individual_input.setEnabled(False)
            self.annotation_status_label.setText("当前模式：类型识别。自动标注会优先回填类型标签。")

        self._apply_filters()
        self._sync_review_form_from_selection()

    def _apply_auto_labeling(self) -> None:
        """Fill local-preprocess sample labels by the current mapping table."""

        mapping_lookup = self._build_mapping_lookup()
        matched_rows = 0
        pending_rows = 0

        for row in range(self.sample_table.rowCount()):
            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            mapping = mapping_lookup.get(device_id)
            if mapping is None:
                self._set_table_value(self.sample_table, row, self.TYPE_COLUMN, "")
                self._set_table_value(self.sample_table, row, self.INDIVIDUAL_COLUMN, "")
                self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, "待标注")
                pending_rows += 1
                self._sync_sample_record_from_row(row)
                continue

            self._set_table_value(self.sample_table, row, self.TYPE_COLUMN, mapping["type"])
            if self.individual_radio.isChecked():
                self._set_table_value(self.sample_table, row, self.INDIVIDUAL_COLUMN, mapping["individual"])
                if mapping["individual"]:
                    self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, "已标注")
                    matched_rows += 1
                else:
                    self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, "待复核")
                    pending_rows += 1
            else:
                self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, "已标注")
                matched_rows += 1
            self._sync_sample_record_from_row(row)

        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self.annotation_status_label.setText(
            f"自动标注完成：{matched_rows} 条已按映射回填，{pending_rows} 条仍需人工复核。"
        )
        self.sample_records_updated.emit(self.get_sample_records())

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
            self.review_include_checkbox.setChecked(True)
            self.review_status_box.setCurrentText("待标注")
            self.review_individual_input.setEnabled(self.individual_radio.isChecked())
            return

        self.review_sample_value.setText(self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN))
        self.review_device_value.setText(self._item_text(self.sample_table, row, self.DEVICE_COLUMN))
        self.review_type_input.setText(self._item_text(self.sample_table, row, self.TYPE_COLUMN))
        self.review_individual_input.setText(self._item_text(self.sample_table, row, self.INDIVIDUAL_COLUMN))
        self.review_include_checkbox.setChecked(self._item_text(self.sample_table, row, self.INCLUDE_COLUMN) != "否")
        status_text = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待标注"
        self.review_status_box.setCurrentText(status_text)
        self.review_individual_input.setEnabled(self.individual_radio.isChecked())

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
        self.annotation_status_label.setText(
            f"样本 {self.review_sample_value.text()} 已保存复核结果，当前状态：{review_status}。"
        )
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
            if row_status != "已标注":
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
        """Generate one dataset version from the current sample table."""

        label_column = self.TYPE_COLUMN if self.dataset_type_radio.isChecked() else self.INDIVIDUAL_COLUMN
        task_type = "类型识别" if self.dataset_type_radio.isChecked() else "个体识别"

        label_counts: dict[str, int] = {}
        selected_sample_ids: list[str] = []
        label_values: dict[str, str] = {}
        for row in range(self.sample_table.rowCount()):
            status_text = self._item_text(self.sample_table, row, self.STATUS_COLUMN)
            label_text = self._item_text(self.sample_table, row, label_column)
            include_text = self._item_text(self.sample_table, row, self.INCLUDE_COLUMN)
            sample_id = self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN)
            if status_text != "已标注" or include_text == "否" or not label_text:
                continue
            label_counts[label_text] = label_counts.get(label_text, 0) + 1
            selected_sample_ids.append(sample_id)
            label_values[sample_id] = label_text

        if not label_counts:
            self.dataset_build_status_label.setText("当前没有可用的已标注样本，无法生成数据集版本。")
            return

        version_id = self._next_generated_version_id()
        record = DatasetVersionRecord(
            version_id=version_id,
            task_type=task_type,
            sample_count=sum(label_counts.values()),
            strategy=self.strategy_box.currentText(),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            source_summary="预处理样本",
            label_counts=label_counts,
        )
        self.dataset_versions.append(record)
        create_dataset_version(record, selected_sample_ids, label_values)
        self.dataset_versions = list_dataset_versions()
        self.version_metric.set_value(version_id)
        self._refresh_dataset_result_table(label_counts)
        self._refresh_history_table()
        detail_text = f"当前标签数 {len(label_counts)}。"
        if task_type == "类型识别" and len(label_counts) > 1:
            detail_text = f"包含 {len(label_counts)} 个类型标签，可继续执行类型识别占位训练。"
        self.dataset_build_status_label.setText(
            f"数据集 {version_id} 已生成：{task_type} | 样本 {record.sample_count} 条 | 来源 预处理样本 | {detail_text}"
        )
        self.dataset_versions_updated.emit(self.get_dataset_versions())

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

        train_ratio = self.train_ratio.value() / 100
        val_ratio = self.val_ratio.value() / 100
        for row_index, (label, count) in enumerate(rows):
            train_count = int(round(count * train_ratio))
            val_count = int(round(count * val_ratio))
            test_count = max(count - train_count - val_count, 0)
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
