from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_TOOL_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def _subprocess_env(env: dict[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy() if env is None else dict(env)
    path = merged.get("PATH", "")
    path_parts = [part for part in path.split(os.pathsep) if part]
    extra_paths = [
        str(tool_dir)
        for tool_dir in DEFAULT_TOOL_DIRS
        if tool_dir.exists() and str(tool_dir) not in path_parts
    ]
    if extra_paths:
        merged["PATH"] = os.pathsep.join([*extra_paths, *path_parts])
    return merged


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
    return subprocess.Popen(cmd, **_hidden_windows_kwargs(kwargs))
