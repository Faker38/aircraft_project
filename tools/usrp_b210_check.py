"""Command line helper for USRP B210 preflight and optional smoke capture."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from config import (  # noqa: E402
    DEFAULT_USRP_BANDWIDTH_MHZ,
    DEFAULT_USRP_CENTER_FREQUENCY_MHZ,
    DEFAULT_USRP_DEVICE_ARGS,
    DEFAULT_USRP_DURATION_S,
    DEFAULT_USRP_EXECUTABLE,
    DEFAULT_USRP_GAIN_DB,
    DEFAULT_USRP_SAMPLE_RATE_MHZ,
    RAW_DATA_DIR,
)
from services import (  # noqa: E402
    USRPCaptureConfig,
    USRPCaptureError,
    format_b210_preflight_summary,
    run_b210_preflight,
    run_usrp_capture,
)


def main(argv: list[str] | None = None) -> int:
    """Run B210 diagnostics from PowerShell."""

    parser = argparse.ArgumentParser(description="USRP B210 / UHD preflight helper")
    parser.add_argument("--args", default=DEFAULT_USRP_DEVICE_ARGS, help="UHD device args, default: type=b200")
    parser.add_argument("--timeout", type=float, default=100.0, help="diagnostic command timeout in seconds")
    parser.add_argument("--smoke-capture", action="store_true", help="also run a short rx_samples_to_file capture")
    parser.add_argument("--executable", default=DEFAULT_USRP_EXECUTABLE, help="rx_samples_to_file command or path")
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_USRP_CENTER_FREQUENCY_MHZ)
    parser.add_argument("--rate-mhz", type=float, default=DEFAULT_USRP_SAMPLE_RATE_MHZ)
    parser.add_argument("--bw-mhz", type=float, default=DEFAULT_USRP_BANDWIDTH_MHZ)
    parser.add_argument("--gain-db", type=float, default=DEFAULT_USRP_GAIN_DB)
    parser.add_argument("--duration", type=float, default=DEFAULT_USRP_DURATION_S)
    parser.add_argument("--output-dir", default=str(RAW_DATA_DIR))
    parsed = parser.parse_args(argv)

    result = run_b210_preflight(parsed.args, timeout_s=parsed.timeout)
    for line in format_b210_preflight_summary(result):
        print(line)

    if not parsed.smoke_capture:
        return 0 if result.is_ready else 2
    if not result.is_ready:
        print("[Skip] B210 预检未通过，跳过最小采集。")
        return 2

    config = USRPCaptureConfig(
        executable_path=parsed.executable,
        device_args=parsed.args,
        center_frequency_hz=parsed.freq_mhz * 1_000_000,
        sample_rate_hz=parsed.rate_mhz * 1_000_000,
        bandwidth_hz=parsed.bw_mhz * 1_000_000,
        gain_db=parsed.gain_db,
        duration_s=parsed.duration,
        output_dir=parsed.output_dir,
        output_format="iq",
        device_label="b210_smoke",
    )
    try:
        capture_result = run_usrp_capture(config, log_callback=print)
    except USRPCaptureError as exc:
        print(f"[ERR] 最小采集失败：{exc}")
        return 3

    output_path = Path(capture_result.output_file_path)
    expected_bytes = int(config.sample_rate_hz * config.duration_s * 4)
    actual_bytes = output_path.stat().st_size if output_path.exists() else 0
    print(f"[Done] 输出文件：{output_path}")
    print(f"[Info] 文件大小：{actual_bytes} bytes，预期约 {expected_bytes} bytes")
    return 0 if actual_bytes > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
