"""桌面端应用入口。"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from config import APP_NAME, APP_VERSION, ensure_project_dirs
from ui.main_window import MainWindow
from ui.styles import AppStyles


def configure_console_encoding() -> None:
    """Force UTF-8 console output on Windows when supported."""

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def print_runtime_diagnostics() -> None:
    """Print interpreter and key binary-package versions for quick troubleshooting."""

    print(f"[ENV] python: {sys.executable}")

    try:
        import numpy

        print(f"[ENV] numpy: {numpy.__version__}")
    except Exception as exc:
        print(f"[ENV] numpy: import failed: {exc}")

    try:
        import cv2

        print(f"[ENV] cv2: {cv2.__version__}")
    except Exception as exc:
        print(f"[ENV] cv2: import failed: {exc}")


def main() -> int:
    """启动 Qt 应用。"""

    configure_console_encoding()
    ensure_project_dirs()
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
