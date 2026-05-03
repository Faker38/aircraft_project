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
- 数据集管理页 SQLite 标注、删除/清空和版本生成
- 数据集版本 `manifest.json` 生成与训练页数据检查
- 类型识别真实训练、模型落盘与识别页真实推理

## 架构文档

- [软件架构与流程说明](docs/system_architecture.md)
- [CAP 格式验证记录](docs/cap_format_analysis.md)
- [预处理算法 CAP 对接说明](docs/preprocess_cap_handoff.md)
- [预处理接入结构图](docs/preprocess_integration_flow.md)
- [仓库使用说明](docs/repository_usage.md)
- [USRP B210 Windows 连接与烟测说明](docs/usrp_b210_setup.md)

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

其中 `data/` 和 `db/` 是本地运行数据目录，已被 Git 忽略，不会提交到仓库。

## 当前主流程

当前联调主流程为：

```text
CAP 预处理输出样本 -> SQLite 标注管理 -> 生成数据集版本 -> manifest.json -> 本地真实训练 -> 本地真实识别
```

数据集管理页已支持：

- 手动标注类型标签和个体标签
- 维护“设备编号-类型标签-个体标签”映射表并自动标注
- 控制样本是否纳入数据集
- 删除样本、删除版本和清空样本数据库
- 生成 `data/datasets/{version_id}/manifest.json`
- 训练 `data/models/{model_id}/model.joblib` 与 `metadata.json`

## 当前说明

- 当前界面版本可直接启动并显示完整 Qt 主窗口
- 设备接入、采集执行、预处理、数据集管理、训练、识别流程目前为联调原型
- 当前主流程聚焦“采集 -> 预处理 -> 数据集 -> 训练 -> 识别”
- 预处理算法当前已统一要求为 `.cap` 输入，不再按 `.mat` 版本继续联调
- 当前 CAP 联调按 `0x200 / 512` 字节头长试跑，并区分 `10 MHz` 分析带宽与 `12.8 MHz` 实际采样率
- 预处理页会自动扫描工作区根目录下全部 `.cap` 文件
- 当前 demo 建议使用中性标签口径，例如 `类别A / 类别B / 类别C`，避免把民航 CAP 样本包装成真实无人机型号
- 类型识别当前已接入真实训练与真实推理，默认使用 `scikit-learn + IQ 特征 + RandomForest`
- 个体指纹识别当前保留功能入口，真实训练与推理服务待接入，不输出假真实结果
- 当前南京 demo 主线优先按本地 Windows CPU 跑通，GPU 不是本轮关键路径
- USRP B210 已按 UHD Windows 默认安装目录做自动命令定位；安装器 PATH 写入失败时仍可使用软件采集入口
- 当前 B210 演示默认使用已验通的 USB2 保守档：`1 Msps / 2 s / 2.4 GHz / 20 dB / RX2`
- 信号预处理页新增 `USRP IQ 演示预处理`，可将 B210 `.iq + .json` 切片成 `.npy` 样本并衔接标注、训练和识别
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
