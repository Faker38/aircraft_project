"""后台工作线程：用于执行 USRP B210 预检。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services import USRPDiagnosticsResult, run_b210_preflight


class USRPDiagnosticsWorker(QObject):
    """把 UHD/B210 预检放到 UI 线程之外执行。"""

    started = Signal()
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, device_args: str, timeout_s: float = 100.0) -> None:
        """保存本次预检配置。"""

        super().__init__()
        self.device_args = device_args
        self.timeout_s = timeout_s

    @Slot()
    def run(self) -> None:
        """在线程中执行 USRP B210 预检。"""

        try:
            self.started.emit()
            result = run_b210_preflight(self.device_args, timeout_s=self.timeout_s)
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"B210 预检执行失败：{exc}")
            return

        if not isinstance(result, USRPDiagnosticsResult):
            self.failed.emit("B210 预检执行失败：服务层未返回有效结果。")
            return
        self.finished.emit(result)
