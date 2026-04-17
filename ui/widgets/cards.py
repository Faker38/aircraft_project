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
        "success": ("#9EE3C3", "rgba(46, 125, 91, 0.22)"),
        "warning": ("#E7C993", "rgba(144, 103, 34, 0.24)"),
        "danger": ("#E3A6A6", "rgba(124, 52, 52, 0.24)"),
        "info": ("#A8CDE6", "rgba(46, 94, 132, 0.24)"),
    }
    _SIZE_STYLES: dict[str, tuple[int, int, int, int, str]] = {
        "sm": (24, 10, 10, 11, "600"),
        "md": (28, 12, 12, 12, "600"),
    }

    def __init__(
        self,
        text: str,
        level: str = "info",
        parent: QWidget | None = None,
        size: str = "md",
    ) -> None:
        """Initialize the badge."""

        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._size = size
        self.set_status(text, level)

    def set_status(self, text: str, level: str = "info", size: str | None = None) -> None:
        """Update the badge label and color palette."""

        if size is not None:
            self._size = size

        foreground, background = self._LEVEL_STYLES.get(level, self._LEVEL_STYLES["info"])
        minimum_height, padding_x, radius, font_size, font_weight = self._SIZE_STYLES.get(
            self._size,
            self._SIZE_STYLES["md"],
        )
        self.setText(text)
        self.setMinimumHeight(minimum_height)
        self.setStyleSheet(
            f"""
            QLabel {{
                color: {foreground};
                background-color: {background};
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: {radius}px;
                padding: 3px {padding_x}px;
                font-size: {font_size}px;
                font-weight: {font_weight};
            }}
            """
        )


class MetricCard(QFrame):
    """Card used to present a key metric and supporting note."""

    def __init__(
        self,
        title: str,
        value: str,
        note: str = "",
        accent_color: str = "#00D9FF",
        compact: bool = False,
        show_note: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the metric card."""

        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setProperty("compact", compact)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16 if compact else 18, 14 if compact else 18, 16 if compact else 18, 14 if compact else 18)
        layout.setSpacing(6 if compact else 8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        accent_marker = QFrame()
        accent_marker.setObjectName("MetricAccent")
        accent_marker.setFixedSize(10, 10)
        accent_marker.setStyleSheet(
            f"background-color: {accent_color}; border-radius: 5px;"
        )

        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")

        title_row.addWidget(accent_marker, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.title_label, 1)

        layout.addLayout(title_row)
        layout.addWidget(self.value_label)

        if show_note and note:
            self.note_label = QLabel(note)
            self.note_label.setWordWrap(True)
            self.note_label.setObjectName("MetricNote")
            layout.addWidget(self.note_label)
        else:
            self.note_label = None

    def set_value(self, value: str) -> None:
        """Update the metric value."""

        self.value_label.setText(value)


class SectionCard(QFrame):
    """Surface card with a title, description, and a body layout."""

    def __init__(
        self,
        title: str,
        description: str = "",
        right_widget: QWidget | None = None,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the section card."""

        super().__init__(parent)
        self.setObjectName("CardPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setProperty("compact", compact)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16 if compact else 18, 14 if compact else 16, 16 if compact else 18, 16 if compact else 18)
        root_layout.setSpacing(14 if compact else 16)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(2)

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
        self.body_layout.setSpacing(12 if compact else 14)
        root_layout.addLayout(self.body_layout)
