"""预处理算法脚本。

当前版本用于把同学提供的 CAP 预处理逻辑纳入项目仓库统一管理。
注意：
- 这里仍以 0x200 / 512 字节头长作为当前联调口径；
- 这里负责完整文件窗口化扫描，不在 Qt 主线程中直接运行。
"""

from __future__ import annotations

import gc
import math
import os
import struct
from datetime import datetime

import numpy as np
import torch
import torch.nn as nn
from scipy import ndimage
from scipy.signal import butter, filtfilt, spectrogram


CAP_HEADER_LENGTH = 0x200
WINDOW_COMPLEX_SAMPLES = 4_000_000


class FastRF1DCNN_V2(nn.Module):
    """无人机信号二分类模型。"""

    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(2, 32, kernel_size=15, stride=4, padding=7),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(4),
            nn.Conv1d(32, 64, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.AdaptiveMaxPool1d(1),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.4),
            nn.Linear(64, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def extract_iq_internal(
    z_raw: np.ndarray,
    fs: float,
    t_start: float,
    t_end: float,
    f_center: float,
    bw: float,
) -> np.ndarray | None:
    """截取指定时频区域，并做一次简单基带平移与低通清理。"""

    start_idx, end_idx = int(t_start * fs), int(t_end * fs)
    z_slice = z_raw[start_idx:end_idx]
    if len(z_slice) == 0:
        return None

    t_vec = np.arange(len(z_slice)) / fs
    z_shifted = z_slice * np.exp(-1j * 2 * np.pi * f_center * t_vec)

    cutoff = min((bw / 2) * 1.2 / (fs / 2), 0.99)
    b, a = butter(N=4, Wn=cutoff, btype="low")
    z_clean = filtfilt(b, a, z_shifted.real) + 1j * filtfilt(b, a, z_shifted.imag)

    fixed_decimation = 2
    return z_clean[::fixed_decimation]


def slice_iq_internal(iq_data: np.ndarray, target_len: int) -> list[np.ndarray]:
    """把一段 IQ 数据按固定窗口切成模型输入块。"""

    chunks: list[np.ndarray] = []
    for index in range(0, len(iq_data) - target_len + 1, target_len):
        chunks.append(iq_data[index : index + target_len])

    if not chunks and len(iq_data) > 0:
        pad = np.pad(iq_data, (0, target_len - len(iq_data)), "constant")
        chunks.append(pad)
    return chunks


def normalize_and_tensor(chunk: np.ndarray, device: torch.device) -> torch.Tensor:
    """把单个 IQ 切片归一化并转成模型张量。"""

    i_part, q_part = np.real(chunk), np.imag(chunk)
    i_centered, q_centered = i_part - np.mean(i_part), q_part - np.mean(q_part)
    std = np.std(np.sqrt(i_centered**2 + q_centered**2)) + 1e-8
    tensor = np.stack([i_centered / std, q_centered / std], axis=0).astype(np.float32)
    return torch.from_numpy(tensor).unsqueeze(0).to(device)


def load_model_weights(model: nn.Module, model_weights_path: str, device: torch.device) -> None:
    """兼容不同 torch 版本加载模型权重。"""

    try:
        state_dict = torch.load(model_weights_path, map_location=device, weights_only=True)
    except TypeError:
        state_dict = torch.load(model_weights_path, map_location=device)
    model.load_state_dict(state_dict)


def build_complex_iq(raw_interleaved: np.ndarray) -> np.ndarray:
    """把大端 int16 交织 IQ 转成 complex64。"""

    z_raw = np.empty(len(raw_interleaved) // 2, dtype=np.complex64)
    z_raw.real = raw_interleaved[0::2].astype(np.float32) / 32768.0
    z_raw.imag = raw_interleaved[1::2].astype(np.float32) / 32768.0
    return z_raw


def build_rect_structure(height: int, width: int) -> np.ndarray:
    """构造与 OpenCV 矩形核等价的布尔结构元素。"""

    return np.ones((max(1, height), max(1, width)), dtype=bool)


def estimate_energy_threshold_db(
    sxx_roi_db: np.ndarray,
    energy_threshold_db: float,
    noise_floor_dbm: float,
    calibration_offset: float,
) -> tuple[float, float]:
    """基于当前窗口的频谱分布估计自适应阈值。"""

    baseline_db = float(np.percentile(sxx_roi_db, 50))
    legacy_threshold_db = (noise_floor_dbm + calibration_offset) + energy_threshold_db
    adaptive_threshold_db = baseline_db + energy_threshold_db
    threshold_db = min(legacy_threshold_db, adaptive_threshold_db)
    return threshold_db, baseline_db


def run_inference_api(
    input_file_path: str,
    slice_length: int = 4096,
    energy_threshold_db: float = 10.0,
    noise_floor_dbm: float = -90.0,
    enable_bandpass: bool = True,
    sample_output_dir: str = "./output",
    min_bandwidth_mhz: float = 6.0,
    min_duration_ms: float = 0.05,
    model_weights_path: str = "best_model_1_detect_v2.pth",
    ai_confidence_threshold: float = 0.85,
    calibration_offset: float = 110.0,
    device_name: str = "cuda" if torch.cuda.is_available() else "cpu",
) -> dict[str, object]:
    """对 CAP 文件执行整文件窗口化预处理和无人机信号判别。"""

    results: dict[str, object] = {
        "success": False,
        "message": "",
        "detected_segment_count": 0,
        "output_sample_count": 0,
        "segments": [],
        "logs": [],
        "candidate_segment_count": 0,  # 新增候选段统计
    }

    def add_log(message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        results["logs"].append(formatted)
        try:
            print(formatted)
        except UnicodeEncodeError:
            safe_message = str(message).replace("✅", "[OK]").replace("❌", "[ERR]")
            print(f"[{timestamp}] {safe_message}")

    try:
        os.makedirs(sample_output_dir, exist_ok=True)
        device = torch.device(device_name)
        add_log(f"启动推理引擎 | 目标文件: {os.path.basename(input_file_path)}")

        model = FastRF1DCNN_V2().to(device)
        load_model_weights(model, model_weights_path, device)
        model.eval()

        add_log("正在解析 3943B-S 硬件文件头...")
        with open(input_file_path, "rb") as file_handle:
            # 当前联调按 0x200 头长试跑，先把头字段和后续 IQ 数据区分开。
            header_bytes = file_handle.read(CAP_HEADER_LENGTH)
            if len(header_bytes) < CAP_HEADER_LENGTH:
                raise ValueError(f"文件异常：不足 {CAP_HEADER_LENGTH} 字节，无法读取完整文件头")

            version = header_bytes[0:8].decode("utf-8", errors="ignore").strip("\x00")
            bandwidth_hz = struct.unpack(">d", header_bytes[16:24])[0]
            sample_rate_hz = bandwidth_hz * 1.28
            center_frequency_hz = struct.unpack(">d", header_bytes[24:32])[0]

            add_log(f"元数据提取成功 -> 版本: {version} | 带宽: {bandwidth_hz / 1e6:.2f}MHz")
            add_log(
                f"物理参数绑定 -> 中心频率: {center_frequency_hz / 1e6:.2f}MHz | "
                f"真实采样率: {sample_rate_hz / 1e6:.2f}MHz"
            )
            add_log(f"数据读取口径 -> CAP 头长: 0x{CAP_HEADER_LENGTH:03X} | IQ 起始偏移: 0x{CAP_HEADER_LENGTH:03X}")

        file_size = os.path.getsize(input_file_path)
        payload_bytes = file_size - CAP_HEADER_LENGTH
        if payload_bytes <= 0:
            raise ValueError("有效载荷为空！无法提取 I/Q 数据。")
        if payload_bytes % 4 != 0:
            raise ValueError("CAP 载荷长度与 IQ 对齐规则不符。")

        total_complex_samples = payload_bytes // 4
        window_count = max(1, math.ceil(total_complex_samples / WINDOW_COMPLEX_SAMPLES))
        add_log(f"数据加载完成，整文件共 {total_complex_samples} 个复数样本，将分 {window_count} 个窗口分析。")

        raw_interleaved = np.memmap(
            input_file_path,
            dtype=">i2",
            mode="r",
            offset=CAP_HEADER_LENGTH,
            shape=(payload_bytes // 2,),
        )

        nperseg, noverlap = 1024, 512
        add_log(
            "能量阈值模式: 当前按窗口中位能量 + 相对阈值自适应估计，"
            f"同时兼容历史口径 (底噪 {noise_floor_dbm} dBm)。"
        )

        segment_id_counter = 1
        for window_index in range(window_count):
            start_complex_index = window_index * WINDOW_COMPLEX_SAMPLES
            end_complex_index = min(total_complex_samples, start_complex_index + WINDOW_COMPLEX_SAMPLES)
            interleaved_start = start_complex_index * 2
            interleaved_end = end_complex_index * 2
            window_interleaved = raw_interleaved[interleaved_start:interleaved_end].astype(np.int16, copy=False)

            if len(window_interleaved) % 2 != 0:
                window_interleaved = window_interleaved[:-1]
            if len(window_interleaved) == 0:
                continue

            z_raw = build_complex_iq(window_interleaved)
            add_log(f"窗口 {window_index + 1}/{window_count} | 样本范围 {start_complex_index} - {end_complex_index - 1}")

            f_bins, _, sxx = spectrogram(
                z_raw,
                fs=sample_rate_hz,
                window="hann",
                nperseg=nperseg,
                noverlap=noverlap,
                return_onesided=False,
                mode="magnitude",
            )
            f_bins = np.fft.fftshift(f_bins)
            sxx = np.fft.fftshift(sxx, axes=0)

            f_roi_mask = (f_bins >= -38e6) & (f_bins <= 38e6)
            f_roi = f_bins[f_roi_mask]
            sxx_roi = 10 * np.log10(sxx[f_roi_mask, :] + 1e-12)
            absolute_threshold_db, baseline_db = estimate_energy_threshold_db(
                sxx_roi,
                energy_threshold_db=energy_threshold_db,
                noise_floor_dbm=noise_floor_dbm,
                calibration_offset=calibration_offset,
            )

            dt = (nperseg - noverlap) / sample_rate_hz
            df = sample_rate_hz / nperseg

            add_log(
                f"窗口 {window_index + 1}/{window_count} 阈值估计 | "
                f"中位能量: {baseline_db:.2f} dB | 生效阈值: {absolute_threshold_db:.2f} dB"
            )
            img_bin = sxx_roi > absolute_threshold_db

            open_structure = build_rect_structure(height=max(1, int(2e6 / df)), width=1)
            img_clean = ndimage.binary_opening(img_bin, structure=open_structure)

            close_structure = build_rect_structure(
                height=max(1, int(4e6 / df)),
                width=max(1, int(0.2e-3 / dt)),
            )
            img_clean = ndimage.binary_closing(img_clean, structure=close_structure)

            labeled_regions, region_count = ndimage.label(img_clean)
            region_slices = ndimage.find_objects(labeled_regions)
            results["candidate_segment_count"] += int(region_count)
            add_log(f"窗口 {window_index + 1}/{window_count} 解析完成，发现 {region_count} 个能量超限区域。")

            for region_slice in region_slices:
                if region_slice is None:
                    continue
                y_slice, x_slice = region_slice
                y = y_slice.start or 0
                x = x_slice.start or 0
                height = (y_slice.stop or y) - y
                width = (x_slice.stop or x) - x
                f_min = f_roi[y]
                f_max = f_roi[min(y + height - 1, len(f_roi) - 1)]
                f_center = (f_max + f_min) / 2
                bandwidth = f_max - f_min
                t_start, t_end = x * dt, (x + width) * dt

                # 当前工程目标是先把流程打通：候选段只要能切出来并保存，
                # 就进入数据集管理等待人工标注；模型结果只作为参考状态。
                safe_bandwidth = max(abs(float(bandwidth)), float(df))
                try:
                    pure_iq = extract_iq_internal(z_raw, sample_rate_hz, t_start, t_end, f_center, safe_bandwidth)
                except Exception as extract_error:
                    add_log(f"候选段提取失败，已跳过：{extract_error}")
                    continue
                if pure_iq is None:
                    continue

                chunks = slice_iq_internal(pure_iq, slice_length)
                if not chunks:
                    continue

                rule_passed = (safe_bandwidth / 1e6) >= min_bandwidth_mhz and (t_end - t_start) * 1000 >= min_duration_ms
                score = 0.0
                is_drone = False
                if rule_passed:
                    tensor_list = [normalize_and_tensor(chunk, device) for chunk in chunks]
                    batch_tensor = torch.cat(tensor_list, dim=0)

                    with torch.no_grad():
                        outputs = model(batch_tensor)
                        probs = torch.softmax(outputs, dim=1)[:, 1].cpu().numpy()

                    score = float(np.percentile(probs, 80))
                    is_drone = score >= ai_confidence_threshold

                output_filename = (
                    f"seg_w{window_index + 1:02d}_{segment_id_counter:03d}_{datetime.now().strftime('%M%S')}.npy"
                )
                output_filepath = os.path.join(sample_output_dir, output_filename)
                np.save(output_filepath, pure_iq)

                segment_absolute_center_hz = center_frequency_hz + f_center
                segment_start_sample = start_complex_index + int(t_start * sample_rate_hz)
                segment_end_sample = start_complex_index + int(t_end * sample_rate_hz)

                segment_result = {
                    "segment_id": f"SEG_{segment_id_counter:03d}",
                    "start_sample": segment_start_sample,
                    "end_sample": segment_end_sample,
                    "duration_ms": round(float((t_end - t_start) * 1000), 2),
                    "center_freq_hz": float(segment_absolute_center_hz),
                    "bandwidth_hz": float(safe_bandwidth),
                    "snr_db": round(float(np.mean(sxx_roi[y : y + height, x : x + width]) - absolute_threshold_db), 2),
                    "score": round(score, 4),
                    "output_file_path": output_filepath,
                    "status": "valid" if is_drone else "discarded",
                }

                results["segments"].append(segment_result)
                if is_drone:
                    results["detected_segment_count"] += 1
                results["output_sample_count"] += 1
                segment_id_counter += 1

            del z_raw
            del window_interleaved
            del sxx
            del sxx_roi
            del img_bin
            del img_clean
            gc.collect()

        results["success"] = True
        results["message"] = "处理成功"
        add_log(f"[OK] 任务结束 | 有效无人机信号检出: {results['detected_segment_count']} 个，候选段总数: {results['candidate_segment_count']} 个")

    except Exception as error:
        results["success"] = False
        results["message"] = f"处理崩溃: {str(error)}"
        add_log(f"[ERR] 致命错误: {str(error)}")

    finally:
        try:
            del model
            if "batch_tensor" in locals():
                del batch_tensor
            torch.cuda.empty_cache()
            gc.collect()
        except Exception:
            pass

    return results


if __name__ == "__main__":
    mock_request = {
        "input_file_path": r"D:\pythonProject8\IQ_2025_01_09_13_55_30.cap",
        "slice_length": 4096,
        "energy_threshold_db": 10.0,
        "noise_floor_dbm": -90.0,
        "enable_bandpass": True,
        "sample_output_dir": "./api_output",
        "min_bandwidth_mhz": 6.0,
        "min_duration_ms": 0.05,
        "model_weights_path": "best_model_1_detect_v2.pth",
        "ai_confidence_threshold": 0.85,
        "calibration_offset": 110.0,
    }

    print("正在模拟前端 API 调用（硬件元数据自动侦测模式）...")
    response_json = run_inference_api(**mock_request)

    import json

    print("\n返回结果示例：")
    print(json.dumps(response_json, indent=4, ensure_ascii=False))
