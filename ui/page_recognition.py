"""Recognition page for drone type and fingerprint identification."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class RecognitionPage(QWidget):
    """Workflow page for drone type and fingerprint recognition."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the recognition page."""

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
        metrics_row.addWidget(MetricCard("类型识别模型", "rf_type_v001", compact=True))
        metrics_row.addWidget(MetricCard("指纹识别模型", "iqcnn_v003", accent_color="#7CB98B", compact=True))
        metrics_row.addWidget(MetricCard("最近识别结果", "DJI_Mavic3", accent_color="#C59A63", compact=True))
        content_layout.addLayout(metrics_row)

        tabs = QTabWidget()
        tabs.addTab(
            self._build_recognition_tab(
                mode_title="无人机类型识别",
                mode_hint="按模型和样本来源执行无人机类型识别。",
                status_text="结果: DJI_Mavic3",
                model_items=["rf_type_v001", "svm_type_v002", "xgb_type_v003"],
                result_rows=[
                    ["DJI_Mavic3", "73.5%"],
                    ["Autel_EVO", "12.4%"],
                    ["FPV_Racing", "8.7%"],
                    ["Unknown", "5.4%"],
                ],
            ),
            "无人机类型识别",
        )
        tabs.addTab(
            self._build_recognition_tab(
                mode_title="无人机个体指纹识别",
                mode_hint="按个体模型执行指纹识别与结果校验。",
                status_text="结果: mavic3_001",
                model_items=["iqcnn_v003", "cnn_lstm_v001"],
                result_rows=[
                    ["mavic3_001", "68.1%"],
                    ["mavic3_002", "17.3%"],
                    ["autel_003", "9.4%"],
                    ["unknown_id", "5.2%"],
                ],
            ),
            "无人机个体指纹识别",
        )
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def _build_recognition_tab(
        self,
        *,
        mode_title: str,
        mode_hint: str,
        status_text: str,
        model_items: list[str],
        result_rows: list[list[str]],
    ) -> QWidget:
        """Create one recognition workspace tab."""

        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        source_card = SectionCard(mode_title, mode_hint, compact=True)
        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        model_selector = QComboBox()
        model_selector.addItems(model_items)

        source_selector = QComboBox()
        source_selector.addItems(["数据库中已有样本", "外部 .cap 文件"])

        sample_selector = QComboBox()
        sample_selector.addItems(["sample_1101.npy", "sample_1103.npy", "demo_capture.cap"])

        form_layout.addRow("识别模型", model_selector)
        form_layout.addRow("样本来源", source_selector)
        form_layout.addRow("目标样本", sample_selector)

        button_row = QHBoxLayout()
        load_button = QPushButton("加载样本")
        run_button = QPushButton("开始识别")
        run_button.setObjectName("PrimaryButton")
        button_row.addWidget(load_button)
        button_row.addWidget(run_button)
        button_row.addStretch(1)

        source_card.body_layout.addLayout(form_layout)
        source_card.body_layout.addLayout(button_row)
        layout.addWidget(source_card, 2)

        result_card = SectionCard(
            "识别结果",
            "显示当前模型输出。",
            right_widget=StatusBadge(status_text, "success", size="sm"),
            compact=True,
        )

        probability_table = QTableWidget(len(result_rows), 2)
        probability_table.setHorizontalHeaderLabels(["目标", "置信度"])
        probability_table.horizontalHeader().setStretchLastSection(True)
        probability_table.verticalHeader().setVisible(False)
        probability_table.setAlternatingRowColors(True)
        configure_scrollable(probability_table)
        for row_index, row_data in enumerate(result_rows):
            for column, value in enumerate(row_data):
                probability_table.setItem(row_index, column, QTableWidgetItem(value))

        result_card.body_layout.addWidget(probability_table)
        layout.addWidget(result_card, 3)
        return tab
