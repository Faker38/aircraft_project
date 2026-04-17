"""Export page for model packaging and delivery preparation."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import EXPORTS_DIR
from ui.widgets import MetricCard, SectionCard, StatusBadge


class ExportPage(QWidget):
    """Workflow page for exporting trained models."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the export page."""

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
        metrics_row.addWidget(MetricCard("导出格式", "ONNX", compact=True))
        metrics_row.addWidget(MetricCard("校核偏差", "0.2%", accent_color="#7CB98B", compact=True))
        metrics_row.addWidget(MetricCard("交付包", "4 项文件", accent_color="#C59A63", compact=True))
        content_layout.addLayout(metrics_row)

        upper_row = QHBoxLayout()
        upper_row.setSpacing(14)
        upper_row.addWidget(self._build_selection_card(), 2)
        upper_row.addWidget(self._build_export_card(), 3)

        content_layout.addLayout(upper_row)
        content_layout.addWidget(self._build_result_card())
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def _build_selection_card(self) -> SectionCard:
        """Create the model selection and detail card."""

        section = SectionCard("模型选择", "确认当前导出对象。", compact=True)

        self.model_box = QComboBox()
        self.model_box.addItems(
            [
                "rf_type_v001 | 类型识别 | RandomForest",
                "iqcnn_v003 | 个体识别 | 1D-CNN",
                "cnn_lstm_v001 | 个体识别 | CNN + LSTM",
            ]
        )
        self.model_box.currentIndexChanged.connect(self._update_model_details)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.detail_labels = {
            "任务类型": QLabel(),
            "算法": QLabel(),
            "数据集版本": QLabel(),
            "最新精度": QLabel(),
        }

        for label in self.detail_labels.values():
            label.setObjectName("ValueLabel")

        form_layout.addRow("模型列表", self.model_box)
        for key, value in self.detail_labels.items():
            form_layout.addRow(key, value)

        section.body_layout.addLayout(form_layout)
        self._update_model_details(0)
        return section

    def _build_export_card(self) -> SectionCard:
        """Create the export configuration card."""

        section = SectionCard(
            "导出配置",
            "设置导出路径和附带文件。",
            right_widget=StatusBadge("待导出", "info", size="sm"),
            compact=True,
        )

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.export_path_input = QLineEdit(str(EXPORTS_DIR))
        self.format_box = QComboBox()
        self.format_box.addItems(["ONNX（必选）", "ONNX + 原始模型", "仅原始模型"])

        form_layout.addRow("导出路径", self.export_path_input)
        form_layout.addRow("导出格式", self.format_box)

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

        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(option_column)
        section.body_layout.addLayout(action_row)
        return section

    def _build_result_card(self) -> SectionCard:
        """Create the export result display card."""

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

    def _update_model_details(self, index: int) -> None:
        """Refresh the detail labels for the selected model."""

        detail_rows = [
            ("类型识别", "RandomForest", "v003", "94.7%"),
            ("个体识别", "1D-CNN", "v002", "92.4%"),
            ("个体识别", "CNN + LSTM", "v002", "93.1%"),
        ]
        task_type, algorithm, dataset_version, accuracy = detail_rows[index]
        self.detail_labels["任务类型"].setText(task_type)
        self.detail_labels["算法"].setText(algorithm)
        self.detail_labels["数据集版本"].setText(dataset_version)
        self.detail_labels["最新精度"].setText(accuracy)
