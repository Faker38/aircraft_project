"""Centralized theme tokens and Qt stylesheet helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


ICON_DIR = Path(__file__).resolve().parents[1] / "resources" / "icons"


@dataclass(frozen=True)
class ThemeTokens:
    """Shared color and spacing tokens for the desktop UI."""

    bg: str = "#0E151D"
    bg_alt: str = "#131C26"
    sidebar: str = "#111923"
    panel: str = "#18232F"
    panel_alt: str = "#1D2A38"
    panel_subtle: str = "#15202B"
    border: str = "rgba(255, 255, 255, 0.08)"
    border_soft: str = "rgba(255, 255, 255, 0.05)"
    text: str = "#E6EDF5"
    text_muted: str = "#94A5B5"
    accent: str = "#5EA6D3"
    accent_dark: str = "#467FAD"
    mono: str = "Consolas"


class AppStyles:
    """Theme bootstrapper for the Qt desktop application."""

    TOKENS = ThemeTokens()

    @classmethod
    def apply(cls, app: QApplication) -> None:
        """Apply palette and application stylesheet."""

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(cls.TOKENS.bg))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(cls.TOKENS.text))
        palette.setColor(QPalette.ColorRole.Base, QColor(cls.TOKENS.bg_alt))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(cls.TOKENS.panel))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(cls.TOKENS.panel_alt))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(cls.TOKENS.text))
        palette.setColor(QPalette.ColorRole.Text, QColor(cls.TOKENS.text))
        palette.setColor(QPalette.ColorRole.Button, QColor(cls.TOKENS.panel))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(cls.TOKENS.text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(cls.TOKENS.accent_dark))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(cls.TOKENS.text))
        app.setPalette(palette)
        app.setStyleSheet(cls._build_stylesheet())

    @classmethod
    def _build_stylesheet(cls) -> str:
        """Build the global stylesheet used by the application."""

        t = cls.TOKENS
        up_arrow = (ICON_DIR / "spin_up.svg").as_posix()
        down_arrow = (ICON_DIR / "spin_down.svg").as_posix()
        check_icon = (ICON_DIR / "check.svg").as_posix()
        return f"""
        * {{
            color: {t.text};
            selection-background-color: rgba(94, 166, 211, 0.22);
            selection-color: {t.text};
        }}
        QWidget {{
            background: transparent;
            font-family: "Microsoft YaHei UI";
            font-size: 10pt;
        }}
        QMainWindow, QDialog {{
            background-color: {t.bg};
        }}
        QScrollArea, QScrollArea > QWidget > QWidget {{
            border: none;
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: rgba(255, 255, 255, 0.02);
            width: 10px;
            margin: 4px 3px 4px 3px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(148, 165, 181, 0.30);
            min-height: 36px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(148, 165, 181, 0.44);
        }}
        QScrollBar::handle:vertical:pressed {{
            background: rgba(94, 166, 211, 0.56);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            background: transparent;
            border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
            border: none;
        }}
        QScrollBar:horizontal {{
            background: rgba(255, 255, 255, 0.02);
            height: 10px;
            margin: 3px 4px 3px 4px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background: rgba(148, 165, 181, 0.30);
            min-width: 36px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: rgba(148, 165, 181, 0.44);
        }}
        QScrollBar::handle:horizontal:pressed {{
            background: rgba(94, 166, 211, 0.56);
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
            background: transparent;
            border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
            border: none;
        }}
        QStatusBar {{
            background-color: {t.bg};
            color: {t.text_muted};
            border-top: 1px solid {t.border_soft};
        }}
        QStatusBar::item {{
            border: none;
        }}
        QFrame#Sidebar {{
            background-color: {t.sidebar};
            border-right: 1px solid {t.border_soft};
        }}
        QFrame#HeaderPanel {{
            background-color: {t.panel_subtle};
            border: 1px solid {t.border};
            border-radius: 12px;
        }}
        QFrame#HeaderStatusStrip {{
            background-color: rgba(255, 255, 255, 0.02);
            border: 1px solid {t.border_soft};
            border-radius: 10px;
        }}
        QFrame#CardPanel, QFrame#MetricCard, QFrame#InfoPanel, QFrame#StepCard,
        QFrame#SummaryPanel, QFrame#WorkflowEntryCard {{
            background-color: {t.panel};
            border: 1px solid {t.border};
            border-radius: 12px;
        }}
        QFrame#MetricCard {{
            min-height: 84px;
        }}
        QFrame#WorkflowEntryCard {{
            background-color: {t.panel_subtle};
        }}
        QLabel#AppTitle {{
            font-size: 16pt;
            font-weight: 700;
        }}
        QLabel#AppSubTitle {{
            color: {t.text_muted};
            font-size: 9.5pt;
        }}
        QLabel#PageTitle {{
            font-size: 17pt;
            font-weight: 700;
        }}
        QLabel#PageDescription {{
            color: {t.text_muted};
        }}
        QLabel#HeaderMetaLabel, QLabel#SidebarSection, QLabel#FieldLabel, QLabel#SummaryKey {{
            color: {t.text_muted};
            font-size: 8.5pt;
            font-weight: 600;
            letter-spacing: 0.6px;
        }}
        QLabel#HeaderMetaValue, QLabel#ValueLabel, QLabel#SummaryValue {{
            color: {t.text};
            font-size: 10pt;
            font-weight: 600;
        }}
        QLabel#HeaderMetaValue, QLabel#ValueLabel {{
            font-family: "{t.mono}";
        }}
        QLabel#SectionTitle {{
            font-size: 11.5pt;
            font-weight: 700;
        }}
        QLabel#SectionDescription, QLabel#MetricNote, QLabel#MutedText, QLabel#HintText,
        QLabel#FlowHint, QLabel#StepDescription {{
            color: {t.text_muted};
        }}
        QLabel#MetricTitle {{
            color: {t.text_muted};
            font-size: 9pt;
            font-weight: 600;
        }}
        QLabel#MetricValue {{
            font-size: 16pt;
            font-weight: 700;
        }}
        QLabel#MonoText {{
            font-family: "{t.mono}";
            color: {t.text};
            font-size: 10pt;
        }}
        QLabel#StepTitle, QLabel#FlowTitle {{
            font-size: 10.8pt;
            font-weight: 700;
        }}
        QLabel#StepIndex, QLabel#FlowIndex {{
            color: {t.accent};
            font-family: "{t.mono}";
            font-size: 11pt;
            font-weight: 700;
        }}
        QPushButton {{
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 9px 14px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: rgba(94, 166, 211, 0.10);
            border: 1px solid rgba(94, 166, 211, 0.22);
        }}
        QPushButton#PrimaryButton {{
            background-color: rgba(94, 166, 211, 0.18);
            border: 1px solid rgba(94, 166, 211, 0.32);
        }}
        QPushButton#DangerButton {{
            background-color: rgba(160, 74, 74, 0.18);
            border: 1px solid rgba(184, 88, 88, 0.28);
        }}
        QPushButton#NavButton {{
            text-align: left;
            padding: 10px 12px;
            border-radius: 10px;
            background-color: transparent;
            border: 1px solid transparent;
            font-size: 10.5pt;
        }}
        QPushButton#NavButton:hover {{
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.06);
        }}
        QPushButton#NavButton:checked {{
            background-color: rgba(94, 166, 211, 0.14);
            border: 1px solid rgba(94, 166, 211, 0.22);
        }}
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: rgba(255, 255, 255, 0.025);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            padding: 8px 10px;
            min-height: 18px;
        }}
        QSpinBox, QDoubleSpinBox {{
            padding-right: 30px;
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid rgba(94, 166, 211, 0.30);
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 22px;
            border-left: 1px solid rgba(255, 255, 255, 0.08);
            border-top-right-radius: 10px;
            background-color: rgba(255, 255, 255, 0.02);
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 22px;
            border-left: 1px solid rgba(255, 255, 255, 0.08);
            border-top: 1px solid rgba(255, 255, 255, 0.06);
            border-bottom-right-radius: 10px;
            background-color: rgba(255, 255, 255, 0.02);
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
            background-color: rgba(94, 166, 211, 0.12);
        }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{up_arrow}");
            width: 10px;
            height: 10px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{down_arrow}");
            width: 10px;
            height: 10px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox::down-arrow {{
            image: url("{down_arrow}");
            width: 10px;
            height: 10px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {t.panel_alt};
            selection-background-color: rgba(94, 166, 211, 0.18);
            border: 1px solid {t.border};
            outline: none;
        }}
        QTabWidget::pane {{
            border: 1px solid {t.border};
            border-radius: 12px;
            top: -1px;
            background: {t.panel};
        }}
        QTabBar::tab {{
            background: transparent;
            color: {t.text_muted};
            padding: 10px 14px;
            margin-right: 6px;
            border-bottom: 2px solid transparent;
        }}
        QTabBar::tab:selected {{
            color: {t.text};
            border-bottom: 2px solid {t.accent};
        }}
        QProgressBar {{
            border-radius: 8px;
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.06);
            text-align: center;
            min-height: 16px;
        }}
        QProgressBar::chunk {{
            border-radius: 7px;
            background-color: {t.accent_dark};
        }}
        QHeaderView::section {{
            background-color: rgba(255, 255, 255, 0.025);
            color: {t.text_muted};
            padding: 10px 8px;
            border: none;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-weight: 600;
        }}
        QTableWidget, QTreeWidget, QListWidget {{
            background-color: rgba(255, 255, 255, 0.018);
            alternate-background-color: rgba(255, 255, 255, 0.032);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 10px;
            gridline-color: rgba(255, 255, 255, 0.04);
        }}
        QTableWidget::item, QTreeWidget::item, QListWidget::item {{
            padding: 8px;
        }}
        QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
            background-color: rgba(94, 166, 211, 0.14);
        }}
        QGroupBox {{
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 10px;
            margin-top: 12px;
            padding: 12px 12px 10px 12px;
            font-weight: 700;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: {t.text};
        }}
        QCheckBox, QRadioButton {{
            spacing: 8px;
            color: {t.text};
        }}
        QCheckBox::indicator {{
            width: 17px;
            height: 17px;
            border-radius: 4px;
            border: 1px solid rgba(148, 165, 181, 0.62);
            background: rgba(255, 255, 255, 0.02);
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid rgba(94, 166, 211, 0.50);
            background: rgba(94, 166, 211, 0.06);
        }}
        QCheckBox::indicator:checked {{
            image: url("{check_icon}");
            border: 1px solid rgba(94, 166, 211, 0.82);
            background: rgba(94, 166, 211, 0.38);
        }}
        QCheckBox::indicator:unchecked {{
            image: none;
        }}
        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 1px solid rgba(148, 165, 181, 0.42);
            background: rgba(255, 255, 255, 0.04);
        }}
        QRadioButton::indicator:hover {{
            border: 1px solid rgba(94, 166, 211, 0.50);
            background: rgba(94, 166, 211, 0.08);
        }}
        QRadioButton::indicator:checked {{
            border: 1px solid rgba(94, 166, 211, 0.78);
            background: qradialgradient(
                cx: 0.5, cy: 0.5, radius: 0.56, fx: 0.5, fy: 0.5,
                stop: 0 rgba(94, 166, 211, 0.96),
                stop: 0.32 rgba(94, 166, 211, 0.96),
                stop: 0.34 rgba(94, 166, 211, 0.18),
                stop: 1 rgba(94, 166, 211, 0.18)
            );
        }}
        QRadioButton::indicator:unchecked {{
            margin-top: 1px;
        }}
        QRadioButton::indicator:checked {{
            margin-top: 1px;
        }}
        QRadioButton::indicator:checked:disabled, QCheckBox::indicator:checked:disabled {{
            border: 1px solid rgba(148, 165, 181, 0.28);
            background: rgba(148, 165, 181, 0.14);
        }}
        QCheckBox::indicator:unchecked:disabled {{
            border: 1px solid rgba(148, 165, 181, 0.22);
            background: rgba(148, 165, 181, 0.06);
        }}
        """
