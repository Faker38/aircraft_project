"""Overview page for the RF identification desktop application."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge, VisualHeroCard


class OverviewPage(QWidget):
    """Landing page that summarizes the five-step workflow."""

    navigate_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the overview page."""

        super().__init__(parent)
        self._device_connected = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = SmoothScrollArea()

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(16)

        content_layout.addWidget(self._build_visual_banner())
        content_layout.addWidget(self._build_summary_section())
        content_layout.addWidget(self._build_workflow_section())
        content_layout.addWidget(self._build_metrics_section())
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._refresh_device_state()

    def _build_visual_banner(self) -> VisualHeroCard:
        """Create a restrained visual banner for the overview page."""

        return VisualHeroCard(
            "工程总览",
            "",
            background_name="overview_header_bg.svg",
            chips=[],
            ornament_name="decor_signal_corner_a.svg",
            height=176,
        )

    def _build_summary_section(self) -> SectionCard:
        """Create the overview summary section."""

        section = SectionCard(
            "任务总览",
            "",
            right_widget=StatusBadge("步骤 1 就绪", "info", size="sm"),
            compact=True,
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(12)

        self.device_value_label = QLabel()
        self.device_value_label.setObjectName("SummaryValue")

        stage_value = QLabel("数据采集")
        stage_value.setObjectName("SummaryValue")

        self.version_value_label = QLabel("未生成")
        self.version_value_label.setObjectName("SummaryValue")

        summary_rows = [
            ("设备状态", self.device_value_label),
            ("阶段", stage_value),
            ("数据集版本", self.version_value_label),
        ]

        for row, (label_text, value_widget) in enumerate(summary_rows):
            key_label = QLabel(label_text)
            key_label.setObjectName("SummaryKey")
            grid.addWidget(key_label, row, 0)
            grid.addWidget(value_widget, row, 1)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)

        primary_button = QPushButton("进入数据采集")
        primary_button.setObjectName("PrimaryButton")
        primary_button.clicked.connect(lambda: self.navigate_requested.emit("capture"))

        action_row.addWidget(primary_button, 0, Qt.AlignmentFlag.AlignLeft)
        action_row.addStretch(1)

        section.body_layout.addLayout(grid)
        section.body_layout.addLayout(action_row)
        return section

    def _build_workflow_section(self) -> SectionCard:
        """Build the lightweight workflow entry section."""

        section = SectionCard(
            "流程入口",
            "",
            compact=True,
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        steps = [
            ("capture", "01", "数据采集", "就绪"),
            ("preprocess", "02", "信号预处理", "就绪"),
            ("dataset", "03", "数据集管理", "就绪"),
            ("train", "04", "模型训练", "就绪"),
            ("recognition", "05", "无人机识别", "就绪"),
        ]

        for index, (page_key, step_no, title, state) in enumerate(steps):
            row = index // 2
            column = index % 2
            grid.addWidget(self._build_step_card(page_key, step_no, title, state), row, column)

        section.body_layout.addLayout(grid)
        return section

    def _build_step_card(
        self,
        page_key: str,
        step_no: str,
        title: str,
        state: str,
    ) -> QFrame:
        """Create a compact workflow entry card."""

        card = QFrame()
        card.setObjectName("WorkflowEntryCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        index_label = QLabel(step_no)
        index_label.setObjectName("FlowIndex")

        title_label = QLabel(title)
        title_label.setObjectName("FlowTitle")

        header_row.addWidget(index_label)
        header_row.addWidget(title_label)
        header_row.addStretch(1)

        state_badge = StatusBadge(state, "info", size="sm")

        open_button = QPushButton("进入模块")
        open_button.clicked.connect(lambda checked=False, key=page_key: self.navigate_requested.emit(key))

        layout.addLayout(header_row)
        layout.addWidget(state_badge, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return card

    def _build_metrics_section(self) -> SectionCard:
        """Build the compact key metrics section."""

        section = SectionCard("关键指标", "", compact=True)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.raw_metric = MetricCard("原始任务数", "0", compact=True)
        self.sample_metric = MetricCard("已处理样本数", "0", accent_color="#7CB98B", compact=True)
        self.version_metric = MetricCard("数据集", "未生成", accent_color="#5EA6D3", compact=True)
        self.model_metric = MetricCard("最新训练模型", "未生成", accent_color="#C59A63", compact=True)
        row.addWidget(self.raw_metric)
        row.addWidget(self.sample_metric)
        row.addWidget(self.version_metric)
        row.addWidget(self.model_metric)

        section.body_layout.addLayout(row)
        return section

    def set_device_connected(self, connected: bool) -> None:
        """Refresh the device status shown on the overview page."""

        self._device_connected = connected
        self._refresh_device_state("3943B 已接入" if connected else "3943B 未接入")

    def set_device_status(self, connected: bool, device_text: str) -> None:
        """Refresh the device status using the shared shell text."""

        self._device_connected = connected
        self._refresh_device_state(device_text)

    def set_workflow_metrics(self, payload: dict[str, object]) -> None:
        """Refresh overview metrics from database-backed workflow state."""

        raw_count = int(payload.get("raw_count", 0))
        sample_count = int(payload.get("sample_count", 0))
        current_version = str(payload.get("current_version") or "未生成")
        latest_model = str(payload.get("latest_model") or "未生成")
        self.raw_metric.set_value(str(raw_count))
        self.sample_metric.set_value(str(sample_count))
        self.version_metric.set_value(current_version)
        self.model_metric.set_value(latest_model)
        self.version_value_label.setText(current_version)

    def _refresh_device_state(self, device_text: str | None = None) -> None:
        """Update summary labels based on the current mocked device state."""

        if device_text:
            self.device_value_label.setText(device_text)
        elif self._device_connected:
            self.device_value_label.setText("3943B 已接入")
        else:
            self.device_value_label.setText("3943B 未接入")
