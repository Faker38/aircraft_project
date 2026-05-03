"""Main window for the RF identification desktop application."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME, APP_SUBTITLE
from services import get_workflow_overview_counts
from ui.page_capture import CapturePage
from ui.page_dataset import DatasetPage
from ui.page_overview import OverviewPage
from ui.page_preprocess import PreprocessPage
from ui.page_recognition import RecognitionPage
from ui.page_train import TrainPage
from ui.widgets import StatusBadge


class MainWindow(QMainWindow):
    """Application shell that hosts the sidebar and workflow pages."""

    PAGE_META: dict[str, tuple[str, str]] = {
        "overview": ("工程总览", "查看当前流程阶段、系统状态和任务入口。"),
        "capture": ("步骤 1 · 数据采集", "完成设备接入、参数配置和原始文件记录。"),
        "preprocess": ("步骤 2 · 信号预处理", "完成信号筛选、切片和样本生成。"),
        "dataset": ("步骤 3 · 数据集管理", "完成已处理样本复核、标签维护与数据集构建。"),
        "train": ("步骤 4 · 模型训练", "执行训练评估并导出模型。"),
        "recognition": ("步骤 5 · 无人机识别", "执行类型识别与个体指纹识别。"),
    }

    def __init__(self) -> None:
        """Initialize the main application window."""

        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 920)
        self.setMinimumSize(1320, 820)

        self.page_buttons: dict[str, QPushButton] = {}
        self.pages: dict[str, QWidget] = {}

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_main_area(), 1)

        self.statusBar().showMessage("系统就绪 | 当前模式：联调")

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start(1000)
        self._refresh_clock()

        self.select_page("overview")

    def _build_sidebar(self) -> QFrame:
        """Create the left navigation sidebar."""

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(272)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("AppTitle")
        subtitle_label = QLabel(APP_SUBTITLE)
        subtitle_label.setObjectName("AppSubTitle")
        subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addSpacing(8)

        section_label = QLabel("任务导航")
        section_label.setObjectName("SidebarSection")
        layout.addWidget(section_label)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_items = [
            ("overview", "工程总览"),
            ("capture", "数据采集"),
            ("preprocess", "信号预处理"),
            ("dataset", "数据集管理"),
            ("train", "模型训练"),
            ("recognition", "无人机识别"),
        ]
        for key, label in nav_items:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page_key=key: self.select_page(page_key))
            self.nav_group.addButton(button)
            self.page_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        status_panel = QFrame()
        status_panel.setObjectName("InfoPanel")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(10)

        status_title = QLabel("系统状态")
        status_title.setObjectName("SectionTitle")

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_label = QLabel("运行模式")
        mode_label.setObjectName("FieldLabel")
        self.sidebar_mode_badge = StatusBadge("联调模式", "info", size="sm")
        mode_row.addWidget(mode_label)
        mode_row.addStretch(1)
        mode_row.addWidget(self.sidebar_mode_badge, 0, Qt.AlignmentFlag.AlignRight)

        device_row = QHBoxLayout()
        device_row.setContentsMargins(0, 0, 0, 0)
        device_row.setSpacing(8)
        device_label = QLabel("设备状态")
        device_label.setObjectName("FieldLabel")
        self.global_connection_badge = StatusBadge("设备未接入", "danger", size="sm")
        device_row.addWidget(device_label)
        device_row.addStretch(1)
        device_row.addWidget(self.global_connection_badge, 0, Qt.AlignmentFlag.AlignRight)

        status_layout.addWidget(status_title)
        status_layout.addLayout(mode_row)
        status_layout.addLayout(device_row)
        layout.addWidget(status_panel)

        return sidebar

    def _build_main_area(self) -> QWidget:
        """Create the main content area with header and stacked pages."""

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(16)

        layout.addWidget(self._build_header())

        self.page_stack = QStackedWidget()

        overview_page = OverviewPage()
        overview_page.navigate_requested.connect(self.select_page)

        capture_page = CapturePage()
        preprocess_page = PreprocessPage()
        dataset_page = DatasetPage()
        train_page = TrainPage()
        recognition_page = RecognitionPage()

        capture_page.connection_state_changed.connect(self._update_connection_badge)
        capture_page.raw_capture_completed.connect(lambda _result: preprocess_page.refresh_input_records(usrp_mode=True))
        capture_page.raw_capture_completed.connect(lambda _result: self._refresh_overview_metrics())
        capture_page.raw_records_changed.connect(lambda: dataset_page.refresh_from_database())
        capture_page.raw_records_changed.connect(lambda: preprocess_page.refresh_input_records())
        capture_page.raw_records_changed.connect(lambda: self._refresh_overview_metrics())
        preprocess_page.navigate_requested.connect(self.select_page)
        preprocess_page.sample_records_generated.connect(dataset_page.add_preprocess_records)
        preprocess_page.workflow_records_changed.connect(lambda: dataset_page.refresh_from_database())
        preprocess_page.workflow_records_changed.connect(lambda: self._refresh_overview_metrics())
        recognition_page.sample_refresh_requested.connect(lambda: dataset_page.refresh_from_database())
        recognition_page.sample_refresh_requested.connect(lambda: self._refresh_overview_metrics())
        dataset_page.dataset_versions_updated.connect(train_page.set_dataset_versions)
        dataset_page.dataset_versions_updated.connect(lambda _records: self._refresh_overview_metrics())
        dataset_page.sample_records_updated.connect(recognition_page.set_sample_records)
        dataset_page.sample_records_updated.connect(lambda _records: self._refresh_overview_metrics())
        train_page.trained_models_updated.connect(recognition_page.set_trained_models)
        train_page.trained_models_updated.connect(lambda _records: self._refresh_overview_metrics())

        self.pages = {
            "overview": overview_page,
            "capture": capture_page,
            "preprocess": preprocess_page,
            "dataset": dataset_page,
            "train": train_page,
            "recognition": recognition_page,
        }
        for page in self.pages.values():
            self.page_stack.addWidget(page)

        train_page.set_dataset_versions(dataset_page.get_dataset_versions())
        recognition_page.set_sample_records(dataset_page.get_sample_records())
        recognition_page.set_trained_models(train_page.get_trained_models())
        self._refresh_overview_metrics()

        layout.addWidget(self.page_stack, 1)
        return wrapper

    def _build_header(self) -> QFrame:
        """Create the top header panel."""

        panel = QFrame()
        panel.setObjectName("HeaderPanel")

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(18)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        self.page_title_label = QLabel()
        self.page_title_label.setObjectName("PageTitle")

        self.page_description_label = QLabel()
        self.page_description_label.setObjectName("PageDescription")
        self.page_description_label.setWordWrap(True)

        title_layout.addWidget(self.page_title_label)
        title_layout.addWidget(self.page_description_label)
        layout.addLayout(title_layout, 1)

        strip = QFrame()
        strip.setObjectName("HeaderStatusStrip")
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(14, 10, 14, 10)
        strip_layout.setSpacing(12)

        mode_label = QLabel("运行模式")
        mode_label.setObjectName("HeaderMetaLabel")
        self.header_mode_badge = StatusBadge("联调模式", "info", size="sm")

        device_label = QLabel("设备状态")
        device_label.setObjectName("HeaderMetaLabel")
        self.header_device_badge = StatusBadge("设备未接入", "danger", size="sm")

        clock_title = QLabel("系统时钟")
        clock_title.setObjectName("HeaderMetaLabel")
        self.clock_label = QLabel()
        self.clock_label.setObjectName("HeaderMetaValue")

        strip_layout.addWidget(mode_label)
        strip_layout.addWidget(self.header_mode_badge)
        strip_layout.addSpacing(4)
        strip_layout.addWidget(device_label)
        strip_layout.addWidget(self.header_device_badge)
        strip_layout.addSpacing(4)
        strip_layout.addWidget(clock_title)
        strip_layout.addWidget(self.clock_label)

        layout.addWidget(strip, 0, Qt.AlignmentFlag.AlignRight)
        return panel

    def select_page(self, key: str) -> None:
        """Select a page by its key."""

        page = self.pages[key]
        self.page_stack.setCurrentWidget(page)

        for page_key, button in self.page_buttons.items():
            button.setChecked(page_key == key)

        title, description = self.PAGE_META[key]
        self.page_title_label.setText(title)
        self.page_description_label.setText(description)
        self.statusBar().showMessage(f"当前页面：{title}")

    def _update_connection_badge(self, connected: bool, device_text: str) -> None:
        """Update shared device status widgets from the capture page."""

        if "联调模拟" in device_text or "预检中" in device_text or "待处理" in device_text:
            badge_level = "warning"
        elif connected:
            badge_level = "success"
        else:
            badge_level = "danger"
        self.global_connection_badge.set_status(device_text, badge_level)
        self.header_device_badge.set_status(device_text, badge_level)

        overview_page = self.pages.get("overview")
        if isinstance(overview_page, OverviewPage):
            overview_page.set_device_status(connected, device_text)

    def _refresh_overview_metrics(self) -> None:
        """Update overview metrics from current database state."""

        overview_page = self.pages.get("overview")
        if isinstance(overview_page, OverviewPage):
            overview_page.set_workflow_metrics(get_workflow_overview_counts())

    def _refresh_clock(self) -> None:
        """Update the header clock display."""

        self.clock_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
