"""后台工作线程：用于执行外部预处理适配层。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services import PreprocessAdapterError, PreprocessRunConfig, PreprocessRunResult, run_preprocess


class PreprocessRunWorker(QObject):
    """把一次预处理任务放到 UI 线程之外执行。"""

    started = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: PreprocessRunConfig) -> None:
        """保存本次执行需要的预处理参数。"""

        super().__init__()
        self.config = config

    @Slot()
    def run(self) -> None:
        """执行预处理适配层，并向页面发回统一结果。"""

        try:
            self.started.emit(self.config.input_file_path)
            result = run_preprocess(self.config)
        except PreprocessAdapterError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"预处理执行失败：{exc}")
            return

        if not isinstance(result, PreprocessRunResult):
            self.failed.emit("预处理执行失败：适配层未返回有效结果。")
            return
        self.finished.emit(result)
