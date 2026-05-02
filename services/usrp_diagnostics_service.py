"""USRP B210 / UHD preflight diagnostics.

The checks in this module are intentionally read-only. They verify that the
UHD command line tools are visible, then run the standard discovery/probe
commands that Ettus recommends before attempting a real capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

from config import UHD_DEFAULT_INSTALL_DIR


REQUIRED_UHD_TOOLS: tuple[str, ...] = (
    "rx_samples_to_file",
    "uhd_find_devices",
    "uhd_usrp_probe",
    "uhd_config_info",
)


@dataclass(frozen=True)
class USRPToolStatus:
    """Resolution status for one UHD command line tool."""

    name: str
    path: str
    found: bool


@dataclass(frozen=True)
class USRPCommandResult:
    """Captured output from one diagnostic command."""

    name: str
    command_line: str
    return_code: int
    timed_out: bool
    output: str

    @property
    def success(self) -> bool:
        """Return whether the command completed successfully."""

        return not self.timed_out and self.return_code == 0


@dataclass(frozen=True)
class USRPDiagnosticsResult:
    """Aggregated B210 preflight result."""

    tools: list[USRPToolStatus]
    version: USRPCommandResult | None
    find_devices: USRPCommandResult | None
    probe: USRPCommandResult | None
    detected_b210: bool
    logs: list[str]

    @property
    def tools_ready(self) -> bool:
        """Return whether all required UHD utilities were found."""

        return all(tool.found for tool in self.tools)

    @property
    def device_ready(self) -> bool:
        """Return whether UHD was able to inspect a B-series device."""

        find_devices_ready = self.find_devices is not None and self.find_devices.success
        probe_ready = self.probe is not None and self.probe.success
        return self.detected_b210 and (find_devices_ready or probe_ready)

    @property
    def is_ready(self) -> bool:
        """Return whether the capture page can treat the B210 path as ready."""

        return self.tools_ready and self.device_ready


def resolve_uhd_tool(name: str) -> str | None:
    """Resolve a UHD tool from PATH or the default Windows install folder."""

    candidate = name.strip()
    if not candidate:
        return None

    direct_path = Path(candidate)
    if direct_path.exists():
        return str(direct_path)

    resolved = shutil.which(candidate)
    if resolved:
        return resolved

    exe_name = candidate if candidate.lower().endswith(".exe") else f"{candidate}.exe"
    for install_candidate in _uhd_tool_candidates(exe_name):
        if install_candidate.exists():
            return str(install_candidate)
    return None


def check_uhd_tools() -> list[USRPToolStatus]:
    """Check whether the UHD tools needed by the B210 workflow are available."""

    statuses: list[USRPToolStatus] = []
    for name in REQUIRED_UHD_TOOLS:
        resolved = resolve_uhd_tool(name)
        statuses.append(USRPToolStatus(name=name, path=resolved or "", found=resolved is not None))
    return statuses


def run_b210_preflight(device_args: str = "type=b200", timeout_s: float = 100.0) -> USRPDiagnosticsResult:
    """Run a B210 preflight check using standard UHD utilities."""

    logs: list[str] = []
    tools = check_uhd_tools()
    tool_paths = {tool.name: tool.path for tool in tools if tool.found}
    normalized_args = device_args.strip() or "type=b200"

    for tool in tools:
        if tool.found:
            logs.append(f"[OK] {tool.name}: {tool.path}")
        else:
            logs.append(f"[ERR] {tool.name}: 未找到")

    version = _run_if_available("uhd_config_info", ["--version"], tool_paths, timeout_s=timeout_s)
    find_devices = _run_if_available("uhd_find_devices", ["--args", normalized_args], tool_paths, timeout_s=timeout_s)
    probe = _run_if_available("uhd_usrp_probe", ["--args", normalized_args], tool_paths, timeout_s=timeout_s)

    for result in (version, find_devices, probe):
        if result is None:
            continue
        logs.extend(_summarize_command_result(result))

    combined_output = "\n".join(
        result.output
        for result in (find_devices, probe)
        if result is not None
    )
    detected_b210 = _looks_like_b210(combined_output)
    if detected_b210:
        logs.append("[OK] UHD 输出中检测到 B210 / B-Series 设备信息。")
        if probe is not None and probe.timed_out:
            logs.append("[WARN] uhd_usrp_probe 初始化超时；USB2 链路下较常见，可先用 1-5 Msps 低速采集验证。")
    elif probe is not None and probe.success:
        logs.append("[WARN] UHD probe 成功，但输出中没有明确的 B210 字样。")
    else:
        logs.append("[ERR] 尚未确认 B210 设备在线。")

    return USRPDiagnosticsResult(
        tools=tools,
        version=version,
        find_devices=find_devices,
        probe=probe,
        detected_b210=detected_b210,
        logs=logs,
    )


def format_b210_preflight_summary(result: USRPDiagnosticsResult) -> list[str]:
    """Build operator-facing preflight summary lines."""

    lines = list(result.logs)
    if result.is_ready:
        lines.append("[Ready] B210 预检通过，可以执行最小采集。")
        return lines

    if not result.tools_ready:
        lines.append("[Next] 请先安装 UHD，并确认 C:\\Program Files\\UHD\\bin 已加入 PATH。")
        lines.append("[Next] 若设备管理器显示未知 USB 设备，请从 C:\\Program Files\\UHD\\share\\uhd\\usbdriver 更新驱动。")
        return lines

    lines.append("[Next] 请确认 B210 使用 USB3 连接，天线接 RF A: RX2，仅做接收测试。")
    lines.append("[Next] 若 uhd_find_devices 看不到设备，拔插同一个 USB3 口；仍不稳定时接外部电源后重试。")
    lines.append("[Next] 若采集中出现 O/overflow，将采样率先降到 5 MHz。")
    return lines


def _run_if_available(
    tool_name: str,
    args: list[str],
    tool_paths: dict[str, str],
    *,
    timeout_s: float,
) -> USRPCommandResult | None:
    """Run one diagnostic command when the executable was found."""

    executable = tool_paths.get(tool_name)
    if not executable:
        return None
    return _run_command([executable, *args], name=tool_name, timeout_s=timeout_s)


def _run_command(command: list[str], *, name: str, timeout_s: float) -> USRPCommandResult:
    """Run a subprocess and capture a bounded text result."""

    command_line = subprocess.list2cmdline(command)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(timeout_s, 1.0),
            check=False,
            env=_build_uhd_env(command[0]),
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in ((exc.stdout or ""), (exc.stderr or "")) if part)
        return USRPCommandResult(
            name=name,
            command_line=command_line,
            return_code=-1,
            timed_out=True,
            output=output.strip(),
        )
    except OSError as exc:
        return USRPCommandResult(
            name=name,
            command_line=command_line,
            return_code=-1,
            timed_out=False,
            output=str(exc),
        )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return USRPCommandResult(
        name=name,
        command_line=command_line,
        return_code=int(completed.returncode),
        timed_out=False,
        output=output.strip(),
    )


def _summarize_command_result(result: USRPCommandResult) -> list[str]:
    """Return compact log lines for one command result."""

    status = "TIMEOUT" if result.timed_out else ("OK" if result.success else "ERR")
    lines = [f"[{status}] {result.name}: {result.command_line}"]
    if result.output:
        preview = _compact_output(result.output)
        lines.append(preview)
    return lines


def _compact_output(output: str, max_chars: int = 900) -> str:
    """Keep command output short enough for the Qt log panel."""

    normalized = "\n".join(line.rstrip() for line in output.splitlines() if line.strip())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n..."


def _looks_like_b210(output: str) -> bool:
    """Return whether UHD output looks like a detected B210."""

    lowered = output.lower()
    return "b210" in lowered or ("b-series" in lowered and "b200" in lowered) or "type: b200" in lowered


def _uhd_tool_candidates(executable_name: str) -> list[Path]:
    """Return likely Windows install paths for a UHD executable."""

    return [
        UHD_DEFAULT_INSTALL_DIR / "bin" / executable_name,
        UHD_DEFAULT_INSTALL_DIR / "lib" / "uhd" / "examples" / executable_name,
        UHD_DEFAULT_INSTALL_DIR / "lib" / "uhd" / "utils" / executable_name,
    ]


def _build_uhd_env(executable: str) -> dict[str, str]:
    """Build an environment that can run UHD examples outside PATH."""

    import os

    env = dict(os.environ)
    additions = [
        str(Path(executable).resolve().parent),
        str(UHD_DEFAULT_INSTALL_DIR / "bin"),
    ]
    path_parts = [item for item in env.get("PATH", "").split(os.pathsep) if item]
    existing = {item.lower() for item in path_parts}
    prepend = [item for item in additions if item.lower() not in existing]
    if prepend:
        env["PATH"] = os.pathsep.join(prepend + [env.get("PATH", "")])
    return env
