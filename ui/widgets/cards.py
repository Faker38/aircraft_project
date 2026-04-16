"""Reusable card widgets used across the desktop application."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class StatusBadge(QLabel):
    """Compact status badge with semantic colors."""

    _LEVEL_STYLES: dict[str, tuple[str, str]] = {
        "success": ("#9FFFD7", "rgba(25, 197, 132, 0.18)"),
        "warning": ("#FFD59A", "rgba(255, 167, 38, 0.18)"),
        "danger": ("#FF9AA2", "rgba(255, 82, 82, 0.18)"),
        "info": ("#9BD9FF", "rgba(0, 153, 255, 0.18)"),
    }

    def __init__(self, text: str, level: str = "info", parent: QWidget | None = None) -> None:
        """Initialize the badge."""

        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(28)
        self.setContentsMargins(10, 4, 10, 4)
        self.set_status(text, level)

    def set_status(self, text: str, level: str = "info") -> None:
        """Update the badge label and color palette."""

        foreground, background = self._LEVEL_STYLES.get(level, self._LEVEL_STYLES["info"])
        self.setText(text)
        self.setStyleSheet(
            f"""
            QLabel {{
                color: {foreground};
                background-color: {background};
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                padding: 4px 12px;
                font-weight: 600;
            }}
            """
        )


class MetricCard(QFrame):
    """Card used to present a key metric and supporting note."""

    def __init__(
        self,
        title: str,
        value: str,
        note: str,
        accent_color: str = "#00D9FF",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the metric card."""

        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        accent_bar = QFrame()
        accent_bar.setFixedWidth(4)
        accent_bar.setStyleSheet(
            f"background-color: {accent_color}; border-radius: 2px;"
        )
        layout.addWidget(accent_bar)

        content_layout = QVBoxLayout()
        content_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")

        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")

        note_label = QLabel(note)
        note_label.setWordWrap(True)
        note_label.setObjectName("MetricNote")

        content_layout.addWidget(title_label)
        content_layout.addWidget(value_label)
        content_layout.addWidget(note_label)
        layout.addLayout(content_layout, 1)


class SectionCard(QFrame):
    """Surface card with a title, description, and a body layout."""

    def __init__(
        self,
        title: str,
        description: str = "",
        right_widget: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the section card."""

        super().__init__(parent)
        self.setObjectName("CardPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 20)
        root_layout.setSpacing(18)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_label.setWordWrap(True)

        header_text_layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("SectionDescription")
            description_label.setWordWrap(True)
            header_text_layout.addWidget(description_label)

        header_layout.addLayout(header_text_layout, 1)
        if right_widget is not None:
            header_layout.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignTop)

        root_layout.addLayout(header_layout)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(14)
        root_layout.addLayout(self.body_layout)
