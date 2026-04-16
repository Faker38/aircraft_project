# aircraft_project

无人机射频信号识别联调平台界面原型。

当前版本已完成以下内容：

- 主窗口与侧边导航
- 数据采集页面
- 信号处理与标注页面
- 模型训练页面
- 模型导出页面
- 深色科技风主题与基础控件样式

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
- 设备接入、采集执行、信号处理、训练和导出流程目前为联调原型
- `qt-material` 未安装时，程序会自动回退到内置样式

## 目录结构

```text
.
├── main.py
├── config.py
├── requirements.txt
├── ui/
├── resources/
└── README.md
```
