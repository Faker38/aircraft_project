"""无人机三阶段识别页：第一个入口承载真实三阶段推理，第二个入口保留待接入。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
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
    ThreeStageRuntimeSelection,
    get_dataset_version_detail,
    predict_three_stage_sample,
    predict_type_sample,
    resolve_three_stage_warmup_sample,
    set_three_stage_runtime_selection,
    validate_three_stage_selection,
    warmup_three_stage_runtime,
)
from ui.recognition_run_worker import RecognitionRunWorker
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, VisualHeroCard, configure_scrollable
from config import EXPORTS_DIR


class RecognitionPage(QWidget):
    """工作流页面：三阶段识别真实推理，个体识别入口保留待接入。"""

    sample_refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化识别页面。"""

        super().__init__(parent)
        self.sample_records: list[SampleRecord] = []
        self.trained_models: list[TrainedModelRecord] = []
        self.mode_controls: dict[str, dict[str, object]] = {}
        self.local_mat_path = ""
        self.local_mat_dir = ""
        self.local_binary_model_path = str(Path(r"D:\pythonProject10\success_three_stage\twin_classify_model.pth"))
        self.local_type_model_path = str(Path(r"D:\pythonProject10\success_three_stage\type_best_model.pth"))
        self.local_type_meta_path = str(Path(r"D:\pythonProject10\success_three_stage\type_best_model.meta.json"))
        self.local_individual_model_path = str(Path(r"D:\pythonProject10\success_three_stage\individual_legacy_best_model.pth"))
        self.local_individual_meta_path = ""
        self._recognition_thread: QThread | None = None
        self._recognition_worker: RecognitionRunWorker | None = None
        self._active_recognition_mode: str | None = None

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
        self.type_model_metric = MetricCard("三阶段识别模型", "未生成", compact=True)
        self.individual_model_metric = MetricCard("个体识别模型", "待接入", accent_color="#7CB98B", compact=True)
        self.latest_result_metric = MetricCard("最近识别结果", "待识别", accent_color="#C59A63", compact=True)
        metrics_row.addWidget(self.type_model_metric)
        metrics_row.addWidget(self.individual_model_metric)
        metrics_row.addWidget(self.latest_result_metric)
        content_layout.addLayout(metrics_row)

        tabs = QTabWidget()
        tabs.addTab(
            self._build_recognition_tab(
                mode_key="type",
                mode_title="三阶段识别",
                mode_hint="当前直接读取本地三阶段权重，对样本执行真实推理。",
                status_text="待识别",
            ),
            "三阶段识别",
        )
        tabs.addTab(
            self._build_recognition_tab(
                mode_key="individual",
                mode_title="个体识别（待接入）",
                mode_hint="当前保留个体指纹识别入口，真实个体模型与推理服务待接入。",
                status_text="待接入",
            ),
            "个体识别（待接入）",
        )
        content_layout.addWidget(tabs)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        # 个体识别当前保留入口，这里先填入固定说明项，避免下拉框为空。
        self._refresh_model_selector("individual")

    def _build_visual_banner(self) -> VisualHeroCard:
        """Create the recognition-page visual banner."""

        return VisualHeroCard(
            "三阶段识别 · 实时判别视图",
            "第一个页承载已接通的三阶段推理；第二个页仅保留入口，个体模型待接入。",
            background_name="recognition_header_bg.svg",
            chips=["三阶段推理", "本地 MAT 测试", "个体待接入"],
            ornament_name="decor_lock_target_c.svg",
            height=170,
        )

    def set_sample_records(self, records: list[SampleRecord]) -> None:
        """刷新识别页的样本列表。"""

        self.sample_records = [
            record for record in records if record.source_type in {"local_preprocess", "usrp_preprocess", "manual_mat"}
        ]
        for mode_key in self.mode_controls:
            self._refresh_sample_selector(mode_key)

    def _refresh_and_load_sample(self, mode_key: str) -> None:
        """请求上游刷新数据库样本，然后加载当前选择。"""

        self.sample_refresh_requested.emit()
        self._refresh_sample_selector(mode_key)
        self._load_selected_sample(mode_key)

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
        if mode_key == "type":
            local_mat_input = QLineEdit(self.local_mat_path)
            local_mat_input.setPlaceholderText("可选：直接选择本地 .mat 文件做三阶段推理测试")
            local_mat_input.textChanged.connect(self._on_local_mat_changed)
            local_mat_row = QHBoxLayout()
            local_mat_row.setSpacing(8)
            local_mat_row.addWidget(local_mat_input)
            local_mat_button = QPushButton("选择 MAT")
            local_mat_button.clicked.connect(self._choose_local_mat_file)
            local_mat_row.addWidget(local_mat_button)
            form_layout.addRow("本地 MAT", local_mat_row)

            local_mat_dir_input = QLineEdit(self.local_mat_dir)
            local_mat_dir_input.setPlaceholderText("可选：选择一个 MAT 目录做批量测试")
            local_mat_dir_input.textChanged.connect(self._on_local_mat_dir_changed)
            local_mat_dir_row = QHBoxLayout()
            local_mat_dir_row.setSpacing(8)
            local_mat_dir_row.addWidget(local_mat_dir_input)
            local_mat_dir_button = QPushButton("选择 MAT 目录")
            local_mat_dir_button.clicked.connect(self._choose_local_mat_dir)
            local_mat_dir_row.addWidget(local_mat_dir_button)
            form_layout.addRow("MAT 目录", local_mat_dir_row)

            binary_model_input = QLineEdit(self.local_binary_model_path)
            binary_model_input.setPlaceholderText("二分类模型 .pth")
            binary_model_input.textChanged.connect(lambda value: setattr(self, "local_binary_model_path", value.strip()))
            binary_model_row = QHBoxLayout()
            binary_model_row.setSpacing(8)
            binary_model_row.addWidget(binary_model_input)
            binary_model_button = QPushButton("选择 .pth")
            binary_model_button.clicked.connect(lambda: self._choose_local_file("local_binary_model_input", "local_binary_model_path", "PTH Files (*.pth)"))
            binary_model_row.addWidget(binary_model_button)
            form_layout.addRow("二分类权重", binary_model_row)

            type_model_input = QLineEdit(self.local_type_model_path)
            type_model_input.setPlaceholderText("类型模型 .pth")
            type_model_input.textChanged.connect(lambda value: setattr(self, "local_type_model_path", value.strip()))
            type_model_row = QHBoxLayout()
            type_model_row.setSpacing(8)
            type_model_row.addWidget(type_model_input)
            type_model_button = QPushButton("选择 .pth")
            type_model_button.clicked.connect(lambda: self._choose_local_file("local_type_model_input", "local_type_model_path", "PTH Files (*.pth)"))
            type_model_row.addWidget(type_model_button)
            form_layout.addRow("类型权重", type_model_row)

            type_meta_input = QLineEdit(self.local_type_meta_path)
            type_meta_input.setPlaceholderText("类型模型 meta.json")
            type_meta_input.textChanged.connect(lambda value: setattr(self, "local_type_meta_path", value.strip()))
            type_meta_row = QHBoxLayout()
            type_meta_row.setSpacing(8)
            type_meta_row.addWidget(type_meta_input)
            type_meta_button = QPushButton("选择 .json")
            type_meta_button.clicked.connect(lambda: self._choose_local_file("local_type_meta_input", "local_type_meta_path", "JSON Files (*.json)"))
            type_meta_row.addWidget(type_meta_button)
            form_layout.addRow("类型 Meta", type_meta_row)

            individual_model_input = QLineEdit(self.local_individual_model_path)
            individual_model_input.setPlaceholderText("个体模型 .pth")
            individual_model_input.textChanged.connect(lambda value: setattr(self, "local_individual_model_path", value.strip()))
            individual_model_row = QHBoxLayout()
            individual_model_row.setSpacing(8)
            individual_model_row.addWidget(individual_model_input)
            individual_model_button = QPushButton("选择 .pth")
            individual_model_button.clicked.connect(lambda: self._choose_local_file("local_individual_model_input", "local_individual_model_path", "PTH Files (*.pth)"))
            individual_model_row.addWidget(individual_model_button)
            form_layout.addRow("个体权重", individual_model_row)

            individual_meta_input = QLineEdit(self.local_individual_meta_path)
            individual_meta_input.setPlaceholderText("个体模型 meta.json，可留空")
            individual_meta_input.textChanged.connect(lambda value: setattr(self, "local_individual_meta_path", value.strip()))
            individual_meta_row = QHBoxLayout()
            individual_meta_row.setSpacing(8)
            individual_meta_row.addWidget(individual_meta_input)
            individual_meta_button = QPushButton("选择 .json")
            individual_meta_button.clicked.connect(lambda: self._choose_local_file("local_individual_meta_input", "local_individual_meta_path", "JSON Files (*.json)"))
            individual_meta_row.addWidget(individual_meta_button)
            form_layout.addRow("个体 Meta", individual_meta_row)

        button_row = QHBoxLayout()
        load_button = QPushButton("刷新并加载样本")
        load_button.clicked.connect(lambda: self._refresh_and_load_sample(mode_key))
        run_button = QPushButton("开始识别")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(lambda: self._run_recognition(mode_key))
        button_row.addWidget(load_button)
        button_row.addWidget(run_button)
        if mode_key == "type":
            apply_button = QPushButton("应用并预热模型")
            apply_button.clicked.connect(self._apply_and_warmup_three_stage_models)
            button_row.addWidget(apply_button)
            batch_button = QPushButton("批量测试 MAT 目录")
            batch_button.clicked.connect(self._run_local_mat_batch_test)
            button_row.addWidget(batch_button)
        button_row.addStretch(1)

        source_card.body_layout.addLayout(form_layout)
        source_card.body_layout.addLayout(button_row)
        layout.addWidget(source_card, 1)

        status_badge = StatusBadge(status_text, "info", size="sm")
        result_card = SectionCard(
            "识别结果",
            "显示当前样本标签、预测结果、预测置信度、适用域和模型信息。",
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
        if mode_key == "type":
            self.mode_controls[mode_key]["local_mat_input"] = local_mat_input
            self.mode_controls[mode_key]["local_mat_dir_input"] = local_mat_dir_input
            self.mode_controls[mode_key]["local_binary_model_input"] = binary_model_input
            self.mode_controls[mode_key]["local_type_model_input"] = type_model_input
            self.mode_controls[mode_key]["local_type_meta_input"] = type_meta_input
            self.mode_controls[mode_key]["local_individual_model_input"] = individual_model_input
            self.mode_controls[mode_key]["local_individual_meta_input"] = individual_meta_input
            self.mode_controls[mode_key]["apply_button"] = apply_button
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
            else model_selector.currentData()
        )

        model_selector.blockSignals(True)
        model_selector.clear()
        if mode_key == "type":
            display_text = "three_stage_deployed | success_three_stage"
            model_selector.addItem(display_text, "three_stage_deployed")
            model_selector.setItemData(model_selector.count() - 1, display_text, Qt.ItemDataRole.ToolTipRole)
            local_display_text = "three_stage_local | 本地权重 MAT 测试"
            model_selector.addItem(local_display_text, "three_stage_local")
            model_selector.setItemData(model_selector.count() - 1, local_display_text, Qt.ItemDataRole.ToolTipRole)
            for record in self.trained_models:
                version_hint = " | 来源版本已删" if self._is_model_version_deleted(record) else ""
                display_text = f"{record.model_id} | {record.dataset_version_id} | {record.accuracy_text}{version_hint}"
                model_selector.addItem(display_text, record)
                model_selector.setItemData(model_selector.count() - 1, display_text, Qt.ItemDataRole.ToolTipRole)
        else:
            model_selector.addItem("保留功能 | 真实个体模型待接入", "pending")
            model_selector.setItemData(
                model_selector.count() - 1,
                "保留功能 | 真实个体模型待接入",
                Qt.ItemDataRole.ToolTipRole,
            )
        model_selector.blockSignals(False)

        if model_selector.count() == 0:
            run_button = controls["run_button"]
            load_button = controls["load_button"]
            assert isinstance(run_button, QPushButton)
            assert isinstance(load_button, QPushButton)
            run_button.setEnabled(False)
            load_button.setEnabled(True)
            self._refresh_sample_selector(mode_key)
            if mode_key == "type" and not self.sample_records:
                self._set_result_rows(mode_key, [["当前无可用模型", "请先在训练页生成类型识别模型"]], status_text="待模型")
            return

        target_index = 0
        if current_model_id is not None:
            for index in range(model_selector.count()):
                record = model_selector.itemData(index)
                if record == current_model_id or (
                    isinstance(record, TrainedModelRecord) and record.model_id == current_model_id
                ):
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

        empty_hint = "当前无预处理样本，请先完成预处理或标注同步" if mode_key == "type" else "个体识别样本暂未准备"
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
            records = list(self.sample_records)
            label_space = set(model_record.label_space) if model_record is not None else set()

            def sort_key(record: SampleRecord) -> tuple[int, str, str]:
                if label_space and record.label_type in label_space:
                    priority = 0
                elif record.label_type:
                    priority = 1
                else:
                    priority = 2
                return (priority, record.device_id, record.sample_id)

            return sorted(records, key=sort_key)
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

    def _selected_type_model_data(self) -> object | None:
        """Return the raw selected type model item data."""

        controls = self.mode_controls.get("type")
        if not controls:
            return None
        model_selector = controls["model_selector"]
        assert isinstance(model_selector, QComboBox)
        return model_selector.currentData()

    def _on_model_changed(self, mode_key: str) -> None:
        """当用户切换模型时刷新顶部状态。"""

        controls = self.mode_controls.get(mode_key)
        if not controls:
            return

        model_selector = controls["model_selector"]
        assert isinstance(model_selector, QComboBox)

        if mode_key == "type":
            record = model_selector.currentData()
            if record == "three_stage_deployed":
                self.type_model_metric.set_value("three_stage_deployed")
            elif record == "three_stage_local":
                self.type_model_metric.set_value("three_stage_local")
            elif isinstance(record, TrainedModelRecord):
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
        model_data = self._selected_type_model_data() if mode_key == "type" else None
        if mode_key == "type" and model_data == "three_stage_local":
            run_button = controls["run_button"]
            load_button = controls["load_button"]
            assert isinstance(run_button, QPushButton)
            assert isinstance(load_button, QPushButton)
            load_button.setEnabled(True)
            run_button.setEnabled(bool(self.local_mat_path.strip()))
            self._set_result_rows(
                mode_key,
                [
                    ["当前模式", "本地 MAT 三阶段推理测试"],
                    ["MAT 文件", self.local_mat_path or "未选择"],
                    ["MAT 目录", self.local_mat_dir or "未选择"],
                    ["二分类权重", self.local_binary_model_path or "未选择"],
                    ["类型权重", self.local_type_model_path or "未选择"],
                    ["类型 Meta", self.local_type_meta_path or "未选择"],
                    ["个体权重", self.local_individual_model_path or "未选择"],
                    ["个体 Meta", self.local_individual_meta_path or "未提供"],
                    ["说明", "该模式直接使用本地 .mat 与本地三阶段权重，不依赖样本库。"],
                ],
                status_text="本地 MAT 待测试",
            )
            return
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
            run_button.setEnabled(isinstance(model_record, TrainedModelRecord))
        else:
            run_button.setEnabled(True)

        current_label = record.label_type if mode_key == "type" else record.label_individual
        label_status = "-"
        if mode_key == "type" and isinstance(model_record, TrainedModelRecord):
            if not current_label:
                label_status = "样本未标注；可识别，但不计算命中。"
            elif current_label in model_record.label_space:
                label_status = "样本标签在当前模型标签空间内。"
            else:
                label_status = "样本标签不在当前模型标签空间内；可识别，但不计算命中。"
            domain_status = self._domain_status_text(record, model_record)
        else:
            domain_status = "-"
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
                ["标签空间状态", label_status],
                ["适用域状态", domain_status],
            ],
            status_text=f"已加载 {record.sample_id}",
            status_level="warning" if domain_status.startswith("域外") else None,
        )

    def _run_recognition(self, mode_key: str) -> None:
        """执行一次识别任务。"""

        if self._recognition_thread is not None and self._recognition_thread.isRunning():
            return

        controls = self.mode_controls[mode_key]
        model_selector = controls["model_selector"]
        sample_selector = controls["sample_selector"]
        assert isinstance(model_selector, QComboBox)
        assert isinstance(sample_selector, QComboBox)

        model_record = model_selector.currentData()
        record = sample_selector.currentData()
        if model_record != "three_stage_local" and not isinstance(record, SampleRecord):
            self._set_result_rows(mode_key, [["???????", "???????????"]], status_text="???")
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

        if model_record == "three_stage_local":
            if not self.local_mat_path.strip():
                self._set_result_rows(
                    mode_key,
                    [
                        ["当前模式", "本地 MAT 三阶段推理测试"],
                        ["错误信息", "请先选择一个本地 .mat 文件。"],
                    ],
                    status_text="待选择 MAT",
                )
                return

            self._start_recognition_task(
                mode_key,
                "本地 MAT 三阶段推理",
                lambda progress_callback=None: {
                    "kind": "three_stage_local",
                    "record": SampleRecord(
                        sample_id=Path(self.local_mat_path).stem,
                        source_type="manual_mat",
                        raw_file_path=self.local_mat_path.strip(),
                        sample_file_path=self.local_mat_path.strip(),
                        label_type="",
                        label_individual="",
                        sample_rate_hz=0.0,
                        center_frequency_hz=0.0,
                        data_format="mat",
                        sample_count=0,
                        device_id="local_mat",
                        start_sample=0,
                        end_sample=0,
                        include_in_dataset=False,
                        status="待标注",
                        source_name="本地 MAT 测试",
                    ),
                    "raw_result": predict_three_stage_sample(
                        self.local_mat_path.strip(),
                        input_path_kind="mat",
                        binary_model_path=self.local_binary_model_path.strip() or None,
                        type_model_path=self.local_type_model_path.strip() or None,
                        type_metadata_path=self.local_type_meta_path.strip() or None,
                        individual_model_path=self.local_individual_model_path.strip() or None,
                        individual_metadata_path=self.local_individual_meta_path.strip() or None,
                        progress_callback=progress_callback,
                        prefer_legacy_direct_path=True,
                    ),
                },
            )
            return

        if model_record != "three_stage_deployed" and not isinstance(model_record, TrainedModelRecord):
            run_button = controls["run_button"]
            assert isinstance(run_button, QPushButton)
            run_button.setEnabled(False)
            self._set_result_rows(mode_key, [["当前无可用模型", "请先在训练页生成类型识别模型"]], status_text="待模型")
            return

        if model_record == "three_stage_deployed":
            self._start_recognition_task(
                mode_key,
                f"三阶段识别: {record.sample_id}",
                lambda progress_callback=None: {
                    "kind": "three_stage_deployed",
                    "record": record,
                    "raw_result": predict_three_stage_sample(
                        record.sample_file_path,
                        input_path_kind="auto",
                        progress_callback=progress_callback,
                        prefer_legacy_direct_path=True,
                    ),
                },
            )
            return

        self._start_recognition_task(
            mode_key,
            f"样本识别: {record.sample_id}",
            lambda: {
                "kind": "type_prediction",
                "record": record,
                "result": predict_type_sample(model_record.model_id, record.sample_file_path),
            },
        )

    def _start_recognition_task(self, mode_key: str, task_label: str, task_callable) -> None:
        """Start one background recognition task."""

        controls = self.mode_controls[mode_key]
        run_button = controls["run_button"]
        load_button = controls["load_button"]
        assert isinstance(run_button, QPushButton)
        assert isinstance(load_button, QPushButton)
        run_button.setEnabled(False)
        load_button.setEnabled(False)
        apply_button = controls.get("apply_button")
        if isinstance(apply_button, QPushButton):
            apply_button.setEnabled(False)
        self._active_recognition_mode = mode_key
        self.latest_result_metric.set_value("识别中")
        self._set_result_rows(mode_key, [["当前状态", f"{task_label} 进行中，请稍候..."]], status_text="识别中")

        thread = QThread(self)
        worker = RecognitionRunWorker(task_label=task_label, task_callable=task_callable)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_recognition_started)
        worker.progress.connect(self._on_recognition_progress)
        worker.finished.connect(self._on_recognition_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_recognition_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_recognition_worker)
        thread.finished.connect(thread.deleteLater)

        self._recognition_thread = thread
        self._recognition_worker = worker
        thread.start()

    def _on_recognition_started(self, task_label: str) -> None:
        mode_key = self._active_recognition_mode or "type"
        self._set_result_rows(mode_key, [["当前状态", f"{task_label} 进行中，请稍候..."]], status_text="识别中")

    def _on_recognition_progress(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("kind") != "three_stage_partial":
            return
        raw_result = payload.get("raw_result")
        if not isinstance(raw_result, dict):
            return
        sample_record = self._current_type_sample_for_progress()
        if sample_record is None:
            return
        self._apply_three_stage_prediction(sample_record, raw_result, partial=True)

    def _on_recognition_finished(self, payload: object) -> None:
        mode_key = self._active_recognition_mode or "type"
        controls = self.mode_controls.get(mode_key, {})
        run_button = controls.get("run_button")
        load_button = controls.get("load_button")
        if isinstance(run_button, QPushButton):
            run_button.setEnabled(True)
        if isinstance(load_button, QPushButton):
            load_button.setEnabled(True)
        apply_button = controls.get("apply_button")
        if isinstance(apply_button, QPushButton):
            apply_button.setEnabled(True)

        if not isinstance(payload, dict):
            self._set_result_rows(mode_key, [["错误信息", "识别结果格式无效。"]], status_text="识别失败")
            return

        kind = payload.get("kind")
        if kind in {"three_stage_local", "three_stage_deployed"}:
            record = payload.get("record")
            raw_result = payload.get("raw_result")
            if isinstance(record, SampleRecord) and isinstance(raw_result, dict):
                self._apply_three_stage_prediction(record, raw_result)
                return
        if kind == "warmup_runtime":
            selection = payload.get("selection")
            warmup_mat = str(payload.get("warmup_mat", ""))
            warmup_result = payload.get("warmup_result")
            if isinstance(selection, ThreeStageRuntimeSelection) and isinstance(warmup_result, dict):
                self.latest_result_metric.set_value("预热完成")
                self._set_result_rows(
                    "type",
                    [
                        ["当前模式", "模型应用与预热"],
                        ["预热样本", warmup_mat],
                        ["二分类权重", selection.binary_model_path],
                        ["类型权重", selection.type_model_path],
                        ["类型 Meta", selection.type_metadata_path],
                        ["个体权重", selection.individual_model_path],
                        ["个体 Meta", selection.individual_metadata_path or "未提供"],
                        ["预热状态", self._format_three_stage_status(str(warmup_result.get("status", "success")))],
                        ["说明", "当前页面后续三阶段识别会复用这套已预热模型。"],
                    ],
                    status_text="模型已预热",
                )
                return
        if kind == "batch_mat_test":
            rows = payload.get("rows")
            mat_dir = str(payload.get("mat_dir", ""))
            mat_count = int(payload.get("mat_count", 0) or 0)
            json_path = str(payload.get("json_path", ""))
            csv_path = str(payload.get("csv_path", ""))
            if isinstance(rows, list):
                success_count = sum(1 for item in rows if isinstance(item, dict) and item.get("status") == "success")
                error_count = sum(1 for item in rows if isinstance(item, dict) and item.get("status") == "error")
                preview_lines: list[str] = []
                for item in rows[:5]:
                    if not isinstance(item, dict):
                        continue
                    file_name = str(item.get("file_name", ""))
                    status = str(item.get("status", ""))
                    predicted_type = str(item.get("predicted_type", "") or "-")
                    predicted_individual = str(item.get("predicted_individual", "") or "-")
                    preview_lines.append(f"{file_name}: {status} / {predicted_type} / {predicted_individual}")
                preview_text = " | ".join(preview_lines) if preview_lines else "-"
                self.latest_result_metric.set_value(f"批量 {success_count}/{mat_count}")
                self._set_result_rows(
                    "type",
                    [
                        ["当前模式", "MAT 目录批量测试"],
                        ["测试目录", mat_dir],
                        ["MAT 数量", str(mat_count)],
                        ["成功数量", str(success_count)],
                        ["失败数量", str(error_count)],
                        ["结果预览", preview_text],
                        ["JSON 导出", json_path],
                        ["CSV 导出", csv_path],
                    ],
                    status_text=f"批量测试完成: {success_count}/{mat_count}",
                )
                return
        if kind == "type_prediction":
            record = payload.get("record")
            result = payload.get("result")
            if isinstance(record, SampleRecord) and isinstance(result, PredictionResult):
                self._apply_type_prediction(record, result)
                return

        self._set_result_rows(mode_key, [["错误信息", "识别结果无法解析。"]], status_text="识别失败")

    def _on_recognition_failed(self, message: str) -> None:
        mode_key = self._active_recognition_mode or "type"
        controls = self.mode_controls.get(mode_key, {})
        run_button = controls.get("run_button")
        load_button = controls.get("load_button")
        if isinstance(run_button, QPushButton):
            run_button.setEnabled(True)
        if isinstance(load_button, QPushButton):
            load_button.setEnabled(True)
        apply_button = controls.get("apply_button")
        if isinstance(apply_button, QPushButton):
            apply_button.setEnabled(True)
        self.latest_result_metric.set_value("识别失败")
        self._set_result_rows(mode_key, [["错误信息", message]], status_text="识别失败")

    def _clear_recognition_worker(self) -> None:
        self._recognition_thread = None
        self._recognition_worker = None
        self._active_recognition_mode = None

    def _apply_type_prediction(self, sample_record: SampleRecord, result: PredictionResult) -> None:
        """把真实类型识别结果渲染到页面。"""

        current_label = sample_record.label_type or "未标注"
        predicted_label = result.predicted_label
        label_space = set(result.model_record.label_space)
        domain_warnings = self._domain_warning_messages(sample_record, result.model_record)
        can_judge_match = current_label != "未标注" and current_label in label_space and not domain_warnings
        is_match = "是" if can_judge_match and predicted_label == current_label else ("否" if can_judge_match else "-")
        match_hint = ""
        if domain_warnings:
            match_hint = "域外样本，命中判断不可用；预测置信度不是准确率，只表示闭集模型在现有标签中的最大类别概率。"
        elif current_label == "未标注":
            match_hint = "样本未标注，命中判断不可用。"
        elif current_label not in label_space:
            match_hint = "样本标签不在当前模型标签空间内，命中判断不可用。"
        probability_text = self._format_probability_text(result.probabilities)
        confidence_text = f"{result.confidence * 100:.2f}%"

        rows = [
            ["当前样本", sample_record.sample_id],
            ["当前标签", self._display_label(current_label)],
            ["预测标签", self._display_label(predicted_label)],
            ["预测置信度", confidence_text],
            ["类别概率", probability_text],
            ["是否命中", is_match],
            ["命中说明", match_hint or "当前标签可用于命中判断。"],
            ["适用域提示", self._domain_status_text(sample_record, result.model_record)],
            ["置信度说明", "预测置信度是 RandomForest 的最大类别概率，不等同于模型准确率。"],
            ["来源文件", sample_record.raw_file_name],
            ["来源路径", sample_record.raw_file_path],
            ["来源类型", sample_record.source_label],
            ["识别模型", result.model_record.model_id],
            ["来源版本", result.model_record.dataset_version_id],
            ["来源版本状态", self._model_version_status_text(result.model_record)],
            ["标签空间", " / ".join(self._display_label(label) for label in result.model_record.label_space)],
        ]
        self.latest_result_metric.set_value(self._display_label(predicted_label))
        if domain_warnings:
            self._set_result_rows(
                "type",
                rows,
                status_text=f"域外结果: {self._display_label(predicted_label)}",
                status_level="warning",
            )
        else:
            self._set_result_rows("type", rows, status_text=f"结果: {self._display_label(predicted_label)}")

    def _apply_three_stage_prediction(
        self,
        sample_record: SampleRecord,
        raw_result: dict[str, object],
        *,
        partial: bool = False,
    ) -> None:
        """Render one deployed three-stage recognition result."""

        current_label = sample_record.label_type or "未标注"
        status = str(raw_result.get("status") or "unknown")
        overall_type = raw_result.get("overall_type_result")
        overall_individual = raw_result.get("overall_individual_result")
        overall_type_result = overall_type if isinstance(overall_type, dict) else {}
        overall_individual_result = overall_individual if isinstance(overall_individual, dict) else {}

        predicted_type = str(
            overall_type_result.get("predicted_class_name")
            or ("NOISE" if status == "no_drone_detected" else "UNKNOWN")
        )
        predicted_individual = str(overall_individual_result.get("predicted_class_name") or "-")
        detected_candidate_bursts = int(raw_result.get("detected_candidate_bursts", 0) or 0)
        accepted_drone_bursts = int(raw_result.get("accepted_drone_bursts", 0) or 0)

        rows = [
            ["当前样本", sample_record.sample_id],
            ["当前标签", self._display_label(current_label)],
            ["运行状态", self._format_three_stage_status(status)],
            ["总体类型预测", self._display_label(predicted_type)],
            ["总体类型置信度", self._format_three_stage_confidence(overall_type_result)],
            ["类型概率", self._format_three_stage_probabilities(overall_type_result)],
            ["总体个体预测", self._display_label(predicted_individual)],
            ["总体个体置信度", self._format_three_stage_confidence(overall_individual_result)],
            ["个体概率", self._format_three_stage_probabilities(overall_individual_result)],
            ["候选段数量", str(detected_candidate_bursts)],
            ["接受无人机段数量", str(accepted_drone_bursts)],
            ["候选段摘要", self._build_three_stage_burst_summary(raw_result)],
            ["候选段详情", self._build_three_stage_burst_details(raw_result)],
            ["统计信息", self._build_three_stage_stats_text(raw_result)],
            ["耗时", self._build_three_stage_timing_text(raw_result)],
            ["来源文件", sample_record.raw_file_name],
            ["来源路径", sample_record.raw_file_path],
            ["来源类型", sample_record.source_label],
            ["识别模型", "three_stage_deployed"],
            ["标签空间", " / ".join(["A", "C", "D", "E", "F", "G", "NOISE"])],
        ]

        result_label = self._display_label(predicted_type)
        self.latest_result_metric.set_value(result_label)
        badge_text = "结果: 未检测到无人机" if status == "no_drone_detected" else f"结果: {result_label}"
        badge_level = "warning" if status == "no_drone_detected" else None
        self._set_result_rows("type", rows, status_text=badge_text, status_level=badge_level)

    def _current_type_sample_for_progress(self) -> SampleRecord | None:
        model_data = self._selected_type_model_data()
        if model_data == "three_stage_local":
            mat_path = self.local_mat_path.strip()
            if not mat_path:
                return None
            return SampleRecord(
                sample_id=Path(mat_path).stem,
                source_type="manual_mat",
                raw_file_path=mat_path,
                sample_file_path=mat_path,
                label_type="",
                label_individual="",
                sample_rate_hz=0.0,
                center_frequency_hz=0.0,
                data_format="mat",
                sample_count=0,
                device_id="local_mat",
                start_sample=0,
                end_sample=0,
                include_in_dataset=False,
                status="寰呮爣娉?",
                source_name="鏈湴 MAT 娴嬭瘯",
            )
        controls = self.mode_controls.get("type", {})
        sample_selector = controls.get("sample_selector")
        if isinstance(sample_selector, QComboBox):
            record = sample_selector.currentData()
            if isinstance(record, SampleRecord):
                return record
        return None

    def _set_result_rows(
        self,
        mode_key: str,
        rows: list[list[str]],
        status_text: str,
        status_level: str | None = None,
    ) -> None:
        """刷新一个页签下的结果表。"""

        controls = self.mode_controls[mode_key]
        status_badge = controls["status_badge"]
        result_table = controls["result_table"]
        assert isinstance(status_badge, StatusBadge)
        assert isinstance(result_table, QTableWidget)

        level = status_level or (
            "success" if status_text.startswith("结果") else ("danger" if "失败" in status_text else "info")
        )
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

    def _format_probability_text(self, probabilities: dict[str, float]) -> str:
        """把模型类别概率格式化成紧凑、可读的结果文本。"""

        if not probabilities:
            return "当前模型未提供类别概率。"
        sorted_items = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        return " / ".join(
            f"{self._display_label(label)} {probability * 100:.2f}%"
            for label, probability in sorted_items
        )

    def _choose_local_mat_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 MAT 文件",
            str(Path(self.local_mat_path).parent if self.local_mat_path else Path.cwd()),
            "MAT Files (*.mat)",
        )
        if not file_path:
            return
        controls = self.mode_controls.get("type", {})
        widget = controls.get("local_mat_input")
        if isinstance(widget, QLineEdit):
            widget.setText(file_path)

    def _choose_local_mat_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择 MAT 目录",
            self.local_mat_dir or str(Path.cwd()),
        )
        if not directory:
            return
        controls = self.mode_controls.get("type", {})
        widget = controls.get("local_mat_dir_input")
        if isinstance(widget, QLineEdit):
            widget.setText(directory)

    def _choose_local_file(self, widget_key: str, attr_name: str, file_filter: str) -> None:
        current_value = getattr(self, attr_name, "")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            str(Path(current_value).parent if current_value else Path.cwd()),
            file_filter,
        )
        if not file_path:
            return
        controls = self.mode_controls.get("type", {})
        widget = controls.get(widget_key)
        if isinstance(widget, QLineEdit):
            widget.setText(file_path)

    def _on_local_mat_changed(self, value: str) -> None:
        self.local_mat_path = value.strip()
        if "type" in self.mode_controls:
            self._load_selected_sample("type")

    def _on_local_mat_dir_changed(self, value: str) -> None:
        self.local_mat_dir = value.strip()
        if "type" in self.mode_controls:
            self._load_selected_sample("type")

    def _run_local_mat_batch_test(self) -> None:
        if self._recognition_thread is not None:
            return
        mat_dir = Path(self.local_mat_dir.strip() or "").expanduser()
        if not mat_dir.exists() or not mat_dir.is_dir():
            self._set_result_rows(
                "type",
                [
                    ["当前模式", "MAT 目录批量测试"],
                    ["错误信息", "请先选择一个有效的 MAT 目录。"],
                ],
                status_text="待选择目录",
            )
            return

        mat_files = sorted(mat_dir.glob("*.mat"))
        if not mat_files:
            self._set_result_rows(
                "type",
                [
                    ["当前模式", "MAT 目录批量测试"],
                    ["目录", str(mat_dir)],
                    ["错误信息", "目录中没有 .mat 文件。"],
                ],
                status_text="无 MAT 文件",
            )
            return

        self._start_recognition_task(
            "type",
            f"MAT 目录批量测试: {mat_dir.name}",
            lambda: {
                "kind": "batch_mat_test",
                **self._run_local_mat_batch_test_payload(mat_dir, mat_files),
            },
        )

    def _apply_and_warmup_three_stage_models(self) -> None:
        if self._recognition_thread is not None:
            return
        warmup_mat = ""
        try:
            warmup_mat = resolve_three_stage_warmup_sample()
        except Exception as exc:
            self._set_result_rows(
                "type",
                [
                    ["????", "???????"],
                    ["????", f"????????? MAT ??: {exc}"],
                ],
                status_text="??????",
            )
            return


        selection = ThreeStageRuntimeSelection(
            binary_model_path=self.local_binary_model_path.strip(),
            type_model_path=self.local_type_model_path.strip(),
            type_metadata_path=self.local_type_meta_path.strip(),
            individual_model_path=self.local_individual_model_path.strip(),
            individual_metadata_path=self.local_individual_meta_path.strip(),
        )
        try:
            validate_three_stage_selection(selection)
        except Exception as exc:
            self._set_result_rows(
                "type",
                [
                    ["当前模式", "模型应用与预热"],
                    ["错误信息", str(exc)],
                ],
                status_text="配置无效",
            )
            return

        self._start_recognition_task(
            "type",
            "应用并预热三阶段模型",
            lambda: self._apply_and_warmup_three_stage_models_payload(selection, warmup_mat),
        )

    def _apply_and_warmup_three_stage_models_payload(
        self,
        selection: ThreeStageRuntimeSelection,
        warmup_mat: str,
    ) -> dict[str, object]:
        set_three_stage_runtime_selection(selection)
        warmup_result = warmup_three_stage_runtime(warmup_mat)
        return {
            "kind": "warmup_runtime",
            "selection": selection,
            "warmup_mat": warmup_mat,
            "warmup_result": warmup_result,
        }

    def _run_local_mat_batch_test_payload(self, mat_dir: Path, mat_files: list[Path]) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        for file_path in mat_files:
            try:
                result = predict_three_stage_sample(
                    str(file_path),
                    input_path_kind="mat",
                    binary_model_path=self.local_binary_model_path.strip() or None,
                    type_model_path=self.local_type_model_path.strip() or None,
                    type_metadata_path=self.local_type_meta_path.strip() or None,
                    individual_model_path=self.local_individual_model_path.strip() or None,
                    individual_metadata_path=self.local_individual_meta_path.strip() or None,
                )
                overall_type = result.get("overall_type_result") if isinstance(result, dict) else {}
                overall_ind = result.get("overall_individual_result") if isinstance(result, dict) else {}
                rows.append(
                    {
                        "file_name": file_path.name,
                        "file_path": str(file_path),
                        "status": str(result.get("status", "")),
                        "predicted_type": str((overall_type or {}).get("predicted_class_name", "")),
                        "type_confidence": float((overall_type or {}).get("confidence", 0.0) or 0.0),
                        "predicted_individual": str((overall_ind or {}).get("predicted_class_name", "")),
                        "individual_confidence": float((overall_ind or {}).get("confidence", 0.0) or 0.0),
                        "candidate_bursts": int(result.get("detected_candidate_bursts", 0) or 0),
                        "accepted_bursts": int(result.get("accepted_drone_bursts", 0) or 0),
                        "raw_result": result,
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "file_name": file_path.name,
                        "file_path": str(file_path),
                        "status": "error",
                        "predicted_type": "",
                        "type_confidence": 0.0,
                        "predicted_individual": "",
                        "individual_confidence": 0.0,
                        "candidate_bursts": 0,
                        "accepted_bursts": 0,
                        "error": str(exc),
                    }
                )

        export_dir = EXPORTS_DIR / "three_stage_batch_tests"
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = f"mat_batch_{mat_dir.name}"
        json_path = export_dir / f"{stem}.json"
        csv_path = export_dir / f"{stem}.csv"

        json_payload = []
        for item in rows:
            json_payload.append(
                {
                    key: value
                    for key, value in item.items()
                    if key != "raw_result"
                }
                | ({"raw_result": item["raw_result"]} if "raw_result" in item else {})
            )
        json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "file_name",
                    "file_path",
                    "status",
                    "predicted_type",
                    "type_confidence",
                    "predicted_individual",
                    "individual_confidence",
                    "candidate_bursts",
                    "accepted_bursts",
                    "error",
                ],
            )
            writer.writeheader()
            for item in rows:
                writer.writerow(
                    {
                        "file_name": item.get("file_name", ""),
                        "file_path": item.get("file_path", ""),
                        "status": item.get("status", ""),
                        "predicted_type": item.get("predicted_type", ""),
                        "type_confidence": item.get("type_confidence", 0.0),
                        "predicted_individual": item.get("predicted_individual", ""),
                        "individual_confidence": item.get("individual_confidence", 0.0),
                        "candidate_bursts": item.get("candidate_bursts", 0),
                        "accepted_bursts": item.get("accepted_bursts", 0),
                        "error": item.get("error", ""),
                    }
                )

        return {
            "mat_dir": str(mat_dir),
            "mat_count": len(mat_files),
            "rows": rows,
            "json_path": str(json_path),
            "csv_path": str(csv_path),
        }

    def _format_three_stage_status(self, status: str) -> str:
        if status == "success":
            return "已完成三阶段识别"
        if status == "no_drone_detected":
            return "未检测到无人机候选段"
        return status or "-"

    def _format_three_stage_confidence(self, stage_result: dict[str, object]) -> str:
        confidence = stage_result.get("confidence")
        if confidence is None:
            return "-"
        try:
            return f"{float(confidence) * 100:.2f}%"
        except (TypeError, ValueError):
            return "-"

    def _format_three_stage_probabilities(self, stage_result: dict[str, object]) -> str:
        raw_probabilities = stage_result.get("class_probabilities")
        if not isinstance(raw_probabilities, dict):
            return "当前阶段未提供概率。"

        probabilities: dict[str, float] = {}
        for label, value in raw_probabilities.items():
            try:
                probabilities[str(label)] = float(value)
            except (TypeError, ValueError):
                continue
        return self._format_probability_text(probabilities)

    def _build_three_stage_burst_summary(self, raw_result: dict[str, object]) -> str:
        burst_results = raw_result.get("burst_results")
        if not isinstance(burst_results, list) or not burst_results:
            return "无候选段"

        parts: list[str] = []
        for burst in burst_results[:3]:
            if not isinstance(burst, dict):
                continue
            burst_idx = int(burst.get("burst_idx", 0) or 0)
            binary_result = burst.get("binary_result")
            type_result = burst.get("type_result")
            is_drone = bool(binary_result.get("is_drone")) if isinstance(binary_result, dict) else False
            type_name = str(type_result.get("predicted_class_name", "-")) if isinstance(type_result, dict) else "-"
            parts.append(f"B{burst_idx}:{'drone' if is_drone else 'skip'}:{type_name}")
        return " / ".join(parts) if parts else "无候选段摘要"

    def _build_three_stage_burst_details(self, raw_result: dict[str, object]) -> str:
        burst_results = raw_result.get("burst_results")
        if not isinstance(burst_results, list) or not burst_results:
            return "无候选段详情"

        details: list[str] = []
        for burst in burst_results[:5]:
            if not isinstance(burst, dict):
                continue
            burst_idx = int(burst.get("burst_idx", 0) or 0)
            slice_count = int(burst.get("slice_count", 0) or 0)
            binary_result = burst.get("binary_result")
            type_result = burst.get("type_result")
            individual_result = burst.get("individual_result")
            is_drone = bool(binary_result.get("is_drone")) if isinstance(binary_result, dict) else False
            type_name = str(type_result.get("predicted_class_name", "-")) if isinstance(type_result, dict) else "-"
            individual_name = (
                str(individual_result.get("predicted_class_name", "-"))
                if isinstance(individual_result, dict)
                else "-"
            )
            details.append(
                f"B{burst_idx}: {slice_count} slices, {'drone' if is_drone else 'skip'}, "
                f"type={type_name}, individual={individual_name}"
            )
        return " | ".join(details) if details else "无候选段详情"

    def _build_three_stage_stats_text(self, raw_result: dict[str, object]) -> str:
        stats = raw_result.get("stats")
        if not isinstance(stats, dict) or not stats:
            return "-"

        parts: list[str] = []
        for key in (
            "candidate_bursts",
            "candidate_slices",
            "accepted_drone_bursts",
            "type_input_slices",
            "individual_input_slices",
        ):
            if key in stats:
                parts.append(f"{key}={stats[key]}")
        return " / ".join(parts) if parts else "-"

    def _build_three_stage_timing_text(self, raw_result: dict[str, object]) -> str:
        timings = raw_result.get("timings")
        if not isinstance(timings, dict) or not timings:
            return "-"

        labels = [
            ("预处理", "preprocess_sec"),
            ("binary", "binary_stage_sec"),
            ("type", "type_stage_sec"),
            ("individual", "individual_stage_sec"),
            ("总耗时", "total_sec"),
        ]
        parts: list[str] = []
        for label, key in labels:
            value = timings.get(key)
            try:
                parts.append(f"{label}={float(value):.3f}s")
            except (TypeError, ValueError):
                continue
        return " / ".join(parts) if parts else "-"

    def _domain_status_text(self, sample_record: SampleRecord, model_record: TrainedModelRecord) -> str:
        """返回当前样本是否落在模型训练适用域内的说明。"""

        warnings = self._domain_warning_messages(sample_record, model_record)
        if not warnings:
            return "样本来源、中心频率和采样率在当前模型训练范围内。"
        return "域外样本：" + "；".join(warnings)

    def _domain_warning_messages(
        self,
        sample_record: SampleRecord,
        model_record: TrainedModelRecord,
    ) -> list[str]:
        """基于模型训练元数据判断样本是否明显域外。"""

        domain = self._model_training_domain(model_record)
        if not domain:
            return []

        warnings: list[str] = []
        source_types = domain.get("source_types")
        if isinstance(source_types, list) and source_types and sample_record.source_type not in source_types:
            warnings.append(
                f"样本来源为 {sample_record.source_label}，模型训练来源为 "
                + " / ".join(str(item) for item in source_types)
            )

        frequency_warning = self._range_warning(
            "中心频率",
            sample_record.center_frequency_hz,
            domain.get("center_frequency_hz_range"),
            unit="MHz",
            divisor=1_000_000.0,
            minimum_margin=5_000_000.0,
        )
        if frequency_warning:
            warnings.append(frequency_warning)

        sample_rate_warning = self._range_warning(
            "采样率",
            sample_record.sample_rate_hz,
            domain.get("sample_rate_hz_range"),
            unit="MHz",
            divisor=1_000_000.0,
            minimum_margin=500_000.0,
        )
        if sample_rate_warning:
            warnings.append(sample_rate_warning)
        return warnings

    def _model_training_domain(self, model_record: TrainedModelRecord) -> dict[str, object]:
        """优先读取模型元数据，旧模型则回退到仍存在的数据集版本。"""

        domain = model_record.metrics.get("training_domain")
        if isinstance(domain, dict):
            return domain

        detail = get_dataset_version_detail(model_record.dataset_version_id)
        if detail is None:
            return {}
        source_types = sorted({item.source_type for item in detail.items if item.source_type})
        frequencies = [item.center_frequency_hz for item in detail.items if item.center_frequency_hz > 0]
        sample_rates = [item.sample_rate_hz for item in detail.items if item.sample_rate_hz > 0]
        return {
            "source_types": source_types,
            "center_frequency_hz_range": self._range_payload(frequencies),
            "sample_rate_hz_range": self._range_payload(sample_rates),
        }

    def _range_payload(self, values: list[float]) -> dict[str, float] | None:
        """把数值列表压缩成范围。"""

        if not values:
            return None
        return {"min": float(min(values)), "max": float(max(values))}

    def _range_warning(
        self,
        label: str,
        value: float,
        range_payload: object,
        *,
        unit: str,
        divisor: float,
        minimum_margin: float,
    ) -> str:
        """判断一个数值是否超出模型训练范围并返回说明。"""

        if value <= 0 or not isinstance(range_payload, dict):
            return ""
        lower = float(range_payload.get("min", 0.0) or 0.0)
        upper = float(range_payload.get("max", 0.0) or 0.0)
        if lower <= 0 or upper <= 0:
            return ""
        margin = max(minimum_margin, abs(upper - lower) * 0.1)
        if lower - margin <= value <= upper + margin:
            return ""
        return (
            f"{label} {value / divisor:.3f} {unit} 超出模型训练范围 "
            f"{lower / divisor:.3f}-{upper / divisor:.3f} {unit}"
        )

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
