"""Background worker used to import one RFUAV IQ file without blocking the UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from services import RFUAVImportCancelledError, RFUAVImportError, RFUAVImportResult, import_rfuav_dataset


class RFUAVImportWorker(QObject):
    """Run one RFUAV public-data import task inside a QThread."""

    progress_changed = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        *,
        dataset_root: Path,
        selected_iq_file: Path,
        slice_length: int,
        output_dir: Path,
    ) -> None:
        """Store the import arguments used by the worker."""

        super().__init__()
        self.dataset_root = Path(dataset_root)
        self.selected_iq_file = Path(selected_iq_file)
        self.slice_length = slice_length
        self.output_dir = Path(output_dir)
        self._cancel_requested = False

    def cancel(self) -> None:
        """Request cancellation for the running import task."""

        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        """Execute the RFUAV import task and emit one terminal signal."""

        try:
            result = import_rfuav_dataset(
                dataset_root=self.dataset_root,
                selected_iq_file=self.selected_iq_file,
                slice_length=self.slice_length,
                output_dir=self.output_dir,
                progress_callback=self._emit_progress,
                cancel_checker=self._is_cancel_requested,
            )
        except RFUAVImportCancelledError:
            self.cancelled.emit()
        except RFUAVImportError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"公开数据导入失败：{exc}")
        else:
            self.finished.emit(result)

    def _emit_progress(self, current: int, total: int, message: str) -> None:
        """Forward service-level progress into Qt signals."""

        self.progress_changed.emit(current, total, message)

    def _is_cancel_requested(self) -> bool:
        """Return whether cancellation has been requested."""

        return self._cancel_requested
