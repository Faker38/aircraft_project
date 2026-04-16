"""Capture page for hardware connection and signal acquisition."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_DEVICE_IP, DEFAULT_DEVICE_PORT
from ui.widgets import SectionCard, StatusBadge


class CapturePage(QWidget):
    """Capture workflow page for device connection and mock acquisition."""

    connection_state_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the capture page."""

        super().__init__(parent)
        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._advance_mock_capture)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        container = QWidget()
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setContentsMargins(6, 6, 6, 6)
        self.content_layout.setSpacing(18)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_connection_card(), 3)
        top_row.addWidget(self._build_guidance_card(), 2)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(14)
        middle_row.addWidget(self._build_parameters_card(), 3)
        middle_row.addWidget(self._build_control_card(), 2)

        self.content_layout.addLayout(top_row)
        self.content_layout.addLayout(middle_row)
        self.content_layout.addWidget(self._build_files_card())
        self.content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._populate_mock_rows()
        self._update_visa_preview()

    def _build_connection_card(self) -> SectionCard:
        """Create the device connection card."""

        header_badge = StatusBadge("设备未接入", "danger")
        self.connection_badge = header_badge

        section = SectionCard(
            "3943B 设备连接",
            "支持 RJ45 LAN 远程控制，VISA 地址格式为 "
            "TCPIP::host_address::port::SOCKET，默认端口 5025。",
            right_widget=header_badge,
        )

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

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        connect_button = QPushButton("连接设备")
        connect_button.setObjectName("PrimaryButton")
        connect_button.clicked.connect(lambda: self._set_connection_state(True))

        disconnect_button = QPushButton("断开连接")
        disconnect_button.clicked.connect(lambda: self._set_connection_state(False))

        ping_button = QPushButton("查询 *IDN?")
        ping_button.clicked.connect(self._mock_query_identity)

        button_row.addWidget(connect_button)
        button_row.addWidget(disconnect_button)
        button_row.addWidget(ping_button)
        button_row.addStretch(1)

        device_grid = QGridLayout()
        device_grid.setHorizontalSpacing(12)
        device_grid.setVerticalSpacing(12)

        self.device_labels = {
            "型号": QLabel("3943B 监测接收机"),
            "接口": QLabel("LAN / VISA / SCPI"),
            "端口": QLabel("5025"),
            "心跳": QLabel("3 秒轮询"),
        }

        for label_widget in self.device_labels.values():
            label_widget.setObjectName("ValueLabel")

        for row, (key, value_label) in enumerate(self.device_labels.items()):
            title_label = QLabel(key)
            title_label.setObjectName("FieldLabel")
            device_grid.addWidget(title_label, row, 0)
            device_grid.addWidget(value_label, row, 1)

        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addLayout(device_grid)
        return section

    def _build_guidance_card(self) -> SectionCard:
        """Create the capture tips card."""

        section = SectionCard(
            "联调要点",
            "采集前请确认网络链路、记录选件和存储路径。",
        )

        tips = [
            "LAN 接口位于设备侧面板，可用于远程控制。",
            "建议使用屏蔽网线，降低电磁干扰对测量结果的影响。",
            "IQ 记录支持 16 位和 32 位模式，当前界面按 32 位流程展示。",
            "当前页面使用联调采集流程，后续可直接接入 CaptureWorker。",
        ]

        for tip in tips:
            tip_label = QLabel(f"• {tip}")
            tip_label.setObjectName("MutedText")
            tip_label.setWordWrap(True)
            section.body_layout.addWidget(tip_label)

        return section

    def _build_parameters_card(self) -> SectionCard:
        """Create the acquisition parameter card."""

        section = SectionCard(
            "采集参数",
            "按默认任务参数完成快速配置。",
        )

        form_layout = QFormLayout()
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

        form_layout.addRow("中心频率", self.center_frequency_input)
        form_layout.addRow("带宽", self.bandwidth_input)
        form_layout.addRow("记录时间", self.duration_input)
        form_layout.addRow("设备编号", self.device_label_input)

        path_hint = QLabel("输出目录：data/raw/；文件名格式：日期_时间_频点_带宽_设备编号.cap。")
        path_hint.setObjectName("HintText")
        path_hint.setWordWrap(True)

        section.body_layout.addLayout(form_layout)
        section.body_layout.addWidget(path_hint)
        return section

    def _build_control_card(self) -> SectionCard:
        """Create the capture execution card."""

        section = SectionCard(
            "采集控制",
            "显示采集状态、执行进度和任务日志。",
        )

        self.capture_stage_badge = StatusBadge("等待开始", "info")
        section.body_layout.addWidget(self.capture_stage_badge, 0, Qt.AlignmentFlag.AlignLeft)

        self.capture_progress = QProgressBar()
        self.capture_progress.setRange(0, 100)
        self.capture_progress.setValue(0)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.start_button = QPushButton("开始采集")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_mock_capture)

        self.stop_button = QPushButton("停止采集")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_mock_capture)

        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addStretch(1)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(180)

        section.body_layout.addWidget(self.capture_progress)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.log_output)
        return section

    def _build_files_card(self) -> SectionCard:
        """Create the captured files table card."""

        section = SectionCard(
            "已采集文件",
            "显示采集文件及处理状态，后续可直接接入 raw_data.db。",
        )

        self.files_table = QTableWidget(0, 6)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.setHorizontalHeaderLabels(
            ["文件名", "中心频率", "带宽", "时长", "设备编号", "状态"]
        )
        self.files_table.horizontalHeader().setStretchLastSection(True)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        section.body_layout.addWidget(self.files_table)
        return section

    def _populate_mock_rows(self) -> None:
        """Insert initial mock rows into the capture table."""

        rows = [
            ["20260415_213011_2400M_20M_drone_001.cap", "2400 MHz", "20 MHz", "180 s", "drone_001", "已处理"],
            ["20260416_093205_5800M_40M_drone_007.cap", "5800 MHz", "40 MHz", "120 s", "drone_007", "原始"],
        ]
        for row_data in rows:
            self._append_row(row_data)

    def _append_row(self, row_data: list[str]) -> None:
        """Append one row to the file table."""

        row_index = self.files_table.rowCount()
        self.files_table.insertRow(row_index)
        for column, value in enumerate(row_data):
            self.files_table.setItem(row_index, column, QTableWidgetItem(value))

    def _update_visa_preview(self) -> None:
        """Refresh the VISA preview string."""

        host = self.ip_input.text().strip() or DEFAULT_DEVICE_IP
        port = self.port_input.value()
        self.visa_preview.setText(f"TCPIP::{host}::{port}::SOCKET")

    def _set_connection_state(self, connected: bool) -> None:
        """Update the mocked device connection state."""

        if connected:
            self.connection_badge.set_status("设备在线", "success")
            self.device_labels["心跳"].setText("3 秒轮询中")
            self._append_log("LAN 链路建立，设备响应正常。")
        else:
            self.connection_badge.set_status("设备未接入", "danger")
            self.device_labels["心跳"].setText("未启用")
            self._append_log("链路已断开，等待重新接入。")
        self.connection_state_changed.emit(connected)

    def _mock_query_identity(self) -> None:
        """Simulate querying the device identity."""

        self._append_log("*IDN? -> CETC,3943B,3943B-2026-001,Firmware 1.0")

    def _start_mock_capture(self) -> None:
        """Start a mocked capture task."""

        self.capture_progress.setValue(0)
        self.capture_stage_badge.set_status("采集中", "warning")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._append_log("下发记录参数，启动 IQ 记录。")
        self._capture_timer.start(150)

    def _advance_mock_capture(self) -> None:
        """Advance the mocked capture progress."""

        next_value = min(100, self.capture_progress.value() + 5)
        self.capture_progress.setValue(next_value)
        if next_value >= 100:
            self._capture_timer.stop()
            self.capture_stage_badge.set_status("已完成", "success")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self._append_log("采集结束，文件已归档至 data/raw/。")
            self._append_mock_capture_file()

    def _stop_mock_capture(self) -> None:
        """Stop the mocked capture task."""

        self._capture_timer.stop()
        self.capture_stage_badge.set_status("已停止", "danger")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
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
            f"{self.center_frequency_input.value():.3f} MHz",
            f"{self.bandwidth_input.value():.3f} MHz",
            f"{self.duration_input.value()} s",
            device_label,
            "原始",
        ]
        self._append_row(row_data)

    def _append_log(self, message: str) -> None:
        """Append one line to the acquisition log."""

        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
