"""Capture page for hardware connection and signal acquisition."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QTimer, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
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

from config import (
    DEFAULT_DEVICE_IP,
    DEFAULT_DEVICE_PORT,
    DEFAULT_USRP_BANDWIDTH_MHZ,
    DEFAULT_USRP_ANTENNA,
    DEFAULT_USRP_CENTER_FREQUENCY_MHZ,
    DEFAULT_USRP_DEVICE_ARGS,
    DEFAULT_USRP_DURATION_S,
    DEFAULT_USRP_EXECUTABLE,
    DEFAULT_USRP_GAIN_DB,
    DEFAULT_USRP_SAMPLE_RATE_MHZ,
    RAW_DATA_DIR,
)
from services import (
    USRPCaptureConfig,
    USRPCaptureResult,
    USRPDiagnosticsResult,
    delete_raw_file_record,
    format_b210_preflight_summary,
    list_raw_files,
    resolve_uhd_tool,
    save_raw_capture_record,
)
from ui.usrp_capture_worker import USRPCaptureWorker
from ui.usrp_diagnostics_worker import USRPDiagnosticsWorker
from ui.widgets import (
    MetricCard,
    SectionCard,
    SmoothScrollArea,
    StatusBadge,
    VisualHeroCard,
    configure_scrollable,
)


class CapturePage(QWidget):
    """Capture workflow page for device connection and raw signal acquisition."""

    connection_state_changed = Signal(bool, str)
    raw_capture_completed = Signal(object)
    raw_records_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the capture page."""

        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._advance_mock_capture)
        self._connected = False
        self._capture_thread: QThread | None = None
        self._capture_worker: USRPCaptureWorker | None = None
        self._diagnostics_thread: QThread | None = None
        self._diagnostics_worker: USRPDiagnosticsWorker | None = None
        self._usrp_stop_requested = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = SmoothScrollArea()

        container = QWidget()
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setContentsMargins(6, 6, 6, 6)
        self.content_layout.setSpacing(16)

        self.content_layout.addWidget(self._build_visual_banner())
        self.content_layout.addLayout(self._build_summary_row())

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_connection_card(), 3)
        top_row.addWidget(self._build_control_card(), 2)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(14)
        bottom_row.addWidget(self._build_parameters_card(), 2)
        bottom_row.addWidget(self._build_files_card(), 3)

        self.content_layout.addLayout(top_row)
        self.content_layout.addLayout(bottom_row)
        self.content_layout.addStretch(1)

        self.scroll_area.setWidget(container)
        root_layout.addWidget(self.scroll_area)

        self._refresh_files_empty_state()
        self._update_visa_preview()
        self._update_usrp_command_preview()
        self._refresh_summary_metrics()
        self._apply_mode_change()

    def _current_page_scroll(self) -> int:
        """Return the capture page outer scroll position."""

        return int(self.scroll_area.verticalScrollBar().value())

    def _preserve_page_scroll(self, position: int) -> None:
        """Restore the outer page scroll after the current UI update settles."""

        def apply_restore() -> None:
            scroll_bar = self.scroll_area.verticalScrollBar()
            target = max(scroll_bar.minimum(), min(scroll_bar.maximum(), int(position)))
            scroll_bar.setValue(target)
            controller = getattr(self.scroll_area, "_smooth_scroll_controller", None)
            if controller is not None and hasattr(controller, "_target_value"):
                controller._target_value = scroll_bar.value()
            self.setFocus(Qt.FocusReason.OtherFocusReason)

        QTimer.singleShot(0, apply_restore)

    def _build_visual_banner(self) -> VisualHeroCard:
        """Create the capture-page visual banner."""

        return VisualHeroCard(
            "数据采集",
            "",
            background_name="capture_header_bg.svg",
            chips=[],
            ornament_name="decor_signal_corner_a.svg",
            height=170,
        )

    def _build_summary_row(self) -> QHBoxLayout:
        """Create the compact summary row."""

        row = QHBoxLayout()
        row.setSpacing(12)

        self.connection_metric = MetricCard("设备状态", "未接入", compact=True)
        self.mode_metric = MetricCard("采集设备", "3943B", compact=True, accent_color="#7CB98B")
        self.file_metric = MetricCard("原始文件", "0", compact=True, accent_color="#C59A63")

        row.addWidget(self.connection_metric)
        row.addWidget(self.mode_metric)
        row.addWidget(self.file_metric)
        return row

    def _build_connection_card(self) -> SectionCard:
        """Create the device connection card."""

        self.connection_badge = StatusBadge("设备未接入", "danger", size="sm")
        section = SectionCard(
            "设备连接",
            "",
            right_widget=self.connection_badge,
            compact=True,
        )

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        self.capture_mode_box = QComboBox()
        self.capture_mode_box.addItems(["3943B", "USRP B210"])
        self.capture_mode_box.currentIndexChanged.connect(self._apply_mode_change)
        mode_row.addWidget(QLabel("采集设备"))
        mode_row.addWidget(self.capture_mode_box, 1)

        self.connection_stack = QStackedWidget()
        self.connection_stack.addWidget(self._build_3943b_connection_widget())
        self.connection_stack.addWidget(self._build_usrp_connection_widget())

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.connect_button = QPushButton("连接设备")
        self.connect_button.setObjectName("PrimaryButton")
        self.connect_button.clicked.connect(lambda: self._set_connection_state(True))

        self.disconnect_button = QPushButton("断开连接")
        self.disconnect_button.clicked.connect(lambda: self._set_connection_state(False))

        self.query_button = QPushButton("查询 *IDN?")
        self.query_button.clicked.connect(self._query_current_backend)

        self.diagnostics_button = QPushButton("B210 预检")
        self.diagnostics_button.clicked.connect(self._run_usrp_diagnostics)

        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.disconnect_button)
        button_row.addWidget(self.query_button)
        button_row.addWidget(self.diagnostics_button)
        button_row.addStretch(1)

        self.connection_status_label = QLabel()
        self.connection_status_label.setObjectName("MutedText")
        self.connection_status_label.setWordWrap(True)

        section.body_layout.addLayout(mode_row)
        section.body_layout.addWidget(self.connection_stack)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.connection_status_label)
        return section

    def _build_3943b_connection_widget(self) -> QWidget:
        """Build the 3943B connection form."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.ip_input = QLineEdit(DEFAULT_DEVICE_IP)
        self.ip_input.textChanged.connect(self._update_visa_preview)

        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(DEFAULT_DEVICE_PORT)
        self.port_input.valueChanged.connect(self._update_visa_preview)

        self.visa_preview = QLabel()
        self.visa_preview.setObjectName("MonoText")
        self.visa_preview.setWordWrap(True)

        form_layout.addRow("设备 IP", self.ip_input)
        form_layout.addRow("LAN 端口", self.port_input)
        form_layout.addRow("VISA 地址", self.visa_preview)

        self.device_grid = QGridLayout()
        self.device_grid.setHorizontalSpacing(12)
        self.device_grid.setVerticalSpacing(10)

        self.device_labels = {
            "型号": QLabel("3943B 监测接收机"),
            "接口": QLabel("LAN / VISA / SCPI"),
            "链路": QLabel("未建立"),
            "记录模式": QLabel("IQ 记录"),
        }

        for label_widget in self.device_labels.values():
            label_widget.setObjectName("ValueLabel")

        for row, (key, value_label) in enumerate(self.device_labels.items()):
            title_label = QLabel(key)
            title_label.setObjectName("FieldLabel")
            self.device_grid.addWidget(title_label, row, 0)
            self.device_grid.addWidget(value_label, row, 1)

        layout.addLayout(form_layout)
        layout.addLayout(self.device_grid)
        return widget

    def _build_usrp_connection_widget(self) -> QWidget:
        """Build the USRP connection form."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.usrp_executable_input = QLineEdit(DEFAULT_USRP_EXECUTABLE)
        self.usrp_executable_input.textChanged.connect(self._update_usrp_command_preview)

        self.usrp_device_args_input = QLineEdit(DEFAULT_USRP_DEVICE_ARGS)
        self.usrp_device_args_input.setPlaceholderText("例如 type=b200")
        self.usrp_device_args_input.textChanged.connect(self._update_usrp_command_preview)

        self.usrp_command_preview = QLabel("-")
        self.usrp_command_preview.setObjectName("MonoText")
        self.usrp_command_preview.setWordWrap(True)

        self.usrp_executable_input.setVisible(False)
        self.usrp_device_args_input.setVisible(False)
        self.usrp_command_preview.setVisible(False)

        layout.addLayout(form_layout)
        return widget

    def _build_control_card(self) -> SectionCard:
        """Create the capture execution card."""

        self.capture_stage_badge = StatusBadge("等待开始", "info", size="sm")
        section = SectionCard(
            "任务控制",
            "",
            right_widget=self.capture_stage_badge,
            compact=True,
        )

        self.capture_progress = QProgressBar()
        self.capture_progress.setRange(0, 100)
        self.capture_progress.setValue(0)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.start_button = QPushButton("开始采集")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_capture)

        self.stop_button = QPushButton("停止采集")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_capture)

        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addStretch(1)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(220)
        configure_scrollable(self.log_output)

        section.body_layout.addWidget(self.capture_progress)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.log_output)
        return section

    def _build_parameters_card(self) -> SectionCard:
        """Create the acquisition parameter card."""

        section = SectionCard(
            "采集参数",
            "",
            compact=True,
        )

        self.parameters_stack = QStackedWidget()
        self.parameters_stack.addWidget(self._build_3943b_parameter_widget())
        self.parameters_stack.addWidget(self._build_usrp_parameter_widget())

        self.parameter_note_label = QLabel()
        self.parameter_note_label.setObjectName("MutedText")
        self.parameter_note_label.setWordWrap(True)
        self.parameter_note_label.setVisible(False)

        section.body_layout.addWidget(self.parameters_stack)
        section.body_layout.addWidget(self.parameter_note_label)
        return section

    def _build_3943b_parameter_widget(self) -> QWidget:
        """Build the 3943B parameter form."""

        widget = QWidget()
        form_layout = QFormLayout(widget)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.center_frequency_input = QDoubleSpinBox()
        self.center_frequency_input.setRange(0.009, 8000.0)
        self.center_frequency_input.setDecimals(3)
        self.center_frequency_input.setSuffix(" MHz")
        self.center_frequency_input.setValue(2400.0)

        self.bandwidth_input = QDoubleSpinBox()
        self.bandwidth_input.setRange(0.009, 8000.0)
        self.bandwidth_input.setDecimals(3)
        self.bandwidth_input.setSuffix(" MHz")
        self.bandwidth_input.setValue(20.0)

        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 3600)
        self.duration_input.setSuffix(" s")
        self.duration_input.setValue(180)

        self.device_label_input = QLineEdit("drone_001")
        self.device_label_input.setPlaceholderText("例如 drone_001")

        output_path = QLabel(str(RAW_DATA_DIR))
        output_path.setObjectName("ValueLabel")
        output_path.setWordWrap(True)

        form_layout.addRow("中心频率", self.center_frequency_input)
        form_layout.addRow("带宽", self.bandwidth_input)
        form_layout.addRow("记录时间", self.duration_input)
        form_layout.addRow("设备编号", self.device_label_input)
        form_layout.addRow("输出目录", output_path)
        return widget

    def _build_usrp_parameter_widget(self) -> QWidget:
        """Build the USRP parameter form."""

        widget = QWidget()
        form_layout = QFormLayout(widget)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.usrp_center_frequency_input = QDoubleSpinBox()
        self.usrp_center_frequency_input.setRange(0.009, 8000.0)
        self.usrp_center_frequency_input.setDecimals(3)
        self.usrp_center_frequency_input.setSuffix(" MHz")
        self.usrp_center_frequency_input.setValue(DEFAULT_USRP_CENTER_FREQUENCY_MHZ)
        self.usrp_center_frequency_input.valueChanged.connect(self._update_usrp_command_preview)

        self.usrp_sample_rate_input = QDoubleSpinBox()
        self.usrp_sample_rate_input.setRange(0.100, 200.0)
        self.usrp_sample_rate_input.setDecimals(3)
        self.usrp_sample_rate_input.setSuffix(" MHz")
        self.usrp_sample_rate_input.setValue(DEFAULT_USRP_SAMPLE_RATE_MHZ)
        self.usrp_sample_rate_input.valueChanged.connect(self._update_usrp_command_preview)

        self.usrp_bandwidth_input = QDoubleSpinBox()
        self.usrp_bandwidth_input.setRange(0.100, 200.0)
        self.usrp_bandwidth_input.setDecimals(3)
        self.usrp_bandwidth_input.setSuffix(" MHz")
        self.usrp_bandwidth_input.setValue(DEFAULT_USRP_BANDWIDTH_MHZ)
        self.usrp_bandwidth_input.valueChanged.connect(self._update_usrp_command_preview)

        self.usrp_gain_input = QDoubleSpinBox()
        self.usrp_gain_input.setRange(0.0, 100.0)
        self.usrp_gain_input.setDecimals(1)
        self.usrp_gain_input.setSuffix(" dB")
        self.usrp_gain_input.setValue(DEFAULT_USRP_GAIN_DB)
        self.usrp_gain_input.valueChanged.connect(self._update_usrp_command_preview)

        self.usrp_duration_input = QDoubleSpinBox()
        self.usrp_duration_input.setRange(0.5, 3600.0)
        self.usrp_duration_input.setDecimals(1)
        self.usrp_duration_input.setSuffix(" s")
        self.usrp_duration_input.setValue(DEFAULT_USRP_DURATION_S)
        self.usrp_duration_input.valueChanged.connect(self._update_usrp_command_preview)

        self.usrp_output_format_box = QComboBox()
        self.usrp_output_format_box.addItem("IQ", "iq")
        self.usrp_output_format_box.addItem("BIN", "bin")
        self.usrp_output_format_box.currentIndexChanged.connect(self._update_usrp_command_preview)

        self.usrp_device_label_input = QLineEdit("usrp_batch_001")
        self.usrp_device_label_input.textChanged.connect(self._update_usrp_command_preview)

        self.usrp_output_dir_input = QLineEdit(str(RAW_DATA_DIR))
        self.usrp_output_dir_input.textChanged.connect(self._update_usrp_command_preview)

        form_layout.addRow("中心频率", self.usrp_center_frequency_input)
        form_layout.addRow("采样率", self.usrp_sample_rate_input)
        form_layout.addRow("带宽", self.usrp_bandwidth_input)
        form_layout.addRow("增益", self.usrp_gain_input)
        form_layout.addRow("采集时长", self.usrp_duration_input)
        form_layout.addRow("文件格式", self.usrp_output_format_box)
        form_layout.addRow("设备编号", self.usrp_device_label_input)
        form_layout.addRow("输出目录", self.usrp_output_dir_input)
        return widget

    def _build_files_card(self) -> SectionCard:
        """Create the captured files table card."""

        section = SectionCard(
            "记录文件",
            "",
            compact=True,
        )

        self.files_table = QTableWidget(0, 6)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.setHorizontalHeaderLabels(
            ["文件名", "格式", "中心频率", "采样率/带宽", "来源/设备", "状态"]
        )
        self.files_table.horizontalHeader().setStretchLastSection(True)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files_table.itemSelectionChanged.connect(self._sync_delete_file_button)
        configure_scrollable(self.files_table)

        file_action_row = QHBoxLayout()
        file_action_row.setSpacing(10)
        self.delete_file_button = QPushButton("移除记录（不删文件）")
        self.delete_file_button.setToolTip(
            "只移除数据库中的原始记录和关联关系，不删除本地文件。"
        )
        self.delete_file_button.clicked.connect(self._delete_selected_record)
        self.delete_file_button.setEnabled(False)
        file_action_row.addWidget(self.delete_file_button)
        file_action_row.addStretch(1)

        self.files_empty_label = QLabel("暂无记录")
        self.files_empty_label.setObjectName("MutedText")
        self.files_empty_label.setWordWrap(True)

        section.body_layout.addWidget(self.files_table)
        section.body_layout.addWidget(self.files_empty_label)
        section.body_layout.addLayout(file_action_row)
        return section

    def _append_row(self, row_data: list[str], *, file_path: str = "") -> None:
        """Append one row to the file table."""

        row_index = self.files_table.rowCount()
        self.files_table.insertRow(row_index)
        for column, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if column == 0 else Qt.AlignmentFlag.AlignCenter)
            )
            if column == 0 and file_path:
                item.setData(Qt.ItemDataRole.UserRole, file_path)
            self.files_table.setItem(row_index, column, item)
        self._refresh_summary_metrics()
        self._refresh_files_empty_state()
        self._sync_delete_file_button()

    def _refresh_files_empty_state(self) -> None:
        """Refresh the empty-state hint for the captured-file table."""

        if hasattr(self, "files_empty_label"):
            self.files_empty_label.setVisible(self.files_table.rowCount() == 0)

    def refresh_records_from_database(self) -> None:
        """Reload the raw-file record table from SQLite."""

        self.files_table.setRowCount(0)
        for record in list_raw_files():
            suffix = Path(record.file_path).suffix.lstrip(".") or "-"
            self._append_row(
                [
                    record.file_name,
                    suffix,
                    f"{record.center_frequency_hz / 1_000_000:.3f} MHz" if record.center_frequency_hz else "-",
                    (
                        f"{record.sample_rate_hz / 1_000_000:.3f} MHz / "
                        f"{record.bandwidth_hz / 1_000_000:.3f} MHz"
                        if record.sample_rate_hz or record.bandwidth_hz
                        else "-"
                    ),
                    Path(record.file_path).parent.name or "-",
                    "原始",
                ],
                file_path=record.file_path,
            )
        self._refresh_summary_metrics()
        self._refresh_files_empty_state()
        self._sync_delete_file_button()

    def _apply_mode_change(self) -> None:
        """Switch the capture page between 3943B and USRP modes."""

        if self._connected:
            self._set_connection_state(False, append_log=False)

        usrp_mode = self._is_usrp_mode()
        self.connection_stack.setCurrentIndex(1 if usrp_mode else 0)
        self.parameters_stack.setCurrentIndex(1 if usrp_mode else 0)
        self.mode_metric.set_value("USRP B210" if usrp_mode else "3943B")
        self.query_button.setText("检测命令" if usrp_mode else "查询 *IDN?")
        self.diagnostics_button.setVisible(usrp_mode)
        self.parameter_note_label.clear()
        self.connection_status_label.clear()
        if usrp_mode:
            self._update_usrp_command_preview()
        self._update_connection_badge_text()
        self._refresh_summary_metrics()

    def _update_visa_preview(self) -> None:
        """Refresh the VISA preview string."""

        host = self.ip_input.text().strip() or DEFAULT_DEVICE_IP
        port = self.port_input.value()
        self.visa_preview.setText(f"TCPIP::{host}::{port}::SOCKET")

    def _update_usrp_command_preview(self) -> None:
        """Refresh the USRP command preview string."""

        executable = self.usrp_executable_input.text().strip() or DEFAULT_USRP_EXECUTABLE
        device_args = self.usrp_device_args_input.text().strip()
        center_frequency_hz = self.usrp_center_frequency_input.value() * 1_000_000
        sample_rate_hz = self.usrp_sample_rate_input.value() * 1_000_000
        gain_db = self.usrp_gain_input.value()
        duration_s = self.usrp_duration_input.value()
        preview_parts = [
            executable,
            "--file <输出文件>",
            f"--freq {center_frequency_hz:.0f}",
            f"--rate {sample_rate_hz:.0f}",
            f"--gain {gain_db:.2f}",
            f"--duration {duration_s:.2f}",
            "--type short",
            f"--ant {DEFAULT_USRP_ANTENNA}",
        ]
        if device_args:
            preview_parts.extend(["--args", device_args])
        bandwidth_hz = self.usrp_bandwidth_input.value() * 1_000_000
        if bandwidth_hz > 0:
            preview_parts.extend(["--bw", f"{bandwidth_hz:.0f}"])
        self.usrp_command_preview.setText(" ".join(preview_parts))
        if hasattr(self, "parameter_note_label") and self._is_usrp_mode():
            self.parameter_note_label.clear()

    def _set_connection_state(self, connected: bool, *, append_log: bool = True) -> None:
        """Update the current backend connection state."""

        if self._is_usrp_mode() and connected:
            if append_log:
                self._append_log("USRP 连接状态以 B210 预检为准，正在启动预检。")
            self._run_usrp_diagnostics()
            return

        self._connected = connected
        if self._is_usrp_mode():
            if connected:
                self.connection_badge.set_status("USRP 就绪", "success")
                if append_log:
                    self._append_log("USRP 采集命令检查通过。")
            else:
                self.connection_badge.set_status("USRP 未接入", "danger")
                if append_log:
                    self._append_log("USRP 采集链路已断开。")
            self.connection_state_changed.emit(connected, "USRP 已就绪" if connected else "USRP 未接入")
        else:
            if connected:
                self.connection_badge.set_status("3943B 已连接", "success")
                self.device_labels["链路"].setText("已建立")
                if append_log:
                    self._append_log("3943B 连接已建立。")
            else:
                self.connection_badge.set_status("3943B 未接入", "danger")
                self.device_labels["链路"].setText("未建立")
                if append_log:
                    self._append_log("链路已断开，等待重新接入。")
            self.connection_state_changed.emit(connected, "3943B 已连接" if connected else "3943B 未接入")

        self._refresh_summary_metrics()

    def _query_current_backend(self) -> None:
        """Trigger one lightweight backend check according to the current mode."""

        if self._is_usrp_mode():
            executable = self.usrp_executable_input.text().strip() or DEFAULT_USRP_EXECUTABLE
            resolved = resolve_uhd_tool(executable)
            if resolved:
                self._append_log(f"USRP 命令检测通过：{resolved}")
            else:
                self._append_log(f"USRP 命令不可用：{executable}")
        else:
            self._append_log("*IDN? -> 3943B")

    def _run_usrp_diagnostics(self) -> None:
        """Run a B210/UHD preflight check in the background."""

        if not self._is_usrp_mode():
            self._append_log("请先选择 USRP B210。")
            return
        if self._diagnostics_thread is not None:
            self._append_log("B210 预检正在运行，请稍候。")
            return

        thread = QThread(self)
        worker = USRPDiagnosticsWorker(self.usrp_device_args_input.text().strip() or DEFAULT_USRP_DEVICE_ARGS)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_usrp_diagnostics_started)
        worker.finished.connect(self._on_usrp_diagnostics_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_usrp_diagnostics_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_usrp_diagnostics_worker)
        thread.finished.connect(thread.deleteLater)

        self._diagnostics_thread = thread
        self._diagnostics_worker = worker
        thread.start()

    def _on_usrp_diagnostics_started(self) -> None:
        """Render B210 preflight start state."""

        self.diagnostics_button.setEnabled(False)
        self._connected = False
        self.connection_state_changed.emit(False, "B210 预检中")
        self.connection_badge.set_status("预检中", "warning")
        self._append_log("开始执行 B210 / UHD 预检。")

    def _on_usrp_diagnostics_finished(self, result: USRPDiagnosticsResult) -> None:
        """Render B210 preflight result."""

        self.diagnostics_button.setEnabled(True)
        for line in format_b210_preflight_summary(result):
            self._append_log(line)
        if result.is_ready:
            self.connection_badge.set_status("B210 就绪", "success")
            self._connected = True
            self.connection_state_changed.emit(True, "B210 已就绪")
        else:
            self.connection_badge.set_status("B210 待处理", "warning")
            self._connected = False
            self.connection_state_changed.emit(False, "B210 待处理")
        self._refresh_summary_metrics()

    def _on_usrp_diagnostics_failed(self, message: str) -> None:
        """Render B210 preflight failure."""

        self.diagnostics_button.setEnabled(True)
        self._connected = False
        self.connection_state_changed.emit(False, "B210 预检失败")
        self.connection_badge.set_status("预检失败", "danger")
        self._append_log(message)

    def _clear_usrp_diagnostics_worker(self) -> None:
        """Clear B210 diagnostics worker references."""

        self._diagnostics_thread = None
        self._diagnostics_worker = None

    def _start_capture(self) -> None:
        """Start a capture task in the current mode."""

        scroll_position = self._current_page_scroll()
        if not self._connected:
            self._append_log("请先完成设备连接或命令检查，再开始采集。")
            self._preserve_page_scroll(scroll_position)
            return

        self.capture_progress.setValue(0)
        self.capture_stage_badge.set_status("采集中", "warning")
        self._set_capture_running_state(True)

        if self._is_usrp_mode():
            self._start_usrp_capture(scroll_position=scroll_position)
        else:
            self._append_log("启动 3943B 采集任务。")
            self._capture_timer.start(150)
            self._preserve_page_scroll(scroll_position)

    def _start_usrp_capture(self, *, scroll_position: int | None = None) -> None:
        """Start one USRP real capture task."""

        if scroll_position is None:
            scroll_position = self._current_page_scroll()

        if self._capture_thread is not None:
            self._preserve_page_scroll(scroll_position)
            return

        config = USRPCaptureConfig(
            executable_path=self.usrp_executable_input.text().strip() or DEFAULT_USRP_EXECUTABLE,
            device_args=self.usrp_device_args_input.text().strip(),
            center_frequency_hz=self.usrp_center_frequency_input.value() * 1_000_000,
            sample_rate_hz=self.usrp_sample_rate_input.value() * 1_000_000,
            bandwidth_hz=self.usrp_bandwidth_input.value() * 1_000_000,
            gain_db=self.usrp_gain_input.value(),
            duration_s=self.usrp_duration_input.value(),
            output_dir=self.usrp_output_dir_input.text().strip() or str(RAW_DATA_DIR),
            output_format=self._current_usrp_output_format(),
            device_label=self.usrp_device_label_input.text().strip() or "usrp",
        )

        thread = QThread(self)
        worker = USRPCaptureWorker(config)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_usrp_capture_started)
        worker.progress_changed.connect(self._on_usrp_capture_progress)
        worker.log_changed.connect(self._append_log)
        worker.finished.connect(self._on_usrp_capture_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.cancelled.connect(self._on_usrp_capture_cancelled)
        worker.cancelled.connect(thread.quit)
        worker.cancelled.connect(worker.deleteLater)
        worker.failed.connect(self._on_usrp_capture_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._clear_usrp_worker)
        thread.finished.connect(thread.deleteLater)

        self._capture_thread = thread
        self._capture_worker = worker
        self._usrp_stop_requested = False
        thread.start()
        self._preserve_page_scroll(scroll_position)

    def _advance_mock_capture(self) -> None:
        """Advance the mocked capture progress."""

        next_value = min(100, self.capture_progress.value() + 5)
        self.capture_progress.setValue(next_value)
        if next_value >= 100:
            self._capture_timer.stop()
            self.capture_stage_badge.set_status("已完成", "success")
            self._set_capture_running_state(False)
            self._append_log("采集结束，已生成 CAP 记录。")
            self._append_mock_capture_file()

    def _stop_capture(self) -> None:
        """Stop the current capture task."""

        if self._is_usrp_mode():
            if self._capture_worker is None or self._usrp_stop_requested:
                return
            self._usrp_stop_requested = True
            self._capture_worker.request_cancel()
            self.stop_button.setEnabled(False)
            self.capture_stage_badge.set_status("停止中", "warning")
            self._append_log("已接收停止请求，等待 USRP 采集阶段安全结束。")
            return

        self._capture_timer.stop()
        self.capture_stage_badge.set_status("已停止", "danger")
        self._set_capture_running_state(False)
        self._append_log("采集任务已终止。")

    def _append_mock_capture_file(self) -> None:
        """Add a newly captured mock file to the table."""

        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        frequency = int(self.center_frequency_input.value())
        bandwidth = int(self.bandwidth_input.value())
        device_label = self.device_label_input.text().strip() or "drone_001"
        file_name = f"{timestamp}_{frequency}M_{bandwidth}M_{device_label}.cap"
        row_data = [
            file_name,
            "cap",
            f"{self.center_frequency_input.value():.3f} MHz",
            f"{self.bandwidth_input.value():.3f} MHz",
            f"3943B / {device_label}",
            "原始",
        ]
        self._append_row(row_data)

    def _on_usrp_capture_started(self, _: str) -> None:
        """Update UI when the USRP worker really starts."""

        self.capture_stage_badge.set_status("采集中", "warning")
        self.status_text = "正在启动 USRP 采集任务"

    def _on_usrp_capture_progress(self, value: int, status_text: str) -> None:
        """Render USRP progress updates."""

        self.capture_progress.setValue(value)
        self.capture_stage_badge.set_status(status_text, "warning")

    def _on_usrp_capture_finished(self, result: USRPCaptureResult) -> None:
        """Render one successful USRP capture result."""

        self.capture_progress.setValue(100)
        self.capture_stage_badge.set_status("已完成", "success")
        self._set_capture_running_state(False)
        self._usrp_stop_requested = False
        save_raw_capture_record(
            file_path=result.output_file_path,
            sample_rate_hz=result.sample_rate_hz,
            center_frequency_hz=result.center_frequency_hz,
            bandwidth_hz=result.bandwidth_hz,
        )
        self._append_row(
            [
                result.file_name,
                Path(result.output_file_path).suffix.lstrip(".") or "iq",
                f"{result.center_frequency_hz / 1_000_000:.3f} MHz",
                f"{result.sample_rate_hz / 1_000_000:.3f} MHz / {result.bandwidth_hz / 1_000_000:.3f} MHz",
                f"USRP / {self.usrp_device_label_input.text().strip() or 'usrp'}",
                "原始",
            ],
            file_path=result.output_file_path,
        )
        self._append_log(f"已登记原始采集文件：{result.output_file_path}")
        self.raw_capture_completed.emit(result)
        self.raw_records_changed.emit()

    def _on_usrp_capture_cancelled(self, message: str) -> None:
        """Render one cancelled USRP capture result."""

        self.capture_stage_badge.set_status("已停止", "danger")
        self._set_capture_running_state(False)
        self._usrp_stop_requested = False
        self._append_log(message)

    def _on_usrp_capture_failed(self, message: str) -> None:
        """Render one failed USRP capture result."""

        self.capture_stage_badge.set_status("采集失败", "danger")
        self._set_capture_running_state(False)
        self._usrp_stop_requested = False
        self._append_log(message)

    def _clear_usrp_worker(self) -> None:
        """Clear USRP worker references after thread exit."""

        self._capture_thread = None
        self._capture_worker = None

    def _append_log(self, message: str) -> None:
        """Append one line to the acquisition log."""

        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")

    def _refresh_summary_metrics(self) -> None:
        """Refresh compact summary metrics."""

        self.connection_metric.set_value("在线" if self._connected else "未接入")
        self.mode_metric.set_value("USRP B210" if self._is_usrp_mode() else "3943B")
        self.file_metric.set_value(str(self.files_table.rowCount()))

    def _sync_delete_file_button(self) -> None:
        """根据当前选择状态刷新原始记录删除按钮。"""

        if not hasattr(self, "delete_file_button"):
            return
        self.delete_file_button.setEnabled(self.files_table.currentRow() >= 0 and self._capture_thread is None)

    def _selected_file_path(self) -> str:
        """返回当前记录对应的数据库文件路径。"""

        row = self.files_table.currentRow()
        if row < 0:
            return ""
        item = self.files_table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def _delete_selected_record(self) -> None:
        """只删除数据库中的原始记录和派生关联，不删除本地文件。"""

        row = self.files_table.currentRow()
        if row < 0:
            self._append_log("请先选择要删除的记录。")
            return

        file_name = self.files_table.item(row, 0).text() if self.files_table.item(row, 0) else "所选记录"
        file_path = self._selected_file_path()
        if not file_path:
            reply = QMessageBox.question(
                self,
                "删除记录",
                f"记录 {file_name} 没有入库路径，仅会从表格移除。\n\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.files_table.removeRow(row)
            self._append_log(f"已从表格移除记录：{file_name}")
            self._refresh_summary_metrics()
            self._refresh_files_empty_state()
            self._sync_delete_file_button()
            return

        reply = QMessageBox.question(
            self,
            "确认删除记录",
            f"确认从数据库删除原始记录 {file_name}？\n\n"
            "本操作只会删除 raw_files、关联预处理任务、样本和数据集关联，不会删除本地 .iq/.json/.cap 文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        counts = delete_raw_file_record(file_path)
        self.files_table.removeRow(row)
        self._append_log(
            "已删除数据库记录："
            f"原始 {counts.get('raw_files', 0)} 条，"
            f"预处理任务 {counts.get('preprocess_tasks', 0)} 条，"
            f"样本 {counts.get('samples', 0)} 条，"
            f"数据集关联 {counts.get('dataset_items', 0)} 条。本地文件未删除。"
        )
        self._refresh_summary_metrics()
        self._refresh_files_empty_state()
        self._sync_delete_file_button()
        self.raw_records_changed.emit()

    def _update_connection_badge_text(self) -> None:
        """Update the connection badge text for the current mode."""

        if self._is_usrp_mode():
            self.connection_badge.set_status("USRP 未接入", "danger")
            self.connection_state_changed.emit(False, "USRP 未接入")
        else:
            self.connection_badge.set_status("3943B 未接入", "danger")
            self.connection_state_changed.emit(False, "3943B 未接入")

    def _current_usrp_output_format(self) -> str:
        """Return the stable USRP output format value."""

        value = self.usrp_output_format_box.currentData()
        return str(value or self.usrp_output_format_box.currentText() or "iq")

    def _is_usrp_mode(self) -> bool:
        """Return whether the current page mode is USRP real capture."""

        return self.capture_mode_box.currentIndex() == 1

    def _set_capture_running_state(self, running: bool) -> None:
        """在采集执行期间统一控制关键控件可用状态。"""

        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.capture_mode_box.setEnabled(not running)
        self.connect_button.setEnabled(not running)
        self.disconnect_button.setEnabled(not running)
        self.query_button.setEnabled(not running)
        self.diagnostics_button.setEnabled(not running and self._diagnostics_thread is None)
        self.connection_stack.setEnabled(not running)
        self.parameters_stack.setEnabled(not running)
        if hasattr(self, "delete_file_button"):
            self.delete_file_button.setEnabled(not running and self.files_table.currentRow() >= 0)
