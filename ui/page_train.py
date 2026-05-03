"""模型训练页：负责真实类型识别训练、结果展示和模型产物联动。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import EXPORTS_DIR
from services import (
    DatasetVersionDetail,
    DatasetVersionRecord,
    ModelEvaluationResult,
    TrainedModelRecord,
    TrainingMetricRow,
    TrainingRunResult,
    delete_trained_model,
    get_dataset_version_detail,
    list_trained_models,
)
from ui.model_eval_worker import ModelEvalWorker
from ui.train_run_worker import TrainRunWorker
from ui.widgets import (
    MetricCard,
    SectionCard,
    SmoothScrollArea,
    StatusBadge,
    VisualHeroCard,
    VisualInfoStrip,
    configure_scrollable,
)


class TrainPage(QWidget):
    """训练页：当前重点支持类型识别真实训练。"""

    trained_models_updated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化训练页。"""

        super().__init__(parent)
        self.dataset_versions: list[DatasetVersionRecord] = []
        self.trained_models: list[TrainedModelRecord] = list_trained_models()
        self._train_thread: QThread | None = None
        self._train_worker: TrainRunWorker | None = None
        self._eval_thread: QThread | None = None
        self._eval_worker: ModelEvalWorker | None = None
        self._stop_requested = False

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
        self.val_accuracy_metric = MetricCard("验证精度", "-", compact=True)
        self.accuracy_metric = MetricCard("测试精度", "-", accent_color="#7CB98B", compact=True)
        self.f1_metric = MetricCard("宏平均 F1", "-", accent_color="#C59A63", compact=True)
        self.export_metric = MetricCard("当前产物", "未生成", accent_color="#6CA5D9", compact=True)
        metrics_row.addWidget(self.val_accuracy_metric)
        metrics_row.addWidget(self.accuracy_metric)
        metrics_row.addWidget(self.f1_metric)
        metrics_row.addWidget(self.export_metric)
        content_layout.addLayout(metrics_row)

        content_layout.addWidget(self._build_config_card())

        lower_row = QHBoxLayout()
        lower_row.setSpacing(14)
        lower_row.addWidget(self._build_results_card(), 3)
        lower_row.addWidget(self._build_export_workspace(), 2)
        content_layout.addLayout(lower_row)
        content_layout.addWidget(self._build_model_test_card())
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._refresh_trained_model_list_from_database()
        self.delete_model_button.setEnabled(bool(self.trained_models))

    def _build_visual_banner(self) -> VisualHeroCard:
        """Create the training-page visual banner."""

        return VisualHeroCard(
            "模型训练 · 可复现实验",
            "当前以 RandomForest 类型识别训练为主，强调版本固定、参数透明和结果可复现；训练页同时提供批量模型测试入口。",
            background_name="train_header_bg.svg",
            chips=["RandomForest", "可复现实验", "批量模型测试"],
            ornament_name="decor_data_panel_b.svg",
            height=170,
        )

    def get_trained_models(self) -> list[TrainedModelRecord]:
        """返回当前可供识别页消费的训练模型记录。"""

        return list(self.trained_models)

    def set_dataset_versions(self, records: list[DatasetVersionRecord]) -> None:
        """刷新训练页中的数据集版本下拉框。"""

        self.dataset_versions = list(records)
        current_version = (
            self.dataset_box.currentData().version_id
            if isinstance(self.dataset_box.currentData(), DatasetVersionRecord)
            else None
        )

        self.dataset_box.blockSignals(True)
        self.dataset_box.clear()
        for record in self.dataset_versions:
            display_text = f"{record.version_id} | {record.task_type} | {record.source_summary}"
            self.dataset_box.addItem(display_text, record)
        self.dataset_box.blockSignals(False)

        if self.dataset_versions:
            target_index = 0
            if current_version is not None:
                for index in range(self.dataset_box.count()):
                    record = self.dataset_box.itemData(index)
                    if isinstance(record, DatasetVersionRecord) and record.version_id == current_version:
                        target_index = index
                        break
            self.dataset_box.setCurrentIndex(target_index)
            self._on_dataset_changed()
        else:
            self.training_log.setPlainText("当前没有可用的数据集版本，请先在数据集管理页生成版本。")

        self._refresh_trained_model_list_from_database()

    def _build_config_card(self) -> SectionCard:
        """创建训练配置区域。"""

        self.training_status_badge = StatusBadge("待启动", "info", size="sm")
        section = SectionCard(
            "训练配置",
            "当前以类型识别真实训练为主；个体指纹识别保留入口，真实训练服务待接入。",
            right_widget=self.training_status_badge,
            compact=True,
        )

        switch_row = QHBoxLayout()
        switch_row.setSpacing(12)
        self.task_type_box = QComboBox()
        self.task_type_box.addItems(["类型识别（真实训练）", "个体识别（保留功能，待接入）"])
        self.task_type_box.currentIndexChanged.connect(self._switch_config_mode)

        self.dataset_box = QComboBox()
        self.dataset_box.currentIndexChanged.connect(self._on_dataset_changed)

        switch_row.addWidget(QLabel("任务类型"))
        switch_row.addWidget(self.task_type_box)
        switch_row.addSpacing(10)
        switch_row.addWidget(QLabel("数据集版本"))
        switch_row.addWidget(self.dataset_box, 1)
        switch_row.addStretch(1)

        self.config_stack = QStackedWidget()
        self.config_stack.addWidget(self._build_ml_form())
        self.config_stack.addWidget(self._build_dl_form())

        action_row = QHBoxLayout()
        self.start_button = QPushButton("开始训练")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_training)

        self.stop_button = QPushButton("中止训练")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._request_stop_training)

        stop_hint = QLabel("训练中可请求停止；若已进入随机森林拟合，需等待当前阶段结束。")
        stop_hint.setObjectName("MutedText")
        stop_hint.setWordWrap(True)

        validate_button = QPushButton("数据检查")
        validate_button.clicked.connect(self._run_dataset_check)

        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(validate_button)
        action_row.addStretch(1)

        section.body_layout.addLayout(switch_row)
        section.body_layout.addWidget(self.config_stack)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(stop_hint)
        return section

    def _build_ml_form(self) -> QGroupBox:
        """创建类型识别训练配置区。"""

        box = QGroupBox("类型识别配置")
        form_layout = QFormLayout(box)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.algorithm_box = QComboBox()
        self.algorithm_box.addItems(["RandomForest"])

        self.model_name_input = QLineEdit("rf_type_demo")
        self.model_name_input.setPlaceholderText("输入模型名称前缀")

        self.n_estimators_spin = QSpinBox()
        self.n_estimators_spin.setRange(10, 1000)
        self.n_estimators_spin.setValue(300)

        self.max_depth_spin = QSpinBox()
        self.max_depth_spin.setRange(0, 128)
        self.max_depth_spin.setSpecialValueText("不限")
        self.max_depth_spin.setValue(24)

        self.random_state_spin = QSpinBox()
        self.random_state_spin.setRange(0, 999999999)
        self.random_state_spin.setValue(42)

        tip_label = QLabel(
            "当前真实训练固定使用 RandomForest。默认随机种子为 42；相同数据集版本、参数与随机种子下，结果稳定重复是预期行为。"
        )
        tip_label.setObjectName("MutedText")
        tip_label.setWordWrap(True)

        form_layout.addRow("算法", self.algorithm_box)
        form_layout.addRow("模型名称", self.model_name_input)
        form_layout.addRow("树数量", self.n_estimators_spin)
        form_layout.addRow("最大深度", self.max_depth_spin)
        form_layout.addRow("随机种子", self.random_state_spin)
        form_layout.addRow("", tip_label)
        return box

    def _build_dl_form(self) -> QGroupBox:
        """创建个体识别演示提示区。"""

        box = QGroupBox("个体识别配置")
        form_layout = QFormLayout(box)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        mode_value = QLabel("待接入")
        mode_value.setObjectName("ValueLabel")
        hint_label = QLabel("个体指纹识别是保留功能，后续接入真实训练服务；当前不会生成假的个体识别模型。")
        hint_label.setObjectName("MutedText")
        hint_label.setWordWrap(True)

        form_layout.addRow("当前状态", mode_value)
        form_layout.addRow("", hint_label)
        return box

    def _build_results_card(self) -> SectionCard:
        """创建训练结果展示区。"""

        section = SectionCard("训练结果", "显示真实训练摘要、混淆矩阵文本和类别指标。", compact=True)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)

        self.confusion_placeholder = QPlainTextEdit()
        self.confusion_placeholder.setReadOnly(True)
        self.confusion_placeholder.setPlainText(
            "训练摘要显示区\n\n"
            "当前尚未执行真实训练。完成训练后，这里会展示标签分布、混淆矩阵和模型产物路径。"
        )
        self.confusion_placeholder.setMinimumHeight(260)
        configure_scrollable(self.confusion_placeholder)

        self.training_log = QPlainTextEdit()
        self.training_log.setReadOnly(True)
        self.training_log.setPlainText(
            "等待训练任务启动。\n"
            "当前页面会直接消费数据集管理页生成的数据集版本与 manifest。"
        )
        self.training_log.setMinimumHeight(260)
        configure_scrollable(self.training_log)

        summary_row.addWidget(self.confusion_placeholder, 2)
        summary_row.addWidget(self.training_log, 1)

        self.detail_table = QTableWidget(0, 5)
        self.detail_table.setHorizontalHeaderLabels(["类别", "精确率", "召回率", "F1", "样本数"])
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setAlternatingRowColors(True)
        configure_scrollable(self.detail_table)

        section.body_layout.addLayout(summary_row)
        section.body_layout.addWidget(self.detail_table)
        return section

    def _build_export_workspace(self) -> QWidget:
        """创建训练产物与模型信息区域。"""

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(self._build_export_config_card())
        layout.addWidget(self._build_export_result_card())
        layout.addStretch(1)
        return wrapper

    def _build_export_config_card(self) -> SectionCard:
        """创建模型产物信息卡片。"""

        self.export_status_badge = StatusBadge("待生成", "info", size="sm")
        section = SectionCard(
            "模型产物",
            "训练完成后，真实模型会落盘为 joblib，并登记到本地数据库供识别页直接读取。",
            right_widget=self.export_status_badge,
            compact=True,
        )

        self.export_model_box = QComboBox()
        self.export_model_box.currentIndexChanged.connect(self._update_export_details)

        self.export_detail_labels = {
            "任务类型": QLabel("-"),
            "算法": QLabel("-"),
            "数据集版本": QLabel("-"),
            "版本状态": QLabel("-"),
            "随机种子": QLabel("-"),
            "树数量": QLabel("-"),
            "最大深度": QLabel("-"),
            "验证精度": QLabel("-"),
            "测试精度": QLabel("-"),
            "模型路径": QLabel("-"),
        }
        for label in self.export_detail_labels.values():
            label.setObjectName("ValueLabel")
            label.setWordWrap(True)

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
        self.format_box.addItems(["原始模型（joblib）", "ONNX（待扩展）"])
        self.format_box.setEnabled(False)

        note_label = QLabel("当前真实导出产物固定为 model.joblib + metadata.json；ONNX 是保留目标，待扩展后再开放选择。")
        note_label.setObjectName("MutedText")
        note_label.setWordWrap(True)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.delete_model_button = QPushButton("删除选中模型")
        self.delete_model_button.clicked.connect(self._delete_selected_model)
        action_row.addWidget(self.delete_model_button)
        action_row.addStretch(1)

        export_layout.addRow("导出目录", self.export_path_input)
        export_layout.addRow("产物格式", self.format_box)

        section.body_layout.addLayout(info_layout)
        section.body_layout.addLayout(export_layout)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(note_label)
        return section

    def _build_export_result_card(self) -> SectionCard:
        """创建产物文件展示区。"""

        section = SectionCard("产物清单", "显示当前模型目录下的真实文件。", compact=True)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.export_summary_badge = StatusBadge("待生成", "info", size="sm")
        self.export_summary_label = QLabel("尚未生成真实模型文件。")
        self.export_summary_label.setObjectName("MutedText")
        self.export_summary_label.setWordWrap(True)
        status_row.addWidget(self.export_summary_badge)
        status_row.addWidget(self.export_summary_label, 1)

        self.export_result_table = QTableWidget(0, 3)
        self.export_result_table.setHorizontalHeaderLabels(["文件名", "类型", "路径"])
        self.export_result_table.horizontalHeader().setStretchLastSection(True)
        self.export_result_table.verticalHeader().setVisible(False)
        self.export_result_table.setAlternatingRowColors(True)
        configure_scrollable(self.export_result_table)

        section.body_layout.addWidget(
            VisualInfoStrip(
                "当前模型库",
                "真实训练完成后会生成 model.joblib 与 metadata.json。即使没有选中模型，也可以通过上方模型列表切换查看当前成果物。",
                illustration_name="empty_no_model.svg",
                ornament_name="decor_data_panel_b.svg",
            )
        )
        section.body_layout.addLayout(status_row)
        section.body_layout.addWidget(self.export_result_table)
        return section

    def _build_model_test_card(self) -> SectionCard:
        """创建训练页内的模型测试工作区。"""

        self.eval_status_badge = StatusBadge("待测试", "info", size="sm")
        section = SectionCard(
            "模型测试",
            "导入外部带标签测试集 CSV，对当前类型识别模型执行批量评估。",
            right_widget=self.eval_status_badge,
            compact=True,
        )

        control_layout = QFormLayout()
        control_layout.setHorizontalSpacing(12)
        control_layout.setVerticalSpacing(12)

        self.eval_model_box = QComboBox()

        csv_row = QHBoxLayout()
        csv_row.setSpacing(10)
        self.eval_manifest_input = QLineEdit()
        self.eval_manifest_input.setPlaceholderText("选择带标签测试集 CSV（sample_id,sample_file_path,label_type）")
        browse_button = QPushButton("选择 CSV")
        browse_button.clicked.connect(self._choose_evaluation_manifest)
        csv_row.addWidget(self.eval_manifest_input, 1)
        csv_row.addWidget(browse_button)

        self.eval_progress = QProgressBar()
        self.eval_progress.setRange(0, 100)
        self.eval_progress.setValue(0)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.eval_start_button = QPushButton("开始测试")
        self.eval_start_button.setObjectName("PrimaryButton")
        self.eval_start_button.clicked.connect(self._start_model_evaluation)
        action_row.addWidget(self.eval_start_button)
        action_row.addStretch(1)

        hint_label = QLabel("CSV 固定字段：sample_id、sample_file_path、label_type。样本文件格式固定为当前训练链路使用的 .npy IQ 样本。")
        hint_label.setObjectName("MutedText")
        hint_label.setWordWrap(True)

        control_layout.addRow("测试模型", self.eval_model_box)
        control_layout.addRow("测试清单", csv_row)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.eval_count_metric = MetricCard("测试样本", "0", compact=True)
        self.eval_accuracy_metric = MetricCard("测试准确率", "-", accent_color="#7CB98B", compact=True)
        self.eval_f1_metric = MetricCard("测试宏平均 F1", "-", accent_color="#C59A63", compact=True)
        self.eval_output_metric = MetricCard("测试报告", "-", accent_color="#6CA5D9", compact=True)
        metrics_row.addWidget(self.eval_count_metric)
        metrics_row.addWidget(self.eval_accuracy_metric)
        metrics_row.addWidget(self.eval_f1_metric)
        metrics_row.addWidget(self.eval_output_metric)

        self.eval_log = QPlainTextEdit()
        self.eval_log.setReadOnly(True)
        self.eval_log.setPlainText("当前还没有执行批量模型测试。")
        self.eval_log.setMinimumHeight(180)
        configure_scrollable(self.eval_log)

        self.eval_confusion_output = QPlainTextEdit()
        self.eval_confusion_output.setReadOnly(True)
        self.eval_confusion_output.setPlainText("测试完成后，这里会显示混淆矩阵与报告输出路径。")
        self.eval_confusion_output.setMinimumHeight(180)
        configure_scrollable(self.eval_confusion_output)

        output_row = QHBoxLayout()
        output_row.setSpacing(12)
        output_row.addWidget(self.eval_log, 1)
        output_row.addWidget(self.eval_confusion_output, 1)

        self.eval_detail_table = QTableWidget(0, 5)
        self.eval_detail_table.setHorizontalHeaderLabels(["类别", "精确率", "召回率", "F1", "样本数"])
        self.eval_detail_table.horizontalHeader().setStretchLastSection(True)
        self.eval_detail_table.verticalHeader().setVisible(False)
        self.eval_detail_table.setAlternatingRowColors(True)
        configure_scrollable(self.eval_detail_table)

        section.body_layout.addLayout(control_layout)
        section.body_layout.addWidget(self.eval_progress)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(hint_label)
        section.body_layout.addLayout(metrics_row)
        section.body_layout.addLayout(output_row)
        section.body_layout.addWidget(self.eval_detail_table)
        return section

    def _start_training(self) -> None:
        """启动真实训练任务。"""

        if self._is_running():
            return

        if self.task_type_box.currentIndex() != 0:
            self.training_status_badge.set_status("待接入", "warning", size="sm")
            self.training_log.setPlainText("个体指纹识别训练入口已保留，真实训练服务待接入；本轮请切回“类型识别（真实训练）”。")
            return

        detail = self._current_dataset_detail()
        if detail is None:
            self.training_status_badge.set_status("无数据集", "danger", size="sm")
            self.training_log.setPlainText("当前没有可用的数据集版本，请先在数据集管理页生成版本。")
            return

        error_message = self._validate_training_ready(detail)
        if error_message:
            self.training_status_badge.set_status("不可训练", "danger", size="sm")
            self.training_log.setPlainText(error_message)
            return

        record = detail.version
        thread = QThread(self)
        worker = TrainRunWorker(
            version_id=record.version_id,
            model_name=self.model_name_input.text().strip() or f"rf_type_{record.version_id}",
            n_estimators=self.n_estimators_spin.value(),
            max_depth=self.max_depth_spin.value(),
            random_state=self.random_state_spin.value(),
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.started.connect(self._on_train_started)
        worker.progress_changed.connect(self._on_train_progress)
        worker.cancelled.connect(self._on_train_cancelled)
        worker.finished.connect(self._on_train_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.cancelled.connect(thread.quit)
        worker.cancelled.connect(worker.deleteLater)
        worker.failed.connect(self._on_train_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_train_worker)
        thread.finished.connect(thread.deleteLater)

        self._train_thread = thread
        self._train_worker = worker
        self._stop_requested = False
        self._set_running_state(True)
        thread.start()

    def _choose_evaluation_manifest(self) -> None:
        """选择一个外部测试集 CSV 清单。"""

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择模型测试清单",
            str(Path.cwd()),
            "CSV 文件 (*.csv)",
        )
        if file_path:
            self.eval_manifest_input.setText(file_path)

    def _start_model_evaluation(self) -> None:
        """启动一次批量模型测试任务。"""

        if self._eval_thread is not None:
            return

        record = self.eval_model_box.currentData()
        if not isinstance(record, TrainedModelRecord):
            self.eval_status_badge.set_status("待模型", "warning", size="sm")
            self.eval_log.setPlainText("请先在训练页生成或选择一个真实类型识别模型。")
            return

        manifest_csv_path = self.eval_manifest_input.text().strip()
        if not manifest_csv_path:
            self.eval_status_badge.set_status("待清单", "warning", size="sm")
            self.eval_log.setPlainText("请先选择外部测试集 CSV 清单。")
            return

        thread = QThread(self)
        worker = ModelEvalWorker(model_id=record.model_id, manifest_csv_path=manifest_csv_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_eval_started)
        worker.progress_changed.connect(self._on_eval_progress)
        worker.finished.connect(self._on_eval_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_eval_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_eval_worker)

        self._eval_thread = thread
        self._eval_worker = worker
        self._set_eval_running_state(True)
        thread.start()

    def _request_stop_training(self) -> None:
        """请求当前训练任务在安全检查点停止。"""

        if not self._is_running() or self._train_worker is None or self._stop_requested:
            return

        self._stop_requested = True
        self._train_worker.request_cancel()
        self.stop_button.setEnabled(False)
        self.training_status_badge.set_status("停止中", "warning", size="sm")
        self._append_training_log("已接收停止请求。若当前已进入随机森林拟合阶段，需等待该阶段结束后停止。")
        self.confusion_placeholder.setPlainText(
            "停止请求已接收。\n\n"
            "当前训练采用单次拟合方式；如果已经进入随机森林拟合阶段，无法瞬时强停，系统会在当前阶段结束后丢弃本次结果，不写入模型。"
        )

    def _on_train_started(self, version_id: str) -> None:
        """在训练真正开始时刷新状态。"""

        self.training_status_badge.set_status("正在准备训练", "info", size="sm")
        self.training_log.setPlainText(
            "\n".join(
                [
                    f"开始训练类型识别模型 | 数据集版本 {version_id}",
                    "当前训练属于传统机器学习的单次拟合过程，不是按 epoch 连续刷新的深度学习训练。",
                    f"当前参数：trees={self.n_estimators_spin.value()} / max_depth={self._format_depth_text(self.max_depth_spin.value())} / seed={self.random_state_spin.value()}",
                ]
            )
        )
        self.confusion_placeholder.setPlainText(
            "训练进行中，请稍候...\n\n"
            "当前会按阶段执行：读取版本 -> 统计划分 -> 提取特征 -> 训练随机森林 -> 评估结果 -> 写入模型。"
        )

    def _on_train_progress(self, stage_text: str, log_text: str) -> None:
        """在训练过程中持续刷新阶段性状态。"""

        self.training_status_badge.set_status(stage_text, "info", size="sm")
        self.confusion_placeholder.setPlainText(
            "\n".join(
                [
                    f"当前阶段：{stage_text}",
                    "",
                    "当前训练属于单次拟合过程，不会像 epoch 式训练那样连续刷新 loss 曲线。",
                    "相同数据集版本、参数与随机种子下，结果稳定重复是预期行为。",
                ]
            )
        )
        self._append_training_log(log_text)

    def _on_train_finished(self, result: TrainingRunResult) -> None:
        """渲染一次真实训练结果。"""

        self._set_running_state(False)
        self._stop_requested = False
        self.training_status_badge.set_status("训练完成", "success", size="sm")
        self.val_accuracy_metric.set_value(result.model_record.validation_accuracy_text)
        self.accuracy_metric.set_value(result.model_record.accuracy_text)
        self.f1_metric.set_value(result.model_record.macro_f1_text)
        self.export_metric.set_value("joblib")
        self.training_log.setPlainText("\n".join(result.logs))
        self.confusion_placeholder.setPlainText(self._build_training_summary(result))
        self._refresh_detail_table(result.metric_rows)

        self._refresh_trained_model_list_from_database(preferred_model_id=result.model_record.model_id)
        self.export_status_badge.set_status("已生成", "success", size="sm")
        self.export_summary_badge.set_status("可用于识别", "success", size="sm")
        self.export_summary_label.setText(
            f"最新模型 {result.model_record.model_id} 已生成，可直接在识别页加载并执行类型识别。"
        )

    def _on_train_cancelled(self, message: str) -> None:
        """渲染一次协作式停止结果。"""

        self._set_running_state(False)
        self._stop_requested = False
        self.training_status_badge.set_status("已停止", "warning", size="sm")
        self.training_log.appendPlainText(message)
        self.confusion_placeholder.setPlainText(
            "本次训练已停止。\n\n"
            "当前请求已在安全检查点生效，本次不会生成新的模型记录，也不会写入新的模型产物。"
        )
        self._refresh_trained_model_list_from_database()
        if self.trained_models:
            self.export_summary_label.setText("本次训练已停止，未生成新模型；当前已有模型记录保持不变。")
        else:
            self.export_metric.set_value("未生成")
            self.export_summary_badge.set_status("待模型", "info", size="sm")
            self.export_summary_label.setText("本次训练已停止，且当前没有可用模型记录。")

    def _on_train_failed(self, message: str) -> None:
        """渲染训练失败结果。"""

        self._set_running_state(False)
        self._stop_requested = False
        self.training_status_badge.set_status("训练失败", "danger", size="sm")
        self.training_log.setPlainText(message)
        self.confusion_placeholder.setPlainText("训练未完成，请先修正数据集或模型配置后重试。")

    def _on_eval_started(self, model_id: str) -> None:
        """在模型测试真正开始时刷新状态。"""

        self.eval_status_badge.set_status("测试中", "warning", size="sm")
        self.eval_progress.setValue(0)
        self.eval_count_metric.set_value("0")
        self.eval_accuracy_metric.set_value("-")
        self.eval_f1_metric.set_value("-")
        self.eval_output_metric.set_value("-")
        self.eval_detail_table.setRowCount(0)
        self.eval_log.setPlainText(
            "\n".join(
                [
                    f"开始测试类型识别模型 | 模型 {model_id}",
                    f"测试清单：{self.eval_manifest_input.text().strip()}",
                ]
            )
        )
        self.eval_confusion_output.setPlainText(
            "模型测试执行中。\n\n"
            "当前会逐条读取外部带标签测试样本，复用真实特征提取与真实模型推理能力完成批量评估。"
        )

    def _on_eval_progress(self, percent: int, stage_text: str, log_text: str) -> None:
        """渲染模型测试阶段进度。"""

        self.eval_status_badge.set_status(stage_text, "warning", size="sm")
        self.eval_progress.setValue(percent)
        current_text = self.eval_log.toPlainText()
        if current_text.endswith(log_text):
            return
        self.eval_log.appendPlainText(log_text)

    def _on_eval_finished(self, result: ModelEvaluationResult) -> None:
        """渲染一次批量模型测试结果。"""

        self._set_eval_running_state(False)
        self.eval_status_badge.set_status("测试完成", "success", size="sm")
        self.eval_progress.setValue(100)
        self.eval_count_metric.set_value(str(result.sample_count))
        self.eval_accuracy_metric.set_value(f"{result.accuracy * 100:.1f}%")
        self.eval_f1_metric.set_value(f"{result.macro_f1:.3f}")
        self.eval_output_metric.set_value(Path(result.report_path).name)
        self.eval_log.setPlainText("\n".join(result.logs))
        self.eval_confusion_output.setPlainText(self._build_evaluation_summary(result))
        self._refresh_evaluation_detail_table(result.metric_rows)

    def _on_eval_failed(self, message: str) -> None:
        """渲染模型测试失败结果。"""

        self._set_eval_running_state(False)
        self.eval_status_badge.set_status("测试失败", "danger", size="sm")
        self.eval_log.setPlainText(message)
        self.eval_confusion_output.setPlainText("模型测试未完成，请先修正外部测试清单或模型状态后重试。")

    def _run_dataset_check(self) -> None:
        """执行训练前的数据集检查。"""

        detail = self._current_dataset_detail()
        if detail is None:
            self.training_log.setPlainText("当前没有可用的数据集版本，请先在数据集管理页生成版本。")
            return

        record = detail.version
        label_counts = self._actual_label_counts(detail)
        split_counts = self._split_counts(detail)
        label_summary = " / ".join(f"{self._display_label(label)}={count}" for label, count in sorted(label_counts.items()))
        lines = [
            f"[Check] 数据集版本：{record.version_id}",
            f"[Check] 任务类型：{record.task_type}",
            f"[Check] Manifest：{detail.manifest_path}",
            f"[Check] 清单样本数：{len(detail.items)}",
            f"[Check] 划分数量：train={split_counts.get('train', 0)} / val={split_counts.get('val', 0)} / test={split_counts.get('test', 0)}",
            f"[Check] 标签数：{len(label_counts)}",
            f"[Check] 标签分布：{label_summary or '-'}",
            f"[Check] 当前训练参数：trees={self.n_estimators_spin.value()} / max_depth={self._format_depth_text(self.max_depth_spin.value())} / seed={self.random_state_spin.value()}",
        ]

        if detail.missing_file_count:
            lines.append(f"[Warn] 有 {detail.missing_file_count} 个样本文件不存在。")
        else:
            lines.append("[OK] 样本文件路径检查通过。")

        if detail.empty_label_count:
            lines.append(f"[Warn] 有 {detail.empty_label_count} 条样本标签为空。")
        else:
            lines.append("[OK] 标签完整性检查通过。")

        error_message = self._validate_training_ready(detail)
        if error_message:
            lines.append(f"[Warn] {error_message}")
        else:
            lines.append("[OK] 当前数据集已满足类型识别真实训练条件。")

        self.training_log.setPlainText("\n".join(lines))

    def _build_training_summary(self, result: TrainingRunResult) -> str:
        """构建训练摘要和混淆矩阵文本。"""

        record = result.model_record
        accuracy_text = record.accuracy_text
        f1_text = record.macro_f1_text
        label_lines = [f"- {self._display_label(label)}: {count}" for label, count in sorted(result.label_counts.items())]

        summary_lines = [
            f"模型编号：{record.model_id}",
            f"数据集版本：{record.dataset_version_id}",
            f"任务类型：{record.task_type}",
            f"训练算法：{record.model_kind}",
            f"验证精度：{record.validation_accuracy_text}",
            f"特征维度：{result.feature_count}",
            f"测试精度：{accuracy_text} | 宏平均 F1：{f1_text}",
            f"训练参数：trees={record.n_estimators_text} / max_depth={record.max_depth_text} / seed={record.random_state_text}",
            f"说明：当前结果来自固定版本 {record.dataset_version_id} 的一次可复现实验。",
            "",
            "标签分布：",
            *label_lines,
            "",
            "混淆矩阵（测试集）：",
        ]

        labels = [row.label for row in result.metric_rows]
        if not labels or not result.confusion_matrix:
            summary_lines.append("当前没有可展示的混淆矩阵。")
            return "\n".join(summary_lines)

        header = "True\\Pred".ljust(18)
        for label in labels:
            header += self._display_label(label)[:14].ljust(16)
        summary_lines.append(header)

        for row_label, row_values in zip(labels, result.confusion_matrix):
            line = self._display_label(row_label)[:14].ljust(18)
            for value in row_values:
                line += str(value).ljust(16)
            summary_lines.append(line)

        summary_lines.extend(
            [
                "",
                f"模型文件：{record.artifact_path}",
                "当前生成的是 demo 可直接加载的真实模型文件，可继续在识别页完成本地验证。",
            ]
        )
        return "\n".join(summary_lines)

    def _build_evaluation_summary(self, result: ModelEvaluationResult) -> str:
        """构建一次批量模型测试的摘要文本。"""

        summary_lines = [
            f"测试模型：{result.model_record.model_id}",
            f"来源版本：{result.model_record.dataset_version_id}",
            f"测试清单：{result.manifest_csv_path}",
            f"测试样本数：{result.sample_count}",
            f"正确率：{result.accuracy * 100:.2f}%",
            f"宏平均 F1：{result.macro_f1:.4f}",
            f"报告文件：{result.report_path}",
            f"指标文件：{result.metrics_csv_path}",
            "",
            "混淆矩阵：",
        ]

        labels = [row.label for row in result.metric_rows]
        if not labels or not result.confusion_matrix:
            summary_lines.append("当前没有可展示的混淆矩阵。")
            return "\n".join(summary_lines)

        header = "True\\Pred".ljust(18)
        for label in labels:
            header += self._display_label(label)[:14].ljust(16)
        summary_lines.append(header)

        for row_label, row_values in zip(labels, result.confusion_matrix):
            line = self._display_label(row_label)[:14].ljust(18)
            for value in row_values:
                line += str(value).ljust(16)
            summary_lines.append(line)
        return "\n".join(summary_lines)

    def _refresh_detail_table(self, metric_rows: list[TrainingMetricRow]) -> None:
        """刷新类别指标表。"""

        self.detail_table.setRowCount(len(metric_rows))
        for row_index, row in enumerate(metric_rows):
            values = [
                self._display_label(row.label),
                f"{row.precision:.3f}",
                f"{row.recall:.3f}",
                f"{row.f1:.3f}",
                str(row.support),
            ]
            for column, value in enumerate(values):
                item = self.detail_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.detail_table.setItem(row_index, column, item)
                item.setText(value)

    def _refresh_evaluation_detail_table(self, metric_rows: list[TrainingMetricRow]) -> None:
        """刷新模型测试的类别指标表。"""

        self.eval_detail_table.setRowCount(len(metric_rows))
        for row_index, row in enumerate(metric_rows):
            values = [
                self._display_label(row.label),
                f"{row.precision:.3f}",
                f"{row.recall:.3f}",
                f"{row.f1:.3f}",
                str(row.support),
            ]
            for column, value in enumerate(values):
                item = self.eval_detail_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.eval_detail_table.setItem(row_index, column, item)
                item.setText(value)

    def _refresh_trained_model_list_from_database(self, preferred_model_id: str | None = None) -> None:
        """从数据库刷新训练模型列表，并同步给识别页。"""

        self.trained_models = list_trained_models("类型识别")
        self.trained_models_updated.emit(self.get_trained_models())

        self.export_model_box.blockSignals(True)
        self.export_model_box.clear()
        self.eval_model_box.blockSignals(True)
        self.eval_model_box.clear()
        for record in self.trained_models:
            display_text = f"{record.model_id} | {record.dataset_version_id} | {record.accuracy_text}"
            self.export_model_box.addItem(display_text, record)
            self.eval_model_box.addItem(display_text, record)
        self.export_model_box.blockSignals(False)
        self.eval_model_box.blockSignals(False)

        if not self.trained_models:
            self._update_export_details(-1)
            self.eval_status_badge.set_status("待模型", "info", size="sm")
            self.eval_start_button.setEnabled(False)
            return

        target_index = 0
        if preferred_model_id:
            for index in range(self.export_model_box.count()):
                record = self.export_model_box.itemData(index)
                if isinstance(record, TrainedModelRecord) and record.model_id == preferred_model_id:
                    target_index = index
                    break
        self.export_model_box.setCurrentIndex(target_index)
        self.eval_model_box.setCurrentIndex(target_index)
        self.eval_start_button.setEnabled(self._eval_thread is None)
        self._update_export_details(target_index)

    def _update_export_details(self, index: int) -> None:
        """刷新当前选中模型的产物信息。"""

        record = self.export_model_box.itemData(index)
        if not isinstance(record, TrainedModelRecord):
            for value in self.export_detail_labels.values():
                value.setText("-")
            self.export_result_table.setRowCount(0)
            self.export_status_badge.set_status("待模型", "info", size="sm")
            self.export_summary_badge.set_status("待模型", "info", size="sm")
            self.export_summary_label.setText("当前没有可用模型记录，请先完成一次真实训练。")
            self.export_metric.set_value("未生成")
            self.delete_model_button.setEnabled(False)
            return

        self.export_detail_labels["任务类型"].setText(record.task_type)
        self.export_detail_labels["算法"].setText(record.model_kind)
        self.export_detail_labels["数据集版本"].setText(record.dataset_version_id)
        version_exists = any(item.version_id == record.dataset_version_id for item in self.dataset_versions)
        self.export_detail_labels["版本状态"].setText("正常" if version_exists else "来源版本已删除")
        self.export_detail_labels["随机种子"].setText(record.random_state_text)
        self.export_detail_labels["树数量"].setText(record.n_estimators_text)
        self.export_detail_labels["最大深度"].setText(record.max_depth_text)
        self.export_detail_labels["验证精度"].setText(record.validation_accuracy_text)
        self.export_detail_labels["测试精度"].setText(record.accuracy_text)
        self.export_detail_labels["模型路径"].setText(record.artifact_path)
        artifact_path = Path(record.artifact_path)
        metadata_path = artifact_path.with_name("metadata.json")
        model_exists = artifact_path.exists()
        metadata_exists = metadata_path.exists()
        if model_exists:
            self.export_status_badge.set_status(record.status, "success", size="sm")
            self.export_summary_badge.set_status("可识别", "success", size="sm")
            if version_exists:
                self.export_summary_label.setText(
                    f"模型 {record.model_id} 已就绪，可直接用于类型识别页面；当前真实产物为 joblib。"
                )
            else:
                self.export_summary_label.setText(
                    f"模型 {record.model_id} 仍可正常用于识别，但其来源数据集版本 {record.dataset_version_id} 已被删除。"
                )
        else:
            self.export_status_badge.set_status("模型缺失", "danger", size="sm")
            self.export_summary_badge.set_status("模型缺失", "danger", size="sm")
            self.export_summary_label.setText(
                f"模型记录 {record.model_id} 仍在数据库中，但模型文件已缺失：{artifact_path}"
            )
        self._refresh_export_result_table(record)
        if not model_exists and metadata_exists:
            self.export_summary_label.setText(
                f"模型记录 {record.model_id} 存在，但仅检测到 metadata.json，未找到 joblib 产物。"
            )
        self.delete_model_button.setEnabled(True)

    def _refresh_export_result_table(self, record: TrainedModelRecord) -> None:
        """根据模型目录刷新产物文件清单。"""

        artifact_path = Path(record.artifact_path)
        rows: list[tuple[str, str, str]] = []
        if artifact_path.exists():
            rows.append((artifact_path.name, "模型", str(artifact_path)))
        metadata_path = artifact_path.with_name("metadata.json")
        if metadata_path.exists():
            rows.append((metadata_path.name, "元数据", str(metadata_path)))

        self.export_result_table.setRowCount(len(rows))
        for row_index, row_data in enumerate(rows):
            for column, value in enumerate(row_data):
                item = self.export_result_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.export_result_table.setItem(row_index, column, item)
                item.setText(value)

    def _delete_selected_model(self) -> None:
        """删除当前选中的模型数据库记录，不删除本地模型文件。"""

        record = self.export_model_box.currentData()
        if not isinstance(record, TrainedModelRecord):
            self.export_summary_label.setText("请先选择要删除的模型。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除模型",
            f"确认从数据库删除模型 {record.model_id}？\n\n"
            "本操作只会移除 SQLite 中的模型记录，不会删除本地 model.joblib 或 metadata.json 文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        delete_trained_model(record.model_id)
        self._refresh_trained_model_list_from_database()
        self.export_metric.set_value("未生成" if not self.trained_models else "joblib")
        if not self.trained_models:
            self.training_status_badge.set_status("待模型", "info", size="sm")
            self.training_log.setPlainText("当前没有可用模型记录，请先执行训练生成真实模型。")
        self.export_summary_label.setText(
            f"已删除模型记录：{record.model_id}。本地模型文件未删除，可按需手动清理。"
        )

    def _on_dataset_changed(self) -> None:
        """切换数据集版本后刷新摘要信息。"""

        detail = self._current_dataset_detail()
        if detail is None:
            return

        if detail.version.task_type == "个体识别":
            self.task_type_box.setCurrentIndex(1)
        else:
            self.task_type_box.setCurrentIndex(0)

        self.model_name_input.setText(f"rf_type_{detail.version.version_id}")

        split_counts = self._split_counts(detail)
        label_counts = self._actual_label_counts(detail)
        self.training_log.setPlainText(
            "\n".join(
                [
                    f"当前数据集：{detail.version.version_id}",
                    f"任务类型：{detail.version.task_type}",
                    f"样本清单：{len(detail.items)} 条",
                    f"标签数：{len(label_counts)}",
                    f"数据划分：train={split_counts.get('train', 0)} / val={split_counts.get('val', 0)} / test={split_counts.get('test', 0)}",
                    f"Manifest：{detail.manifest_path}",
                    "点击“数据检查”可执行完整检查。满足条件后即可开始真实训练。",
                ]
            )
        )

    def _current_dataset_detail(self) -> DatasetVersionDetail | None:
        """读取当前选中数据集版本的完整详情。"""

        record = self.dataset_box.currentData()
        if not isinstance(record, DatasetVersionRecord):
            return None
        return get_dataset_version_detail(record.version_id)

    def _validate_training_ready(self, detail: DatasetVersionDetail) -> str:
        """检查当前数据集是否满足真实训练条件。"""

        if detail.version.task_type != "类型识别":
            return "当前只支持类型识别真实训练，请选择“类型识别”数据集版本。"
        if not detail.items:
            return "当前数据集版本没有样本清单。"
        if detail.missing_file_count:
            return f"当前版本有 {detail.missing_file_count} 个样本文件不存在。"
        if detail.empty_label_count:
            return f"当前版本有 {detail.empty_label_count} 条样本标签为空。"

        label_counts = self._actual_label_counts(detail)
        if len(label_counts) < 2:
            return "至少需要两类类型标签，当前数据集还不能执行真实训练。"

        split_counts = self._split_counts(detail)
        for split_name in ("train", "val", "test"):
            if split_counts.get(split_name, 0) <= 0:
                return f"当前版本缺少 {split_name} 集样本，请先调整数据集划分。"
        return ""

    def _split_counts(self, detail: DatasetVersionDetail) -> dict[str, int]:
        """统计一个版本下 train / val / test 的样本数量。"""

        counts: dict[str, int] = {"train": 0, "val": 0, "test": 0}
        for item in detail.items:
            counts[item.split] = counts.get(item.split, 0) + 1
        return counts

    def _actual_label_counts(self, detail: DatasetVersionDetail) -> dict[str, int]:
        """基于真实样本清单统计标签数，避免使用过期版本摘要。"""

        counts = Counter(item.label_value for item in detail.items if item.label_value)
        return {str(key): int(value) for key, value in counts.items()}

    def _switch_config_mode(self, index: int) -> None:
        """切换训练模式配置区。"""

        self.config_stack.setCurrentIndex(index)
        if index == 1:
            self.training_status_badge.set_status("待接入", "warning", size="sm")
        elif not self._is_running():
            self.training_status_badge.set_status("待启动", "info", size="sm")

    def _set_running_state(self, running: bool) -> None:
        """根据训练状态统一启用或禁用控件。"""

        self.dataset_box.setEnabled(not running)
        self.task_type_box.setEnabled(not running)
        self.model_name_input.setEnabled(not running)
        self.n_estimators_spin.setEnabled(not running)
        self.max_depth_spin.setEnabled(not running)
        self.random_state_spin.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running and not self._stop_requested)
        self.eval_model_box.setEnabled(not running and self._eval_thread is None)
        self.eval_manifest_input.setEnabled(not running and self._eval_thread is None)
        self.eval_start_button.setEnabled((not running) and self._eval_thread is None and bool(self.trained_models))

    def _set_eval_running_state(self, running: bool) -> None:
        """根据模型测试状态统一启用或禁用测试控件。"""

        self.eval_model_box.setEnabled(not running and not self._is_running())
        self.eval_manifest_input.setEnabled(not running and not self._is_running())
        self.eval_start_button.setEnabled((not running) and not self._is_running() and bool(self.trained_models))
        self.start_button.setEnabled((not running) and not self._is_running())

    def _is_running(self) -> bool:
        """返回当前是否存在正在执行的训练任务。"""

        return self._train_thread is not None

    def _clear_train_worker(self) -> None:
        """在线程退出后清理训练 worker 引用。"""

        self._train_thread = None
        self._train_worker = None

    def _clear_eval_worker(self) -> None:
        """在线程退出后清理模型测试 worker 引用。"""

        self._eval_thread = None
        self._eval_worker = None
        self.eval_start_button.setEnabled(bool(self.trained_models) and not self._is_running())

    def _display_label(self, label: str) -> str:
        """把标签转换为适合界面展示的文本。"""

        return label.replace("_", " ")

    def _append_training_log(self, message: str) -> None:
        """向训练日志追加一条阶段消息，避免重复刷同一行。"""

        current_text = self.training_log.toPlainText()
        if current_text.endswith(message):
            return
        self.training_log.appendPlainText(message)

    def _format_depth_text(self, max_depth: int) -> str:
        """把训练页中的最大深度配置转换为展示文本。"""

        return "不限" if int(max_depth) <= 0 else str(int(max_depth))
