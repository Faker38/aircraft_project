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

from ui.widgets import MetricCard, SectionCard, SmoothScrollArea, StatusBadge


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

        content_layout.addWidget(self._build_summary_section())
        content_layout.addWidget(self._build_workflow_section())
        content_layout.addWidget(self._build_metrics_section())
        content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

        self._refresh_device_state()

    def _build_summary_section(self) -> SectionCard:
        """Create the overview summary section."""

        section = SectionCard(
            "任务总览",
            "当前任务按采集、预处理、数据集管理、训练、识别五个步骤组织。",
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

        version_value = QLabel("v003")
        version_value.setObjectName("SummaryValue")

        summary_rows = [
            ("设备状态", self.device_value_label),
            ("当前阶段", stage_value),
            ("数据集版本", version_value),
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

        hint_label = QLabel("首屏仅保留任务状态和模块入口。")
        hint_label.setObjectName("MutedText")

        action_row.addWidget(primary_button, 0, Qt.AlignmentFlag.AlignLeft)
        action_row.addWidget(hint_label)
        action_row.addStretch(1)

        section.body_layout.addLayout(grid)
        section.body_layout.addLayout(action_row)
        return section

    def _build_workflow_section(self) -> SectionCard:
        """Build the lightweight workflow entry section."""

        section = SectionCard(
            "流程入口",
            "按任务步骤进入对应模块。",
            compact=True,
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        steps = [
            ("capture", "01", "数据采集", "待执行", "设备接入与记录控制"),
            ("preprocess", "02", "信号预处理", "待处理", "原始文件筛选与样本生成"),
            ("dataset", "03", "数据集管理", "待整理", "公开数据导入、标注维护与数据集构建"),
            ("train", "04", "模型训练", "可训练", "训练评估与模型导出"),
            ("recognition", "05", "无人机识别", "待识别", "类型识别与个体指纹识别"),
        ]

        for index, (page_key, step_no, title, state, hint) in enumerate(steps):
            row = index // 2
            column = index % 2
            grid.addWidget(self._build_step_card(page_key, step_no, title, state, hint), row, column)

        section.body_layout.addLayout(grid)
        return section

    def _build_step_card(
        self,
        page_key: str,
        step_no: str,
        title: str,
        state: str,
        hint: str,
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
        hint_label = QLabel(hint)
        hint_label.setObjectName("FlowHint")
        hint_label.setWordWrap(True)

        open_button = QPushButton("进入模块")
        open_button.clicked.connect(lambda checked=False, key=page_key: self.navigate_requested.emit(key))

        layout.addLayout(header_row)
        layout.addWidget(state_badge, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(hint_label)
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return card

    def _build_metrics_section(self) -> SectionCard:
        """Build the compact key metrics section."""

        section = SectionCard("关键指标", "显示当前工程常用指标。", compact=True)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(MetricCard("数据集版本", "v003", compact=True))
        row.addWidget(MetricCard("最新模型精度", "94.7%", accent_color="#7CB98B", compact=True))
        row.addWidget(MetricCard("当前识别模型", "iqcnn_v003", accent_color="#C59A63", compact=True))

        section.body_layout.addLayout(row)
        return section

    def set_device_connected(self, connected: bool) -> None:
        """Refresh the device status shown on the overview page."""

        self._device_connected = connected
        self._refresh_device_state()

    def _refresh_device_state(self) -> None:
        """Update summary labels based on the current mocked device state."""

        if self._device_connected:
            self.device_value_label.setText("3943B 已接入")
        else:
            self.device_value_label.setText("3943B 未接入")
