"""后台工作线程：用于执行类型识别模型测试。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services import ModelEvaluationResult, ModelServiceError, evaluate_type_model


class ModelEvalWorker(QObject):
    """把一次模型测试放到 UI 线程之外执行。"""

    started = Signal(str)
    progress_changed = Signal(int, str, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, *, model_id: str, manifest_csv_path: str) -> None:
        """保存本次测试任务所需参数。"""

        super().__init__()
        self.model_id = model_id
        self.manifest_csv_path = manifest_csv_path

    @Slot()
    def run(self) -> None:
        """在线程中执行批量模型测试并返回统一结果。"""

        try:
            self.started.emit(self.model_id)
            result = evaluate_type_model(
                self.model_id,
                self.manifest_csv_path,
                progress_callback=self.progress_changed.emit,
            )
        except ModelServiceError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"模型测试执行失败：{exc}")
            return

        if not isinstance(result, ModelEvaluationResult):
            self.failed.emit("模型测试执行失败：服务层未返回有效测试结果。")
            return
        self.finished.emit(result)
