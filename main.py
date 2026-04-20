"""桌面端应用入口。"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from config import APP_NAME, APP_VERSION, ensure_project_dirs
from ui.main_window import MainWindow
from ui.styles import AppStyles


def main() -> int:
    """启动 Qt 应用。"""

    ensure_project_dirs()

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
