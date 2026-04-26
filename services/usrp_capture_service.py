"""USRP 采集服务：通过外部命令执行真实采集。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import time

from config import RAW_DATA_DIR


class USRPCaptureError(RuntimeError):
    """USRP 采集阶段的统一业务异常。"""


class USRPCaptureCancelled(USRPCaptureError):
    """用于标记一次协作式采集中止。"""


@dataclass(frozen=True)
class USRPCaptureConfig:
    """一次 USRP 采集任务的最小配置。"""

    executable_path: str
    device_args: str
    center_frequency_hz: float
    sample_rate_hz: float
    bandwidth_hz: float
    gain_db: float
    duration_s: float
    output_dir: str
    output_format: str
    device_label: str


@dataclass(frozen=True)
class USRPCaptureResult:
    """一次真实采集完成后的统一结果。"""

    output_file_path: str
    metadata_file_path: str
    file_name: str
    sample_rate_hz: float
    center_frequency_hz: float
    bandwidth_hz: float
    duration_s: float
    command_line: str
    logs: list[str]


def run_usrp_capture(
    config: USRPCaptureConfig,
    *,
    progress_callback: Callable[[int, str], None] | None = None,
    log_callback: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> USRPCaptureResult:
    """通过外部 USRP 采集命令执行一次真实采集。"""

    executable = _resolve_executable(config.executable_path)
    output_dir = Path(config.output_dir or RAW_DATA_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = _build_output_path(output_dir, config)
    command = _build_command(executable, config, output_path)
    command_line = subprocess.list2cmdline(command)
    logs: list[str] = [
        f"[Start] 启动 USRP 采集任务 | 输出文件：{output_path.name}",
        f"[Info] 采集命令：{command_line}",
    ]
    _emit_log(log_callback, logs[-2])
    _emit_log(log_callback, logs[-1])
    _emit_progress(progress_callback, 0, "正在启动采集命令")
    _raise_if_cancelled(cancel_check, "采集已停止：在启动 USRP 命令前取消。")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    start_time = time.monotonic()
    last_log_second = -1
    try:
        while process.poll() is None:
            elapsed = time.monotonic() - start_time
            if cancel_check is not None and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise USRPCaptureCancelled("采集已停止：USRP 任务已终止，未保留本次结果。")

            percent = min(95, int((elapsed / max(config.duration_s, 0.1)) * 95))
            _emit_progress(progress_callback, percent, f"正在采集 IQ 数据：{elapsed:.1f}s / {config.duration_s:.1f}s")
            current_second = int(elapsed)
            if current_second != last_log_second and current_second % 2 == 0:
                log_text = f"[Info] USRP 采集中：{elapsed:.1f}s / {config.duration_s:.1f}s"
                logs.append(log_text)
                _emit_log(log_callback, log_text)
                last_log_second = current_second
            time.sleep(0.2)
    finally:
        stdout_text = ""
        if process.stdout is not None:
            try:
                stdout_text = process.stdout.read().strip()
            except Exception:
                stdout_text = ""

    if stdout_text:
        for line in stdout_text.splitlines():
            text = line.strip()
            if text:
                logs.append(text)
                _emit_log(log_callback, text)

    return_code = int(process.returncode or 0)
    if return_code != 0:
        raise USRPCaptureError(f"USRP 采集命令执行失败，返回码 {return_code}。")
    if not output_path.exists():
        raise USRPCaptureError(f"USRP 采集命令已结束，但未发现输出文件：{output_path}")

    metadata_path = output_path.with_suffix(".json")
    metadata_payload = {
        "device_backend": "usrp",
        "device_args": config.device_args,
        "center_frequency_hz": float(config.center_frequency_hz),
        "sample_rate_hz": float(config.sample_rate_hz),
        "bandwidth_hz": float(config.bandwidth_hz),
        "gain_db": float(config.gain_db),
        "duration_s": float(config.duration_s),
        "output_file_path": str(output_path),
        "created_at": _now_text(),
        "command_line": command_line,
    }
    metadata_path.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logs.append(f"[Done] 采集完成，原始 IQ 文件：{output_path}")
    logs.append(f"[Done] 元数据文件：{metadata_path}")
    _emit_log(log_callback, logs[-2])
    _emit_log(log_callback, logs[-1])
    _emit_progress(progress_callback, 100, "采集完成")

    return USRPCaptureResult(
        output_file_path=str(output_path),
        metadata_file_path=str(metadata_path),
        file_name=output_path.name,
        sample_rate_hz=float(config.sample_rate_hz),
        center_frequency_hz=float(config.center_frequency_hz),
        bandwidth_hz=float(config.bandwidth_hz),
        duration_s=float(config.duration_s),
        command_line=command_line,
        logs=logs,
    )


def _resolve_executable(executable_path: str) -> str:
    """解析 USRP 外部命令的真实可执行路径。"""

    candidate = executable_path.strip()
    if not candidate:
        raise USRPCaptureError("请先填写 USRP 采集程序路径或命令名。")
    if Path(candidate).exists():
        return str(Path(candidate))
    resolved = shutil.which(candidate)
    if resolved:
        return resolved
    raise USRPCaptureError(f"未找到 USRP 采集命令：{candidate}")


def _build_output_path(output_dir: Path, config: USRPCaptureConfig) -> Path:
    """按当前参数生成一个独立输出文件名。"""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    frequency_mhz = int(round(config.center_frequency_hz / 1_000_000))
    sample_rate_mhz = int(round(config.sample_rate_hz / 1_000_000))
    label = _sanitize_name(config.device_label or "usrp")
    extension = "bin" if config.output_format.lower() == "bin" else "iq"
    return output_dir / f"{timestamp}_{frequency_mhz}M_{sample_rate_mhz}M_{label}.{extension}"


def _build_command(executable: str, config: USRPCaptureConfig, output_path: Path) -> list[str]:
    """构造默认的 USRP 采集命令行。"""

    command = [
        executable,
        "--file",
        str(output_path),
        "--freq",
        f"{float(config.center_frequency_hz):.0f}",
        "--rate",
        f"{float(config.sample_rate_hz):.0f}",
        "--gain",
        f"{float(config.gain_db):.2f}",
        "--duration",
        f"{float(config.duration_s):.2f}",
        "--type",
        "short",
    ]
    if config.device_args.strip():
        command.extend(["--args", config.device_args.strip()])
    if float(config.bandwidth_hz) > 0:
        command.extend(["--bw", f"{float(config.bandwidth_hz):.0f}"])
    return command


def _emit_progress(progress_callback: Callable[[int, str], None] | None, percent: int, status_text: str) -> None:
    """向 UI 层发出采集进度。"""

    if progress_callback is None:
        return
    progress_callback(int(percent), status_text)


def _emit_log(log_callback: Callable[[str], None] | None, text: str) -> None:
    """向 UI 层发出采集日志。"""

    if log_callback is None:
        return
    log_callback(text)


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None, message: str) -> None:
    """在启动前检查是否已请求取消。"""

    if cancel_check is not None and cancel_check():
        raise USRPCaptureCancelled(message)


def _sanitize_name(value: str) -> str:
    """把任意设备标识压缩成适合文件名的文本。"""

    compact = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value.strip())
    return compact.strip("_") or "usrp"


def _now_text() -> str:
    """返回统一时间文本。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
