"""无人机识别页：类型识别接入真实模型，个体识别保留演示态。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services import (
    ModelServiceError,
    PredictionResult,
    SampleRecord,
    TrainedModelRecord,
    get_dataset_version_detail,
    predict_type_sample,
)
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, VisualHeroCard, configure_scrollable


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

        content_layout.addWidget(self._build_visual_banner())
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.type_model_metric = MetricCard("类型识别模型", "未生成", compact=True)
        self.individual_model_metric = MetricCard("指纹识别模型", "待接入", accent_color="#7CB98B", compact=True)
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
                mode_hint="当前保留个体指纹识别入口，真实个体模型与推理服务待接入。",
                status_text="待接入",
            ),
            "无人机个体指纹识别",
        )
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        # 个体识别当前保留入口，这里先填入固定说明项，避免下拉框为空。
        self._refresh_model_selector("individual")

    def _build_visual_banner(self) -> VisualHeroCard:
        """Create the recognition-page visual banner."""

        return VisualHeroCard(
            "无人机识别 · 实时判别视图",
            "当前类型识别页直接读取训练页输出的真实模型进行推理；个体指纹识别入口已保留，真实服务待接入。",
            background_name="recognition_header_bg.svg",
            chips=["真实模型推理", "标签空间校验", "结果可追溯"],
            ornament_name="decor_lock_target_c.svg",
            height=170,
        )

    def set_sample_records(self, records: list[SampleRecord]) -> None:
        """刷新识别页的样本列表。"""

        self.sample_records = [
            record for record in records if record.source_type in {"local_preprocess", "usrp_preprocess"}
        ]
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
        source_card.setMinimumWidth(430)
        source_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        model_selector = QComboBox()
        model_selector.setMinimumContentsLength(34)
        model_selector.setMinimumWidth(420)
        model_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        model_selector.view().setTextElideMode(Qt.TextElideMode.ElideMiddle)
        model_selector.currentIndexChanged.connect(lambda *_: self._on_model_changed(mode_key))

        sample_selector = QComboBox()
        sample_selector.setMinimumContentsLength(34)
        sample_selector.setMinimumWidth(420)
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
        layout.addWidget(source_card, 1)

        status_badge = StatusBadge(status_text, "info", size="sm")
        result_card = SectionCard(
            "识别结果",
            "显示当前样本标签、预测结果、置信度和模型信息。",
            right_widget=status_badge,
            compact=True,
        )
        result_card.setMinimumWidth(450)
        result_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        result_table = QTableWidget(0, 2)
        result_table.setHorizontalHeaderLabels(["项目", "内容"])
        result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        result_table.verticalHeader().setVisible(False)
        result_table.setAlternatingRowColors(True)
        result_table.setWordWrap(False)
        result_table.setMinimumHeight(260)
        configure_scrollable(result_table)

        result_card.body_layout.addWidget(result_table)
        layout.addWidget(result_card, 1)

        self.mode_controls[mode_key] = {
            "model_selector": model_selector,
            "sample_selector": sample_selector,
            "run_button": run_button,
            "load_button": load_button,
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
                version_hint = " | 来源版本已删" if self._is_model_version_deleted(record) else ""
                display_text = f"{record.model_id} | {record.dataset_version_id} | {record.accuracy_text}{version_hint}"
                model_selector.addItem(display_text, record)
        else:
            model_selector.addItem("保留功能 | 真实个体模型待接入", "pending")
        model_selector.blockSignals(False)

        if model_selector.count() == 0:
            run_button = controls["run_button"]
            load_button = controls["load_button"]
            assert isinstance(run_button, QPushButton)
            assert isinstance(load_button, QPushButton)
            run_button.setEnabled(False)
            load_button.setEnabled(False)
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
        run_button = controls["run_button"]
        load_button = controls["load_button"]
        assert isinstance(run_button, QPushButton)
        assert isinstance(load_button, QPushButton)
        run_button.setEnabled(True)
        load_button.setEnabled(True)
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

        model_record = self._selected_type_model_record() if mode_key == "type" else None
        records = self._records_for_mode(mode_key, model_record=model_record)
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

        empty_hint = (
            "当前模型无匹配样本，请在数据集页确认标签或切换模型"
            if mode_key == "type" and model_record is not None
            else ("请先在数据集页补齐已标注样本" if mode_key == "type" else "个体识别样本暂未准备")
        )
        run_button = controls["run_button"]
        load_button = controls["load_button"]
        assert isinstance(run_button, QPushButton)
        assert isinstance(load_button, QPushButton)
        run_button.setEnabled(False)
        load_button.setEnabled(False)
        self._set_result_rows(mode_key, [["当前无可用样本", empty_hint]], status_text="待识别")

    def _records_for_mode(
        self,
        mode_key: str,
        *,
        model_record: TrainedModelRecord | None = None,
    ) -> list[SampleRecord]:
        """按页签模式过滤更适合演示的样本。"""

        if mode_key == "type":
            labeled_records = [record for record in self.sample_records if record.label_type]
            if model_record is not None:
                label_space = set(model_record.label_space)
                return [record for record in labeled_records if record.label_type in label_space]
            return labeled_records or list(self.sample_records)
        labeled_records = [record for record in self.sample_records if record.label_individual]
        return labeled_records or list(self.sample_records)

    def _selected_type_model_record(self) -> TrainedModelRecord | None:
        """Return the selected type model record when one is available."""

        controls = self.mode_controls.get("type")
        if not controls:
            return None
        model_selector = controls["model_selector"]
        assert isinstance(model_selector, QComboBox)
        record = model_selector.currentData()
        return record if isinstance(record, TrainedModelRecord) else None

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
            self.individual_model_metric.set_value("待接入")

        if mode_key == "type":
            self._refresh_sample_selector(mode_key)
        else:
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
            waiting_text = "请先在训练页生成模型" if mode_key == "type" else "个体指纹识别入口已保留，真实服务待接入"
            sample_selector.setToolTip("")
            self._set_result_rows(mode_key, [["当前无可用样本", waiting_text]], status_text="待识别")
            return

        run_button = controls["run_button"]
        load_button = controls["load_button"]
        assert isinstance(run_button, QPushButton)
        assert isinstance(load_button, QPushButton)
        load_button.setEnabled(True)
        model_record = None
        if mode_key == "type":
            model_record = self._selected_type_model_record()
            if isinstance(model_record, TrainedModelRecord) and record.label_type not in model_record.label_space:
                self._refresh_sample_selector(mode_key)
                return
            run_button.setEnabled(isinstance(model_record, TrainedModelRecord))
        else:
            run_button.setEnabled(True)

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
                [
                    "来源版本状态",
                    self._model_version_status_text(model_record)
                    if mode_key == "type" and isinstance(model_record, TrainedModelRecord)
                    else "-",
                ],
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
            rows = [
                ["当前样本", record.sample_id],
                ["当前标签", current_label],
                ["来源文件", record.raw_file_name],
                ["来源路径", record.raw_file_path],
                ["当前状态", "个体指纹识别入口已保留，真实模型与推理服务待接入。"],
            ]
            self.latest_result_metric.set_value("个体待接入")
            self._set_result_rows(mode_key, rows, status_text="待接入")
            return

        model_record = model_selector.currentData()
        if not isinstance(model_record, TrainedModelRecord):
            run_button = controls["run_button"]
            assert isinstance(run_button, QPushButton)
            run_button.setEnabled(False)
            self._set_result_rows(mode_key, [["当前无可用模型", "请先在训练页生成类型识别模型"]], status_text="待模型")
            return

        current_label = record.label_type or "未标注"
        if current_label != "未标注" and current_label not in model_record.label_space:
            self._refresh_sample_selector(mode_key)
            self._set_result_rows(
                mode_key,
                [
                    ["当前样本", record.sample_id],
                    ["当前标签", self._display_label(current_label)],
                    ["当前模型", model_record.model_id],
                    ["提示", "已按当前模型标签空间重新筛选样本；请使用匹配样本或切换模型。"],
                ],
                status_text="待识别",
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
            ["来源版本", result.model_record.dataset_version_id],
            ["来源版本状态", self._model_version_status_text(result.model_record)],
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
        status_badge.set_status(self._compact_middle(status_text, 28), level, size="sm")
        status_badge.setToolTip(status_text)
        result_table.setRowCount(len(rows))
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                item = result_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    result_table.setItem(row_index, column, item)
                item.setToolTip(value)
                item.setText(value if column == 0 else self._compact_middle(value, 80))

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

    def _compact_middle(self, text: str, limit: int) -> str:
        """Return text with the middle elided for stable tables and badges."""

        if len(text) <= limit:
            return text
        keep = max((limit - 3) // 2, 4)
        tail = max(limit - 3 - keep, 4)
        return f"{text[:keep]}...{text[-tail:]}"

    def _is_model_version_deleted(self, record: TrainedModelRecord) -> bool:
        """判断模型来源的数据集版本当前是否已删除。"""

        return get_dataset_version_detail(record.dataset_version_id) is None

    def _model_version_status_text(self, record: TrainedModelRecord) -> str:
        """返回模型来源版本的状态文本。"""

        return "来源版本已删除" if self._is_model_version_deleted(record) else "正常"
