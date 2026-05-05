"""Startup dialog for selecting and warming up three-stage model artifacts."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from services.three_stage_runtime import (
    ThreeStageRuntimeSelection,
    set_three_stage_runtime_selection,
    validate_three_stage_selection,
    warmup_three_stage_runtime,
)
from ui.recognition_run_worker import RecognitionRunWorker


class ThreeStageStartupDialog(QDialog):
    """Select three-stage weights once at startup and warm them up."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("三阶段模型启动配置")
        self.setModal(True)
        self.resize(760, 360)
        self._thread: QThread | None = None
        self._worker: RecognitionRunWorker | None = None
        self.selection: ThreeStageRuntimeSelection | None = None

        layout = QVBoxLayout(self)
        intro = QLabel("启动前选择三阶段权重和 meta 信息，确认后预热一次，后续单文件识别直接复用。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.binary_input = self._build_file_row(form, "二分类权重", r"D:\pythonProject10\success_three_stage\twin_classify_model.pth", "PTH Files (*.pth)")
        self.type_model_input = self._build_file_row(form, "类型权重", r"D:\pythonProject10\success_three_stage\type_best_model.pth", "PTH Files (*.pth)")
        self.type_meta_input = self._build_file_row(form, "类型 Meta", r"D:\pythonProject10\success_three_stage\type_best_model.meta.json", "JSON Files (*.json)")
        self.individual_model_input = self._build_file_row(form, "个体权重", r"D:\pythonProject10\success_three_stage\individual_legacy_best_model.pth", "PTH Files (*.pth)")
        self.individual_meta_input = self._build_file_row(form, "个体 Meta", "", "JSON Files (*.json)")
        self.warmup_mat_input = self._build_file_row(form, "预热 MAT", r"D:\pythonProject10\A1_IN_S0_slice_4.mat", "MAT Files (*.mat)")
        layout.addLayout(form)

        self.status_label = QLabel("等待确认。")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._start_warmup)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _build_file_row(self, form: QFormLayout, label: str, default_value: str, file_filter: str) -> QLineEdit:
        row = QHBoxLayout()
        input_widget = QLineEdit(default_value)
        row.addWidget(input_widget)
        button = QPushButton("选择")
        button.clicked.connect(lambda: self._choose_file(input_widget, file_filter))
        row.addWidget(button)
        form.addRow(label, row)
        return input_widget

    def _choose_file(self, target: QLineEdit, file_filter: str) -> None:
        current_value = target.text().strip()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            str(Path(current_value).parent if current_value else Path.cwd()),
            file_filter,
        )
        if file_path:
            target.setText(file_path)

    def _start_warmup(self) -> None:
        selection = ThreeStageRuntimeSelection(
            binary_model_path=self.binary_input.text().strip(),
            type_model_path=self.type_model_input.text().strip(),
            type_metadata_path=self.type_meta_input.text().strip(),
            individual_model_path=self.individual_model_input.text().strip(),
            individual_metadata_path=self.individual_meta_input.text().strip(),
        )
        try:
            validate_three_stage_selection(selection)
        except Exception as exc:
            QMessageBox.warning(self, "配置无效", str(exc))
            return

        warmup_mat = self.warmup_mat_input.text().strip()
        if not warmup_mat:
            QMessageBox.warning(self, "缺少预热样本", "请选择一个用于预热的 MAT 文件。")
            return

        set_three_stage_runtime_selection(selection)
        self.selection = selection
        self.status_label.setText("正在预热三阶段模型，请稍候...")
        self.buttons.setEnabled(False)

        thread = QThread(self)
        worker = RecognitionRunWorker(
            task_label="three_stage_startup_warmup",
            task_callable=lambda: warmup_three_stage_runtime(warmup_mat),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_warmup_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(self._on_warmup_failed)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_warmup_finished(self, _payload: object) -> None:
        self.status_label.setText("三阶段模型预热完成。")
        self.accept()

    def _on_warmup_failed(self, message: str) -> None:
        self.status_label.setText(f"预热失败：{message}")
        self.buttons.setEnabled(True)
