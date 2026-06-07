import os

from course_navigator import processes


def test_subprocess_env_prepends_existing_tool_paths(tmp_path, monkeypatch):
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()
    monkeypatch.setattr(processes, "DEFAULT_TOOL_DIRS", (tool_dir,))

    env = processes._subprocess_env({"PATH": "/usr/bin"})

    assert env["PATH"].split(os.pathsep) == [str(tool_dir), "/usr/bin"]


def test_subprocess_env_skips_missing_and_duplicate_tool_paths(tmp_path, monkeypatch):
    tool_dir = tmp_path / "tools"
    missing_dir = tmp_path / "missing"
    tool_dir.mkdir()
    monkeypatch.setattr(processes, "DEFAULT_TOOL_DIRS", (tool_dir, missing_dir))

    env = processes._subprocess_env({"PATH": os.pathsep.join([str(tool_dir), "/usr/bin"])})

    assert env["PATH"].split(os.pathsep) == [str(tool_dir), "/usr/bin"]
