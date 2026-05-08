"""Lightweight pre-commit smoke checks for the desktop workflow.

This script intentionally avoids pytest so it can run on a fresh Windows
machine with the project dependencies installed:

    python -B tools/smoke_checks.py
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    """Run all smoke checks and return a process exit code."""

    os.environ.setdefault("QT_QPA_PLATFORM", "minimal")
    check_python_ast()
    check_dataset_split_semantics()
    check_dataset_ratio_controls()
    check_recognition_domain_warning()
    check_qt_minimal_instantiation()
    print("[OK] smoke checks completed")
    return 0


def check_python_ast() -> None:
    """Parse every Python source file in the repository."""

    parsed_count = 0
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in {".git", "__pycache__"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        parsed_count += 1
    print(f"[OK] AST parsed {parsed_count} Python files")


def check_dataset_split_semantics() -> None:
    """Verify dataset split behavior is real and reproducible."""

    from services import SampleRecord
    from ui.dataset_build_worker import build_split_values

    records = []
    for label in ("频点A", "频点B"):
        for index in range(6):
            records.append(
                _sample_record(
                    sample_id=f"{label}_{index:02d}",
                    label_type=label,
                    device_id=f"{label}_dev_{index % 3}",
                )
            )

    first = build_split_values(
        records,
        task_type="类型识别",
        strategy="按标签随机划分",
        train_ratio=50,
        val_ratio=25,
        test_ratio=25,
    )
    second = build_split_values(
        records,
        task_type="类型识别",
        strategy="按标签随机划分",
        train_ratio=50,
        val_ratio=25,
        test_ratio=25,
    )
    assert first == second, "random stratified split must be reproducible"
    assert set(first.values()) == {"train", "val", "test"}, "all split buckets should be used"

    insufficient_records = [_sample_record(sample_id="single_label_sample", label_type="频点A", device_id="dev_001")]
    try:
        build_split_values(
            insufficient_records,
            task_type="类型识别",
            strategy="按标签随机划分",
            train_ratio=50,
            val_ratio=0,
            test_ratio=50,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("label split should reject labels that cannot enter both train and test")
    print("[OK] dataset split semantics")


def check_dataset_ratio_controls() -> None:
    """Verify test-only generation visibly changes ratios and normal generation restores them."""

    from PySide6.QtWidgets import QApplication

    from ui.page_dataset import DatasetPage

    app = QApplication.instance() or QApplication([])
    page = DatasetPage()
    page.sample_records = []
    page.train_ratio.setValue(60)
    page.val_ratio.setValue(20)
    page.test_ratio.setValue(20)
    page._generate_test_dataset_version()
    assert (
        page.train_ratio.value(),
        page.val_ratio.value(),
        page.test_ratio.value(),
    ) == (0, 0, 100), "test dataset generation should show 0/0/100 ratios"
    page._generate_dataset_version()
    assert (
        page.train_ratio.value(),
        page.val_ratio.value(),
        page.test_ratio.value(),
    ) == (60, 20, 20), "normal dataset generation should restore the remembered training ratios"
    page.close()
    app.processEvents()
    print("[OK] dataset ratio controls")


def check_recognition_domain_warning() -> None:
    """Verify out-of-domain samples produce an explicit warning."""

    from PySide6.QtWidgets import QApplication

    from services import SampleRecord, TrainedModelRecord
    from ui.page_recognition import RecognitionPage

    app = QApplication.instance() or QApplication([])
    page = RecognitionPage()
    sample = SampleRecord(
        sample_id="cap_1090_demo",
        source_type="local_preprocess",
        raw_file_path=str(REPO_ROOT / "data" / "raw" / "civil_1090.cap"),
        sample_file_path=str(REPO_ROOT / "data" / "samples" / "civil_1090.npy"),
        label_type="",
        label_individual="",
        sample_rate_hz=12_800_000.0,
        center_frequency_hz=1_090_000_000.0,
        data_format="complex64_npy",
        sample_count=4096,
        device_id="civil_1090",
        start_sample=0,
        end_sample=4095,
        source_name="CAP 预处理输出",
    )
    model = TrainedModelRecord(
        model_id="usrp_domain_smoke",
        dataset_version_id="v_smoke",
        task_type="类型识别",
        model_kind="RandomForest",
        label_space=["频点2400M"],
        artifact_path=str(REPO_ROOT / "data" / "models" / "usrp_domain_smoke" / "model.joblib"),
        metrics={
            "training_domain": {
                "source_types": ["usrp_preprocess"],
                "center_frequency_hz_range": {"min": 2_400_000_000.0, "max": 2_400_000_000.0},
                "sample_rate_hz_range": {"min": 1_000_000.0, "max": 5_000_000.0},
            }
        },
    )
    warnings = page._domain_warning_messages(sample, model)
    page.close()
    assert warnings, "1090 MHz CAP sample should be marked out-of-domain for a USRP 2.4 GHz model"
    print("[OK] recognition domain warning")


def check_qt_minimal_instantiation() -> None:
    """Instantiate the main window under the Qt minimal platform."""

    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.pages["capture"].files_table.rowCount() == 0, "capture table should start empty"
    window.close()
    app.processEvents()
    print("[OK] Qt minimal main window instantiation")


def _sample_record(*, sample_id: str, label_type: str, device_id: str):
    """Create one compact sample record for split tests."""

    from services import SampleRecord

    return SampleRecord(
        sample_id=sample_id,
        source_type="usrp_preprocess",
        raw_file_path=str(REPO_ROOT / "data" / "raw" / f"{device_id}.iq"),
        sample_file_path=str(REPO_ROOT / "data" / "samples" / f"{sample_id}.npy"),
        label_type=label_type,
        label_individual=f"{label_type}_001",
        sample_rate_hz=1_000_000.0,
        center_frequency_hz=2_400_000_000.0,
        data_format="complex64_npy",
        sample_count=4096,
        device_id=device_id,
        start_sample=0,
        end_sample=4095,
        status="已标注",
    )


if __name__ == "__main__":
    raise SystemExit(main())
