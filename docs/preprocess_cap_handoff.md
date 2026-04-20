# 预处理算法 CAP 对接说明

## 1. 当前联调口径

当前预处理模块统一按 `.cap` 文件联调，不再按 `.mat` 输入继续推进。

本轮采用的工作口径如下：

- CAP 头长按 `0x200`，即 `512` 字节试跑
- `0x0010` 位置读取到的值先解释为**分析带宽**
- 当前样例文件中该值为 `10 MHz`
- 实际 IQ 采样率按 `bandwidth_hz * 1.28` 计算，当前样例应为 `12.8 MHz`
- `0x0018` 位置读取**中心频率**
- IQ 数据从 `0x200` 后开始读取
- IQ 数据格式按大端 `int16` 交织解释：`I0,Q0,I1,Q1...`

说明：

- `0x200` 是当前联调口径，不作为永久铁结论
- 若后续拿到更多样本并推翻该假设，再统一调整

## 2. 前端传给算法的正式输入

```json
{
  "input_file_path": "D:/data/IQ_2025_01_09_13_55_30.cap",
  "slice_length": 4096,
  "energy_threshold_db": 10.0,
  "noise_floor_dbm": -90.0,
  "min_bandwidth_mhz": 6.0,
  "min_duration_ms": 0.05,
  "enable_bandpass": true,
  "sample_output_dir": "D:/data/output",
  "model_weights_path": "./weights/best_model_v2.pth",
  "ai_confidence_threshold": 0.85
}
```

说明：

- 前端不再传 `sample_rate_hz`
- 前端不再传 `center_frequency_hz`
- 前端不再传 `cap_datatype`
- 采样率、中心频率与头长口径由算法内部统一处理

## 3. 算法返回给前端的结构

输出 JSON 结构保持不变：

```json
{
  "success": true,
  "message": "处理成功",
  "detected_segment_count": 1,
  "output_sample_count": 2,
  "segments": [
    {
      "segment_id": "SEG_001",
      "start_sample": 150020,
      "end_sample": 167500,
      "duration_ms": 0.22,
      "center_freq_hz": 2462500000.0,
      "bandwidth_hz": 12000000.0,
      "snr_db": 18.5,
      "score": 0.9912,
      "output_file_path": "D:/data/output/seg_4215_001.npy",
      "status": "valid"
    }
  ],
  "logs": [
    "[16:20:01] 启动推理引擎 | 目标文件: IQ_2025_01_09_13_55_30.cap",
    "[16:20:02] 能量截断阈值生效: 20.00 (底噪 -90.0 dBm)",
    "[16:20:04] [OK] 任务结束 | 有效无人机信号检出: 1 个"
  ]
}
```

## 4. 页面需要展示的内容

预处理页当前固定展示以下内容：

- 任务状态
- 检出信号段数
- 输出样本数
- 当前输出目录
- 处理日志
- `segments` 结果表

`segments` 表格固定展示：

- `segment_id`
- `start_sample`
- `end_sample`
- `duration_ms`
- `center_freq_hz`
- `bandwidth_hz`
- `snr_db`
- `score`
- `output_file_path`
- `status`

同时页面只读显示 CAP 头解析结果：

- 分析带宽
- 实际采样率
- 中心频率

## 5. 当前验收标准

本轮 CAP 版联调至少满足：

- 能直接读取 `IQ_2025_01_09_13_55_30.cap`
- 头长按 `0x200` 试跑时，带宽显示为 `10 MHz`
- 实际采样率按规则计算为 `12.8 MHz`
- 中心频率可正常读出
- 输出 JSON 结构保持兼容
- `logs` 可直接显示到 Qt 页面
- 若检出到有效信号，则 `segments[*].output_file_path` 能对应真实样本文件

## 6. 当前边界

- 本轮先打通“CAP -> 算法 -> Qt 页面 -> 样本记录”的联调链路
- 本轮不接数据库
- 本轮不把 `0x200` 写死为永久格式结论
- 后续若头长口径变化，只需统一调整算法、CAP 探针和界面文案
