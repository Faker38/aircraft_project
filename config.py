"""桌面端应用配置。"""

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
FEATURES_DIR: Path = DATA_DIR / "features"
MODELS_DIR: Path = DATA_DIR / "models"
EXPORTS_DIR: Path = DATA_DIR / "exports"
RESOURCES_DIR: Path = BASE_DIR / "resources"
ICONS_DIR: Path = RESOURCES_DIR / "icons"
PREPROCESS_MODELS_DIR: Path = BASE_DIR / "models"

# 预处理算法默认模型路径。更换模型时，将 .pth 放入 /models 后修改这里即可。
PREPROCESS_MODEL_PATH: Path = PREPROCESS_MODELS_DIR / "best_model_1_detect_v2.pth"

DEFAULT_DEVICE_IP: str = "192.168.1.100"
DEFAULT_DEVICE_PORT: int = 5025


def ensure_project_dirs() -> None:
    """创建项目运行时需要的核心目录结构。"""

    project_dirs: list[Path] = [
        DB_DIR,
        RAW_DATA_DIR,
        SAMPLES_DIR,
        FEATURES_DIR,
        MODELS_DIR,
        EXPORTS_DIR,
        ICONS_DIR,
        PREPROCESS_MODELS_DIR,
    ]
    for directory in project_dirs:
        directory.mkdir(parents=True, exist_ok=True)
