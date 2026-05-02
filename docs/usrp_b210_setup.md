# USRP B210 Windows 连接与烟测说明

## 当前结论

- Windows 已能识别 `Ettus Research LLC B200/B210`。
- UHD `uhd_usrp_probe --args "type=b200"` 能识别 `B210`，序列号 `30FB59C`。
- 低速接收烟测已成功：`1 Msps / 2 s / short IQ` 输出 `8,000,000` 字节。
- 阶梯稳定性测试已通过：`1 Msps / 2 s` 连续 3 次、`2 Msps / 2 s`、`5 Msps / 2 s` 文件大小均符合预期。
- 当前探测显示 `Operating over USB 2`，后续若要跑 `12.8 Msps`，应换到稳定 USB3 口或更换 USB3 线。

## 安装注意

安装 UHD 时如果出现：

```text
Warning! PATH too long installer unable to modify PATH!
```

这不代表 UHD 安装失败，只代表安装器没能自动修改系统 `PATH`。当前软件会自动查找 UHD 默认路径，并在启动采集子进程时补齐 DLL 搜索路径。

默认安装后的关键路径：

```text
C:\Program Files\UHD\bin\uhd_find_devices.exe
C:\Program Files\UHD\bin\uhd_usrp_probe.exe
C:\Program Files\UHD\bin\uhd_config_info.exe
C:\Program Files\UHD\lib\uhd\examples\rx_samples_to_file.exe
```

注意：`rx_samples_to_file.exe` 不在 `bin` 目录，而在 `lib\uhd\examples` 目录。

## 设备连接

1. B210 放在绝缘平面上，避免电路板接触金属。
2. 天线先接 `RF A: RX2`。
3. 只做接收测试，不运行任何 `tx_*` 发射命令。
4. 优先使用电脑直连 USB3 口，不建议先接扩展坞。
5. 如果识别不稳定，再接 B210 外部电源。

## 只读验证命令

```powershell
& "C:\Program Files\UHD\bin\uhd_config_info.exe" --version
& "C:\Program Files\UHD\bin\uhd_find_devices.exe" --args "type=b200"
& "C:\Program Files\UHD\bin\uhd_usrp_probe.exe" --args "type=b200"
```

如果第一次 `uhd_find_devices` 加载 firmware 后 `probe` 暂时找不到设备，等待 5 到 10 秒再执行一次。
在 USB2 链路下，`uhd_usrp_probe` 可能需要 70 秒左右才完成；软件内预检已按这个耗时放宽超时时间。

## 低速烟测命令

当前电脑显示 USB2 链路时，先使用低速采样：

```powershell
$env:PATH = "C:\Program Files\UHD\bin;" + $env:PATH
& "C:\Program Files\UHD\lib\uhd\examples\rx_samples_to_file.exe" `
  --args "type=b200" `
  --file "D:\桌面\QT_gemini\rf_identification\data\raw\b210_smoke_1msps.iq" `
  --freq 2.4e9 `
  --rate 1e6 `
  --gain 20 `
  --duration 2 `
  --type short `
  --ant RX2 `
  --progress `
  --stats
```

预期输出文件大小：

```text
1,000,000 samples/s * 2 s * 4 bytes = 8,000,000 bytes
```

## 软件内使用

进入“数据采集”页：

- 模式：`USRP 真实采集`
- 设备地址：`type=b200`
- 先点：`B210 预检`
- 当前 USB2 链路默认参数：`1 Msps / 2 s / 2.4 GHz / 10 MHz / 20 dB / RX2`
- 当前 USB2 链路可演示参数：`2 Msps / 2 s`，需要更强采集感时可用 `5 Msps / 2 s`
- 稳定 USB3 链路建议参数：`12.8 Msps / 10 MHz / 20 dB / 3 s`

若采集日志里出现 `O` 或 overflow，先把采样率降到 `5 Msps`，仍不稳定时换 USB3 口或 USB3 线。
首次点击“开始采集”时，UHD 会先做固件、FPGA、时钟和 LO 锁定初始化；界面里设置的 `2 s / 3 s` 是实际采样时长，不是从点击按钮到结束的总等待时间。USB2 链路下建议至少等待 20 到 30 秒再判断是否卡住。

## 阶梯测试记录

2026-05-02 已完成以下本机测试，输出目录为 `rf_identification\data\raw`：

| 参数 | 次数 | 预期文件大小 | 实际结果 |
| --- | ---: | ---: | --- |
| `1 Msps / 2 s` | 3 | `8,000,000` bytes | 3 个 `.iq` 均匹配，均生成同名 `.json` |
| `2 Msps / 2 s` | 1 | `16,000,000` bytes | `.iq` 匹配，生成同名 `.json` |
| `5 Msps / 2 s` | 1 | `40,000,000` bytes | `.iq` 匹配，生成同名 `.json` |

同名 `.json` 已确认记录 `sample_rate_hz`、`center_frequency_hz`、`duration_s`、`bandwidth_hz`、`gain_db` 和命令行参数。

## 南京演示口径

- B210 用于现场展示“软件已经能接入真实采集硬件，并能生成原始 `.iq + .json` 采集记录”。
- 当前 `.iq` 可进入“USRP IQ 演示预处理”桥接链路，切片成 `.npy` 样本后衔接标注、数据集、训练和识别页面。
- CAP 算法预处理主链路仍保持原样；USRP 演示预处理是并行入口，不替代正式 CAP 算法链路。
- 正式采集设备仍是 `3941B`；B210 是本轮演示与采集链路验证设备。
- 若现场没有真实无人机信号，USRP 演示标签采用 `频点A / 频点B / 频点C`，只表示 2.4 GHz 环境频点类别，不宣传为真实无人机型号。

## USRP 端到端演示流程

1. 接好 `RF A: RX2` 天线，进入“数据采集”页，选择 `USRP 真实采集`。
2. 分别采集 `2412 MHz`、`2437 MHz`、`2462 MHz`，建议参数为 `5 Msps / 2 s / 10 MHz / 30 dB`。
3. 进入“信号预处理”页，输入模式选择 `USRP IQ 演示预处理`。
4. 对每个 `.iq` 文件执行演示预处理，系统会切片生成 `.npy` 样本并建议标签：
   - `2412 MHz -> 频点A`
   - `2437 MHz -> 频点B`
   - `2462 MHz -> 频点C`
5. 进入“数据集管理”页，确认或修改标签后生成“类型识别”数据集版本。
6. 进入“模型训练”页训练 RandomForest 类型识别模型。
7. 进入“无人机识别”页选择新模型和 USRP 样本，执行识别。
