"""无人机识别页：类型识别接入真实模型，个体识别保留演示态。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
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

from services import ModelServiceError, PredictionResult, SampleRecord, TrainedModelRecord, predict_type_sample
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class RecognitionPage(QWidget):
    """工作流页面：类型识别真实推理，个体识别演示显示。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化识别页面。"""

        super().__init__(parent)
        self.sample_records: list[SampleRecord] = []
        self.trained_models: list[TrainedModelRecord] = []
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
        self.type_model_metric = MetricCard("类型识别模型", "未生成", compact=True)
        self.individual_model_metric = MetricCard("指纹识别模型", "演示模式", accent_color="#7CB98B", compact=True)
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
                mode_hint="当前直接读取训练页输出的真实模型文件，对样本执行真实类型推理。",
                status_text="待识别",
            ),
            "无人机类型识别",
        )
        tabs.addTab(
            self._build_recognition_tab(
                mode_key="individual",
                mode_title="无人机个体指纹识别",
                mode_hint="当前保留演示结构，后续再接入真实个体识别模型。",
                status_text="演示模式",
            ),
            "无人机个体指纹识别",
        )
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        # 个体识别当前仍是演示模式，这里先填入一个固定说明项，避免下拉框为空。
        self._refresh_model_selector("individual")

    def set_sample_records(self, records: list[SampleRecord]) -> None:
        """刷新识别页的样本列表。"""

        self.sample_records = [record for record in records if record.source_type == "local_preprocess"]
        for mode_key in self.mode_controls:
            self._refresh_sample_selector(mode_key)

    def set_trained_models(self, records: list[TrainedModelRecord]) -> None:
        """刷新识别页可选的真实模型列表。"""

        self.trained_models = [record for record in records if record.task_type == "类型识别" and record.status == "训练完成"]
        self._refresh_model_selector("type")
        self._update_type_metric()

    def _build_recognition_tab(
        self,
        *,
        mode_key: str,
        mode_title: str,
        mode_hint: str,
        status_text: str,
    ) -> QWidget:
        """创建一个识别工作页签。"""

        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        source_card = SectionCard(mode_title, mode_hint, compact=True)
        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        model_selector = QComboBox()
        model_selector.currentIndexChanged.connect(lambda *_: self._on_model_changed(mode_key))

        sample_selector = QComboBox()
        sample_selector.setMinimumContentsLength(28)
        sample_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        sample_selector.view().setTextElideMode(Qt.TextElideMode.ElideMiddle)
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
            "显示当前样本标签、预测结果、置信度和模型信息。",
            right_widget=status_badge,
            compact=True,
        )

        result_table = QTableWidget(0, 2)
        result_table.setHorizontalHeaderLabels(["项目", "内容"])
        result_table.horizontalHeader().setStretchLastSection(True)
        result_table.verticalHeader().setVisible(False)
        result_table.setAlternatingRowColors(True)
        configure_scrollable(result_table)

        result_card.body_layout.addWidget(result_table)
        layout.addWidget(result_card, 3)

        self.mode_controls[mode_key] = {
            "model_selector": model_selector,
            "sample_selector": sample_selector,
            "status_badge": status_badge,
            "result_table": result_table,
        }
        self._set_result_rows(mode_key, [["等待识别任务", "-"]], status_text=status_text)
        return tab

    def _refresh_model_selector(self, mode_key: str) -> None:
        """刷新一个页签下的模型下拉框。"""

        controls = self.mode_controls.get(mode_key)
        if not controls:
            return

        model_selector = controls["model_selector"]
        assert isinstance(model_selector, QComboBox)

        current_model_id = (
            model_selector.currentData().model_id
            if isinstance(model_selector.currentData(), TrainedModelRecord)
            else None
        )

        model_selector.blockSignals(True)
        model_selector.clear()
        if mode_key == "type":
            for record in self.trained_models:
                display_text = f"{record.model_id} | {record.dataset_version_id} | {record.accuracy_text}"
                model_selector.addItem(display_text, record)
        else:
            model_selector.addItem("演示模式 | 个体识别待接入", "demo")
        model_selector.blockSignals(False)

        if model_selector.count() == 0:
            self._set_result_rows(mode_key, [["当前无可用模型", "请先在训练页生成类型识别模型"]], status_text="待模型")
            return

        target_index = 0
        if current_model_id is not None:
            for index in range(model_selector.count()):
                record = model_selector.itemData(index)
                if isinstance(record, TrainedModelRecord) and record.model_id == current_model_id:
                    target_index = index
                    break
        model_selector.setCurrentIndex(target_index)
        self._on_model_changed(mode_key)

    def _refresh_sample_selector(self, mode_key: str) -> None:
        """刷新一个页签下的样本下拉框。"""

        controls = self.mode_controls[mode_key]
        sample_selector = controls["sample_selector"]
        assert isinstance(sample_selector, QComboBox)

        current_sample_id = (
            sample_selector.currentData().sample_id
            if isinstance(sample_selector.currentData(), SampleRecord)
            else None
        )

        records = self._records_for_mode(mode_key)
        sample_selector.blockSignals(True)
        sample_selector.clear()
        for record in records:
            label_text = record.label_type if mode_key == "type" else record.label_individual
            display_text = (
                f"{self._compact_sample_id(record.sample_id)} | {self._display_label(label_text or '未标注')} | "
                f"{self._compact_source_name(record.raw_file_name)}"
            )
            sample_selector.addItem(display_text, record)
            tooltip_text = (
                f"样本编号：{record.sample_id}\n"
                f"当前标签：{self._display_label(label_text or '未标注')}\n"
                f"来源文件：{record.raw_file_name}\n"
                f"来源路径：{record.raw_file_path}"
            )
            sample_selector.setItemData(sample_selector.count() - 1, tooltip_text, Qt.ItemDataRole.ToolTipRole)
        sample_selector.blockSignals(False)

        if records:
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

        empty_hint = "请先在数据集页补齐已标注样本" if mode_key == "type" else "个体识别样本暂未准备"
        self._set_result_rows(mode_key, [["当前无可用样本", empty_hint]], status_text="待识别")

    def _records_for_mode(self, mode_key: str) -> list[SampleRecord]:
        """按页签模式过滤更适合演示的样本。"""

        if mode_key == "type":
            labeled_records = [record for record in self.sample_records if record.label_type]
            return labeled_records or list(self.sample_records)
        labeled_records = [record for record in self.sample_records if record.label_individual]
        return labeled_records or list(self.sample_records)

    def _on_model_changed(self, mode_key: str) -> None:
        """当用户切换模型时刷新顶部状态。"""

        controls = self.mode_controls.get(mode_key)
        if not controls:
            return

        model_selector = controls["model_selector"]
        assert isinstance(model_selector, QComboBox)

        if mode_key == "type":
            record = model_selector.currentData()
            if isinstance(record, TrainedModelRecord):
                self.type_model_metric.set_value(record.model_id)
            else:
                self.type_model_metric.set_value("未生成")
        else:
            self.individual_model_metric.set_value("演示模式")

        self._load_selected_sample(mode_key)

    def _update_type_metric(self) -> None:
        """根据当前模型列表刷新顶部类型模型指标。"""

        if self.trained_models:
            self.type_model_metric.set_value(self.trained_models[0].model_id)
        else:
            self.type_model_metric.set_value("未生成")

    def _load_selected_sample(self, mode_key: str) -> None:
        """加载当前选中的样本摘要。"""

        controls = self.mode_controls[mode_key]
        sample_selector = controls["sample_selector"]
        assert isinstance(sample_selector, QComboBox)

        record = sample_selector.currentData()
        if not isinstance(record, SampleRecord):
            waiting_text = "请先在训练页生成模型" if mode_key == "type" else "当前为演示模式"
            sample_selector.setToolTip("")
            self._set_result_rows(mode_key, [["当前无可用样本", waiting_text]], status_text="待识别")
            return

        current_label = record.label_type if mode_key == "type" else record.label_individual
        sample_selector.setToolTip(
            f"样本编号：{record.sample_id}\n来源文件：{record.raw_file_name}\n来源路径：{record.raw_file_path}"
        )
        self._set_result_rows(
            mode_key,
            [
                ["当前样本", record.sample_id],
                ["当前标签", self._display_label(current_label or "未标注")],
                ["来源文件", record.raw_file_name],
                ["来源路径", record.raw_file_path],
                ["来源类型", record.source_label],
                ["样本路径", record.sample_file_path],
            ],
            status_text=f"已加载 {record.sample_id}",
        )

    def _run_recognition(self, mode_key: str) -> None:
        """执行一次识别任务。"""

        controls = self.mode_controls[mode_key]
        model_selector = controls["model_selector"]
        sample_selector = controls["sample_selector"]
        assert isinstance(model_selector, QComboBox)
        assert isinstance(sample_selector, QComboBox)

        record = sample_selector.currentData()
        if not isinstance(record, SampleRecord):
            self._set_result_rows(mode_key, [["当前无可用样本", "请先在数据集页整理样本"]], status_text="待识别")
            return

        if mode_key == "individual":
            current_label = record.label_individual or "未标注"
            predicted_label = current_label if current_label != "未标注" else "unknown_id"
            rows = [
                ["当前样本", record.sample_id],
                ["当前标签", current_label],
                ["预测标签", predicted_label],
                ["置信度", "演示模式"],
                ["是否命中", "是" if current_label != "未标注" else "否"],
                ["来源文件", record.raw_file_name],
                ["来源路径", record.raw_file_path],
                ["备注", "当前为演示级个体识别结果，不作为正式评估依据。"],
            ]
            self.latest_result_metric.set_value(predicted_label)
            self._set_result_rows(mode_key, rows, status_text=f"结果: {predicted_label}")
            return

        model_record = model_selector.currentData()
        if not isinstance(model_record, TrainedModelRecord):
            self._set_result_rows(mode_key, [["当前无可用模型", "请先在训练页生成类型识别模型"]], status_text="待模型")
            return

        current_label = record.label_type or "未标注"
        if current_label != "未标注" and current_label not in model_record.label_space:
            self._set_result_rows(
                mode_key,
                [
                    ["当前样本", record.sample_id],
                    ["当前标签", self._display_label(current_label)],
                    ["当前模型", model_record.model_id],
                    ["提示", "该样本标签不在当前模型标签空间内，请切换匹配的数据集模型。"],
                ],
                status_text="标签不匹配",
            )
            return

        try:
            result = predict_type_sample(model_record.model_id, record.sample_file_path)
        except ModelServiceError as exc:
            self._set_result_rows(
                mode_key,
                [
                    ["当前样本", record.sample_id],
                    ["当前模型", model_record.model_id],
                    ["错误信息", str(exc)],
                ],
                status_text="识别失败",
            )
            return

        self._apply_type_prediction(record, result)

    def _apply_type_prediction(self, sample_record: SampleRecord, result: PredictionResult) -> None:
        """把真实类型识别结果渲染到页面。"""

        current_label = sample_record.label_type or "未标注"
        predicted_label = result.predicted_label
        is_match = "是" if current_label != "未标注" and predicted_label == current_label else "否"
        confidence_text = f"{result.confidence * 100:.2f}%"

        rows = [
            ["当前样本", sample_record.sample_id],
            ["当前标签", self._display_label(current_label)],
            ["预测标签", self._display_label(predicted_label)],
            ["置信度", confidence_text],
            ["是否命中", is_match],
            ["来源文件", sample_record.raw_file_name],
            ["来源路径", sample_record.raw_file_path],
            ["来源类型", sample_record.source_label],
            ["识别模型", result.model_record.model_id],
            ["标签空间", " / ".join(self._display_label(label) for label in result.model_record.label_space)],
        ]
        self.latest_result_metric.set_value(self._display_label(predicted_label))
        self._set_result_rows("type", rows, status_text=f"结果: {self._display_label(predicted_label)}")

    def _set_result_rows(self, mode_key: str, rows: list[list[str]], status_text: str) -> None:
        """刷新一个页签下的结果表。"""

        controls = self.mode_controls[mode_key]
        status_badge = controls["status_badge"]
        result_table = controls["result_table"]
        assert isinstance(status_badge, StatusBadge)
        assert isinstance(result_table, QTableWidget)

        level = "success" if status_text.startswith("结果") else ("danger" if "失败" in status_text else "info")
        status_badge.set_status(status_text, level, size="sm")
        result_table.setRowCount(len(rows))
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                item = result_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    result_table.setItem(row_index, column, item)
                item.setText(value)

    def _display_label(self, label: str) -> str:
        """把标签转换为适合界面展示的文本。"""

        return label.replace("_", " ")

    def _compact_source_name(self, file_name: str) -> str:
        """Return a compact file name for combo-box display."""

        if len(file_name) <= 28:
            return file_name
        return f"{file_name[:12]}...{file_name[-12:]}"

    def _compact_sample_id(self, sample_id: str) -> str:
        """Return a compact sample ID for combo-box display."""

        if len(sample_id) <= 26:
            return sample_id
        return f"{sample_id[:10]}...{sample_id[-10:]}"
