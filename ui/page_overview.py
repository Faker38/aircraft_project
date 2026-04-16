"""Overview page for the RF identification desktop application."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.widgets import MetricCard, SectionCard, StatusBadge


class OverviewPage(QWidget):
    """Landing page that summarizes the four-step workflow."""

    navigate_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the overview page."""

        super().__init__(parent)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        container = QWidget()
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setContentsMargins(6, 6, 6, 6)
        self.content_layout.setSpacing(18)

        self.content_layout.addWidget(self._build_hero_panel())
        self.content_layout.addLayout(self._build_metrics_row())
        self.content_layout.addWidget(self._build_workflow_section())
        self.content_layout.addWidget(self._build_readiness_section())
        self.content_layout.addStretch(1)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)

    def _build_hero_panel(self) -> QFrame:
        """Create the hero panel shown at the top of the overview."""

        panel = QFrame()
        panel.setObjectName("HeroPanel")

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(22)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(10)

        eyebrow = QLabel("工程总览")
        eyebrow.setObjectName("HeroEyebrow")

        title = QLabel("无人机射频识别任务链路")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)

        description = QLabel(
            "本页汇总设备接入、数据流转、训练评估和模型交付状态，"
            "用于联调验证与项目展示。"
        )
        description.setObjectName("HeroDescription")
        description.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        capture_button = QPushButton("打开采集模块")
        capture_button.setObjectName("PrimaryButton")
        capture_button.clicked.connect(lambda: self.navigate_requested.emit("capture"))

        train_button = QPushButton("打开训练模块")
        train_button.clicked.connect(lambda: self.navigate_requested.emit("train"))

        button_row.addWidget(capture_button)
        button_row.addWidget(train_button)
        button_row.addStretch(1)

        text_layout.addWidget(eyebrow)
        text_layout.addWidget(title)
        text_layout.addWidget(description)
        text_layout.addLayout(button_row)
        layout.addLayout(text_layout, 3)

        side_panel = QFrame()
        side_panel.setObjectName("InfoPanel")

        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(20, 18, 20, 18)
        side_layout.setSpacing(10)

        status_badge = StatusBadge("联调阶段", "success")
        side_layout.addWidget(status_badge, 0, Qt.AlignmentFlag.AlignLeft)

        signal_chain_title = QLabel("工程阶段")
        signal_chain_title.setObjectName("SectionTitle")
        side_layout.addWidget(signal_chain_title)

        for text in [
            "1. 界面基线与交互规范",
            "2. 设备接入与记录控制",
            "3. 处理链路与训练联调",
            "4. 实装设备与文件格式适配",
        ]:
            item = QLabel(text)
            item.setObjectName("MutedText")
            item.setWordWrap(True)
            side_layout.addWidget(item)

        side_layout.addStretch(1)
        layout.addWidget(side_panel, 2)
        return panel

    def _build_metrics_row(self) -> QHBoxLayout:
        """Build the summary metric cards row."""

        layout = QHBoxLayout()
        layout.setSpacing(14)

        cards = [
            MetricCard("设备接口", "LAN / VISA", "RJ45 远程接入，默认端口 5025。", "#00D9FF"),
            MetricCard("数据载体", ".cap / .npy", "原始文件、IQ 样本和特征文件分层存储。", "#19C584"),
            MetricCard("训练路径", "ML / DL", "类型识别与个体识别分别配置。", "#FFA726"),
            MetricCard("交付格式", "ONNX", "导出模型时同步生成配置与推理脚本。", "#0097E6"),
        ]
        for card in cards:
            layout.addWidget(card)
        return layout

    def _build_workflow_section(self) -> SectionCard:
        """Build the workflow step section."""

        section = SectionCard(
            "任务链路",
            "按业务顺序组织模块，便于切换、联调和状态查看。",
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        steps: list[tuple[str, str, str, list[str]]] = [
            (
                "capture",
                "01 / 数据采集",
                "连接 3943B，设置参数并保存原始数据文件。",
                ["设备接入", "参数配置", "采集记录"],
            ),
            (
                "process",
                "02 / 信号处理",
                "生成 IQ 样本，完成标注和数据集构建。",
                ["处理链路", "标注管理", "数据集版本"],
            ),
            (
                "train",
                "03 / 模型训练",
                "配置训练任务并完成结果评估。",
                ["训练配置", "评估指标", "单样本校验"],
            ),
            (
                "export",
                "04 / 模型导出",
                "导出模型文件及配套交付内容。",
                ["模型信息", "导出配置", "交付结果"],
            ),
        ]

        for index, (page_key, title, description, bullets) in enumerate(steps):
            row = index // 2
            column = index % 2
            grid.addWidget(self._build_step_card(page_key, title, description, bullets), row, column)

        section.body_layout.addLayout(grid)
        return section

    def _build_step_card(
        self,
        page_key: str,
        title: str,
        description: str,
        bullets: list[str],
    ) -> QFrame:
        """Create a single workflow step card."""

        card = QFrame()
        card.setObjectName("StepCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        index_label = QLabel(title.split("/")[0].strip())
        index_label.setObjectName("StepIndex")

        title_label = QLabel(title.split("/", 1)[1].strip())
        title_label.setObjectName("StepTitle")

        description_label = QLabel(description)
        description_label.setObjectName("StepDescription")
        description_label.setWordWrap(True)

        layout.addWidget(index_label)
        layout.addWidget(title_label)
        layout.addWidget(description_label)

        for bullet in bullets:
            bullet_label = QLabel(f"• {bullet}")
            bullet_label.setObjectName("MutedText")
            layout.addWidget(bullet_label)

        open_button = QPushButton("打开模块")
        open_button.clicked.connect(lambda: self.navigate_requested.emit(page_key))
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)

        return card

    def _build_readiness_section(self) -> SectionCard:
        """Create the project readiness summary section."""

        section = SectionCard(
            "当前状态",
            "当前版本已完成流程组织、信息层级和后续模块接入接口。",
        )

        row = QHBoxLayout()
        row.setSpacing(14)

        readiness_cards = [
            ("流程闭环", "采集、处理、训练和交付按任务顺序独立组织。"),
            ("状态清晰", "深色界面、青蓝高亮和卡片布局统一。"),
            ("便于扩展", "后续接入线程、数据库和设备服务时无需重构界面。"),
        ]

        for title, description in readiness_cards:
            card = QFrame()
            card.setObjectName("InfoPanel")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            card_layout.setSpacing(10)

            badge = StatusBadge("已落实", "success")
            heading = QLabel(title)
            heading.setObjectName("StepTitle")

            detail = QLabel(description)
            detail.setObjectName("MutedText")
            detail.setWordWrap(True)

            card_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
            card_layout.addWidget(heading)
            card_layout.addWidget(detail)
            row.addWidget(card)

        section.body_layout.addLayout(row)
        return section
