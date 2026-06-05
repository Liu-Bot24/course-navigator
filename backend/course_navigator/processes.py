from __future__ import annotations

import subprocess
import sys
from typing import Any


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
    return subprocess.run(cmd, **_hidden_windows_kwargs(kwargs))


def popen_hidden(cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    return subprocess.Popen(cmd, **_hidden_windows_kwargs(kwargs))
