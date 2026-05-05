"""信号预处理页：负责 CAP 预览、参数配置和算法执行。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QHeaderView,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)

from config import BASE_DIR, RAW_DATA_DIR
from services import (
    CapProbeError,
    CapProbeResult,
    PreprocessRunConfig,
    PreprocessRunResult,
    USRPDemoPreprocessConfig,
    USRPDemoPreprocessError,
    USRPDemoPreprocessInfo,
    USRPDemoPreprocessResult,
    default_preprocess_output_dir,
    default_usrp_demo_output_dir,
    delete_raw_file_record,
    get_raw_file_delete_impact,
    list_raw_files,
    list_usrp_iq_captures,
    probe_cap_file,
    preview_usrp_iq_file,
    resolve_default_model_weights_path,
    save_preprocess_result,
    save_usrp_preprocess_result,
    upsert_usrp_label_mappings,
)
from ui.preprocess_run_worker import PreprocessRunWorker
from ui.usrp_demo_preprocess_worker import USRPDemoPreprocessWorker
from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, configure_scrollable


class PreprocessPage(QWidget):
    """CAP 预览与预处理执行页面。"""

    navigate_requested = Signal(str)
    sample_records_generated = Signal(object)
    workflow_records_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化预处理页面。"""

        super().__init__(parent)
        self.cap_records = self._build_input_records(usrp_mode=False)
        self.current_probe_result: CapProbeResult | None = None
        self.current_usrp_info: USRPDemoPreprocessInfo | None = None
        self.current_run_result: PreprocessRunResult | USRPDemoPreprocessResult | None = None
        self._last_run_config: PreprocessRunConfig | None = None
        self._run_thread: QThread | None = None
        self._run_worker: PreprocessRunWorker | USRPDemoPreprocessWorker | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(12)
        self.file_metric = MetricCard("原始文件", "0", compact=True)
        self.status_metric = MetricCard("任务状态", "待执行", accent_color="#7CB98B", compact=True)
        self.detected_metric = MetricCard("检出信号段", "0", accent_color="#C59A63", compact=True)
        self.candidate_metric = MetricCard("候选信号段", "0", accent_color="#F2C94C", compact=True)  # 新增控件
        self.output_metric = MetricCard("已保存样本", "0", accent_color="#5EA6D3", compact=True)
        metrics_row.addWidget(self.file_metric)
        metrics_row.addWidget(self.status_metric)
        metrics_row.addWidget(self.detected_metric)
        metrics_row.addWidget(self.candidate_metric)
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

        self._sync_mode_text()
        self.file_metric.set_value(str(len(self.cap_records)))
        if self.file_table.rowCount():
            self.file_table.selectRow(0)
            self._update_file_selection_state()
            self._load_selected_cap_preview()
        else:
            self._reset_preview("当前未发现可用 CAP 文件。", badge_level="warning")

    def _build_input_records(self, *, usrp_mode: bool | None = None) -> list[dict[str, object]]:
        """根据当前模式扫描可预处理的原始文件。"""

        if usrp_mode is None:
            usrp_mode = self._is_usrp_demo_mode()
        return self._build_usrp_iq_records() if usrp_mode else self._build_cap_records()

    def _build_cap_records(self) -> list[dict[str, object]]:
        """从本地文件和数据库记录合并展示全部 CAP 原始文件。"""

        workspace_root = BASE_DIR.parent
        records_by_key: dict[str, dict[str, object]] = {}
        cap_paths = sorted(
            workspace_root.glob("*.cap"),
            key=lambda item: (self._sample_kind_priority(item), item.name.lower()),
        )
        for path in cap_paths:
            sample_kind = self._sample_kind_for_cap(path)
            records_by_key[self._path_key(path)] = self._build_source_record(
                path=path,
                kind=sample_kind,
                location="工作区根目录",
                db_registered=False,
            )
        self._merge_database_raw_records(records_by_key, suffixes={".cap"})
        return self._sorted_source_records(records_by_key.values())

    def _build_usrp_iq_records(self) -> list[dict[str, object]]:
        """从本地文件和数据库记录合并展示 USRP IQ 原始文件。"""

        records_by_key: dict[str, dict[str, object]] = {}
        for path in sorted(RAW_DATA_DIR.glob("*.iq"), key=lambda item: item.stat().st_mtime, reverse=True):
            records_by_key[self._path_key(path)] = self._build_source_record(
                path=path,
                kind="USRP IQ",
                location="data/raw",
                db_registered=False,
            )
        for path in list_usrp_iq_captures():
            key = self._path_key(path)
            if key not in records_by_key:
                records_by_key[key] = self._build_source_record(
                    path=path,
                    kind="USRP IQ",
                    location="data/raw",
                    db_registered=False,
                )
        self._merge_database_raw_records(records_by_key, suffixes={".iq", ".bin"})
        return self._sorted_source_records(records_by_key.values())

    def _merge_database_raw_records(self, records_by_key: dict[str, dict[str, object]], *, suffixes: set[str]) -> None:
        """把数据库中仍有记录的原始文件合并到本地扫描列表。"""

        for raw_record in list_raw_files():
            path = Path(raw_record.file_path)
            if path.suffix.lower() not in suffixes:
                continue
            key = self._path_key(path)
            existing = records_by_key.get(key)
            if existing is None:
                records_by_key[key] = self._build_source_record(
                    path=path,
                    kind=("USRP IQ" if path.suffix.lower() == ".iq" else "USRP BIN")
                    if path.suffix.lower() in {".iq", ".bin"}
                    else (self._sample_kind_for_cap(path) if path.exists() else "CAP 原始"),
                    location=self._display_location_for(path),
                    db_registered=True,
                )
                continue
            existing["db_registered"] = True
            existing["status"] = self._source_record_status(path, db_registered=True)

    def _build_source_record(
        self,
        *,
        path: Path,
        kind: str,
        location: str,
        db_registered: bool,
    ) -> dict[str, object]:
        """构造原始文件表的一行记录。"""

        return {
            "name": path.name,
            "kind": kind,
            "path": path,
            "location": location,
            "exists": path.exists(),
            "db_registered": db_registered,
            "status": self._source_record_status(path, db_registered=db_registered),
        }

    def _source_record_status(self, path: Path, *, db_registered: bool) -> str:
        """返回原始文件表的用户可理解状态。"""

        if not path.exists():
            return "本地缺失" if db_registered else "文件缺失"
        if path.suffix.lower() == ".bin":
            return "留档"
        if path.suffix.lower() == ".iq" and not path.with_suffix(".json").exists():
            return "缺少 JSON"
        return "已入库" if db_registered else "未入库"

    def _display_location_for(self, path: Path) -> str:
        """把文件位置压缩成适合表格展示的文本。"""

        try:
            return str(path.parent.resolve().relative_to(BASE_DIR.resolve()))
        except ValueError:
            return str(path.parent)

    def _path_key(self, path: Path) -> str:
        """生成跨本地扫描和数据库记录合并用的路径键。"""

        try:
            return str(path.resolve()).lower()
        except OSError:
            return str(path).lower()

    def _sorted_source_records(self, records: object) -> list[dict[str, object]]:
        """按状态和文件名整理原始文件表顺序。"""

        return sorted(
            (dict(record) for record in records),
            key=lambda record: (
                1 if str(record.get("status", "")) == "本地缺失" else 0,
                str(record.get("name", "")).lower(),
            )
        )

    def _sample_kind_for_cap(self, path: Path) -> str:
        """根据文件名和大小给 CAP 样本做一个紧凑类型标记。"""

        if path.name.lower() == "head.cap" or path.stat().st_size <= 2 * 1024 * 1024:
            return "头部截取"
        return "完整样本"

    def _sample_kind_priority(self, path: Path) -> int:
        """返回 CAP 样本类型的排序优先级。"""

        return 1 if self._sample_kind_for_cap(path) == "头部截取" else 0

    def _build_file_card(self) -> SectionCard:
        """创建 CAP 文件选择卡片。"""

        section = SectionCard("原始文件", "支持 CAP 流程测试预处理和 USRP IQ 三阶段对齐预处理两条入口。", compact=True)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(QLabel("输入模式"))
        self.input_mode_box = QComboBox()
        self.input_mode_box.addItems(["CAP 算法预处理", "USRP IQ 三阶段预处理"])
        self.input_mode_box.currentIndexChanged.connect(self._on_input_mode_changed)
        mode_row.addWidget(self.input_mode_box)
        mode_row.addStretch(1)

        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "样本类型", "文件大小", "存放位置", "状态"])
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.file_table.itemSelectionChanged.connect(self._update_file_selection_state)
        configure_scrollable(self.file_table)

        self._render_file_table()

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.probe_button = QPushButton("读取头信息")
        self.probe_button.setObjectName("PrimaryButton")
        self.probe_button.clicked.connect(self._load_selected_cap_preview)

        self.refresh_files_button = QPushButton("刷新文件列表")
        self.refresh_files_button.clicked.connect(self.refresh_input_records)

        self.delete_raw_file_button = QPushButton("删除选中文件")
        self.delete_raw_file_button.setObjectName("DangerButton")
        self.delete_raw_file_button.setToolTip(
            "用于原始文件列表：可选择只删除数据库记录，或同时删除本地原始文件；"
            "USRP .iq/.bin 会连同同名 .json 元数据一起处理。"
        )
        self.delete_raw_file_button.clicked.connect(self._delete_selected_raw_file)
        self.delete_raw_file_button.setEnabled(False)

        self.file_status_badge = StatusBadge("待选择", "info", size="sm")

        action_row.addWidget(self.probe_button)
        action_row.addWidget(self.refresh_files_button)
        action_row.addWidget(self.delete_raw_file_button)
        action_row.addWidget(self.file_status_badge)
        action_row.addStretch(1)

        self.file_status_label = QLabel("当前会自动扫描工作区根目录下全部 CAP 文件，并支持先预览头字段，再按同一文件发起预处理运行。")
        self.file_status_label.setObjectName("MutedText")
        self.file_status_label.setWordWrap(True)

        section.body_layout.addLayout(mode_row)
        section.body_layout.addWidget(self.file_table)
        section.body_layout.addLayout(action_row)
        section.body_layout.addWidget(self.file_status_label)
        return section

    def _render_file_table(self) -> None:
        """Render the current CAP/USRP source records."""

        self.file_table.setRowCount(len(self.cap_records))
        for row_index, record in enumerate(self.cap_records):
            path = Path(record["path"])
            exists = bool(record["exists"])
            size_text = self._format_bytes(path.stat().st_size) if exists else "-"
            status_text = str(record.get("status") or ("未入库" if exists else "文件缺失"))
            values = [
                str(record["name"]),
                str(record["kind"]),
                size_text,
                str(record["location"]),
                status_text,
            ]
            for column, value in enumerate(values):
                self._set_table_value(self.file_table, row_index, column, value)

    def refresh_input_records(self, checked: bool = False, *, usrp_mode: bool | None = None) -> None:
        """重新扫描当前模式或指定模式下的原始文件列表。"""

        del checked
        if usrp_mode is not None and self._is_usrp_demo_mode() != usrp_mode:
            self.input_mode_box.setCurrentIndex(1 if usrp_mode else 0)
            return

        self.cap_records = self._build_input_records(usrp_mode=usrp_mode)
        self.current_probe_result = None
        self.current_usrp_info = None
        self.current_run_result = None
        self._render_file_table()
        self.file_metric.set_value(str(len(self.cap_records)))
        self.output_dir_input.setText(str(self._default_output_dir_for_selected_mode()))
        self._reset_preview(
            "请选择 USRP IQ 文件后读取元数据和 IQ 预览。"
            if self._is_usrp_demo_mode()
            else "请选择 CAP 文件后读取头信息。"
        )
        self.segment_table.setRowCount(0)
        self.log_output.setPlainText("等待日志输出。")
        self.goto_dataset_button.setEnabled(False)
        self._sync_mode_text()
        if self.file_table.rowCount():
            self.file_table.selectRow(0)
            self._update_file_selection_state()
            self._load_selected_cap_preview()
        else:
            self._update_file_selection_state()

    def _on_input_mode_changed(self) -> None:
        """Switch between CAP and USRP demo preprocessing input modes."""

        self.refresh_input_records()

    def _sync_mode_text(self) -> None:
        """Refresh user-facing hints for the selected preprocessing mode."""

        if self._is_usrp_demo_mode():
            self.file_status_label.setText("当前扫描 data/raw 下带同名 JSON 的 USRP .iq 文件，用于演示级 IQ 切片。")
            self.config_status_label.setText(
                "USRP 演示预处理会把 .iq 切成 complex64 .npy，并按 2412/2437/2462 MHz 自动建议频点标签。"
            )
            self.preview_note_label.setText("请选择 USRP IQ 文件后读取元数据和 IQ 预览。")
            return
        self.file_status_label.setText("当前会自动扫描工作区根目录下全部 CAP 文件，并支持先预览头字段，再按同一文件发起预处理运行。")
        self.config_status_label.setText(
            "当前默认按 0x200 / 512 字节头长试跑；能量阈值按窗口中位能量做相对抬升，默认 +1.0 dB。"
        )

    def _build_config_card(self) -> SectionCard:
        """创建预处理参数配置卡片。"""

        self.run_status_badge = StatusBadge("待执行", "info", size="sm")
        section = SectionCard(
            "预处理参数",
            "解析 CAP 头后自动绑定带宽、采样率和中心频率，用户只配置必要的筛选参数。",
            right_widget=self.run_status_badge,
            compact=True,
        )

        # 这三个值由 CAP 头自动解析，用户只读查看，不再手填。
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

        # 这里保留的是用户真正需要调的筛选参数，避免界面被算法内部细节淹没。
        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self.slice_length_input = QSpinBox()
        self.slice_length_input.setRange(1024, 262144)
        self.slice_length_input.setSingleStep(1024)
        self.slice_length_input.setValue(4096)

        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0.0, 20.0)
        self.threshold_input.setDecimals(1)
        self.threshold_input.setSuffix(" dB")
        self.threshold_input.setValue(1.0)

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

        self.config_status_label = QLabel(
            "当前默认按 0x200 / 512 字节头长试跑；能量阈值按窗口中位能量做相对抬升，默认 +1.0 dB。"
        )
        self.config_status_label.setObjectName("MutedText")
        self.config_status_label.setWordWrap(True)

        section.body_layout.addLayout(parsed_layout)
        section.body_layout.addWidget(self.process_progress)
        section.body_layout.addLayout(form_layout)
        section.body_layout.addLayout(button_row)
        section.body_layout.addWidget(self.config_status_label)
        return section

    def _build_probe_card(self) -> SectionCard:
        """创建 CAP 头信息预览卡片。"""

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
        self.preview_field_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.preview_field_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.preview_field_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.preview_field_table.setColumnWidth(0, 150)
        self.preview_field_table.setColumnWidth(1, 120)
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
                self._set_table_value(self.preview_field_table, row_index, column, value)

        self.preview_stats_table = QTableWidget(2, 5)
        self.preview_stats_table.setHorizontalHeaderLabels(["分量", "均值", "标准差", "最小值", "最大值"])
        self.preview_stats_table.horizontalHeader().setStretchLastSection(True)
        self.preview_stats_table.verticalHeader().setVisible(False)
        self.preview_stats_table.setAlternatingRowColors(True)
        self.preview_stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for column in range(self.preview_stats_table.columnCount()):
            self.preview_stats_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        configure_scrollable(self.preview_stats_table)
        stats_rows = [
            ("I 分量", "-", "-", "-", "-"),
            ("Q 分量", "-", "-", "-", "-"),
        ]
        for row_index, row_data in enumerate(stats_rows):
            for column, value in enumerate(row_data):
                self._set_table_value(self.preview_stats_table, row_index, column, value)

        self.preview_iq_table = QTableWidget(0, 3)
        self.preview_iq_table.setHorizontalHeaderLabels(["序号", "I", "Q"])
        self.preview_iq_table.horizontalHeader().setStretchLastSection(True)
        self.preview_iq_table.verticalHeader().setVisible(False)
        self.preview_iq_table.setAlternatingRowColors(True)
        self.preview_iq_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for column in range(self.preview_iq_table.columnCount()):
            self.preview_iq_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        configure_scrollable(self.preview_iq_table)

        section.body_layout.addLayout(info_form)
        section.body_layout.addWidget(self.preview_note_label)
        section.body_layout.addWidget(self.preview_field_table)
        section.body_layout.addWidget(self.preview_stats_table)
        section.body_layout.addWidget(self.preview_iq_table)
        return section

    def _build_result_card(self) -> SectionCard:
        """创建预处理结果卡片。"""

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
        summary_form.addRow("已保存样本", self.output_value)
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
        self.segment_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for column in range(self.segment_table.columnCount()):
            self.segment_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self.segment_table.setColumnWidth(0, 110)
        self.segment_table.setColumnWidth(1, 95)
        self.segment_table.setColumnWidth(2, 95)
        self.segment_table.setColumnWidth(3, 95)
        self.segment_table.setColumnWidth(4, 130)
        self.segment_table.setColumnWidth(5, 110)
        self.segment_table.setColumnWidth(6, 85)
        self.segment_table.setColumnWidth(7, 85)
        self.segment_table.setColumnWidth(8, 260)
        self.segment_table.setColumnWidth(9, 90)
        configure_scrollable(self.segment_table)

        log_and_table_row.addWidget(self.log_output, 2)
        log_and_table_row.addWidget(self.segment_table, 3)

        section.body_layout.addLayout(summary_form)
        section.body_layout.addWidget(self.result_message_label)
        section.body_layout.addLayout(log_and_table_row)
        return section

    def _selected_record(self) -> dict[str, object] | None:
        """返回当前选中的 CAP 文件记录。"""

        row = self.file_table.currentRow()
        if row < 0 or row >= len(self.cap_records):
            return None
        return self.cap_records[row]

    def _update_file_selection_state(self) -> None:
        """根据当前文件选择状态刷新相关控件。"""

        record = self._selected_record()
        if record is None:
            self.probe_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.delete_raw_file_button.setEnabled(False)
            self.file_status_badge.set_status("未选择", "warning", size="sm")
            self.file_status_label.setText("请选择一条原始文件记录后，再执行预览或预处理。")
            return

        path = Path(record["path"])
        exists = bool(record["exists"])
        status_text = str(record.get("status", ""))
        can_preprocess = exists and (not self._is_usrp_demo_mode() or status_text in {"已入库", "未入库"})
        self.probe_button.setEnabled(can_preprocess and not self._is_running())
        self.start_button.setEnabled(can_preprocess and not self._is_running())
        self.delete_raw_file_button.setEnabled(not self._is_running())
        if can_preprocess:
            self.file_status_badge.set_status("可预处理", "success", size="sm")
            action_text = "元数据预览或演示预处理" if self._is_usrp_demo_mode() else "头信息预览或 CAP 预处理"
            self.file_status_label.setText(f"已选文件：{path.name} | 路径：{path} | 可继续执行{action_text}。")
            if not self.output_dir_input.text().strip():
                self.output_dir_input.setText(str(self._default_output_dir_for(path)))
        elif exists:
            self.file_status_badge.set_status(status_text or "不可预处理", "warning", size="sm")
            self.file_status_label.setText(
                f"已选文件：{path.name} | 路径：{path} | 当前状态：{status_text or '不可预处理'}。"
                "USRP 演示预处理只接收 .iq + 同名 .json，.bin 仅作为采集留档。"
            )
        else:
            self.file_status_badge.set_status("缺失", "danger", size="sm")
            self.file_status_label.setText(f"未找到文件：{path}。请确认样本文件仍在原位置。")

    def _delete_selected_raw_file(self) -> None:
        """删除当前原始文件的数据库记录，可选同步删除本地原始文件。"""

        record = self._selected_record()
        if record is None:
            self.file_status_label.setText("请先选择要删除的原始文件。")
            return

        path = Path(record["path"])
        impact = get_raw_file_delete_impact(str(path))
        local_files = self._raw_local_files_for_delete(path)
        local_file_lines = [
            f"- {file_path}" + ("" if file_path.exists() else "（本地已不存在）")
            for file_path in local_files
        ]
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("删除原始文件")
        message.setText(f"准备删除原始文件：{path.name}")
        message.setInformativeText(
            "请选择删除方式。\n\n"
            "数据库影响："
            f"原始记录 {impact.get('raw_files', 0)} 条，"
            f"预处理任务 {impact.get('preprocess_tasks', 0)} 条，"
            f"样本 {impact.get('samples', 0)} 条，"
            f"数据集关联 {impact.get('dataset_items', 0)} 条，"
            f"更新版本 {impact.get('dataset_versions_updated', 0)} 个，"
            f"删除空版本 {impact.get('dataset_versions_deleted', 0)} 个。\n\n"
            "本地文件清单：\n"
            + "\n".join(local_file_lines)
            + "\n\n选择删除本地文件后不可恢复。"
        )
        db_only_button = message.addButton("仅删除数据库记录", QMessageBox.ButtonRole.AcceptRole)
        delete_files_button = message.addButton("删除数据库记录和本地文件", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = message.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(cancel_button)
        message.exec()

        clicked_button = message.clickedButton()
        if clicked_button == cancel_button:
            self.file_status_label.setText("已取消删除操作。")
            return

        delete_local_files = clicked_button == delete_files_button
        if delete_local_files and not self._delete_local_raw_files(local_files):
            return

        try:
            counts = delete_raw_file_record(str(path))
        except Exception as exc:
            self.file_status_label.setText(f"本地文件处理完成，但数据库记录删除失败：{exc}")
            return

        self.refresh_input_records()
        local_text = "本地文件已删除；" if delete_local_files else "本地文件已保留；"
        self.file_status_label.setText(
            f"已删除 {path.name} 的数据库关联："
            f"原始记录 {counts.get('raw_files', 0)} 条，"
            f"预处理任务 {counts.get('preprocess_tasks', 0)} 条，"
            f"样本 {counts.get('samples', 0)} 条，"
            f"数据集关联 {counts.get('dataset_items', 0)} 条。{local_text}"
        )
        self.workflow_records_changed.emit()

    def _raw_local_files_for_delete(self, path: Path) -> list[Path]:
        """返回删除一个原始文件时允许一并处理的本地文件列表。"""

        files = [path]
        if path.suffix.lower() in {".iq", ".bin"}:
            files.append(path.with_suffix(".json"))
        return files

    def _delete_local_raw_files(self, file_paths: list[Path]) -> bool:
        """删除允许范围内的本地原始文件，失败时不继续清数据库。"""

        existing_files = [path for path in file_paths if path.exists()]
        invalid_files = [path for path in existing_files if not path.is_file()]
        if invalid_files:
            self.file_status_label.setText(
                "删除已取消：以下路径不是普通文件，系统不会自动删除："
                + "；".join(str(path) for path in invalid_files)
            )
            return False

        try:
            for path in existing_files:
                path.unlink()
        except OSError as exc:
            self.file_status_label.setText(f"本地文件删除失败，数据库记录未删除：{exc}")
            return False
        return True

    def _load_selected_cap_preview(self) -> None:
        """读取当前选中 CAP 文件的头信息并刷新预览区。"""

        if self._is_usrp_demo_mode():
            self._load_selected_usrp_preview()
            return

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

    def _load_selected_usrp_preview(self) -> None:
        """读取当前选中 USRP IQ 文件的元数据和 IQ 预览。"""

        record = self._selected_record()
        if record is None:
            self._reset_preview("请先选择一条 USRP IQ 文件记录。", badge_level="warning")
            return

        path = Path(record["path"])
        try:
            result = preview_usrp_iq_file(path)
        except USRPDemoPreprocessError as exc:
            self._reset_preview(str(exc), badge_level="danger")
            self.status_metric.set_value("异常")
            return

        self._apply_usrp_preview(result)

    def _apply_probe_result(self, result: CapProbeResult) -> None:
        """把探针结果渲染到预览区和参数摘要区。"""

        self.current_probe_result = result
        self.current_usrp_info = None
        # 页面和算法必须保持同一口径，这里会直接展示当前联调使用的头长。
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
        self._set_preview_field_labels(
            [
                ("版本号", "0x0000"),
                ("分析带宽", "0x0010"),
                ("实际采样率", "0x0010 × 1.28"),
                ("中心频率", "0x0018"),
                ("帧采样数", "0x0110"),
                ("块大小", "0x0114"),
            ]
        )
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

    def _apply_usrp_preview(self, result: USRPDemoPreprocessInfo) -> None:
        """把 USRP IQ 预览结果渲染到预览区和参数摘要区。"""

        self.current_probe_result = None
        self.current_usrp_info = result
        self.preview_status_badge.set_status("USRP 就绪", "success", size="sm")
        self.preview_file_value.setText(result.path.name)
        self.preview_size_value.setText(self._format_bytes(result.file_size))
        self.preview_header_value.setText("-")
        self.preview_offset_value.setText("-")
        self.preview_scope_value.setText(f"前 {result.statistics_window_pairs:,} 组 IQ")
        self.preview_note_label.setText(
            "USRP IQ 文件没有 CAP 包头；本表仅展示采样参数，包头偏移列已置空。"
        )

        self._set_preview_field_labels(
            [
                ("格式", "-"),
                ("分析带宽", "-"),
                ("实际采样率", "-"),
                ("中心频率", "-"),
                ("IQ 点数", "-"),
                ("天线", "-"),
            ]
        )
        field_values = [
            "USRP IQ",
            f"{result.bandwidth_hz / 1_000_000:.3f} MHz",
            f"{result.sample_rate_hz / 1_000_000:.3f} MHz",
            f"{result.center_frequency_hz / 1_000_000:.3f} MHz",
            f"{result.iq_pair_count:,}",
            result.antenna or "-",
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
        self.status_metric.set_value("USRP 预览")

    def _start_preprocess_run(self) -> None:
        """收集当前参数并启动后台预处理任务。"""

        if self._is_running():
            return

        record = self._selected_record()
        if record is None:
            self.result_message_label.setText("请先选择一条原始文件记录。")
            return

        if self._is_usrp_demo_mode():
            self._start_usrp_demo_preprocess(record)
            return

        if self.current_probe_result is None or Path(record["path"]) != self.current_probe_result.path:
            self._load_selected_cap_preview()
            if self.current_probe_result is None:
                return

        input_path = Path(record["path"])
        # 页面只把必要的业务参数传给适配层，采样率和中心频率由 CAP 头自动解析。
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
        self._last_run_config = config

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

        # 算法运行放到后台线程，避免主界面在处理期间卡死。
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

    def _start_usrp_demo_preprocess(self, record: dict[str, object]) -> None:
        """收集参数并启动 USRP IQ 演示预处理。"""

        if self.current_usrp_info is None or Path(record["path"]) != self.current_usrp_info.path:
            self._load_selected_usrp_preview()
            if self.current_usrp_info is None:
                return

        input_path = Path(record["path"])
        config = USRPDemoPreprocessConfig(
            input_file_path=str(input_path),
            slice_length=self.slice_length_input.value(),
            energy_threshold_db=self.threshold_input.value(),
            sample_output_dir=self.output_dir_input.text().strip() or str(self._default_output_dir_for(input_path)),
        )

        self._set_running_state(True)
        self.current_run_result = None
        self.result_message_label.setText("USRP IQ 演示预处理任务已提交，正在后台执行。")
        self.run_state_value.setText("运行中")
        self.result_status_badge.set_status("运行中", "info", size="sm")
        self.run_status_badge.set_status("运行中", "info", size="sm")
        self.status_metric.set_value("运行中")
        self.output_dir_value.setText(config.sample_output_dir)
        self.log_output.setPlainText("USRP IQ 演示预处理启动中，请稍候...\n")
        self.segment_table.setRowCount(0)

        thread = QThread(self)
        worker = USRPDemoPreprocessWorker(config)
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
        """在任务开始时更新页面提示。"""

        self.log_output.setPlainText(f"启动预处理任务：{Path(input_file_path).name}\n")

    def _on_run_finished(self, result: PreprocessRunResult | USRPDemoPreprocessResult) -> None:
        """渲染一次完成后的预处理结果。"""

        self.current_run_result = result
        self._set_running_state(False)

        if isinstance(result, USRPDemoPreprocessResult):
            self._apply_usrp_preview(result.input_info)
        elif result.cap_info is not None:
            self._apply_probe_result(result.cap_info)

        self.detected_metric.set_value(str(result.detected_segment_count))
        saved_sample_count = len(result.sample_records)
        self.output_metric.set_value(str(saved_sample_count))
        # 新增候选段数展示
        if hasattr(result, "candidate_segment_count"):
            if hasattr(self, "candidate_metric"):
                self.candidate_metric.set_value(str(result.candidate_segment_count))
            if hasattr(self, "candidate_value"):
                self.candidate_value.setText(str(result.candidate_segment_count))
        self.detected_value.setText(str(result.detected_segment_count))
        self.output_value.setText(str(saved_sample_count))
        self.output_dir_value.setText(result.sample_output_dir)
        self.log_output.setPlainText("\n".join(result.logs) if result.logs else "本次任务未返回日志。")
        self._render_segment_table(result.segments)
        self._save_run_result_to_database(result)

        if result.success:
            self.run_state_value.setText("完成")
            self.result_message_label.setText(result.message or "预处理完成。")
            self.result_status_badge.set_status("处理完成", "success", size="sm")
            self.run_status_badge.set_status("处理完成", "success", size="sm")
            self.status_metric.set_value("完成")
            self.goto_dataset_button.setEnabled(bool(result.sample_records))
            # 只有有效片段被整理成样本记录后，才允许进入数据集管理继续流程。
            if result.sample_records:
                self.sample_records_generated.emit(result.sample_records)
                if isinstance(result, USRPDemoPreprocessResult):
                    self.config_status_label.setText(
                        f"本次已同步 {len(result.sample_records)} 条 USRP 三阶段候选样本，可直接进入数据集管理进行标注确认。"
                    )
                else:
                    self.config_status_label.setText(
                        f"本次已同步 {len(result.sample_records)} 条候选样本记录，可直接进入数据集管理进行标注确认。"
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
        """渲染一次后台任务失败结果。"""

        self._set_running_state(False)
        self.run_state_value.setText("失败")
        self.result_message_label.setText(message)
        self.result_status_badge.set_status("处理失败", "danger", size="sm")
        self.run_status_badge.set_status("处理失败", "danger", size="sm")
        self.status_metric.set_value("失败")
        self.log_output.setPlainText(message)
        self.goto_dataset_button.setEnabled(False)

    def _save_run_result_to_database(self, result: PreprocessRunResult | USRPDemoPreprocessResult) -> None:
        """保存预处理任务、候选样本和原始文件信息到数据库。"""

        if isinstance(result, USRPDemoPreprocessResult):
            try:
                save_usrp_preprocess_result(result)
                self.workflow_records_changed.emit()
            except Exception as exc:
                self.config_status_label.setText(f"USRP 三阶段预处理已完成，但数据库写入失败：{exc}")
            return

        if self._last_run_config is None:
            return
        try:
            save_preprocess_result(self._last_run_config, result)
            self.workflow_records_changed.emit()
        except Exception as exc:
            self.config_status_label.setText(f"预处理已完成，但数据库写入失败：{exc}")

    def _clear_run_worker(self) -> None:
        """在线程退出后清理 worker 引用。"""

        self._run_thread = None
        self._run_worker = None

    def _render_segment_table(self, segments: list[dict[str, object]]) -> None:
        """把标准化后的片段结果渲染到结果表。"""

        self.segment_table.setRowCount(len(segments))
        for row_index, segment in enumerate(segments):
            output_file_path = str(segment.get("output_file_path", ""))
            values = [
                str(segment.get("segment_id", "")),
                str(segment.get("start_sample", "")),
                str(segment.get("end_sample", "")),
                f"{float(segment.get('duration_ms', 0.0)):.2f}",
                f"{float(segment.get('center_freq_hz', 0.0)):.1f}",
                f"{float(segment.get('bandwidth_hz', 0.0)):.1f}",
                f"{float(segment.get('snr_db', 0.0)):.2f}",
                f"{float(segment.get('score', 0.0)):.4f}",
                output_file_path,
                str(segment.get("status", "")),
            ]
            for column, value in enumerate(values):
                self._set_table_value(self.segment_table, row_index, column, value)
            first_item = self.segment_table.item(row_index, 0)
            if first_item is not None:
                first_item.setData(Qt.ItemDataRole.UserRole, output_file_path)

    def _set_running_state(self, running: bool) -> None:
        """根据后台任务状态统一启用或禁用控件。"""

        self.probe_button.setEnabled(not running)
        self.refresh_files_button.setEnabled(not running)
        selected_record = self._selected_record()
        can_preprocess = False
        if selected_record is not None:
            status_text = str(selected_record.get("status", ""))
            can_preprocess = bool(selected_record["exists"]) and (
                not self._is_usrp_demo_mode() or status_text in {"已入库", "未入库"}
            )
        self.start_button.setEnabled(not running and can_preprocess)
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
        if hasattr(self, "delete_raw_file_button"):
            self.delete_raw_file_button.setEnabled(not running and self._selected_record() is not None)

        if running:
            self.process_progress.setRange(0, 0)
        else:
            self.process_progress.setRange(0, 100)
            self.process_progress.setValue(100 if self.current_run_result and self.current_run_result.success else 0)

    def _is_running(self) -> bool:
        """返回当前是否存在正在执行的预处理任务。"""

        return self._run_thread is not None

    def _reset_preview(self, message: str, badge_level: str = "info") -> None:
        """把预览区重置到安全占位状态。"""

        label = "待读取" if badge_level == "info" else "读取失败"
        self.current_probe_result = None
        self.current_usrp_info = None
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
        """设置表格单元格文本，不存在时自动创建 item。"""

        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        item.setText(value)
        item.setToolTip(value)
        is_path_column = table in (getattr(self, "file_table", None), getattr(self, "segment_table", None)) and column in {0, 8}
        alignment = Qt.AlignmentFlag.AlignVCenter | (
            Qt.AlignmentFlag.AlignLeft if is_path_column else Qt.AlignmentFlag.AlignCenter
        )
        item.setTextAlignment(alignment)

    def _item_text(self, table: QTableWidget, row: int, column: int) -> str:
        """读取一个表格单元格的紧凑文本。"""

        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _set_preview_field_labels(self, rows: list[tuple[str, str]]) -> None:
        """刷新预览字段表的字段名和来源说明。"""

        for row_index, (field_name, source_text) in enumerate(rows):
            self._set_table_value(self.preview_field_table, row_index, 0, field_name)
            self._set_table_value(self.preview_field_table, row_index, 1, source_text)

    def _default_output_dir_for(self, path: Path) -> Path:
        """返回某个原始文件默认对应的输出目录。"""

        base_dir = default_usrp_demo_output_dir() if self._is_usrp_demo_mode() else default_preprocess_output_dir()
        return base_dir / path.stem

    def _default_output_dir_for_selected_mode(self) -> Path:
        """返回当前模式的默认输出目录。"""

        return default_usrp_demo_output_dir() if self._is_usrp_demo_mode() else default_preprocess_output_dir()

    def _is_usrp_demo_mode(self) -> bool:
        """返回当前是否处于 USRP IQ 演示预处理模式。"""

        return hasattr(self, "input_mode_box") and self.input_mode_box.currentIndex() == 1

    def _format_bytes(self, size: int) -> str:
        """把文件大小格式化为紧凑可读文本。"""

        units = ["B", "KB", "MB", "GB"]
        current_size = float(size)
        for unit in units:
            if current_size < 1024.0 or unit == units[-1]:
                return f"{current_size:.1f} {unit}" if unit != "B" else f"{int(current_size)} B"
            current_size /= 1024.0
        return f"{size} B"
