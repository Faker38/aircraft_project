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
from ui.page_capture import CapturePage
from ui.page_export import ExportPage
from ui.page_overview import OverviewPage
from ui.page_process import ProcessPage
from ui.page_train import TrainPage
from ui.widgets import StatusBadge


class MainWindow(QMainWindow):
    """Application shell that hosts the sidebar and workflow pages."""

    PAGE_META: dict[str, tuple[str, str]] = {
        "overview": ("工程总览", "集中查看采集、处理、训练和交付链路。"),
        "capture": ("步骤 1 · 数据采集", "配置设备接入与采集参数，生成原始数据文件。"),
        "process": ("步骤 2 · 信号处理与标注", "完成信号处理、样本标注和数据集构建。"),
        "train": ("步骤 3 · 模型训练", "配置训练任务并完成结果评估。"),
        "export": ("步骤 4 · 模型导出", "导出部署模型及配套交付文件。"),
    }

    def __init__(self) -> None:
        """Initialize the main application window."""

        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1560, 960)
        self.setMinimumSize(1320, 820)

        self.page_buttons: dict[str, QPushButton] = {}
        self.pages: dict[str, QWidget] = {}

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        main_area = self._build_main_area()

        root_layout.addWidget(sidebar)
        root_layout.addWidget(main_area, 1)

        self.statusBar().showMessage("系统已加载，当前为联调模式。")

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start(1000)
        self._refresh_clock()

        self.select_page("overview")

    def _build_sidebar(self) -> QFrame:
        """Create the left navigation sidebar."""

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(290)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)

        branding_frame = QFrame()
        branding_frame.setObjectName("InfoPanel")
        branding_layout = QVBoxLayout(branding_frame)
        branding_layout.setContentsMargins(18, 18, 18, 18)
        branding_layout.setSpacing(8)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("AppTitle")
        subtitle_label = QLabel(APP_SUBTITLE)
        subtitle_label.setObjectName("AppSubTitle")
        subtitle_label.setWordWrap(True)

        branding_layout.addWidget(title_label)
        branding_layout.addWidget(subtitle_label)
        layout.addWidget(branding_frame)

        section_label = QLabel("任务导航")
        section_label.setObjectName("SidebarSection")
        layout.addWidget(section_label)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_items = [
            ("overview", "总览"),
            ("capture", "数据采集"),
            ("process", "信号处理"),
            ("train", "模型训练"),
            ("export", "模型导出"),
        ]
        for key, label in nav_items:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page_key=key: self.select_page(page_key))
            self.nav_group.addButton(button)
            self.page_buttons[key] = button
            layout.addWidget(button)

        layout.addSpacing(8)
        device_panel = QFrame()
        device_panel.setObjectName("InfoPanel")
        device_layout = QVBoxLayout(device_panel)
        device_layout.setContentsMargins(18, 18, 18, 18)
        device_layout.setSpacing(10)

        device_title = QLabel("系统状态")
        device_title.setObjectName("StepTitle")
        self.global_connection_badge = StatusBadge("3943B 未接入", "danger")
        device_hint = QLabel("支持 LAN/VISA 接入配置、状态监测和采集控制。")
        device_hint.setObjectName("MutedText")
        device_hint.setWordWrap(True)

        device_layout.addWidget(device_title)
        device_layout.addWidget(self.global_connection_badge, 0, Qt.AlignmentFlag.AlignLeft)
        device_layout.addWidget(device_hint)
        layout.addWidget(device_panel)

        layout.addStretch(1)
        return sidebar

    def _build_main_area(self) -> QWidget:
        """Create the main content area with header and stacked pages."""

        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(18)

        layout.addWidget(self._build_header())

        self.page_stack = QStackedWidget()

        overview_page = OverviewPage()
        overview_page.navigate_requested.connect(self.select_page)

        capture_page = CapturePage()
        capture_page.connection_state_changed.connect(self._update_connection_badge)

        process_page = ProcessPage()
        train_page = TrainPage()
        export_page = ExportPage()

        self.pages = {
            "overview": overview_page,
            "capture": capture_page,
            "process": process_page,
            "train": train_page,
            "export": export_page,
        }
        for page in self.pages.values():
            self.page_stack.addWidget(page)

        layout.addWidget(self.page_stack, 1)
        return wrapper

    def _build_header(self) -> QFrame:
        """Create the top header panel."""

        panel = QFrame()
        panel.setObjectName("HeaderPanel")

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(18)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(4)

        self.page_title_label = QLabel()
        self.page_title_label.setObjectName("PageTitle")

        self.page_description_label = QLabel()
        self.page_description_label.setObjectName("PageDescription")
        self.page_description_label.setWordWrap(True)

        title_layout.addWidget(self.page_title_label)
        title_layout.addWidget(self.page_description_label)

        layout.addLayout(title_layout, 1)

        right_layout = QHBoxLayout()
        right_layout.setSpacing(10)

        mode_panel = QFrame()
        mode_panel.setObjectName("HeaderInfoPanel")
        mode_layout = QVBoxLayout(mode_panel)
        mode_layout.setContentsMargins(14, 10, 14, 10)
        mode_layout.setSpacing(6)

        mode_title = QLabel("运行状态")
        mode_title.setObjectName("HeaderMetaLabel")
        self.global_mode_badge = StatusBadge("联调模式", "info")
        mode_layout.addWidget(mode_title)
        mode_layout.addWidget(self.global_mode_badge, 0, Qt.AlignmentFlag.AlignLeft)

        clock_panel = QFrame()
        clock_panel.setObjectName("HeaderInfoPanel")
        clock_layout = QVBoxLayout(clock_panel)
        clock_layout.setContentsMargins(14, 10, 14, 10)
        clock_layout.setSpacing(6)

        clock_title = QLabel("系统时钟")
        clock_title.setObjectName("HeaderMetaLabel")
        self.clock_label = QLabel()
        self.clock_label.setObjectName("HeaderMetaValue")
        clock_layout.addWidget(clock_title)
        clock_layout.addWidget(self.clock_label)

        right_layout.addWidget(mode_panel)
        right_layout.addWidget(clock_panel)

        layout.addLayout(right_layout)
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
        self.statusBar().showMessage(f"已切换到 {title}")

    def _update_connection_badge(self, connected: bool) -> None:
        """Update the global connection badge from the capture page."""

        if connected:
            self.global_connection_badge.set_status("3943B 已接入", "success")
        else:
            self.global_connection_badge.set_status("3943B 未接入", "danger")

    def _refresh_clock(self) -> None:
        """Update the header clock display."""

        self.clock_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
