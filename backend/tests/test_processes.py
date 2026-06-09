import os
import sys

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


def test_subprocess_env_prepends_runtime_tool_paths_from_launcher(tmp_path, monkeypatch):
    node_dir = tmp_path / "runtime-tools" / "node"
    uv_dir = tmp_path / "runtime-tools" / "uv"
    missing_dir = tmp_path / "runtime-tools" / "missing"
    node_dir.mkdir(parents=True)
    uv_dir.mkdir(parents=True)
    monkeypatch.setattr(processes, "DEFAULT_TOOL_DIRS", ())

    env = processes._subprocess_env(
        {
            "PATH": "/usr/bin",
            "COURSE_NAVIGATOR_RUNTIME_TOOL_PATHS": os.pathsep.join(
                [str(node_dir), str(uv_dir), str(missing_dir)]
            ),
        }
    )

    assert env["PATH"].split(os.pathsep) == [str(node_dir), str(uv_dir), "/usr/bin"]


def test_resolve_tool_uses_runtime_tool_paths_from_launcher(tmp_path, monkeypatch):
    node_dir = tmp_path / "runtime-tools" / "node"
    node_dir.mkdir(parents=True)
    executable_name = "node.exe" if sys.platform == "win32" else "node"
    node = node_dir / executable_name
    node.write_text("", encoding="utf-8")
    node.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setenv("COURSE_NAVIGATOR_RUNTIME_TOOL_PATHS", str(node_dir))
    monkeypatch.setattr(processes, "DEFAULT_TOOL_DIRS", ())

    assert processes.resolve_tool("node") == node
