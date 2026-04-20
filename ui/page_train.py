"""Training page for placeholder model training and export workflows."""

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
from services import DatasetVersionRecord
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class TrainPage(QWidget):
    """Workflow page used to configure training, evaluate results, and export models."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the training page."""

        super().__init__(parent)
        self.dataset_versions: list[DatasetVersionRecord] = []
        self.export_models: list[dict[str, str]] = []

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.accuracy_metric = MetricCard("最新精度", "94.7%", compact=True)
        self.f1_metric = MetricCard("F1 分数", "0.942", accent_color="#7CB98B", compact=True)
        self.export_metric = MetricCard("导出格式", "ONNX", accent_color="#C59A63", compact=True)
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
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def set_dataset_versions(self, records: list[DatasetVersionRecord]) -> None:
        """Refresh the dataset selector from the dataset-management page."""

        self.dataset_versions = list(records)
        current_version = self.dataset_box.currentData().version_id if isinstance(self.dataset_box.currentData(), DatasetVersionRecord) else None

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

    def _build_config_card(self) -> SectionCard:
        """Create the training configuration card."""

        self.training_status_badge = StatusBadge("待启动", "info", size="sm")
        section = SectionCard(
            "训练配置",
            "选择任务类型、数据集版本和训练参数。当前优先验证预处理输出样本的训练链路。",
            right_widget=self.training_status_badge,
            compact=True,
        )

        switch_row = QHBoxLayout()
        switch_row.setSpacing(12)
        self.task_type_box = QComboBox()
        self.task_type_box.addItems(["类型识别（机器学习）", "个体识别（深度学习）"])
        self.task_type_box.currentIndexChanged.connect(self._switch_config_mode)

        self.dataset_box = QComboBox()

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
        start_button = QPushButton("执行训练")
        start_button.setObjectName("PrimaryButton")
        start_button.clicked.connect(self._run_placeholder_training)

        stop_button = QPushButton("中止训练")
        stop_button.setObjectName("DangerButton")

        validate_button = QPushButton("数据检查")
        validate_button.clicked.connect(self._run_dataset_check)

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

        section = SectionCard("结果评估", "显示当前训练摘要、混淆矩阵文本和分类明细。", compact=True)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)

        self.confusion_placeholder = QPlainTextEdit()
        self.confusion_placeholder.setReadOnly(True)
        self.confusion_placeholder.setPlainText(
            "训练摘要显示区\n\n"
            "执行训练后，这里会按当前数据集版本刷新任务摘要和二分类混淆矩阵文本。"
        )
        self.confusion_placeholder.setMinimumHeight(240)
        configure_scrollable(self.confusion_placeholder)

        self.training_log = QPlainTextEdit()
        self.training_log.setReadOnly(True)
        self.training_log.setPlainText(
            "等待训练任务启动。\n"
            "当前页面会消费数据集管理页生成的数据集版本。"
        )
        self.training_log.setMinimumHeight(240)
        configure_scrollable(self.training_log)

        summary_row.addWidget(self.confusion_placeholder, 2)
        summary_row.addWidget(self.training_log, 1)

        self.detail_table = QTableWidget(0, 5)
        self.detail_table.setHorizontalHeaderLabels(["类别 / 个体", "精确率", "召回率", "F1", "样本数"])
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setAlternatingRowColors(True)
        configure_scrollable(self.detail_table)

        section.body_layout.addLayout(summary_row)
        section.body_layout.addWidget(self.detail_table)
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

        self._set_export_models(
            [
                {
                    "name": "rf_type_v001",
                    "task_type": "类型识别",
                    "algorithm": "RandomForest",
                    "dataset_version": "v003",
                    "accuracy": "94.7%",
                },
                {
                    "name": "iqcnn_v003",
                    "task_type": "个体识别",
                    "algorithm": "1D-CNN",
                    "dataset_version": "v002",
                    "accuracy": "92.4%",
                },
                {
                    "name": "cnn_lstm_v001",
                    "task_type": "个体识别",
                    "algorithm": "CNN + LSTM",
                    "dataset_version": "v002",
                    "accuracy": "93.1%",
                },
            ]
        )
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

    def _set_export_models(self, models: list[dict[str, str]]) -> None:
        """Replace the export model list and refresh the detail panel."""

        self.export_models = models
        current_name = self.export_model_box.currentData()["name"] if isinstance(self.export_model_box.currentData(), dict) else None
        self.export_model_box.blockSignals(True)
        self.export_model_box.clear()
        for model in models:
            display_text = f"{model['name']} | {model['task_type']} | {model['algorithm']}"
            self.export_model_box.addItem(display_text, model)
        self.export_model_box.blockSignals(False)

        if models:
            target_index = 0
            if current_name is not None:
                for index in range(self.export_model_box.count()):
                    model = self.export_model_box.itemData(index)
                    if isinstance(model, dict) and model["name"] == current_name:
                        target_index = index
                        break
            self.export_model_box.setCurrentIndex(target_index)
            self._update_export_details(target_index)

    def _run_dataset_check(self) -> None:
        """Run one lightweight dataset sanity check."""

        record = self.dataset_box.currentData()
        if not isinstance(record, DatasetVersionRecord):
            self.training_log.setPlainText("当前没有可用的数据集版本，请先在数据集管理页生成版本。")
            return

        binary_type = self._is_binary_type_dataset(record)
        label_summary = " / ".join(self._display_label(label) for label in sorted(record.label_counts))
        lines = [
            f"[Check] 数据集版本：{record.version_id}",
            f"[Check] 任务类型：{record.task_type}",
            f"[Check] 样本数：{record.sample_count}",
            f"[Check] 来源：{record.source_summary}",
            f"[Check] 类别 / 个体数量：{len(record.label_counts)}",
            f"[Check] 标签分布：{label_summary}",
        ]
        if len(record.label_counts) == 1:
            lines.append("[Warn] 当前为单类数据集，仅用于链路验证，不适合作为最终模型评估依据。")
        elif binary_type:
            lines.append("[OK] 当前为二分类类型识别数据集，可继续执行训练联调。")
        elif record.task_type == "类型识别":
            lines.append("[OK] 当前为多类类型识别数据集，可继续执行类型识别占位训练流程。")
        else:
            lines.append("[OK] 当前数据集具备多类标签，可继续执行占位训练流程。")
        self.training_log.setPlainText("\n".join(lines))

    def _run_placeholder_training(self) -> None:
        """Run one placeholder training flow from the current dataset version."""

        record = self.dataset_box.currentData()
        if not isinstance(record, DatasetVersionRecord):
            self.training_status_badge.set_status("无数据集", "danger", size="sm")
            self.training_log.setPlainText("未选择有效数据集版本，请先在数据集管理页生成版本。")
            return

        label_count = len(record.label_counts)
        is_single_class = label_count == 1
        binary_type = self._is_binary_type_dataset(record)
        task_type = record.task_type

        if is_single_class:
            accuracy_text = "100.0%"
            f1_text = "1.000"
            self.training_status_badge.set_status("单类验证", "warning", size="sm")
        elif binary_type:
            accuracy_text = "95.6%"
            f1_text = "0.955"
            self.training_status_badge.set_status("二分类完成", "success", size="sm")
        else:
            accuracy_text = "93.8%" if task_type == "类型识别" else "92.6%"
            f1_text = "0.938" if task_type == "类型识别" else "0.926"
            self.training_status_badge.set_status("训练完成", "success", size="sm")

        self.accuracy_metric.set_value(accuracy_text)
        self.f1_metric.set_value(f1_text)
        self.export_metric.set_value("ONNX")

        self.confusion_placeholder.setPlainText(
            self._build_training_summary(record, is_single_class, binary_type, accuracy_text, f1_text)
        )

        log_lines = [
            f"[Start] 数据集版本 {record.version_id}",
            f"[Info] 任务类型 {task_type}",
            f"[Info] 样本总数 {record.sample_count}",
            f"[Info] 来源 {record.source_summary}",
        ]
        if is_single_class:
            log_lines.extend(
                [
                    "[Warn] 当前数据集仅含单类标签，本次训练结果仅用于验证样本 -> 数据集 -> 训练链路。",
                    "[Done] 已生成演示级模型输出，不代表最终识别能力。",
                ]
            )
        elif binary_type:
            label_lines = [f"[Info] 类别分布 {self._display_label(label)}={count}" for label, count in sorted(record.label_counts.items())]
            log_lines.extend(
                [
                    *label_lines,
                    "[Phase] 执行二分类数据校验与标签一致性检查。",
                    "[Epoch 01] train_acc=0.82, val_acc=0.80",
                    "[Epoch 08] train_acc=0.94, val_acc=0.93",
                    "[Epoch 16] train_acc=0.96, val_acc=0.95",
                    f"[Done] 二分类联调完成，最终精度 {accuracy_text}，F1 {f1_text}",
                ]
            )
        else:
            log_lines.extend(
                [
                    "[Info] 当前版本已具备多类标签，适合继续验证类型识别训练链路。",
                    "[Epoch 01] train_acc=0.78, val_acc=0.74",
                    "[Epoch 12] train_acc=0.91, val_acc=0.88",
                    f"[Done] 最终精度 {accuracy_text}，F1 {f1_text}",
                ]
            )
        self.training_log.setPlainText("\n".join(log_lines))

        self._refresh_detail_table(record, is_single_class, binary_type)
        self._append_export_model(record, accuracy_text)

    def _refresh_detail_table(self, record: DatasetVersionRecord, is_single_class: bool, binary_type: bool) -> None:
        """Render class-level placeholder metrics for the current dataset version."""

        rows = sorted(record.label_counts.items(), key=lambda item: item[0])
        self.detail_table.setRowCount(len(rows))

        for row_index, (label, count) in enumerate(rows):
            if is_single_class:
                values = [self._display_label(label), "1.00", "1.00", "1.00", str(count)]
            elif binary_type:
                precision = "0.96" if row_index == 0 else "0.95"
                recall = "0.95" if row_index == 0 else "0.96"
                f1 = "0.95" if row_index == 0 else "0.95"
                values = [self._display_label(label), precision, recall, f1, str(count)]
            else:
                precision = "0.94" if row_index % 2 == 0 else "0.92"
                recall = "0.95" if row_index % 2 == 0 else "0.91"
                f1 = "0.95" if row_index % 2 == 0 else "0.92"
                values = [self._display_label(label), precision, recall, f1, str(count)]
            for column, value in enumerate(values):
                item = self.detail_table.item(row_index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.detail_table.setItem(row_index, column, item)
                item.setText(value)

    def _is_binary_type_dataset(self, record: DatasetVersionRecord) -> bool:
        """Return whether one dataset should be shown as a binary type-recognition run."""

        return record.task_type == "类型识别" and len(record.label_counts) == 2

    def _display_label(self, label: str) -> str:
        """Return a UI-friendly label for summary text and result tables."""

        return label.replace("_", " ")

    def _build_training_summary(
        self,
        record: DatasetVersionRecord,
        is_single_class: bool,
        binary_type: bool,
        accuracy_text: str,
        f1_text: str,
    ) -> str:
        """Build the summary and confusion-matrix text shown in the result area."""

        label_lines = [f"- {self._display_label(label)}: {count}" for label, count in sorted(record.label_counts.items())]
        summary_lines = [
            f"当前版本：{record.version_id}",
            f"任务类型：{record.task_type}",
            f"来源：{record.source_summary}",
            f"标签数量：{len(record.label_counts)}",
            f"最新精度：{accuracy_text} | F1：{f1_text}",
            "",
            "标签分布：",
            *label_lines,
            "",
        ]

        if is_single_class:
            summary_lines.extend(
                [
                    "当前为单类验证模式。",
                    "本区域仅用于确认预处理样本 -> 数据集版本 -> 训练页面的链路可用。",
                ]
            )
            return "\n".join(summary_lines)

        if binary_type:
            labels = sorted(record.label_counts.items(), key=lambda item: item[0])
            (label_a, count_a), (label_b, count_b) = labels
            error_a = max(1, round(count_a * 0.05))
            error_b = max(1, round(count_b * 0.04))
            matrix_lines = [
                "二分类混淆矩阵（占位）",
                "",
                f"                Pred {self._display_label(label_a):<14} Pred {self._display_label(label_b)}",
                f"True {self._display_label(label_a):<14}{count_a - error_a:<18}{error_a}",
                f"True {self._display_label(label_b):<14}{error_b:<18}{count_b - error_b}",
                "",
                "当前结果用于二分类类型识别联调展示。",
            ]
            return "\n".join([*summary_lines, *matrix_lines])

        summary_lines.extend(
            [
                "当前为多类占位训练结果展示区。",
                "后续接入真实训练后，这里可替换为正式混淆矩阵与评估指标。",
            ]
        )
        return "\n".join(summary_lines)

    def _append_export_model(self, record: DatasetVersionRecord, accuracy_text: str) -> None:
        """Append or refresh one exportable placeholder model entry."""

        task_type = record.task_type
        if task_type == "类型识别":
            model_name = f"rf_type_{record.version_id}"
            algorithm = "RandomForest"
        else:
            model_name = f"iqcnn_{record.version_id}"
            algorithm = "1D-CNN"

        updated = False
        for model in self.export_models:
            if model["name"] != model_name:
                continue
            model["dataset_version"] = record.version_id
            model["accuracy"] = accuracy_text
            updated = True
            break

        if not updated:
            self.export_models.append(
                {
                    "name": model_name,
                    "task_type": task_type,
                    "algorithm": algorithm,
                    "dataset_version": record.version_id,
                    "accuracy": accuracy_text,
                }
            )

        self._set_export_models(self.export_models)
        for index in range(self.export_model_box.count()):
            model = self.export_model_box.itemData(index)
            if isinstance(model, dict) and model["name"] == model_name:
                self.export_model_box.setCurrentIndex(index)
                break

    def _update_export_details(self, index: int) -> None:
        """Refresh export model detail labels."""

        model = self.export_model_box.itemData(index)
        if not isinstance(model, dict):
            for value in self.export_detail_labels.values():
                value.setText("-")
            return

        self.export_detail_labels["任务类型"].setText(model["task_type"])
        self.export_detail_labels["算法"].setText(model["algorithm"])
        self.export_detail_labels["数据集版本"].setText(model["dataset_version"])
        self.export_detail_labels["最新精度"].setText(model["accuracy"])

    def _switch_config_mode(self, index: int) -> None:
        """Switch between the machine learning and deep learning config forms."""

        self.config_stack.setCurrentIndex(index)
