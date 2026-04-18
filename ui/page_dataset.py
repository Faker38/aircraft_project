"""Dataset page for mapping maintenance, annotation, and dataset building."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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

from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class DatasetPage(QWidget):
    """Workflow page for mapping maintenance and dataset management."""

    DEVICE_COLUMN = 2
    TYPE_COLUMN = 4
    INDIVIDUAL_COLUMN = 5
    STATUS_COLUMN = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the dataset page."""

        super().__init__(parent)
        self._mapping_edit_row: int | None = None

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
        self.pending_metric = MetricCard("待复核样本", "0", accent_color="#7CB98B", compact=True)
        self.version_metric = MetricCard("数据集版本", "v003", accent_color="#C59A63", compact=True)
        metrics_row.addWidget(self.mapping_metric)
        metrics_row.addWidget(self.pending_metric)
        metrics_row.addWidget(self.version_metric)
        content_layout.addLayout(metrics_row)

        tabs = QTabWidget()
        tabs.addTab(self._build_labeling_tab(), "样本标注")
        tabs.addTab(self._build_dataset_tab(), "数据集构建")
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._sync_device_filter_options()
        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()

    def _build_labeling_tab(self) -> QWidget:
        """Create the annotation management tab."""

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_mapping_card(), 2)
        top_row.addWidget(self._build_sample_label_card(), 3)

        layout.addLayout(top_row)
        return tab

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

        self.mapping_status_label = QLabel("维护好映射表后，样本可按设备编号自动回填标签。")
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

        mode_hint = QLabel("建议先维护编号映射，系统可自动回填标签；仅对未匹配或异常样本做人工复核。")
        mode_hint.setObjectName("MutedText")
        mode_hint.setWordWrap(True)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.device_filter = QComboBox()
        self.device_filter.addItems(["全部设备", "drone_001", "drone_003", "drone_007"])
        self.device_filter.currentIndexChanged.connect(self._apply_filters)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部状态", "待复核", "已标注"])
        self.status_filter.currentIndexChanged.connect(self._apply_filters)

        filter_row.addWidget(QLabel("设备筛选"))
        filter_row.addWidget(self.device_filter)
        filter_row.addWidget(QLabel("标注状态"))
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch(1)

        self.sample_table = QTableWidget(4, 7)
        self.sample_table.setHorizontalHeaderLabels(
            ["样本 ID", "来源文件", "设备编号", "SNR", "类型标签", "个体标签", "状态"]
        )
        self.sample_table.horizontalHeader().setStretchLastSection(True)
        self.sample_table.verticalHeader().setVisible(False)
        self.sample_table.setAlternatingRowColors(True)
        self.sample_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sample_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sample_table.itemSelectionChanged.connect(self._sync_review_form_from_selection)
        configure_scrollable(self.sample_table)

        sample_rows = [
            ["1101", "20260415_213011.cap", "drone_001", "18.5 dB", "DJI_Mavic3", "mavic3_001", "已标注"],
            ["1102", "20260415_213011.cap", "drone_001", "17.9 dB", "DJI_Mavic3", "mavic3_001", "已标注"],
            ["1103", "20260416_093205.cap", "drone_007", "13.1 dB", "FPV_Racing", "fpv_007", "已标注"],
            ["1104", "20260416_101155.cap", "drone_003", "11.0 dB", "", "", "待复核"],
        ]
        for row_index, row_data in enumerate(sample_rows):
            for column, value in enumerate(row_data):
                self.sample_table.setItem(row_index, column, QTableWidgetItem(value))

        review_title = QLabel("复核区")
        review_title.setObjectName("SectionTitle")

        review_hint = QLabel("点击样本行后，在这里做少量修正。正常样本不需要逐条手工标注。")
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

        self.annotation_status_label = QLabel("当前模式：类型识别。自动标注会优先回填类型标签。")
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
            "设置分集比例和划分策略。",
            right_widget=StatusBadge("版本 v003", "warning", size="sm"),
            compact=True,
        )

        mode_row = QHBoxLayout()
        type_radio = QRadioButton("类型识别")
        type_radio.setChecked(True)
        individual_radio = QRadioButton("个体识别")
        mode_row.addWidget(type_radio)
        mode_row.addWidget(individual_radio)
        mode_row.addStretch(1)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        train_ratio = QSpinBox()
        train_ratio.setRange(10, 90)
        train_ratio.setSuffix(" %")
        train_ratio.setValue(70)

        val_ratio = QSpinBox()
        val_ratio.setRange(5, 45)
        val_ratio.setSuffix(" %")
        val_ratio.setValue(15)

        test_ratio = QSpinBox()
        test_ratio.setRange(5, 45)
        test_ratio.setSuffix(" %")
        test_ratio.setValue(15)

        strategy_box = QComboBox()
        strategy_box.addItems(["按样本随机分层", "按设备个体隔离"])

        form_layout.addRow("训练集", train_ratio)
        form_layout.addRow("验证集", val_ratio)
        form_layout.addRow("测试集", test_ratio)
        form_layout.addRow("划分策略", strategy_box)

        action_row = QHBoxLayout()
        generate_button = QPushButton("生成数据集")
        generate_button.setObjectName("PrimaryButton")
        action_row.addWidget(generate_button)
        action_row.addStretch(1)

        build_card.body_layout.addLayout(mode_row)
        build_card.body_layout.addLayout(form_layout)
        build_card.body_layout.addLayout(action_row)
        top_row.addWidget(build_card, 2)

        result_card = SectionCard("划分结果", "查看各分集样本数量。", compact=True)
        result_table = QTableWidget(4, 4)
        result_table.setHorizontalHeaderLabels(["类别 / 个体", "训练集", "验证集", "测试集"])
        result_table.horizontalHeader().setStretchLastSection(True)
        result_table.verticalHeader().setVisible(False)
        result_table.setAlternatingRowColors(True)
        configure_scrollable(result_table)
        result_rows = [
            ["DJI_Mavic3", "480", "103", "102"],
            ["Autel_EVO", "322", "69", "69"],
            ["FPV_Racing", "618", "132", "132"],
            ["未标注", "0", "0", "14"],
        ]
        for row_index, row_data in enumerate(result_rows):
            for column, value in enumerate(row_data):
                result_table.setItem(row_index, column, QTableWidgetItem(value))

        result_card.body_layout.addWidget(result_table)
        top_row.addWidget(result_card, 3)

        history_card = SectionCard("历史版本", "显示已生成数据集。", compact=True)
        history_table = QTableWidget(3, 5)
        history_table.setHorizontalHeaderLabels(["版本号", "任务类型", "训练样本", "策略", "创建时间"])
        history_table.horizontalHeader().setStretchLastSection(True)
        history_table.verticalHeader().setVisible(False)
        history_table.setAlternatingRowColors(True)
        configure_scrollable(history_table)
        history_rows = [
            ["v001", "类型识别", "1260", "随机分层", "2026-04-09 18:22"],
            ["v002", "个体识别", "980", "个体隔离", "2026-04-13 20:06"],
            ["v003", "类型识别", "1420", "随机分层", "2026-04-16 16:10"],
        ]
        for row_index, row_data in enumerate(history_rows):
            for column, value in enumerate(row_data):
                history_table.setItem(row_index, column, QTableWidgetItem(value))

        history_card.body_layout.addWidget(history_table)

        layout.addLayout(top_row)
        layout.addWidget(history_card)
        return tab

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
        """Fill sample labels by the current mapping table."""

        mapping_lookup = self._build_mapping_lookup()
        matched_rows = 0
        pending_rows = 0

        for row in range(self.sample_table.rowCount()):
            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            mapping = mapping_lookup.get(device_id)
            if mapping is None:
                self._set_table_value(self.sample_table, row, self.TYPE_COLUMN, "")
                self._set_table_value(self.sample_table, row, self.INDIVIDUAL_COLUMN, "")
                self._set_table_value(self.sample_table, row, self.STATUS_COLUMN, "待复核")
                pending_rows += 1
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

        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self.annotation_status_label.setText(
            f"自动标注完成：{matched_rows} 条已按映射回填，{pending_rows} 条仍需人工复核。"
        )

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

        self.review_sample_value.setText(self._item_text(self.sample_table, row, 0))
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

        self._refresh_annotation_metrics()
        self._apply_filters()
        self._sync_review_form_from_selection()
        self.annotation_status_label.setText(
            f"样本 {self.review_sample_value.text()} 已保存复核结果，当前状态：{review_status}。"
        )

    def _apply_filters(self) -> None:
        """Filter the sample table by device and annotation status."""

        selected_device = self.device_filter.currentText()
        selected_status = self.status_filter.currentText()

        for row in range(self.sample_table.rowCount()):
            device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
            row_status = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待复核"

            visible = True
            if selected_device != "全部设备" and device_id != selected_device:
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
        """Refresh the top metrics for mappings and pending reviews."""

        mapping_count = self.mapping_table.rowCount()
        pending_count = 0

        if hasattr(self, "sample_table"):
            for row in range(self.sample_table.rowCount()):
                row_status = self._item_text(self.sample_table, row, self.STATUS_COLUMN) or "待复核"
                if row_status != "已标注":
                    pending_count += 1

        self.mapping_metric.set_value(str(mapping_count))
        self.pending_metric.set_value(str(pending_count))

    def _sync_device_filter_options(self) -> None:
        """Refresh the device filter from sample rows and mapping rows."""

        if not hasattr(self, "device_filter"):
            return

        current_text = self.device_filter.currentText() or "全部设备"
        device_ids: set[str] = set()

        if hasattr(self, "sample_table"):
            for row in range(self.sample_table.rowCount()):
                device_id = self._item_text(self.sample_table, row, self.DEVICE_COLUMN)
                if device_id:
                    device_ids.add(device_id)

        if hasattr(self, "mapping_table"):
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
