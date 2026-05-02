"""后台工作线程：用于执行 USRP IQ 演示预处理。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services import (
    USRPDemoPreprocessConfig,
    USRPDemoPreprocessError,
    USRPDemoPreprocessResult,
    run_usrp_demo_preprocess,
)


class USRPDemoPreprocessWorker(QObject):
    """把一次 USRP IQ 演示预处理放到 UI 线程之外执行。"""

    started = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: USRPDemoPreprocessConfig) -> None:
        """保存本次执行需要的 USRP 演示预处理参数。"""

        super().__init__()
        self.config = config

    @Slot()
    def run(self) -> None:
        """执行 USRP 演示预处理，并向页面发回统一结果。"""

        try:
            self.started.emit(self.config.input_file_path)
            result = run_usrp_demo_preprocess(self.config)
        except USRPDemoPreprocessError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"USRP IQ 演示预处理执行失败：{exc}")
            return

        if not isinstance(result, USRPDemoPreprocessResult):
            self.failed.emit("USRP IQ 演示预处理失败：服务层未返回有效结果。")
            return
        self.finished.emit(result)
