"""Processing page for signal extraction, labeling, and dataset building."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
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


class ProcessPage(QWidget):
    """Workflow page for data processing and dataset curation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the process page."""

        super().__init__(parent)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        metrics_row.addWidget(MetricCard("待处理批次", "12", compact=True))
        metrics_row.addWidget(MetricCard("样本数量", "3,428", accent_color="#7CB98B", compact=True))
        metrics_row.addWidget(MetricCard("数据集版本", "v003", accent_color="#C59A63", compact=True))
        content_layout.addLayout(metrics_row)

        tabs = QTabWidget()
        tabs.addTab(self._build_processing_tab(), "信号处理")
        tabs.addTab(self._build_labeling_tab(), "标注管理")
        tabs.addTab(self._build_dataset_tab(), "数据集构建")
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def _build_processing_tab(self) -> QWidget:
        """Create the signal processing tab."""

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        file_card = SectionCard("原始文件", "选择待处理记录。", compact=True)
        file_table = QTableWidget(3, 5)
        file_table.setHorizontalHeaderLabels(["文件名", "设备编号", "采样时长", "状态", "更新时间"])
        file_table.horizontalHeader().setStretchLastSection(True)
        file_table.verticalHeader().setVisible(False)
        file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        file_table.setAlternatingRowColors(True)
        file_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(file_table)

        mock_rows = [
            ["20260415_213011_2400M_20M_drone_001.cap", "drone_001", "180 s", "raw", "2026-04-15 21:30"],
            ["20260416_093205_5800M_40M_drone_007.cap", "drone_007", "120 s", "raw", "2026-04-16 09:33"],
            ["20260416_101155_2450M_10M_drone_003.cap", "drone_003", "90 s", "error", "2026-04-16 10:14"],
        ]
        for row_index, row_data in enumerate(mock_rows):
            for column, value in enumerate(row_data):
                file_table.setItem(row_index, column, QTableWidgetItem(value))
        file_card.body_layout.addWidget(file_table)
        top_row.addWidget(file_card, 3)

        config_card = SectionCard(
            "处理参数",
            "设置切片与检测参数。",
            right_widget=StatusBadge("待处理", "info", size="sm"),
            compact=True,
        )
        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        slice_length_input = QSpinBox()
        slice_length_input.setRange(1024, 262144)
        slice_length_input.setSingleStep(1024)
        slice_length_input.setValue(65536)

        threshold_input = QDoubleSpinBox()
        threshold_input.setRange(0.0, 30.0)
        threshold_input.setDecimals(1)
        threshold_input.setSuffix(" dB")
        threshold_input.setValue(6.0)

        bandpass_checkbox = QCheckBox("启用带通滤波")

        form_layout.addRow("切片长度", slice_length_input)
        form_layout.addRow("能量阈值", threshold_input)
        form_layout.addRow("滤波选项", bandpass_checkbox)

        process_progress = QProgressBar()
        process_progress.setValue(42)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        start_button = QPushButton("开始处理")
        start_button.setObjectName("PrimaryButton")
        stop_button = QPushButton("停止任务")
        stop_button.setObjectName("DangerButton")

        button_row.addWidget(start_button)
        button_row.addWidget(stop_button)
        button_row.addStretch(1)

        config_card.body_layout.addWidget(process_progress)
        config_card.body_layout.addLayout(form_layout)
        config_card.body_layout.addLayout(button_row)
        top_row.addWidget(config_card, 2)

        flow_card = SectionCard("处理摘要", "解析 -> 归一化 -> 切片 -> 入库", compact=True)
        flow_label = QLabel("当前链路按 .cap 解析、信号筛选、样本切片和元数据入库顺序执行。")
        flow_label.setObjectName("MutedText")
        flow_label.setWordWrap(True)
        flow_card.body_layout.addWidget(flow_label)

        layout.addLayout(top_row)
        layout.addWidget(flow_card)
        return tab

    def _build_labeling_tab(self) -> QWidget:
        """Create the labeling management tab."""

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        mapping_card = SectionCard("编号映射", "维护设备与标签关系。", compact=True)
        mapping_table = QTableWidget(3, 4)
        mapping_table.setHorizontalHeaderLabels(["设备编号", "类型标签", "个体标签", "备注"])
        mapping_table.horizontalHeader().setStretchLastSection(True)
        mapping_table.verticalHeader().setVisible(False)
        mapping_table.setAlternatingRowColors(True)
        configure_scrollable(mapping_table)
        mapping_rows = [
            ["drone_001", "DJI_Mavic3", "mavic3_001", "甲方样机 A"],
            ["drone_003", "Autel_EVO", "autel_003", "Autel 目标机"],
            ["drone_007", "FPV_Racing", "fpv_007", "竞速穿越机"],
        ]
        for row_index, row_data in enumerate(mapping_rows):
            for column, value in enumerate(row_data):
                mapping_table.setItem(row_index, column, QTableWidgetItem(value))

        mapping_buttons = QHBoxLayout()
        for text in ["新增映射", "编辑映射", "删除映射"]:
            mapping_buttons.addWidget(QPushButton(text))
        mapping_buttons.addStretch(1)

        mapping_card.body_layout.addWidget(mapping_table)
        mapping_card.body_layout.addLayout(mapping_buttons)
        top_row.addWidget(mapping_card, 2)

        label_card = SectionCard("样本标注", "按设备与状态筛选样本。", compact=True)

        mode_row = QHBoxLayout()
        type_radio = QRadioButton("类型识别")
        type_radio.setChecked(True)
        individual_radio = QRadioButton("个体识别")
        mode_row.addWidget(type_radio)
        mode_row.addWidget(individual_radio)
        mode_row.addStretch(1)

        filter_row = QHBoxLayout()
        device_filter = QComboBox()
        device_filter.addItems(["全部设备", "drone_001", "drone_003", "drone_007"])
        label_filter = QComboBox()
        label_filter.addItems(["全部标签", "未标注", "已标注"])
        filter_row.addWidget(QLabel("设备筛选"))
        filter_row.addWidget(device_filter)
        filter_row.addWidget(QLabel("标注状态"))
        filter_row.addWidget(label_filter)
        filter_row.addStretch(1)

        sample_table = QTableWidget(4, 6)
        sample_table.setHorizontalHeaderLabels(
            ["样本 ID", "来源文件", "设备编号", "SNR", "类型标签", "个体标签"]
        )
        sample_table.horizontalHeader().setStretchLastSection(True)
        sample_table.verticalHeader().setVisible(False)
        sample_table.setAlternatingRowColors(True)
        configure_scrollable(sample_table)

        sample_rows = [
            ["1101", "20260415_213011.cap", "drone_001", "18.5 dB", "DJI_Mavic3", "mavic3_001"],
            ["1102", "20260415_213011.cap", "drone_001", "17.9 dB", "DJI_Mavic3", "mavic3_001"],
            ["1103", "20260416_093205.cap", "drone_007", "13.1 dB", "FPV_Racing", "fpv_007"],
            ["1104", "20260416_101155.cap", "drone_003", "11.0 dB", "", ""],
        ]
        for row_index, row_data in enumerate(sample_rows):
            for column, value in enumerate(row_data):
                sample_table.setItem(row_index, column, QTableWidgetItem(value))

        action_row = QHBoxLayout()
        auto_button = QPushButton("自动标注")
        auto_button.setObjectName("PrimaryButton")
        manual_button = QPushButton("手动标注所选")
        action_row.addWidget(auto_button)
        action_row.addWidget(manual_button)
        action_row.addStretch(1)

        label_card.body_layout.addLayout(mode_row)
        label_card.body_layout.addLayout(filter_row)
        label_card.body_layout.addWidget(sample_table)
        label_card.body_layout.addLayout(action_row)
        top_row.addWidget(label_card, 3)

        layout.addLayout(top_row)
        return tab

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
