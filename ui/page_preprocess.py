"""Preprocess page for signal filtering, slicing, and CAP preview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
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
from services import CapProbeError, CapProbeResult, probe_cap_file
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class PreprocessPage(QWidget):
    """Workflow page for signal preprocessing and CAP import preview."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the preprocess page."""

        super().__init__(parent)
        self.cap_records = self._build_cap_records()

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
        self.preview_metric = MetricCard("导入预览", "待读取", accent_color="#7CB98B", compact=True)
        self.slice_metric = MetricCard("当前切片", "65536", accent_color="#C59A63", compact=True)
        metrics_row.addWidget(self.file_metric)
        metrics_row.addWidget(self.preview_metric)
        metrics_row.addWidget(self.slice_metric)
        content_layout.addLayout(metrics_row)

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        top_row.addWidget(self._build_file_card(), 3)
        top_row.addWidget(self._build_config_card(), 2)

        content_layout.addLayout(top_row)
        content_layout.addWidget(self._build_probe_card())
        content_layout.addWidget(self._build_flow_card())
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

        section = SectionCard("原始文件", "选择 CAP 文件并执行只读导入预览。", compact=True)

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
            path = record["path"]
            exists = bool(record["exists"])
            size_text = self._format_bytes(path.stat().st_size) if exists else "-"
            status_text = "可预览" if exists else "文件缺失"
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

        self.file_status_label = QLabel("当前预览为只读探针，不写入样本库，也不生成预处理结果。")
        self.file_status_label.setObjectName("MutedText")
        self.file_status_label.setWordWrap(True)

        section.body_layout.addWidget(self.file_table)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.file_status_label)
        return section

    def _build_config_card(self) -> SectionCard:
        """Create the preprocess configuration card."""

        section = SectionCard(
            "预处理参数",
            "当前仅保留参数界面，真实切片服务后续接入。",
            right_widget=StatusBadge("待处理", "info", size="sm"),
            compact=True,
        )

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        slice_length_input = QSpinBox()
        slice_length_input.setRange(1024, 262144)
        slice_length_input.setSingleStep(1024)
        slice_length_input.setValue(65536)

        threshold_input = QDoubleSpinBox()
        threshold_input.setRange(0.0, 30.0)
        threshold_input.setDecimals(1)
        threshold_input.setSuffix(" dB")
        threshold_input.setValue(6.0)

        noise_floor_input = QDoubleSpinBox()
        noise_floor_input.setRange(-120.0, 0.0)
        noise_floor_input.setDecimals(1)
        noise_floor_input.setSuffix(" dBm")
        noise_floor_input.setValue(-82.0)

        bandpass_checkbox = QCheckBox("启用带通滤波")
        bandpass_checkbox.setChecked(True)

        form_layout.addRow("切片长度", slice_length_input)
        form_layout.addRow("能量阈值", threshold_input)
        form_layout.addRow("噪声基底", noise_floor_input)
        form_layout.addRow("滤波选项", bandpass_checkbox)

        process_progress = QProgressBar()
        process_progress.setValue(42)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        start_button = QPushButton("开始预处理")
        start_button.setObjectName("PrimaryButton")
        stop_button = QPushButton("停止任务")
        stop_button.setObjectName("DangerButton")

        button_row.addWidget(start_button)
        button_row.addWidget(stop_button)
        button_row.addStretch(1)

        section.body_layout.addWidget(process_progress)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        return section

    def _build_probe_card(self) -> SectionCard:
        """Create the CAP preview card."""

        self.preview_status_badge = StatusBadge("待读取", "info", size="sm")
        section = SectionCard(
            "CAP 导入预览",
            "显示已验证头字段、IQ 统计摘要和少量样本预览。",
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
        self.preview_header_value = QLabel("0x2C00 / 11264 B")
        self.preview_header_value.setObjectName("ValueLabel")
        self.preview_offset_value = QLabel("0x2C00")
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

        self.preview_field_table = QTableWidget(5, 3)
        self.preview_field_table.setHorizontalHeaderLabels(["字段", "偏移", "值"])
        self.preview_field_table.horizontalHeader().setStretchLastSection(True)
        self.preview_field_table.verticalHeader().setVisible(False)
        self.preview_field_table.setAlternatingRowColors(True)
        self.preview_field_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_scrollable(self.preview_field_table)

        field_rows = [
            ("版本号", "0x0000", "-"),
            ("采样率", "0x0010", "-"),
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

    def _build_flow_card(self) -> SectionCard:
        """Create the preprocessing summary card."""

        section = SectionCard("处理摘要", "导入预览 -> 归一化 -> 切片 -> 样本输出", compact=True)

        flow_row = QHBoxLayout()
        flow_row.setSpacing(12)

        items = [
            ("01", "导入预览", "读取 .cap 头信息并确认 IQ 数据布局"),
            ("02", "信号筛选", "去偏置并执行滤波"),
            ("03", "样本切片", "提取有效片段并生成样本"),
            ("04", "结果输出", "写入样本与统计信息"),
        ]

        for index, title, hint in items:
            block = QWidget()
            layout = QVBoxLayout(block)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)

            index_label = QLabel(index)
            index_label.setObjectName("FlowIndex")
            title_label = QLabel(title)
            title_label.setObjectName("FlowTitle")
            hint_label = QLabel(hint)
            hint_label.setObjectName("FlowHint")
            hint_label.setWordWrap(True)

            layout.addWidget(index_label)
            layout.addWidget(title_label)
            layout.addWidget(hint_label)
            flow_row.addWidget(block)

        section.body_layout.addLayout(flow_row)
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
            self.file_status_badge.set_status("未选择", "warning", size="sm")
            self.file_status_label.setText("请选择一条 CAP 文件记录后，再执行导入预览。")
            return

        path = Path(record["path"])
        exists = bool(record["exists"])
        self.probe_button.setEnabled(exists)
        if exists:
            self.file_status_badge.set_status("可预览", "success", size="sm")
            self.file_status_label.setText(
                f"已选文件：{path.name} | 路径：{path} | 当前操作为只读头信息预览。"
            )
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
            self.preview_metric.set_value("异常")
            return

        self._apply_probe_result(result)
        self.preview_metric.set_value("已读取")

    def _apply_probe_result(self, result: CapProbeResult) -> None:
        """Render a probe result into the preview widgets."""

        self.preview_status_badge.set_status("预览就绪", "success", size="sm")
        self.preview_file_value.setText(result.path.name)
        self.preview_size_value.setText(self._format_bytes(result.file_size))
        self.preview_header_value.setText(f"0x2C00 / {result.header_length} B")
        self.preview_offset_value.setText("0x2C00")
        self.preview_scope_value.setText(f"前 {result.statistics_window_pairs:,} 组 IQ")

        note_text = "当前仅展示已验证字段，其余头部参数仍标记为待确认。"
        if result.is_partial_capture:
            note_text = "当前为截取样本，仅代表前 1MB 数据窗口；不作为完整预处理结果。"
        self.preview_note_label.setText(
            note_text + " 待确认字段：" + "、".join(result.unresolved_fields)
        )

        field_values = [
            result.version,
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

    def _reset_preview(self, message: str, badge_level: str = "info") -> None:
        """Reset the preview card to a safe placeholder state."""

        label = "待读取" if badge_level == "info" else "读取失败"
        self.preview_status_badge.set_status(label, badge_level, size="sm")
        self.preview_file_value.setText("-")
        self.preview_size_value.setText("-")
        self.preview_scope_value.setText("-")
        self.preview_note_label.setText(message)

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

    def _format_bytes(self, size: int) -> str:
        """Format one file size for compact preview output."""

        units = ["B", "KB", "MB", "GB"]
        current_size = float(size)
        for unit in units:
            if current_size < 1024.0 or unit == units[-1]:
                return f"{current_size:.1f} {unit}" if unit != "B" else f"{int(current_size)} B"
            current_size /= 1024.0
        return f"{size} B"
