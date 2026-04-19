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

from services import SampleRecord
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class RecognitionPage(QWidget):
    """Workflow page for drone type and fingerprint recognition."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the recognition page."""

        super().__init__(parent)
        self.sample_records: list[SampleRecord] = []
        self.mode_controls: dict[str, dict[str, object]] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.type_model_metric = MetricCard("类型识别模型", "rf_type_v001", compact=True)
        self.individual_model_metric = MetricCard("指纹识别模型", "iqcnn_v003", accent_color="#7CB98B", compact=True)
        self.latest_result_metric = MetricCard("最近识别结果", "待识别", accent_color="#C59A63", compact=True)
        metrics_row.addWidget(self.type_model_metric)
        metrics_row.addWidget(self.individual_model_metric)
        metrics_row.addWidget(self.latest_result_metric)
        content_layout.addLayout(metrics_row)

        tabs = QTabWidget()
        tabs.addTab(
            self._build_recognition_tab(
                mode_key="type",
                mode_title="无人机类型识别",
                mode_hint="从统一样本记录中选择样本，执行类型识别演示流程。",
                status_text="待识别",
                model_items=["rf_type_v001", "svm_type_v002", "xgb_type_v003"],
            ),
            "无人机类型识别",
        )
        tabs.addTab(
            self._build_recognition_tab(
                mode_key="individual",
                mode_title="无人机个体指纹识别",
                mode_hint="从统一样本记录中选择样本，执行个体指纹识别演示流程。",
                status_text="待识别",
                model_items=["iqcnn_v003", "cnn_lstm_v001"],
            ),
            "无人机个体指纹识别",
        )
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def set_sample_records(self, records: list[SampleRecord]) -> None:
        """Refresh recognition sample selectors from the dataset page."""

        self.sample_records = list(records)
        for mode_key, controls in self.mode_controls.items():
            sample_selector = controls["sample_selector"]
            assert isinstance(sample_selector, QComboBox)
            current_sample_id = sample_selector.currentData().sample_id if isinstance(sample_selector.currentData(), SampleRecord) else None

            sample_selector.blockSignals(True)
            sample_selector.clear()
            for record in self.sample_records:
                display_text = f"{record.sample_id} | {record.label_type or '未标注'} | {record.raw_file_name}"
                sample_selector.addItem(display_text, record)
            sample_selector.blockSignals(False)

            if self.sample_records:
                target_index = 0
                if current_sample_id is not None:
                    for index in range(sample_selector.count()):
                        sample_record = sample_selector.itemData(index)
                        if isinstance(sample_record, SampleRecord) and sample_record.sample_id == current_sample_id:
                            target_index = index
                            break
                sample_selector.setCurrentIndex(target_index)
                self._load_selected_sample(mode_key)
            else:
                self._set_result_rows(mode_key, [["无可用样本", "-"]], status_text="待识别")

    def _build_recognition_tab(
        self,
        *,
        mode_key: str,
        mode_title: str,
        mode_hint: str,
        status_text: str,
        model_items: list[str],
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
        source_selector.addItems(["统一样本记录", "公开数据导入", "本地预处理输出"])

        sample_selector = QComboBox()
        sample_selector.addItems(["等待数据集页提供样本"])

        form_layout.addRow("识别模型", model_selector)
        form_layout.addRow("样本来源", source_selector)
        form_layout.addRow("目标样本", sample_selector)

        button_row = QHBoxLayout()
        load_button = QPushButton("加载样本")
        load_button.clicked.connect(lambda: self._load_selected_sample(mode_key))
        run_button = QPushButton("开始识别")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(lambda: self._run_recognition(mode_key))
        button_row.addWidget(load_button)
        button_row.addWidget(run_button)
        button_row.addStretch(1)

        source_card.body_layout.addLayout(form_layout)
        source_card.body_layout.addLayout(button_row)
        layout.addWidget(source_card, 2)

        status_badge = StatusBadge(status_text, "info", size="sm")
        result_card = SectionCard(
            "识别结果",
            "显示当前模型输出和统一样本记录中的标签信息。",
            right_widget=status_badge,
            compact=True,
        )

        probability_table = QTableWidget(0, 2)
        probability_table.setHorizontalHeaderLabels(["目标", "置信度"])
        probability_table.horizontalHeader().setStretchLastSection(True)
        probability_table.verticalHeader().setVisible(False)
        probability_table.setAlternatingRowColors(True)
        configure_scrollable(probability_table)

        result_card.body_layout.addWidget(probability_table)
        layout.addWidget(result_card, 3)

        self.mode_controls[mode_key] = {
            "sample_selector": sample_selector,
            "status_badge": status_badge,
            "probability_table": probability_table,
        }
        self._set_result_rows(mode_key, [["等待识别任务", "-"]], status_text=status_text)
        return tab

    def _load_selected_sample(self, mode_key: str) -> None:
        """Update the status strip for the selected sample."""

        controls = self.mode_controls[mode_key]
        sample_selector = controls["sample_selector"]
        assert isinstance(sample_selector, QComboBox)

        record = sample_selector.currentData()
        if not isinstance(record, SampleRecord):
            self._set_result_rows(mode_key, [["无可用样本", "-"]], status_text="待识别")
            return

        label = record.label_type if mode_key == "type" else record.label_individual
        self._set_result_rows(
            mode_key,
            [
                ["样本编号", record.sample_id],
                ["当前标签", label or "未标注"],
            ],
            status_text=f"已加载 {record.sample_id}",
        )

    def _run_recognition(self, mode_key: str) -> None:
        """Run one placeholder recognition flow for the selected sample."""

        controls = self.mode_controls[mode_key]
        sample_selector = controls["sample_selector"]
        assert isinstance(sample_selector, QComboBox)

        record = sample_selector.currentData()
        if not isinstance(record, SampleRecord):
            self._set_result_rows(mode_key, [["无可用样本", "-"]], status_text="待识别")
            return

        if mode_key == "type":
            target_label = record.label_type or "Unknown"
            rows = [
                [target_label, "92.4%"],
                ["Unknown", "7.6%"],
            ]
            self.latest_result_metric.set_value(target_label)
        else:
            target_label = record.label_individual or "unknown_id"
            rows = [
                [target_label, "89.1%"],
                ["unknown_id", "10.9%"],
            ]
            self.latest_result_metric.set_value(target_label)

        self._set_result_rows(mode_key, rows, status_text=f"结果: {target_label}")

    def _set_result_rows(self, mode_key: str, rows: list[list[str]], status_text: str) -> None:
        """Render one probability/result table for a recognition mode."""

        controls = self.mode_controls[mode_key]
        status_badge = controls["status_badge"]
        probability_table = controls["probability_table"]
        assert isinstance(status_badge, StatusBadge)
        assert isinstance(probability_table, QTableWidget)

        level = "success" if status_text.startswith("结果") else "info"
        status_badge.set_status(status_text, level, size="sm")
        probability_table.setRowCount(len(rows))
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                item = probability_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    probability_table.setItem(row_index, column, item)
                item.setText(value)
