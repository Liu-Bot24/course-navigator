import os
import subprocess
import sys
import threading

from course_navigator import processes


def test_terminate_process_tree_stops_processes_the_child_started():
    # The grandchild inherits stdout, so the pipe reaches EOF only once both
    # the child and the grandchild are gone.
    script = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n"
    )
    process = processes.popen_hidden([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"
        processes.terminate_process_tree(process)
        closed = threading.Event()
        threading.Thread(target=lambda: (process.stdout.read(), closed.set()), daemon=True).start()
        assert closed.wait(10), "a grandchild process kept running"
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_terminate_process_tree_leaves_finished_processes_alone():
    process = processes.popen_hidden([sys.executable, "-c", "pass"])
    process.wait(timeout=30)

    processes.terminate_process_tree(process)

    assert process.returncode == 0


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
