# 仓库使用说明

## 项目简介

本项目是面向 3943B 采集链路的无人机射频信号预处理、数据集构建、模型训练与识别联调平台。

## 环境配置

- Python：建议 `3.10+`
- 核心依赖：`PySide6`、`numpy`、`scipy`、`opencv-python`、`torch`、`scikit-learn`
- 完整依赖安装：

```powershell
pip install -r requirements.txt
```

如果已有 CUDA 版 `torch` 环境，建议先保留原 CUDA 环境，再按需补装其他依赖，避免覆盖已有 GPU 版本。

## 使用步骤

### 第一步：模型放置

请将训练好的 `.pth` 模型文件放入 `/models` 文件夹，并在 `config.py` 中修改对应路径。
模型文件仅用于本地运行，不建议提交到 Git 仓库。

当前对应配置项：

```python
PREPROCESS_MODEL_PATH = PREPROCESS_MODELS_DIR / "best_model_1_detect_v2.pth"
```

### 第二步：启动程序

在仓库根目录执行：

```powershell
python main.py
```

## 待实现 / 协作项

- 预处理模块需补充 `candidate_count` 计数输出（由算法侧负责）。
