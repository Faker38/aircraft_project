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
                mode_hint="基于当前已处理样本执行类型识别联调，后续接入真实模型后替换演示推理结果。",
                status_text="待识别",
                model_items=["rf_type_v001", "svm_type_v002", "xgb_type_v003"],
            ),
            "无人机类型识别",
        )
        tabs.addTab(
            self._build_recognition_tab(
                mode_key="individual",
                mode_title="无人机个体指纹识别",
                mode_hint="当前仅保留演示结构，用于联调个体识别流程，不作为正式评估结果。",
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

        self.sample_records = [record for record in records if record.source_type == "local_preprocess"]
        for mode_key in self.mode_controls:
            self._refresh_sample_selector(mode_key)

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

        sample_selector = QComboBox()
        sample_selector.addItems(["等待数据集页提供样本"])
        sample_selector.currentIndexChanged.connect(lambda *_: self._load_selected_sample(mode_key))

        form_layout.addRow("识别模型", model_selector)
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
            "显示当前预测结果、命中状态和样本来源信息。",
            right_widget=status_badge,
            compact=True,
        )

        probability_table = QTableWidget(0, 2)
        probability_table.setHorizontalHeaderLabels(["项目", "内容"])
        probability_table.horizontalHeader().setStretchLastSection(True)
        probability_table.verticalHeader().setVisible(False)
        probability_table.setAlternatingRowColors(True)
        configure_scrollable(probability_table)

        result_card.body_layout.addWidget(probability_table)
        layout.addWidget(result_card, 3)

        self.mode_controls[mode_key] = {
            "model_selector": model_selector,
            "sample_selector": sample_selector,
            "status_badge": status_badge,
            "probability_table": probability_table,
        }
        self._set_result_rows(mode_key, [["等待识别任务", "-"]], status_text=status_text)
        return tab

    def _refresh_sample_selector(self, mode_key: str) -> None:
        """Refresh one sample selector from the current processed sample list."""

        controls = self.mode_controls[mode_key]
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
            return

        self._set_result_rows(mode_key, [["当前无可用样本", "请先在数据集页整理样本"]], status_text="待识别")

    def _load_selected_sample(self, mode_key: str) -> None:
        """Update the status strip for the selected sample."""

        controls = self.mode_controls[mode_key]
        sample_selector = controls["sample_selector"]
        assert isinstance(sample_selector, QComboBox)

        record = sample_selector.currentData()
        if not isinstance(record, SampleRecord):
            self._set_result_rows(mode_key, [["当前无可用样本", "请先在数据集页整理样本"]], status_text="待识别")
            return

        label = record.label_type if mode_key == "type" else record.label_individual
        self._set_result_rows(
            mode_key,
            [
                ["当前样本", record.sample_id],
                ["当前标签", label or "未标注"],
                ["来源文件", record.raw_file_name],
                ["来源类型", record.source_label],
            ],
            status_text=f"已加载 {record.sample_id}",
        )

    def _run_recognition(self, mode_key: str) -> None:
        """Run one placeholder recognition flow for the selected sample."""

        controls = self.mode_controls[mode_key]
        model_selector = controls["model_selector"]
        sample_selector = controls["sample_selector"]
        assert isinstance(model_selector, QComboBox)
        assert isinstance(sample_selector, QComboBox)

        record = sample_selector.currentData()
        if not isinstance(record, SampleRecord):
            self._set_result_rows(mode_key, [["当前无可用样本", "请先在数据集页整理样本"]], status_text="待识别")
            return

        model_name = model_selector.currentText().split(" | ")[0]
        if mode_key == "type":
            current_label = record.label_type or "未标注"
            predicted_label, confidence_text = self._predict_type_result(record)
            is_match = "是" if current_label and current_label != "未标注" and predicted_label == current_label else "否"
            rows = [
                ["当前样本", record.sample_id],
                ["当前标签", self._display_label(current_label)],
                ["预测标签", self._display_label(predicted_label)],
                ["置信度", confidence_text],
                ["是否命中", is_match],
                ["来源文件", record.raw_file_name],
                ["来源类型", record.source_label],
                ["识别模型", model_name],
            ]
            self.latest_result_metric.set_value(self._display_label(predicted_label))
            self._set_result_rows(mode_key, rows, status_text=f"结果: {self._display_label(predicted_label)}")
        else:
            current_label = record.label_individual or "未标注"
            predicted_label, confidence_text = self._predict_individual_result(record)
            is_match = "是" if current_label and current_label != "未标注" and predicted_label == current_label else "否"
            rows = [
                ["当前样本", record.sample_id],
                ["当前标签", current_label],
                ["预测标签", predicted_label],
                ["置信度", confidence_text],
                ["是否命中", is_match],
                ["来源文件", record.raw_file_name],
                ["来源类型", record.source_label],
                ["备注", "当前为演示级个体识别结果，不作为正式评估依据。"],
            ]
            self.latest_result_metric.set_value(predicted_label)
            self._set_result_rows(mode_key, rows, status_text=f"结果: {predicted_label}")

    def _predict_type_result(self, record: SampleRecord) -> tuple[str, str]:
        """Return one stable placeholder prediction for type recognition."""

        if record.label_type:
            return record.label_type, "93.8%"
        return "Unknown", "64.0%"

    def _predict_individual_result(self, record: SampleRecord) -> tuple[str, str]:
        """Return one stable placeholder prediction for individual recognition."""

        if record.label_individual:
            return record.label_individual, "90.2%"
        return "unknown_id", "58.0%"

    def _display_label(self, label: str) -> str:
        """Return one UI-friendly label string."""

        return label.replace("_", " ")

    def _set_result_rows(self, mode_key: str, rows: list[list[str]], status_text: str) -> None:
        """Render one result table for a recognition mode."""

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
