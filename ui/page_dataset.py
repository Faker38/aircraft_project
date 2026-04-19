"""Dataset page for mapping maintenance, public sample import, and dataset management."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import BASE_DIR, RFUAV_SAMPLES_DIR
from services import (
    DatasetVersionRecord,
    RFUAVImportError,
    RFUAVImportResult,
    SampleRecord,
    import_rfuav_dataset,
    probe_rfuav_dataset,
)
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class DatasetPage(QWidget):
    """Workflow page for public sample import, annotation, and dataset management."""

    sample_records_updated = Signal(object)
    dataset_versions_updated = Signal(object)

    SAMPLE_ID_COLUMN = 0
    SOURCE_COLUMN = 1
    RAW_FILE_COLUMN = 2
    DEVICE_COLUMN = 3
    SAMPLE_COUNT_COLUMN = 4
    TYPE_COLUMN = 5
    INDIVIDUAL_COLUMN = 6
    STATUS_COLUMN = 7

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the dataset page."""

        super().__init__(parent)
        self._mapping_edit_row: int | None = None
        self.sample_records: list[SampleRecord] = self._build_initial_sample_records()
        self.dataset_versions: list[DatasetVersionRecord] = self._build_initial_dataset_versions()
        self._rfuav_import_result: RFUAVImportResult | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.mapping_metric = MetricCard("映射数量", "0", compact=True)
        self.sample_metric = MetricCard("样本总数", "0", accent_color="#7CB98B", compact=True)
        self.pending_metric = MetricCard("待复核样本", "0", accent_color="#C59A63", compact=True)
        self.version_metric = MetricCard("数据集版本", "v003", accent_color="#5EA6D3", compact=True)
        metrics_row.addWidget(self.mapping_metric)
        metrics_row.addWidget(self.sample_metric)
        metrics_row.addWidget(self.pending_metric)
        metrics_row.addWidget(self.version_metric)
        content_layout.addLayout(metrics_row)

        tabs = QTabWidget()
        tabs.addTab(self._build_labeling_tab(), "样本标注")
        tabs.addTab(self._build_dataset_tab(), "数据集构建")
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._refresh_sample_table()
        self._refresh_history_table()
        self._refresh_dataset_result_table(self.dataset_versions[-1].label_counts)
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self._refresh_public_dataset_probe()

    def get_sample_records(self) -> list[SampleRecord]:
        """Return the current downstream sample records."""

        return list(self.sample_records)

    def get_dataset_versions(self) -> list[DatasetVersionRecord]:
        """Return the current dataset versions."""

        return list(self.dataset_versions)

    def _build_labeling_tab(self) -> QWidget:
        """Create the annotation management tab."""

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        layout.addWidget(self._build_public_import_card())

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_mapping_card(), 2)
        top_row.addWidget(self._build_sample_label_card(), 3)

        layout.addLayout(top_row)
        return tab

    def _build_public_import_card(self) -> SectionCard:
        """Create the RFUAV public dataset import card."""

        self.public_import_badge = StatusBadge("待导入", "info", size="sm")
        section = SectionCard(
            "公开数据导入",
            "将 RFUAV 已筛选好的无人机信号样本直接导入后半流程，不占用信号预处理链路。",
            right_widget=self.public_import_badge,
            compact=True,
        )

        dataset_root = self._guess_public_dataset_root()
        self.public_dataset_root_input = QLineEdit(str(dataset_root) if dataset_root else "")
        self.public_output_dir_input = QLineEdit(str(RFUAV_SAMPLES_DIR))
        self.public_slice_length = QSpinBox()
        self.public_slice_length.setRange(1024, 262144)
        self.public_slice_length.setSingleStep(1024)
        self.public_slice_length.setValue(65536)

        source_row = QHBoxLayout()
        source_row.setSpacing(10)
        source_row.addWidget(QLabel("数据根目录"))
        source_row.addWidget(self.public_dataset_root_input, 1)
        select_source_button = QPushButton("选择目录")
        select_source_button.clicked.connect(self._choose_public_dataset_root)
        source_row.addWidget(select_source_button)
        probe_button = QPushButton("读取元数据")
        probe_button.clicked.connect(self._refresh_public_dataset_probe)
        source_row.addWidget(probe_button)

        output_row = QHBoxLayout()
        output_row.setSpacing(10)
        output_row.addWidget(QLabel("样本输出目录"))
        output_row.addWidget(self.public_output_dir_input, 1)
        select_output_button = QPushButton("选择目录")
        select_output_button.clicked.connect(self._choose_public_output_dir)
        output_row.addWidget(select_output_button)

        meta_layout = QFormLayout()
        meta_layout.setHorizontalSpacing(12)
        meta_layout.setVerticalSpacing(10)

        self.public_drone_value = QLabel("-")
        self.public_drone_value.setObjectName("ValueLabel")
        self.public_individual_value = QLabel("-")
        self.public_individual_value.setObjectName("ValueLabel")
        self.public_file_count_value = QLabel("-")
        self.public_file_count_value.setObjectName("ValueLabel")
        self.public_generated_value = QLabel("待导入")
        self.public_generated_value.setObjectName("ValueLabel")

        meta_layout.addRow("机型标签", self.public_drone_value)
        meta_layout.addRow("个体标签", self.public_individual_value)
        meta_layout.addRow("原始文件数", self.public_file_count_value)
        meta_layout.addRow("切片长度", self.public_slice_length)
        meta_layout.addRow("已导入样本", self.public_generated_value)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        import_button = QPushButton("导入公开数据")
        import_button.setObjectName("PrimaryButton")
        import_button.clicked.connect(self._import_public_dataset)
        action_row.addWidget(import_button)
        action_row.addStretch(1)

        self.public_status_label = QLabel("默认查找工作区中的 FUTABA T10J 数据目录，可手动切换到其他 RFUAV 样本目录。")
        self.public_status_label.setObjectName("MutedText")
        self.public_status_label.setWordWrap(True)

        section.body_layout.addLayout(source_row)
        section.body_layout.addLayout(output_row)
        section.body_layout.addLayout(meta_layout)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.public_status_label)
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

        self.mapping_status_label = QLabel("维护好映射表后，本地预处理输出样本可按设备编号自动回填标签。")
        self.mapping_status_label.setObjectName("MutedText")
        self.mapping_status_label.setWordWrap(True)

        section.body_layout.addWidget(self.mapping_table)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.mapping_status_label)
        return section

    def _build_sample_label_card(self) -> SectionCard:
        """Create the sample annotation card."""

        section = SectionCard("样本标注", "先自动标注，再人工复核异常样本。", compact=True)

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

        mode_hint = QLabel("公开数据导入样本默认已带标签；本地预处理输出样本建议先维护映射，再做自动标注。")
        mode_hint.setObjectName("MutedText")
        mode_hint.setWordWrap(True)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.device_filter = QComboBox()
        self.device_filter.currentIndexChanged.connect(self._apply_filters)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部状态", "待复核", "已标注"])
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        filter_row.addWidget(QLabel("设备筛选"))
        filter_row.addWidget(self.device_filter)
        filter_row.addWidget(QLabel("标注状态"))
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch(1)

        self.sample_table = QTableWidget(0, 8)
        self.sample_table.setHorizontalHeaderLabels(
            ["样本 ID", "来源类型", "来源文件", "设备编号", "样本点数", "类型标签", "个体标签", "状态"]
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

        review_hint = QLabel("点击样本行后，在这里做少量修正。已带标签的公开数据样本通常不需要逐条修改。")
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
        self.review_status_box.addItems(["待复核", "已标注"])
        self.review_type_input.setPlaceholderText("输入类型标签")
        self.review_individual_input.setPlaceholderText("输入个体标签")

        review_layout.addRow("样本 ID", self.review_sample_value)
        review_layout.addRow("设备编号", self.review_device_value)
        review_layout.addRow("类型标签", self.review_type_input)
        review_layout.addRow("个体标签", self.review_individual_input)
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

        self.annotation_status_label = QLabel("当前模式：类型识别。自动标注仅作用于本地预处理输出样本。")
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

    def _build_dataset_tab(self) -> QWidget:
        """Create the dataset build tab."""

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        build_card = SectionCard(
            "划分配置",
            "根据当前样本表生成数据集版本。公开数据 FUTABA 当前仅用于后半链路验证。",
            right_widget=StatusBadge("版本管理", "warning", size="sm"),
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

        self.dataset_build_status_label = QLabel("当前可基于本地样本与公开数据导入样本生成新版本。")
        self.dataset_build_status_label.setObjectName("MutedText")
        self.dataset_build_status_label.setWordWrap(True)

        build_card.body_layout.addLayout(mode_row)
        build_card.body_layout.addLayout(form_layout)
        build_card.body_layout.addLayout(action_row)
        build_card.body_layout.addWidget(self.dataset_build_status_label)
        top_row.addWidget(build_card, 2)

        result_card = SectionCard("划分结果", "显示当前版本的类别或个体样本数。", compact=True)
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["类别 / 个体", "训练集", "验证集", "测试集"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        configure_scrollable(self.result_table)
        result_card.body_layout.addWidget(self.result_table)
        top_row.addWidget(result_card, 3)

        history_card = SectionCard("历史版本", "显示已生成数据集与来源。", compact=True)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(["版本号", "任务类型", "训练样本", "策略", "来源", "创建时间"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        configure_scrollable(self.history_table)
        history_card.body_layout.addWidget(self.history_table)

        layout.addLayout(top_row)
        layout.addWidget(history_card)
        return tab

    def _build_initial_sample_records(self) -> list[SampleRecord]:
        """Create the initial mixed sample list used by the current prototype."""

        mock_root = BASE_DIR / "data"
        rows = [
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
                source_name="本地采集",
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
                source_name="本地采集",
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
                source_name="本地采集",
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
                source_name="本地采集",
            ),
        ]
        return rows

    def _build_initial_dataset_versions(self) -> list[DatasetVersionRecord]:
        """Create the existing prototype dataset history."""

        return [
            DatasetVersionRecord(
                version_id="v001",
                task_type="类型识别",
                sample_count=1260,
                strategy="按样本随机分层",
                created_at="2026-04-09 18:22",
                source_summary="本地样本",
                label_counts={"DJI_Mavic3": 685, "Autel_EVO": 460, "FPV_Racing": 882},
            ),
            DatasetVersionRecord(
                version_id="v002",
                task_type="个体识别",
                sample_count=980,
                strategy="按设备个体隔离",
                created_at="2026-04-13 20:06",
                source_summary="本地样本",
                label_counts={"mavic3_001": 312, "autel_003": 276, "fpv_007": 392},
            ),
            DatasetVersionRecord(
                version_id="v003",
                task_type="类型识别",
                sample_count=1420,
                strategy="按样本随机分层",
                created_at="2026-04-16 16:10",
                source_summary="本地样本",
                label_counts={"DJI_Mavic3": 685, "Autel_EVO": 460, "FPV_Racing": 882},
            ),
        ]

    def _guess_public_dataset_root(self) -> Path | None:
        """Return the current FUTABA RFUAV directory if it exists."""

        candidate = BASE_DIR.parent / "FUTABA%20T10J" / "FUTABA T10J"
        return candidate if candidate.exists() else None

    def _choose_public_dataset_root(self) -> None:
        """Open one directory chooser for the RFUAV dataset root."""

        selected = QFileDialog.getExistingDirectory(self, "选择 RFUAV 数据根目录", self.public_dataset_root_input.text())
        if selected:
            self.public_dataset_root_input.setText(selected)
            self._refresh_public_dataset_probe()

    def _choose_public_output_dir(self) -> None:
        """Open one directory chooser for the sample output root."""

        selected = QFileDialog.getExistingDirectory(self, "选择样本输出目录", self.public_output_dir_input.text())
        if selected:
            self.public_output_dir_input.setText(selected)

    def _refresh_public_dataset_probe(self) -> None:
        """Probe the configured RFUAV dataset and refresh the import card."""

        dataset_root = Path(self.public_dataset_root_input.text().strip()) if self.public_dataset_root_input.text().strip() else None
        if dataset_root is None:
            self.public_import_badge.set_status("未配置", "warning", size="sm")
            self.public_drone_value.setText("-")
            self.public_individual_value.setText("-")
            self.public_file_count_value.setText("-")
            self.public_generated_value.setText("待导入")
            self.public_status_label.setText("请先选择公开数据根目录，再执行元数据读取或样本导入。")
            return

        try:
            probe = probe_rfuav_dataset(dataset_root)
        except RFUAVImportError as exc:
            self.public_import_badge.set_status("异常", "danger", size="sm")
            self.public_drone_value.setText("-")
            self.public_individual_value.setText("-")
            self.public_file_count_value.setText("-")
            self.public_generated_value.setText("待导入")
            self.public_status_label.setText(str(exc))
            return

        type_label = probe.drone_label.replace(" ", "_")
        individual_label = f"{type_label}_{probe.serial_number}"
        self.public_import_badge.set_status("可导入", "success", size="sm")
        self.public_drone_value.setText(type_label)
        self.public_individual_value.setText(individual_label)
        self.public_file_count_value.setText(str(len(probe.iq_files)))
        if self._rfuav_import_result is None:
            self.public_generated_value.setText("待导入")
        self.public_status_label.setText(
            f"元数据已读取：{probe.drone_label} | 采样率 {probe.sample_rate_hz / 1_000_000:.1f} MHz | "
            f"中心频率 {probe.center_frequency_hz / 1_000_000:.1f} MHz"
        )

    def _import_public_dataset(self) -> None:
        """Import RFUAV public samples into the shared sample table."""

        dataset_root_text = self.public_dataset_root_input.text().strip()
        output_dir_text = self.public_output_dir_input.text().strip()
        if not dataset_root_text:
            self.public_status_label.setText("请先配置公开数据根目录。")
            self.public_import_badge.set_status("未配置", "warning", size="sm")
            return
        if not output_dir_text:
            self.public_status_label.setText("请先配置样本输出目录。")
            self.public_import_badge.set_status("未配置", "warning", size="sm")
            return

        self.public_import_badge.set_status("导入中", "warning", size="sm")
        self.public_status_label.setText("正在执行公开数据样本切片，请稍候...")
        QApplication.processEvents()

        try:
            result = import_rfuav_dataset(
                Path(dataset_root_text),
                self.public_slice_length.value(),
                Path(output_dir_text),
            )
        except RFUAVImportError as exc:
            self.public_import_badge.set_status("失败", "danger", size="sm")
            self.public_status_label.setText(str(exc))
            return

        self._rfuav_import_result = result
        self.public_generated_value.setText(str(result.generated_sample_count))
        self.public_import_badge.set_status("导入完成", "success", size="sm")
        self.public_status_label.setText(
            f"公开数据导入完成：{result.dataset_name} | 原始文件 {result.imported_raw_file_count} 个 | "
            f"生成样本 {result.generated_sample_count} 个。"
        )

        self.sample_records = [record for record in self.sample_records if record.source_type != "rfuav_public"]
        self.sample_records.extend(result.sample_records)
        self._refresh_sample_table()
        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self.sample_records_updated.emit(self.get_sample_records())

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
                record.label_type,
                record.label_individual,
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
            if self._item_text(self.sample_table, row, self.SOURCE_COLUMN) == "公开数据导入":
                continue

            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            mapping = mapping_lookup.get(device_id)
            if mapping is None:
                self._set_table_value(self.sample_table, row, self.TYPE_COLUMN, "")
                self._set_table_value(self.sample_table, row, self.INDIVIDUAL_COLUMN, "")
                self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, "待复核")
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

    def _sync_review_form_from_selection(self) -> None:
        """Load the selected sample into the manual review area."""

        row = self.sample_table.currentRow()
        if row < 0:
            self.review_sample_value.setText("未选择")
            self.review_device_value.setText("-")
            self.review_type_input.clear()
            self.review_individual_input.clear()
            self.review_status_box.setCurrentText("待复核")
            self.review_individual_input.setEnabled(self.individual_radio.isChecked())
            return

        self.review_sample_value.setText(self._item_text(self.sample_table, row, self.SAMPLE_ID_COLUMN))
        self.review_device_value.setText(self._item_text(self.sample_table, row, self.DEVICE_COLUMN))
        self.review_type_input.setText(self._item_text(self.sample_table, row, self.TYPE_COLUMN))
        self.review_individual_input.setText(self._item_text(self.sample_table, row, self.INDIVIDUAL_COLUMN))
        status_text = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待复核"
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

        if review_status == "已标注" and not type_label:
            self.annotation_status_label.setText("状态为已标注时，至少需要填写类型标签。")
            return

        if review_status == "已标注" and self.individual_radio.isChecked() and not individual_label:
            self.annotation_status_label.setText("个体识别模式下，状态为已标注时需要填写个体标签。")
            return

        self._set_table_value(self.sample_table, row, self.TYPE_COLUMN, type_label)
        if self.individual_radio.isChecked():
            self._set_table_value(self.sample_table, row, self.INDIVIDUAL_COLUMN, individual_label)
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
                status=self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待复核",
                device_id=self._item_text(self.sample_table, row, self.DEVICE_COLUMN),
            )
            break

    def _apply_filters(self) -> None:
        """Filter the sample table by device and annotation status."""

        selected_device = self.device_filter.currentText()
        selected_status = self.status_filter.currentText()

        for row in range(self.sample_table.rowCount()):
            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            row_status = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待复核"

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
            row_status = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待复核"
            if row_status != "已标注":
                pending_count += 1

        self.mapping_metric.set_value(str(mapping_count))
        self.sample_metric.set_value(str(self.sample_table.rowCount()))
        self.pending_metric.set_value(str(pending_count))

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
        public_rows = 0
        local_rows = 0
        for row in range(self.sample_table.rowCount()):
            status_text = self._item_text(self.sample_table, row, self.STATUS_COLUMN)
            label_text = self._item_text(self.sample_table, row, label_column)
            if status_text != "已标注" or not label_text:
                continue
            label_counts[label_text] = label_counts.get(label_text, 0) + 1
            if self._item_text(self.sample_table, row, self.SOURCE_COLUMN) == "公开数据导入":
                public_rows += 1
            else:
                local_rows += 1

        if not label_counts:
            self.dataset_build_status_label.setText("当前没有可用的已标注样本，无法生成数据集版本。")
            return

        source_summary = "公开数据导入" if public_rows and not local_rows else "混合样本" if public_rows else "本地样本"
        version_id = self._next_generated_version_id()
        record = DatasetVersionRecord(
            version_id=version_id,
            task_type=task_type,
            sample_count=sum(label_counts.values()),
            strategy=self.strategy_box.currentText(),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            source_summary=source_summary,
            label_counts=label_counts,
        )
        self.dataset_versions.append(record)
        self.version_metric.set_value(version_id)
        self._refresh_dataset_result_table(label_counts)
        self._refresh_history_table()
        self.dataset_build_status_label.setText(
            f"数据集 {version_id} 已生成：{task_type} | 样本 {record.sample_count} 条 | 来源 {source_summary}。"
        )
        self.dataset_versions_updated.emit(self.get_dataset_versions())

    def _next_generated_version_id(self) -> str:
        """Return the next dataset version ID for generated datasets."""

        generated_numbers = [
            int(record.version_id.split("_v")[-1])
            for record in self.dataset_versions
            if record.version_id.startswith("rfuav_v")
        ]
        next_number = max(generated_numbers, default=0) + 1
        return f"rfuav_v{next_number:03d}"

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
