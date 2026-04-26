"""后台工作线程：用于执行 USRP 真实采集。"""

from __future__ import annotations

from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from services.usrp_capture_service import (
    USRPCaptureCancelled,
    USRPCaptureConfig,
    USRPCaptureError,
    USRPCaptureResult,
    run_usrp_capture,
)


class USRPCaptureWorker(QObject):
    """把一次 USRP 真实采集放到 UI 线程之外执行。"""

    started = Signal(str)
    progress_changed = Signal(int, str)
    log_changed = Signal(str)
    cancelled = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: USRPCaptureConfig) -> None:
        """保存本次采集所需配置。"""

        super().__init__()
        self.config = config
        self._cancel_event = Event()

    def request_cancel(self) -> None:
        """请求当前采集任务在安全检查点停止。"""

        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        """在线程中执行真实采集并返回统一结果。"""

        try:
            self.started.emit(self.config.output_dir)
            result = run_usrp_capture(
                self.config,
                progress_callback=self.progress_changed.emit,
                log_callback=self.log_changed.emit,
                cancel_check=self._cancel_event.is_set,
            )
        except USRPCaptureCancelled as exc:
            self.cancelled.emit(str(exc))
            return
        except USRPCaptureError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"USRP 采集执行失败：{exc}")
            return

        if not isinstance(result, USRPCaptureResult):
            self.failed.emit("USRP 采集执行失败：服务层未返回有效结果。")
            return
        self.finished.emit(result)
