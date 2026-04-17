"""Training page for machine learning and deep learning workflows."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import MetricCard, SectionCard, StatusBadge


class TrainPage(QWidget):
    """Workflow page used to configure and present training results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the training page."""

        super().__init__(parent)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        metrics_row.addWidget(MetricCard("最新精度", "94.7%", compact=True))
        metrics_row.addWidget(MetricCard("F1 分数", "0.942", accent_color="#7CB98B", compact=True))
        metrics_row.addWidget(MetricCard("任务模型", "IQCNN_v3", accent_color="#C59A63", compact=True))
        content_layout.addLayout(metrics_row)

        content_layout.addWidget(self._build_config_card())

        lower_row = QHBoxLayout()
        lower_row.setSpacing(14)
        lower_row.addWidget(self._build_results_card(), 3)
        lower_row.addWidget(self._build_inference_card(), 2)
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

        training_log = QPlainTextEdit()
        training_log.setReadOnly(True)
        training_log.setPlainText(
            "[Epoch 01] train_acc=0.74, val_acc=0.71\n"
            "[Epoch 10] train_acc=0.88, val_acc=0.84\n"
            "[Epoch 21] train_acc=0.95, val_acc=0.93\n"
            "最优权重已归档至 data/models/"
        )
        training_log.setMinimumHeight(240)

        summary_row.addWidget(confusion_placeholder, 2)
        summary_row.addWidget(training_log, 1)

        detail_table = QTableWidget(4, 5)
        detail_table.setHorizontalHeaderLabels(["类别", "精确率", "召回率", "F1", "样本数"])
        detail_table.horizontalHeader().setStretchLastSection(True)
        detail_table.verticalHeader().setVisible(False)
        detail_table.setAlternatingRowColors(True)
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

    def _build_inference_card(self) -> SectionCard:
        """Create the single-sample inference demo card."""

        section = SectionCard(
            "单样本校验",
            "加载样本并查看当前模型输出。",
            right_widget=StatusBadge("结果: DJI_Mavic3", "success", size="sm"),
            compact=True,
        )

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        model_selector = QComboBox()
        model_selector.addItems(["rf_type_v001", "iqcnn_v003", "cnn_lstm_v001"])

        source_selector = QComboBox()
        source_selector.addItems(["数据库中已有样本", "外部 .cap 文件"])

        sample_selector = QComboBox()
        sample_selector.addItems(["sample_1101.npy", "sample_1103.npy", "demo_capture.cap"])

        form_layout.addRow("选择模型", model_selector)
        form_layout.addRow("样本来源", source_selector)
        form_layout.addRow("目标样本", sample_selector)

        probability_table = QTableWidget(4, 2)
        probability_table.setHorizontalHeaderLabels(["类别", "置信度"])
        probability_table.horizontalHeader().setStretchLastSection(True)
        probability_table.verticalHeader().setVisible(False)
        probability_table.setAlternatingRowColors(True)
        rows = [
            ["DJI_Mavic3", "73.5%"],
            ["Autel_EVO", "12.4%"],
            ["FPV_Racing", "8.7%"],
            ["Unknown", "5.4%"],
        ]
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                probability_table.setItem(row_index, column, QTableWidgetItem(value))

        button_row = QHBoxLayout()
        load_button = QPushButton("加载样本")
        run_button = QPushButton("开始识别")
        run_button.setObjectName("PrimaryButton")
        button_row.addWidget(load_button)
        button_row.addWidget(run_button)
        button_row.addStretch(1)

        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(probability_table)
        return section

    def _switch_config_mode(self, index: int) -> None:
        """Switch between the machine learning and deep learning config forms."""

        self.config_stack.setCurrentIndex(index)
