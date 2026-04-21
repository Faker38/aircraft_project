# aircraft_project

无人机射频信号识别联调平台界面原型。

当前版本已完成以下内容：

- 主窗口与侧边导航
- 数据采集页面
- 信号预处理页面
- 数据集管理页面
- 模型训练页面（含模型导出）
- 无人机识别页面
- 深色科技风主题与基础控件样式
- 预处理页 CAP 头预览与外部算法联调入口

## 架构文档

- [软件架构与流程说明](docs/system_architecture.md)
- [CAP 格式验证记录](docs/cap_format_analysis.md)
- [预处理算法 CAP 对接说明](docs/preprocess_cap_handoff.md)
- [预处理接入结构图](docs/preprocess_integration_flow.md)
- [仓库使用说明](docs/repository_usage.md)

## 运行环境

- Windows 10/11
- Python 3.10+

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 启动界面

```powershell
python main.py
```

程序启动后会自动创建以下目录：

- `data/`
- `db/`
- `resources/icons/`

## 当前说明

- 当前界面版本可直接启动并显示完整 Qt 主窗口
- 设备接入、采集执行、预处理、数据集管理、训练、识别流程目前为联调原型
- 当前主流程聚焦“采集 -> 预处理 -> 数据集 -> 训练 -> 识别”
- 预处理算法当前已统一要求为 `.cap` 输入，不再按 `.mat` 版本继续联调
- 当前 CAP 联调按 `0x200 / 512` 字节头长试跑，并区分 `10 MHz` 分析带宽与 `12.8 MHz` 实际采样率
- `qt-material` 未安装时，程序会自动回退到内置样式

## 目录结构

```text
.
├── docs/
├── main.py
├── config.py
├── requirements.txt
├── ui/
├── resources/
└── README.md
```
