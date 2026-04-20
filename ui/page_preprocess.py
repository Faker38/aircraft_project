"""Preprocess page for CAP preview, parameter configuration, and algorithm execution."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)

from config import BASE_DIR
from services import (
    CapProbeError,
    CapProbeResult,
    PreprocessRunConfig,
    PreprocessRunResult,
    default_preprocess_output_dir,
    probe_cap_file,
    resolve_default_model_weights_path,
)
from ui.preprocess_run_worker import PreprocessRunWorker
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class PreprocessPage(QWidget):
    """Workflow page for CAP preview and preprocess execution."""

    navigate_requested = Signal(str)
    sample_records_generated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the preprocess page."""

        super().__init__(parent)
        self.cap_records = self._build_cap_records()
        self.current_probe_result: CapProbeResult | None = None
        self.current_run_result: PreprocessRunResult | None = None
        self._run_thread: QThread | None = None
        self._run_worker: PreprocessRunWorker | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.file_metric = MetricCard("CAP 文件", "0", compact=True)
        self.status_metric = MetricCard("任务状态", "待执行", accent_color="#7CB98B", compact=True)
        self.detected_metric = MetricCard("检出信号段", "0", accent_color="#C59A63", compact=True)
        self.output_metric = MetricCard("输出样本", "0", accent_color="#5EA6D3", compact=True)
        metrics_row.addWidget(self.file_metric)
        metrics_row.addWidget(self.status_metric)
        metrics_row.addWidget(self.detected_metric)
        metrics_row.addWidget(self.output_metric)
        content_layout.addLayout(metrics_row)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_file_card(), 3)
        top_row.addWidget(self._build_config_card(), 2)
        content_layout.addLayout(top_row)

        content_layout.addWidget(self._build_probe_card())
        content_layout.addWidget(self._build_result_card())
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self.file_metric.set_value(str(len(self.cap_records)))
        if self.file_table.rowCount():
            self.file_table.selectRow(0)
            self._update_file_selection_state()
            self._load_selected_cap_preview()
        else:
            self._reset_preview("当前未发现可用 CAP 文件。", badge_level="warning")

    def _build_cap_records(self) -> list[dict[str, object]]:
        """Build the current CAP file list from the workspace root."""

        workspace_root = BASE_DIR.parent
        records: list[dict[str, object]] = []
        candidates = [
            ("IQ_2025_01_09_13_55_30.cap", "完整样本"),
            ("head.cap", "头部截取"),
        ]
        for file_name, sample_kind in candidates:
            path = workspace_root / file_name
            records.append(
                {
                    "name": file_name,
                    "kind": sample_kind,
                    "path": path,
                    "location": "工作区根目录",
                    "exists": path.exists(),
                }
            )
        return records

    def _build_file_card(self) -> SectionCard:
        """Create the CAP file selection card."""

        section = SectionCard("原始文件", "选择 CAP 文件后，可先执行头信息预览，再发起预处理任务。", compact=True)

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "样本类型", "文件大小", "存放位置", "状态"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.file_table.itemSelectionChanged.connect(self._update_file_selection_state)
        configure_scrollable(self.file_table)

        self.file_table.setRowCount(len(self.cap_records))
        for row_index, record in enumerate(self.cap_records):
            path = Path(record["path"])
            exists = bool(record["exists"])
            size_text = self._format_bytes(path.stat().st_size) if exists else "-"
            status_text = "可联调" if exists else "文件缺失"
            values = [
                str(record["name"]),
                str(record["kind"]),
                size_text,
                str(record["location"]),
                status_text,
            ]
            for column, value in enumerate(values):
                self.file_table.setItem(row_index, column, QTableWidgetItem(value))

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.probe_button = QPushButton("读取头信息")
        self.probe_button.setObjectName("PrimaryButton")
        self.probe_button.clicked.connect(self._load_selected_cap_preview)

        self.file_status_badge = StatusBadge("待选择", "info", size="sm")

        action_row.addWidget(self.probe_button)
        action_row.addWidget(self.file_status_badge)
        action_row.addStretch(1)

        self.file_status_label = QLabel("当前支持先预览 CAP 头字段，再按同一文件发起预处理运行。")
        self.file_status_label.setObjectName("MutedText")
        self.file_status_label.setWordWrap(True)

        section.body_layout.addWidget(self.file_table)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.file_status_label)
        return section

    def _build_config_card(self) -> SectionCard:
        """Create the preprocess configuration card."""

        self.run_status_badge = StatusBadge("待执行", "info", size="sm")
        section = SectionCard(
            "预处理参数",
            "解析 CAP 头后自动绑定带宽、采样率和中心频率，用户只配置必要的筛选参数。",
            right_widget=self.run_status_badge,
            compact=True,
        )

        parsed_layout = QFormLayout()
        parsed_layout.setHorizontalSpacing(12)
        parsed_layout.setVerticalSpacing(10)

        self.bandwidth_value = QLabel("-")
        self.bandwidth_value.setObjectName("ValueLabel")
        self.sample_rate_value = QLabel("-")
        self.sample_rate_value.setObjectName("ValueLabel")
        self.center_freq_value = QLabel("-")
        self.center_freq_value.setObjectName("ValueLabel")

        parsed_layout.addRow("分析带宽", self.bandwidth_value)
        parsed_layout.addRow("实际采样率", self.sample_rate_value)
        parsed_layout.addRow("中心频率", self.center_freq_value)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.slice_length_input = QSpinBox()
        self.slice_length_input.setRange(1024, 262144)
        self.slice_length_input.setSingleStep(1024)
        self.slice_length_input.setValue(4096)

        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0.0, 30.0)
        self.threshold_input.setDecimals(1)
        self.threshold_input.setSuffix(" dB")
        self.threshold_input.setValue(10.0)

        self.noise_floor_input = QDoubleSpinBox()
        self.noise_floor_input.setRange(-120.0, 0.0)
        self.noise_floor_input.setDecimals(1)
        self.noise_floor_input.setSuffix(" dBm")
        self.noise_floor_input.setValue(-90.0)

        self.min_bandwidth_input = QDoubleSpinBox()
        self.min_bandwidth_input.setRange(0.0, 80.0)
        self.min_bandwidth_input.setDecimals(1)
        self.min_bandwidth_input.setSuffix(" MHz")
        self.min_bandwidth_input.setValue(6.0)

        self.min_duration_input = QDoubleSpinBox()
        self.min_duration_input.setRange(0.01, 1000.0)
        self.min_duration_input.setDecimals(2)
        self.min_duration_input.setSuffix(" ms")
        self.min_duration_input.setValue(0.05)

        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.0, 1.0)
        self.confidence_input.setDecimals(2)
        self.confidence_input.setSingleStep(0.01)
        self.confidence_input.setValue(0.85)

        self.bandpass_checkbox = QCheckBox("启用带通滤波")
        self.bandpass_checkbox.setChecked(True)

        default_output_dir = default_preprocess_output_dir()
        self.output_dir_input = QLineEdit(str(default_output_dir))
        self.output_dir_input.setPlaceholderText(str(default_output_dir))

        try:
            default_model_path = resolve_default_model_weights_path()
            default_model_text = str(default_model_path)
        except Exception:
            default_model_text = ""
        self.model_path_input = QLineEdit(default_model_text)
        self.model_path_input.setPlaceholderText("选择或填写模型权重路径")

        form_layout.addRow("切片长度", self.slice_length_input)
        form_layout.addRow("能量阈值", self.threshold_input)
        form_layout.addRow("噪声基底", self.noise_floor_input)
        form_layout.addRow("最小带宽", self.min_bandwidth_input)
        form_layout.addRow("最小时长", self.min_duration_input)
        form_layout.addRow("置信度阈值", self.confidence_input)
        form_layout.addRow("滤波选项", self.bandpass_checkbox)
        form_layout.addRow("输出目录", self.output_dir_input)
        form_layout.addRow("模型权重", self.model_path_input)

        self.process_progress = QProgressBar()
        self.process_progress.setRange(0, 100)
        self.process_progress.setValue(0)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.start_button = QPushButton("开始预处理")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_preprocess_run)

        self.goto_dataset_button = QPushButton("进入数据集管理")
        self.goto_dataset_button.clicked.connect(lambda: self.navigate_requested.emit("dataset"))
        self.goto_dataset_button.setEnabled(False)

        button_row.addWidget(self.start_button)
        button_row.addWidget(self.goto_dataset_button)
        button_row.addStretch(1)

        self.config_status_label = QLabel("当前默认按 0x200 / 512 字节头长试跑，算法与界面保持同一口径。")
        self.config_status_label.setObjectName("MutedText")
        self.config_status_label.setWordWrap(True)

        section.body_layout.addLayout(parsed_layout)
        section.body_layout.addWidget(self.process_progress)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.config_status_label)
        return section

    def _build_probe_card(self) -> SectionCard:
        """Create the CAP preview card."""

        self.preview_status_badge = StatusBadge("待读取", "info", size="sm")
        section = SectionCard(
            "CAP 导入预览",
            "按当前试跑口径展示带宽、实际采样率、中心频率和少量 IQ 预览。",
            right_widget=self.preview_status_badge,
            compact=True,
        )

        info_form = QFormLayout()
        info_form.setHorizontalSpacing(12)
        info_form.setVerticalSpacing(10)

        self.preview_file_value = QLabel("-")
        self.preview_file_value.setObjectName("ValueLabel")
        self.preview_size_value = QLabel("-")
        self.preview_size_value.setObjectName("ValueLabel")
        self.preview_header_value = QLabel("0x200 / 512 B")
        self.preview_header_value.setObjectName("ValueLabel")
        self.preview_offset_value = QLabel("0x200")
        self.preview_offset_value.setObjectName("ValueLabel")
        self.preview_scope_value = QLabel("-")
        self.preview_scope_value.setObjectName("ValueLabel")

        info_form.addRow("文件", self.preview_file_value)
        info_form.addRow("文件大小", self.preview_size_value)
        info_form.addRow("头长度", self.preview_header_value)
        info_form.addRow("IQ 起始偏移", self.preview_offset_value)
        info_form.addRow("统计范围", self.preview_scope_value)

        self.preview_note_label = QLabel("请选择 CAP 文件后读取头信息。")
        self.preview_note_label.setObjectName("MutedText")
        self.preview_note_label.setWordWrap(True)

        self.preview_field_table = QTableWidget(6, 3)
        self.preview_field_table.setHorizontalHeaderLabels(["字段", "偏移", "值"])
        self.preview_field_table.horizontalHeader().setStretchLastSection(True)
        self.preview_field_table.verticalHeader().setVisible(False)
        self.preview_field_table.setAlternatingRowColors(True)
        self.preview_field_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.preview_field_table)

        field_rows = [
            ("版本号", "0x0000", "-"),
            ("分析带宽", "0x0010", "-"),
            ("实际采样率", "0x0010 × 1.28", "-"),
            ("中心频率", "0x0018", "-"),
            ("帧采样数", "0x0110", "-"),
            ("块大小", "0x0114", "-"),
        ]
        for row_index, row_data in enumerate(field_rows):
            for column, value in enumerate(row_data):
                self.preview_field_table.setItem(row_index, column, QTableWidgetItem(value))

        self.preview_stats_table = QTableWidget(2, 5)
        self.preview_stats_table.setHorizontalHeaderLabels(["分量", "均值", "标准差", "最小值", "最大值"])
        self.preview_stats_table.horizontalHeader().setStretchLastSection(True)
        self.preview_stats_table.verticalHeader().setVisible(False)
        self.preview_stats_table.setAlternatingRowColors(True)
        self.preview_stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.preview_stats_table)
        stats_rows = [
            ("I 分量", "-", "-", "-", "-"),
            ("Q 分量", "-", "-", "-", "-"),
        ]
        for row_index, row_data in enumerate(stats_rows):
            for column, value in enumerate(row_data):
                self.preview_stats_table.setItem(row_index, column, QTableWidgetItem(value))

        self.preview_iq_table = QTableWidget(0, 3)
        self.preview_iq_table.setHorizontalHeaderLabels(["序号", "I", "Q"])
        self.preview_iq_table.horizontalHeader().setStretchLastSection(True)
        self.preview_iq_table.verticalHeader().setVisible(False)
        self.preview_iq_table.setAlternatingRowColors(True)
        self.preview_iq_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.preview_iq_table)

        section.body_layout.addLayout(info_form)
        section.body_layout.addWidget(self.preview_note_label)
        section.body_layout.addWidget(self.preview_field_table)
        section.body_layout.addWidget(self.preview_stats_table)
        section.body_layout.addWidget(self.preview_iq_table)
        return section

    def _build_result_card(self) -> SectionCard:
        """Create the preprocess result card."""

        self.result_status_badge = StatusBadge("待执行", "info", size="sm")
        section = SectionCard(
            "预处理结果",
            "显示本次任务状态、输出目录、日志和有效信号段结果。",
            right_widget=self.result_status_badge,
            compact=True,
        )

        summary_form = QFormLayout()
        summary_form.setHorizontalSpacing(12)
        summary_form.setVerticalSpacing(10)

        self.run_state_value = QLabel("待执行")
        self.run_state_value.setObjectName("ValueLabel")
        self.detected_value = QLabel("0")
        self.detected_value.setObjectName("ValueLabel")
        self.output_value = QLabel("0")
        self.output_value.setObjectName("ValueLabel")
        self.output_dir_value = QLabel("-")
        self.output_dir_value.setObjectName("ValueLabel")
        self.output_dir_value.setWordWrap(True)

        summary_form.addRow("任务状态", self.run_state_value)
        summary_form.addRow("检出信号段", self.detected_value)
        summary_form.addRow("输出样本数", self.output_value)
        summary_form.addRow("输出目录", self.output_dir_value)

        self.result_message_label = QLabel("等待预处理任务启动。")
        self.result_message_label.setObjectName("MutedText")
        self.result_message_label.setWordWrap(True)

        log_and_table_row = QHBoxLayout()
        log_and_table_row.setSpacing(12)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlainText("等待日志输出。")
        self.log_output.setMinimumHeight(220)
        configure_scrollable(self.log_output)

        self.segment_table = QTableWidget(0, 10)
        self.segment_table.setHorizontalHeaderLabels(
            [
                "片段编号",
                "起始点",
                "结束点",
                "时长(ms)",
                "中心频率(Hz)",
                "带宽(Hz)",
                "SNR(dB)",
                "置信度",
                "输出文件",
                "状态",
            ]
        )
        self.segment_table.horizontalHeader().setStretchLastSection(True)
        self.segment_table.verticalHeader().setVisible(False)
        self.segment_table.setAlternatingRowColors(True)
        self.segment_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.segment_table)

        log_and_table_row.addWidget(self.log_output, 2)
        log_and_table_row.addWidget(self.segment_table, 3)

        section.body_layout.addLayout(summary_form)
        section.body_layout.addWidget(self.result_message_label)
        section.body_layout.addLayout(log_and_table_row)
        return section

    def _selected_record(self) -> dict[str, object] | None:
        """Return the currently selected CAP record."""

        row = self.file_table.currentRow()
        if row < 0 or row >= len(self.cap_records):
            return None
        return self.cap_records[row]

    def _update_file_selection_state(self) -> None:
        """Refresh selection-dependent controls for the file table."""

        record = self._selected_record()
        if record is None:
            self.probe_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.file_status_badge.set_status("未选择", "warning", size="sm")
            self.file_status_label.setText("请选择一条 CAP 文件记录后，再执行预览或预处理。")
            return

        path = Path(record["path"])
        exists = bool(record["exists"])
        self.probe_button.setEnabled(exists and not self._is_running())
        self.start_button.setEnabled(exists and not self._is_running())
        if exists:
            self.file_status_badge.set_status("可联调", "success", size="sm")
            self.file_status_label.setText(
                f"已选文件：{path.name} | 路径：{path} | 可继续执行头信息预览或预处理运行。"
            )
            if not self.output_dir_input.text().strip():
                self.output_dir_input.setText(str(self._default_output_dir_for(path)))
        else:
            self.file_status_badge.set_status("缺失", "danger", size="sm")
            self.file_status_label.setText(f"未找到文件：{path}。请确认样本文件位于工作区根目录。")

    def _load_selected_cap_preview(self) -> None:
        """Probe the selected CAP file and refresh the preview area."""

        record = self._selected_record()
        if record is None:
            self._reset_preview("请先选择一条 CAP 文件记录。", badge_level="warning")
            return

        path = Path(record["path"])
        try:
            result = probe_cap_file(path)
        except CapProbeError as exc:
            self._reset_preview(str(exc), badge_level="danger")
            self.status_metric.set_value("异常")
            return

        self._apply_probe_result(result)

    def _apply_probe_result(self, result: CapProbeResult) -> None:
        """Render a probe result into the preview widgets and config summary."""

        self.current_probe_result = result
        self.preview_status_badge.set_status("预览就绪", "success", size="sm")
        self.preview_file_value.setText(result.path.name)
        self.preview_size_value.setText(self._format_bytes(result.file_size))
        self.preview_header_value.setText(f"0x{result.header_length:03X} / {result.header_length} B")
        self.preview_offset_value.setText(f"0x{result.header_length:03X}")
        self.preview_scope_value.setText(f"前 {result.statistics_window_pairs:,} 组 IQ")

        note_text = "当前按 0x200 / 512 字节头长试跑，带宽与实际采样率已拆分展示。"
        if result.is_partial_capture:
            note_text = "当前为截取样本，仅代表前 1MB 数据窗口；用于快速验证头字段与早期 IQ 数据。"
        self.preview_note_label.setText(
            note_text + " 待确认字段：" + "、".join(result.unresolved_fields)
        )

        field_values = [
            result.version,
            f"{result.bandwidth_hz / 1_000_000:.3f} MHz",
            f"{result.sample_rate_hz / 1_000_000:.3f} MHz",
            f"{result.center_frequency_hz / 1_000_000:.3f} MHz",
            str(result.frame_sample_count),
            str(result.block_size),
        ]
        for row_index, value in enumerate(field_values):
            self._set_table_value(self.preview_field_table, row_index, 2, value)

        self._set_table_value(self.preview_stats_table, 0, 1, f"{result.statistics.i_mean:.2f}")
        self._set_table_value(self.preview_stats_table, 0, 2, f"{result.statistics.i_std:.2f}")
        self._set_table_value(self.preview_stats_table, 0, 3, str(result.statistics.i_min))
        self._set_table_value(self.preview_stats_table, 0, 4, str(result.statistics.i_max))
        self._set_table_value(self.preview_stats_table, 1, 1, f"{result.statistics.q_mean:.2f}")
        self._set_table_value(self.preview_stats_table, 1, 2, f"{result.statistics.q_std:.2f}")
        self._set_table_value(self.preview_stats_table, 1, 3, str(result.statistics.q_min))
        self._set_table_value(self.preview_stats_table, 1, 4, str(result.statistics.q_max))

        self.preview_iq_table.setRowCount(len(result.preview_pairs))
        for row_index, (sample_index, i_value, q_value) in enumerate(result.preview_pairs):
            values = [str(sample_index), str(i_value), str(q_value)]
            for column, value in enumerate(values):
                self._set_table_value(self.preview_iq_table, row_index, column, value)

        self.bandwidth_value.setText(f"{result.bandwidth_hz / 1_000_000:.3f} MHz")
        self.sample_rate_value.setText(f"{result.sample_rate_hz / 1_000_000:.3f} MHz")
        self.center_freq_value.setText(f"{result.center_frequency_hz / 1_000_000:.3f} MHz")
        self.status_metric.set_value("预览就绪")
        self.slice_length_input.setValue(self.slice_length_input.value())

    def _start_preprocess_run(self) -> None:
        """Collect the current parameters and start the preprocess worker."""

        if self._is_running():
            return

        record = self._selected_record()
        if record is None:
            self.result_message_label.setText("请先选择一条 CAP 文件记录。")
            return

        if self.current_probe_result is None or Path(record["path"]) != self.current_probe_result.path:
            self._load_selected_cap_preview()
            if self.current_probe_result is None:
                return

        input_path = Path(record["path"])
        config = PreprocessRunConfig(
            input_file_path=str(input_path),
            slice_length=self.slice_length_input.value(),
            energy_threshold_db=self.threshold_input.value(),
            noise_floor_dbm=self.noise_floor_input.value(),
            min_bandwidth_mhz=self.min_bandwidth_input.value(),
            min_duration_ms=self.min_duration_input.value(),
            enable_bandpass=self.bandpass_checkbox.isChecked(),
            sample_output_dir=self.output_dir_input.text().strip() or str(self._default_output_dir_for(input_path)),
            model_weights_path=self.model_path_input.text().strip(),
            ai_confidence_threshold=self.confidence_input.value(),
        )

        self._set_running_state(True)
        self.current_run_result = None
        self.result_message_label.setText("预处理任务已提交，正在后台执行。")
        self.run_state_value.setText("运行中")
        self.result_status_badge.set_status("运行中", "info", size="sm")
        self.run_status_badge.set_status("运行中", "info", size="sm")
        self.status_metric.set_value("运行中")
        self.output_dir_value.setText(config.sample_output_dir)
        self.log_output.setPlainText("任务启动中，请稍候...\n")
        self.segment_table.setRowCount(0)

        thread = QThread(self)
        worker = PreprocessRunWorker(config)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.started.connect(self._on_run_started)
        worker.finished.connect(self._on_run_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_run_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_run_worker)
        thread.finished.connect(thread.deleteLater)

        self._run_thread = thread
        self._run_worker = worker
        thread.start()

    def _on_run_started(self, input_file_path: str) -> None:
        """Update the UI when the worker starts running."""

        self.log_output.setPlainText(f"启动预处理任务：{Path(input_file_path).name}\n")

    def _on_run_finished(self, result: PreprocessRunResult) -> None:
        """Render a finished preprocess result."""

        self.current_run_result = result
        self._set_running_state(False)

        if result.cap_info is not None:
            self._apply_probe_result(result.cap_info)

        self.detected_metric.set_value(str(result.detected_segment_count))
        self.output_metric.set_value(str(result.output_sample_count))
        self.detected_value.setText(str(result.detected_segment_count))
        self.output_value.setText(str(result.output_sample_count))
        self.output_dir_value.setText(result.sample_output_dir)
        self.log_output.setPlainText("\n".join(result.logs) if result.logs else "本次任务未返回日志。")
        self._render_segment_table(result.segments)

        if result.success:
            self.run_state_value.setText("完成")
            self.result_message_label.setText(result.message or "预处理完成。")
            self.result_status_badge.set_status("处理完成", "success", size="sm")
            self.run_status_badge.set_status("处理完成", "success", size="sm")
            self.status_metric.set_value("完成")
            self.goto_dataset_button.setEnabled(bool(result.sample_records))
            if result.sample_records:
                self.sample_records_generated.emit(result.sample_records)
                self.config_status_label.setText(
                    f"本次已同步 {len(result.sample_records)} 条有效样本记录，可直接进入数据集管理继续后续流程。"
                )
            else:
                self.config_status_label.setText("本次未生成可同步的有效样本记录，可继续调整阈值后重试。")
        else:
            self.run_state_value.setText("失败")
            self.result_message_label.setText(result.message or "预处理失败。")
            self.result_status_badge.set_status("处理失败", "danger", size="sm")
            self.run_status_badge.set_status("处理失败", "danger", size="sm")
            self.status_metric.set_value("失败")
            self.goto_dataset_button.setEnabled(False)

    def _on_run_failed(self, message: str) -> None:
        """Render one worker-side failure."""

        self._set_running_state(False)
        self.run_state_value.setText("失败")
        self.result_message_label.setText(message)
        self.result_status_badge.set_status("处理失败", "danger", size="sm")
        self.run_status_badge.set_status("处理失败", "danger", size="sm")
        self.status_metric.set_value("失败")
        self.log_output.setPlainText(message)
        self.goto_dataset_button.setEnabled(False)

    def _clear_run_worker(self) -> None:
        """Reset worker references after the thread exits."""

        self._run_thread = None
        self._run_worker = None

    def _render_segment_table(self, segments: list[dict[str, object]]) -> None:
        """Render normalized segment rows into the result table."""

        self.segment_table.setRowCount(len(segments))
        for row_index, segment in enumerate(segments):
            values = [
                str(segment.get("segment_id", "")),
                str(segment.get("start_sample", "")),
                str(segment.get("end_sample", "")),
                f"{float(segment.get('duration_ms', 0.0)):.2f}",
                f"{float(segment.get('center_freq_hz', 0.0)):.1f}",
                f"{float(segment.get('bandwidth_hz', 0.0)):.1f}",
                f"{float(segment.get('snr_db', 0.0)):.2f}",
                f"{float(segment.get('score', 0.0)):.4f}",
                str(segment.get("output_file_path", "")),
                str(segment.get("status", "")),
            ]
            for column, value in enumerate(values):
                self._set_table_value(self.segment_table, row_index, column, value)

    def _set_running_state(self, running: bool) -> None:
        """Enable or disable controls based on the current worker state."""

        self.probe_button.setEnabled(not running)
        self.start_button.setEnabled(not running and self._selected_record() is not None and bool(self._selected_record()["exists"]))
        self.file_table.setEnabled(not running)
        self.slice_length_input.setEnabled(not running)
        self.threshold_input.setEnabled(not running)
        self.noise_floor_input.setEnabled(not running)
        self.min_bandwidth_input.setEnabled(not running)
        self.min_duration_input.setEnabled(not running)
        self.confidence_input.setEnabled(not running)
        self.bandpass_checkbox.setEnabled(not running)
        self.output_dir_input.setEnabled(not running)
        self.model_path_input.setEnabled(not running)

        if running:
            self.process_progress.setRange(0, 0)
        else:
            self.process_progress.setRange(0, 100)
            self.process_progress.setValue(100 if self.current_run_result and self.current_run_result.success else 0)

    def _is_running(self) -> bool:
        """Return whether a preprocess task is currently active."""

        return self._run_thread is not None

    def _reset_preview(self, message: str, badge_level: str = "info") -> None:
        """Reset the preview card to a safe placeholder state."""

        label = "待读取" if badge_level == "info" else "读取失败"
        self.current_probe_result = None
        self.preview_status_badge.set_status(label, badge_level, size="sm")
        self.preview_file_value.setText("-")
        self.preview_size_value.setText("-")
        self.preview_scope_value.setText("-")
        self.preview_note_label.setText(message)
        self.bandwidth_value.setText("-")
        self.sample_rate_value.setText("-")
        self.center_freq_value.setText("-")

        for row_index in range(self.preview_field_table.rowCount()):
            self._set_table_value(self.preview_field_table, row_index, 2, "-")
        for row_index in range(self.preview_stats_table.rowCount()):
            for column in range(1, self.preview_stats_table.columnCount()):
                self._set_table_value(self.preview_stats_table, row_index, column, "-")
        self.preview_iq_table.setRowCount(0)

    def _set_table_value(self, table: QTableWidget, row: int, column: int, value: str) -> None:
        """Set one table cell value, creating the item if needed."""

        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        item.setText(value)

    def _default_output_dir_for(self, path: Path) -> Path:
        """Return the default output directory for one CAP file."""

        return default_preprocess_output_dir() / path.stem

    def _format_bytes(self, size: int) -> str:
        """Format one file size for compact preview output."""

        units = ["B", "KB", "MB", "GB"]
        current_size = float(size)
        for unit in units:
            if current_size < 1024.0 or unit == units[-1]:
                return f"{current_size:.1f} {unit}" if unit != "B" else f"{int(current_size)} B"
            current_size /= 1024.0
        return f"{size} B"
