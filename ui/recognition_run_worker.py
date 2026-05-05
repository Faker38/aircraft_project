"""Background worker for recognition-page inference tasks."""

from __future__ import annotations

import inspect

from PySide6.QtCore import QObject, Signal, Slot


class RecognitionRunWorker(QObject):
    """Run one recognition task off the UI thread."""

    started = Signal(str)
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, *, task_label: str, task_callable) -> None:
        super().__init__()
        self.task_label = task_label
        self.task_callable = task_callable

    @Slot()
    def run(self) -> None:
        try:
            self.started.emit(self.task_label)
            call_kwargs = {}
            signature = inspect.signature(self.task_callable)
            if "progress_callback" in signature.parameters:
                call_kwargs["progress_callback"] = self.progress.emit
            result = self.task_callable(**call_kwargs)
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)
