"""Training page for machine learning, deep learning, and export workflows."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import EXPORTS_DIR
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class TrainPage(QWidget):
    """Workflow page used to configure training, evaluate results, and export models."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the training page."""

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
        metrics_row.addWidget(MetricCard("最新精度", "94.7%", compact=True))
        metrics_row.addWidget(MetricCard("F1 分数", "0.942", accent_color="#7CB98B", compact=True))
        metrics_row.addWidget(MetricCard("导出格式", "ONNX", accent_color="#C59A63", compact=True))
        content_layout.addLayout(metrics_row)

        content_layout.addWidget(self._build_config_card())

        lower_row = QHBoxLayout()
        lower_row.setSpacing(14)
        lower_row.addWidget(self._build_results_card(), 3)
        lower_row.addWidget(self._build_export_workspace(), 2)
        content_layout.addLayout(lower_row)
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def _build_config_card(self) -> SectionCard:
        """Create the training configuration card."""

        section = SectionCard(
            "训练配置",
            "选择任务类型、数据集版本和训练参数。",
            right_widget=StatusBadge("待启动", "info", size="sm"),
            compact=True,
        )

        switch_row = QHBoxLayout()
        switch_row.setSpacing(12)
        self.task_type_box = QComboBox()
        self.task_type_box.addItems(["类型识别（机器学习）", "个体识别（深度学习）"])
        self.task_type_box.currentIndexChanged.connect(self._switch_config_mode)

        self.dataset_box = QComboBox()
        self.dataset_box.addItems(["v001", "v002", "v003"])

        switch_row.addWidget(QLabel("任务类型"))
        switch_row.addWidget(self.task_type_box)
        switch_row.addSpacing(10)
        switch_row.addWidget(QLabel("数据集版本"))
        switch_row.addWidget(self.dataset_box)
        switch_row.addStretch(1)

        self.config_stack = QStackedWidget()
        self.config_stack.addWidget(self._build_ml_form())
        self.config_stack.addWidget(self._build_dl_form())

        action_row = QHBoxLayout()
        start_button = QPushButton("执行训练")
        start_button.setObjectName("PrimaryButton")
        stop_button = QPushButton("中止训练")
        stop_button.setObjectName("DangerButton")
        validate_button = QPushButton("数据检查")

        action_row.addWidget(start_button)
        action_row.addWidget(stop_button)
        action_row.addWidget(validate_button)
        action_row.addStretch(1)

        section.body_layout.addLayout(switch_row)
        section.body_layout.addWidget(self.config_stack)
        section.body_layout.addLayout(action_row)
        return section

    def _build_ml_form(self) -> QGroupBox:
        """Create the machine learning configuration panel."""

        box = QGroupBox("类型识别配置")
        form_layout = QFormLayout(box)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        algorithm_box = QComboBox()
        algorithm_box.addItems(["RandomForest", "SVM", "XGBoost"])

        model_name = QComboBox()
        model_name.setEditable(True)
        model_name.addItems(["rf_type_v001", "svm_type_v002", "xgb_type_v003"])

        n_estimators = QSpinBox()
        n_estimators.setRange(10, 1000)
        n_estimators.setValue(300)

        max_depth = QSpinBox()
        max_depth.setRange(2, 128)
        max_depth.setValue(24)

        form_layout.addRow("算法", algorithm_box)
        form_layout.addRow("模型名称", model_name)
        form_layout.addRow("树数量 / 迭代数", n_estimators)
        form_layout.addRow("最大深度", max_depth)
        return box

    def _build_dl_form(self) -> QGroupBox:
        """Create the deep learning configuration panel."""

        box = QGroupBox("个体识别配置")
        form_layout = QFormLayout(box)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        network_box = QComboBox()
        network_box.addItems(["1D-CNN", "CNN + LSTM"])

        model_name = QComboBox()
        model_name.setEditable(True)
        model_name.addItems(["iqcnn_v003", "cnn_lstm_v001"])

        batch_size = QSpinBox()
        batch_size.setRange(1, 512)
        batch_size.setValue(16)

        epochs = QSpinBox()
        epochs.setRange(1, 500)
        epochs.setValue(50)

        learning_rate = QComboBox()
        learning_rate.setEditable(True)
        learning_rate.addItems(["1e-3", "5e-4", "1e-4"])

        form_layout.addRow("网络结构", network_box)
        form_layout.addRow("模型名称", model_name)
        form_layout.addRow("批大小", batch_size)
        form_layout.addRow("训练轮次", epochs)
        form_layout.addRow("学习率", learning_rate)
        return box

    def _build_results_card(self) -> SectionCard:
        """Create the unified results display card."""

        section = SectionCard("结果评估", "显示训练结果和分类明细。", compact=True)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)

        confusion_placeholder = QPlainTextEdit()
        confusion_placeholder.setReadOnly(True)
        confusion_placeholder.setPlainText(
            "混淆矩阵显示区\n\n"
            "后续接入 Matplotlib 或 seaborn 画布。"
        )
        confusion_placeholder.setMinimumHeight(240)
        configure_scrollable(confusion_placeholder)

        training_log = QPlainTextEdit()
        training_log.setReadOnly(True)
        training_log.setPlainText(
            "[Epoch 01] train_acc=0.74, val_acc=0.71\n"
            "[Epoch 10] train_acc=0.88, val_acc=0.84\n"
            "[Epoch 21] train_acc=0.95, val_acc=0.93\n"
            "最优权重已归档至 data/models/"
        )
        training_log.setMinimumHeight(240)
        configure_scrollable(training_log)

        summary_row.addWidget(confusion_placeholder, 2)
        summary_row.addWidget(training_log, 1)

        detail_table = QTableWidget(4, 5)
        detail_table.setHorizontalHeaderLabels(["类别", "精确率", "召回率", "F1", "样本数"])
        detail_table.horizontalHeader().setStretchLastSection(True)
        detail_table.verticalHeader().setVisible(False)
        detail_table.setAlternatingRowColors(True)
        configure_scrollable(detail_table)
        rows = [
            ["DJI_Mavic3", "0.96", "0.94", "0.95", "205"],
            ["Autel_EVO", "0.92", "0.90", "0.91", "138"],
            ["FPV_Racing", "0.95", "0.97", "0.96", "264"],
            ["Unknown", "0.88", "0.84", "0.86", "29"],
        ]
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                detail_table.setItem(row_index, column, QTableWidgetItem(value))

        section.body_layout.addLayout(summary_row)
        section.body_layout.addWidget(detail_table)
        return section

    def _build_export_workspace(self) -> QWidget:
        """Create the export workspace shown beside training results."""

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(self._build_export_config_card())
        layout.addWidget(self._build_export_result_card())
        layout.addStretch(1)
        return wrapper

    def _build_export_config_card(self) -> SectionCard:
        """Create the integrated export configuration card."""

        section = SectionCard(
            "模型导出",
            "选择模型并生成交付文件。",
            right_widget=StatusBadge("待导出", "info", size="sm"),
            compact=True,
        )

        self.export_model_box = QComboBox()
        self.export_model_box.addItems(
            [
                "rf_type_v001 | 类型识别 | RandomForest",
                "iqcnn_v003 | 个体识别 | 1D-CNN",
                "cnn_lstm_v001 | 个体识别 | CNN + LSTM",
            ]
        )
        self.export_model_box.currentIndexChanged.connect(self._update_export_details)

        self.export_detail_labels = {
            "任务类型": QLabel(),
            "算法": QLabel(),
            "数据集版本": QLabel(),
            "最新精度": QLabel(),
        }
        for label in self.export_detail_labels.values():
            label.setObjectName("ValueLabel")

        info_layout = QFormLayout()
        info_layout.setHorizontalSpacing(12)
        info_layout.setVerticalSpacing(12)
        info_layout.addRow("模型列表", self.export_model_box)
        for key, value in self.export_detail_labels.items():
            info_layout.addRow(key, value)

        export_layout = QFormLayout()
        export_layout.setHorizontalSpacing(12)
        export_layout.setVerticalSpacing(12)

        self.export_path_input = QLineEdit(str(EXPORTS_DIR))
        self.format_box = QComboBox()
        self.format_box.addItems(["ONNX（必选）", "ONNX + 原始模型", "仅原始模型"])

        export_layout.addRow("导出路径", self.export_path_input)
        export_layout.addRow("导出格式", self.format_box)

        self.include_readme = QCheckBox("附带 README.md")
        self.include_readme.setChecked(True)
        self.include_example = QCheckBox("附带 inference_example.py")
        self.include_example.setChecked(True)
        self.include_preprocess = QCheckBox("附带 preprocess_config.json")
        self.include_preprocess.setChecked(True)
        self.include_mapping = QCheckBox("附带 class_mapping.json")
        self.include_mapping.setChecked(True)

        option_column = QVBoxLayout()
        option_column.setSpacing(8)
        for checkbox in [
            self.include_readme,
            self.include_example,
            self.include_preprocess,
            self.include_mapping,
        ]:
            option_column.addWidget(checkbox)

        action_row = QHBoxLayout()
        export_button = QPushButton("执行导出")
        export_button.setObjectName("PrimaryButton")
        verify_button = QPushButton("执行精度校核")
        action_row.addWidget(export_button)
        action_row.addWidget(verify_button)
        action_row.addStretch(1)

        section.body_layout.addLayout(info_layout)
        section.body_layout.addLayout(export_layout)
        section.body_layout.addLayout(option_column)
        section.body_layout.addLayout(action_row)

        self._update_export_details(0)
        return section

    def _build_export_result_card(self) -> SectionCard:
        """Create the export result card."""

        section = SectionCard("交付结果", "显示导出文件与校核状态。", compact=True)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.addWidget(StatusBadge("校核通过", "success", size="sm"))

        drift_label = QLabel("原模型 94.7% | ONNX Runtime 94.5% | 偏差 0.2%")
        drift_label.setObjectName("MutedText")
        status_row.addWidget(drift_label)
        status_row.addStretch(1)

        result_table = QTableWidget(5, 3)
        result_table.setHorizontalHeaderLabels(["文件名", "类型", "备注"])
        result_table.horizontalHeader().setStretchLastSection(True)
        result_table.verticalHeader().setVisible(False)
        result_table.setAlternatingRowColors(True)
        configure_scrollable(result_table)
        rows = [
            ["model.onnx", "模型", "ONNX 推理模型"],
            ["class_mapping.json", "配置", "类别 ID 到标签映射"],
            ["preprocess_config.json", "配置", "预处理参数"],
            ["inference_example.py", "推理脚本", "完整推理样例"],
            ["README.md", "交付文档", "部署与调用说明"],
        ]
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                result_table.setItem(row_index, column, QTableWidgetItem(value))

        section.body_layout.addLayout(status_row)
        section.body_layout.addWidget(result_table)
        return section

    def _update_export_details(self, index: int) -> None:
        """Refresh export model detail labels."""

        detail_rows = [
            ("类型识别", "RandomForest", "v003", "94.7%"),
            ("个体识别", "1D-CNN", "v002", "92.4%"),
            ("个体识别", "CNN + LSTM", "v002", "93.1%"),
        ]
        task_type, algorithm, dataset_version, accuracy = detail_rows[index]
        self.export_detail_labels["任务类型"].setText(task_type)
        self.export_detail_labels["算法"].setText(algorithm)
        self.export_detail_labels["数据集版本"].setText(dataset_version)
        self.export_detail_labels["最新精度"].setText(accuracy)

    def _switch_config_mode(self, index: int) -> None:
        """Switch between the machine learning and deep learning config forms."""

        self.config_stack.setCurrentIndex(index)
