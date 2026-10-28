from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_TOOL_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)
RUNTIME_TOOL_PATHS_ENV = "COURSE_NAVIGATOR_RUNTIME_TOOL_PATHS"
# Tests replace subprocess.Popen with fakes, which have no process tree.
_REAL_POPEN = subprocess.Popen


def _subprocess_env(env: dict[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy() if env is None else dict(env)
    path = merged.get("PATH", "")
    path_parts = [part for part in path.split(os.pathsep) if part]
    extra_paths = []
    for tool_dir in _candidate_tool_dirs(merged):
        tool_path = str(tool_dir)
        if tool_dir.exists() and tool_path not in path_parts and tool_path not in extra_paths:
            extra_paths.append(tool_path)
    if extra_paths:
        merged["PATH"] = os.pathsep.join([*extra_paths, *path_parts])
    return merged


def _candidate_tool_dirs(env: dict[str, str]) -> list[Path]:
    runtime_paths = [
        Path(part)
        for part in env.get(RUNTIME_TOOL_PATHS_ENV, "").split(os.pathsep)
        if part
    ]
    return [*runtime_paths, *DEFAULT_TOOL_DIRS]


def resolve_tool(name: str, env: dict[str, str] | None = None) -> Path | None:
    merged = _subprocess_env(env)
    resolved = shutil.which(name, path=merged.get("PATH", ""))
    return Path(resolved) if resolved else None


def _hidden_windows_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    if not sys.platform.startswith("win"):
        return kwargs
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", None)
    if create_no_window is not None:
        kwargs.setdefault("creationflags", create_no_window)
    startup_info_factory = getattr(subprocess, "STARTUPINFO", None)
    if startup_info_factory is not None and kwargs.get("startupinfo") is None:
        startupinfo = startup_info_factory()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    return kwargs


def run_hidden(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs["env"] = _subprocess_env(kwargs.get("env"))
    return subprocess.run(cmd, **_hidden_windows_kwargs(kwargs))


def popen_hidden(cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    kwargs["env"] = _subprocess_env(kwargs.get("env"))
    if not sys.platform.startswith("win"):
        # Its own process group lets a cancel stop everything it started.
        kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(cmd, **_hidden_windows_kwargs(kwargs))


def terminate_process_tree(process: subprocess.Popen[str], timeout: float = 5) -> None:
    """Stops `process` and the processes it started, such as yt-dlp's ffmpeg."""
    if process.poll() is not None:
        return
    if isinstance(process, _REAL_POPEN):
        if sys.platform.startswith("win"):
            try:
                run_hidden(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        elif _owns_process_group(process):
            _signal_group(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            # Children that ignored SIGTERM or outlived the parent go too.
            _signal_group(process.pid, signal.SIGKILL)
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def _owns_process_group(process: subprocess.Popen[str]) -> bool:
    try:
        return os.getpgid(process.pid) == process.pid
    except OSError:
        return False


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except OSError:
        pass
