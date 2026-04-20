"""Background worker used to execute the external preprocess adapter."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services import PreprocessAdapterError, PreprocessRunConfig, PreprocessRunResult, run_preprocess


class PreprocessRunWorker(QObject):
    """Execute one preprocess task off the UI thread."""

    started = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: PreprocessRunConfig) -> None:
        """Store the preprocess config for execution."""

        super().__init__()
        self.config = config

    @Slot()
    def run(self) -> None:
        """Run the preprocess adapter and emit a normalized result."""

        try:
            self.started.emit(self.config.input_file_path)
            result = run_preprocess(self.config)
        except PreprocessAdapterError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            self.failed.emit(f"预处理执行失败：{exc}")
            return

        if not isinstance(result, PreprocessRunResult):
            self.failed.emit("预处理执行失败：适配层未返回有效结果。")
            return
        self.finished.emit(result)
