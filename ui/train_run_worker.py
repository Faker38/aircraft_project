"""后台工作线程：用于执行类型识别真实训练。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from services import ModelServiceError, TrainingRunResult, train_type_model


class TrainRunWorker(QObject):
    """把一次训练任务放到 UI 线程之外执行。"""

    started = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        *,
        version_id: str,
        model_name: str,
        n_estimators: int,
        max_depth: int,
    ) -> None:
        """保存本次训练任务所需参数。"""

        super().__init__()
        self.version_id = version_id
        self.model_name = model_name
        self.n_estimators = n_estimators
        self.max_depth = max_depth

    @Slot()
    def run(self) -> None:
        """在线程中执行真实训练并返回统一结果。"""

        try:
            self.started.emit(self.version_id)
            result = train_type_model(
                self.version_id,
                model_name=self.model_name,
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
            )
        except ModelServiceError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # pragma: no cover - 线程边界上的保护性兜底
            self.failed.emit(f"训练执行失败：{exc}")
            return

        if not isinstance(result, TrainingRunResult):
            self.failed.emit("训练执行失败：服务层未返回有效训练结果。")
            return
        self.finished.emit(result)
