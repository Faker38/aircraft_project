"""Centralized theme tokens and Qt stylesheet helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

try:
    from qt_material import apply_stylesheet as apply_material_stylesheet
except ImportError:
    apply_material_stylesheet = None


ICON_DIR = Path(__file__).resolve().parents[1] / "resources" / "icons"


@dataclass(frozen=True)
class ThemeTokens:
    """Shared color and spacing tokens for the desktop UI."""

    bg: str = "#08111B"
    bg_alt: str = "#0D1826"
    panel: str = "#111F30"
    panel_alt: str = "#17283C"
    border: str = "rgba(125, 213, 252, 0.12)"
    border_strong: str = "rgba(0, 217, 255, 0.24)"
    text: str = "#E9F4FF"
    text_muted: str = "#97AFC2"
    accent: str = "#00D9FF"
    accent_dark: str = "#0097E6"
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

        if apply_material_stylesheet is not None:
            apply_material_stylesheet(app, theme="dark_cyan.xml")

        app.setStyleSheet(cls._build_stylesheet())

    @classmethod
    def _build_stylesheet(cls) -> str:
        """Build the global stylesheet used by the application."""

        t = cls.TOKENS
        up_arrow = (ICON_DIR / "spin_up.svg").as_posix()
        down_arrow = (ICON_DIR / "spin_down.svg").as_posix()
        return f"""
        * {{
            color: {t.text};
            selection-background-color: rgba(0, 217, 255, 0.22);
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
        QStatusBar {{
            background-color: rgba(8, 17, 27, 0.92);
            color: {t.text_muted};
            border-top: 1px solid {t.border};
        }}
        QStatusBar::item {{
            border: none;
        }}
        QFrame#Sidebar {{
            background-color: rgba(7, 15, 23, 0.92);
            border-right: 1px solid {t.border};
        }}
        QFrame#HeaderPanel {{
            background-color: rgba(10, 20, 31, 0.90);
            border: 1px solid {t.border};
            border-radius: 18px;
        }}
        QFrame#HeaderInfoPanel {{
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 14px;
        }}
        QFrame#HeroPanel {{
            background-color: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 1,
                stop: 0 rgba(0, 217, 255, 0.16),
                stop: 0.48 rgba(9, 26, 42, 0.94),
                stop: 1 rgba(0, 151, 230, 0.14)
            );
            border: 1px solid {t.border_strong};
            border-radius: 24px;
        }}
        QFrame#CardPanel, QFrame#MetricCard, QFrame#StepCard, QFrame#InfoPanel {{
            background-color: rgba(17, 31, 48, 0.96);
            border: 1px solid {t.border};
            border-radius: 18px;
        }}
        QLabel#AppTitle {{
            font-size: 18pt;
            font-weight: 700;
        }}
        QLabel#AppSubTitle {{
            color: {t.text_muted};
            font-size: 10pt;
        }}
        QLabel#PageTitle {{
            font-size: 18pt;
            font-weight: 700;
        }}
        QLabel#PageDescription {{
            color: {t.text_muted};
        }}
        QLabel#HeaderMetaLabel {{
            color: {t.text_muted};
            font-size: 8.5pt;
            font-weight: 600;
        }}
        QLabel#HeaderMetaValue {{
            font-family: "{t.mono}";
            color: {t.text};
            font-size: 10.5pt;
            font-weight: 600;
        }}
        QLabel#HeroEyebrow {{
            color: {t.accent};
            font-weight: 700;
            letter-spacing: 1px;
        }}
        QLabel#HeroTitle {{
            font-size: 22pt;
            font-weight: 700;
        }}
        QLabel#HeroDescription {{
            color: {t.text_muted};
            font-size: 10.5pt;
        }}
        QLabel#SectionTitle {{
            font-size: 12.5pt;
            font-weight: 700;
        }}
        QLabel#SectionDescription {{
            color: {t.text_muted};
        }}
        QLabel#MetricTitle {{
            color: {t.text_muted};
            font-size: 9.5pt;
            font-weight: 600;
        }}
        QLabel#MetricValue {{
            font-size: 18pt;
            font-weight: 700;
        }}
        QLabel#MetricNote {{
            color: {t.text_muted};
            font-size: 9pt;
        }}
        QLabel#MonoText {{
            font-family: "{t.mono}";
            color: {t.accent};
            font-size: 10pt;
        }}
        QLabel#StepIndex {{
            color: {t.accent};
            font-family: "{t.mono}";
            font-size: 13pt;
            font-weight: 700;
        }}
        QLabel#StepTitle {{
            font-size: 12pt;
            font-weight: 700;
        }}
        QLabel#StepDescription, QLabel#HintText, QLabel#MutedText {{
            color: {t.text_muted};
        }}
        QLabel#FieldLabel {{
            color: {t.text_muted};
            font-size: 9pt;
            font-weight: 600;
        }}
        QLabel#ValueLabel {{
            font-family: "{t.mono}";
            color: {t.text};
        }}
        QLabel#SidebarSection {{
            color: {t.text_muted};
            font-size: 8.5pt;
            font-weight: 700;
            letter-spacing: 1px;
        }}
        QPushButton {{
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 10px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: rgba(0, 217, 255, 0.10);
            border: 1px solid rgba(0, 217, 255, 0.28);
        }}
        QPushButton#PrimaryButton {{
            background-color: rgba(0, 217, 255, 0.16);
            border: 1px solid rgba(0, 217, 255, 0.42);
        }}
        QPushButton#DangerButton {{
            background-color: rgba(255, 82, 82, 0.14);
            border: 1px solid rgba(255, 82, 82, 0.28);
        }}
        QPushButton#NavButton {{
            text-align: left;
            padding: 12px 14px;
            border-radius: 14px;
            background-color: transparent;
            border: 1px solid transparent;
            font-size: 10.5pt;
        }}
        QPushButton#NavButton:hover {{
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }}
        QPushButton#NavButton:checked {{
            background-color: rgba(0, 217, 255, 0.16);
            border: 1px solid rgba(0, 217, 255, 0.34);
        }}
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background-color: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 8px 10px;
            min-height: 20px;
        }}
        QSpinBox, QDoubleSpinBox {{
            padding-right: 30px;
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid rgba(0, 217, 255, 0.38);
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 22px;
            border-left: 1px solid rgba(255, 255, 255, 0.08);
            border-top-right-radius: 12px;
            background-color: rgba(255, 255, 255, 0.02);
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 22px;
            border-left: 1px solid rgba(255, 255, 255, 0.08);
            border-top: 1px solid rgba(255, 255, 255, 0.06);
            border-bottom-right-radius: 12px;
            background-color: rgba(255, 255, 255, 0.02);
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
            background-color: rgba(0, 217, 255, 0.10);
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
            selection-background-color: rgba(0, 217, 255, 0.18);
            border: 1px solid {t.border};
            outline: none;
        }}
        QTabWidget::pane {{
            border: 1px solid {t.border};
            border-radius: 18px;
            top: -1px;
            background: rgba(17, 31, 48, 0.95);
        }}
        QTabBar::tab {{
            background: transparent;
            color: {t.text_muted};
            padding: 10px 16px;
            margin-right: 6px;
            border-bottom: 2px solid transparent;
        }}
        QTabBar::tab:selected {{
            color: {t.text};
            border-bottom: 2px solid {t.accent};
        }}
        QProgressBar {{
            border-radius: 10px;
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.06);
            text-align: center;
            min-height: 18px;
        }}
        QProgressBar::chunk {{
            border-radius: 9px;
            background-color: {t.accent_dark};
        }}
        QHeaderView::section {{
            background-color: rgba(255, 255, 255, 0.03);
            color: {t.text_muted};
            padding: 10px 8px;
            border: none;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-weight: 600;
        }}
        QTableWidget, QTreeWidget, QListWidget {{
            background-color: rgba(255, 255, 255, 0.025);
            alternate-background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 14px;
            gridline-color: rgba(255, 255, 255, 0.05);
        }}
        QTableWidget::item, QTreeWidget::item, QListWidget::item {{
            padding: 8px;
        }}
        QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
            background-color: rgba(0, 217, 255, 0.14);
        }}
        QGroupBox {{
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 16px;
            margin-top: 12px;
            padding: 14px 14px 10px 14px;
            font-weight: 700;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            padding: 0 6px;
            color: {t.text};
        }}
        """
