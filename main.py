"""桌面端应用入口。"""

from __future__ import annotations

import os
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from config import APP_NAME, APP_VERSION, ensure_project_dirs
from services import init_database
from ui.main_window import MainWindow
from ui.styles import AppStyles


def configure_console_encoding() -> None:
    """在 Windows 控制台支持时强制使用 UTF-8 输出。"""

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def print_runtime_diagnostics() -> None:
    """打印关键运行环境信息，便于排查依赖和解释器问题。"""

    print(f"[环境] python: {sys.executable}")

    try:
        import numpy

        print(f"[环境] numpy: {numpy.__version__}")
    except Exception as exc:
        print(f"[环境] numpy: 导入失败: {exc}")

    try:
        import cv2

        print(f"[环境] cv2: {cv2.__version__}")
    except Exception as exc:
        print(f"[环境] cv2: 导入失败: {exc}")


def _configure_qt_logging() -> None:
    """Reduce noisy Windows monitor-interface logs without hiding app errors."""

    existing_rules = os.environ.get("QT_LOGGING_RULES", "").strip()
    screen_rule = "qt.qpa.screen=false"
    if screen_rule in existing_rules:
        return
    os.environ["QT_LOGGING_RULES"] = f"{existing_rules};{screen_rule}" if existing_rules else screen_rule


def main() -> int:
    """启动 Qt 应用。"""

    configure_console_encoding()
    _configure_qt_logging()
    ensure_project_dirs()
    init_database()
    print_runtime_diagnostics()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 10))

    AppStyles.apply(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
