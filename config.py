"""Application configuration for the RF identification desktop UI."""

from __future__ import annotations

from pathlib import Path

APP_NAME: str = "无人机射频信号识别系统"
APP_VERSION: str = "0.1.0"
APP_SUBTITLE: str = "3943B 射频识别联调平台"

BASE_DIR: Path = Path(__file__).resolve().parent
DB_DIR: Path = BASE_DIR / "db"
DATA_DIR: Path = BASE_DIR / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw"
SAMPLES_DIR: Path = DATA_DIR / "samples"
RFUAV_SAMPLES_DIR: Path = SAMPLES_DIR / "rfuav"
FEATURES_DIR: Path = DATA_DIR / "features"
MODELS_DIR: Path = DATA_DIR / "models"
EXPORTS_DIR: Path = DATA_DIR / "exports"
RESOURCES_DIR: Path = BASE_DIR / "resources"
ICONS_DIR: Path = RESOURCES_DIR / "icons"

DEFAULT_DEVICE_IP: str = "192.168.1.100"
DEFAULT_DEVICE_PORT: int = 5025


def ensure_project_dirs() -> None:
    """Create the core directory structure used by the desktop project."""

    project_dirs: list[Path] = [
        DB_DIR,
        RAW_DATA_DIR,
        SAMPLES_DIR,
        RFUAV_SAMPLES_DIR,
        FEATURES_DIR,
        MODELS_DIR,
        EXPORTS_DIR,
        ICONS_DIR,
    ]
    for directory in project_dirs:
        directory.mkdir(parents=True, exist_ok=True)
