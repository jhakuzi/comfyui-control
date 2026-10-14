from pathlib import Path
import subprocess
import sys
import time

import pytest
from PySide6.QtTest import QTest

from comfyui_control.config import Config
from comfyui_control.controller import Controller


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "Condition did not complete before timeout"


@pytest.fixture
def server(app, tmp_path):
    (tmp_path / "main.py").write_text('import time\nprint("server ready ✓", flush=True)\nwhile True: time.sleep(.1)\n')
    controller = Controller(Config(comfy_dir=str(tmp_path), python=sys.executable))
    logs, errors = [], []
    controller.output.connect(logs.append)
    controller.problem.connect(errors.append)
    yield controller, logs, errors, tmp_path
    controller.shutdown()
    wait_for(lambda: controller.state == "stopped")


def test_start_output_restart_stop(server):
    c, logs, errors, _ = server
    c.start()
    wait_for(lambda: "server ready ✓" in "".join(logs))
    first_pid = c._pid
    assert c.state == "running"
    c.restart()
    wait_for(lambda: c.state == "running" and c._pid != first_pid)
    c.stop()
    wait_for(lambda: c.state == "stopped")
    assert c.process is None
    assert not errors


def test_process_group_stops_children(server):
    c, logs, _, path = server
    child_file = path / "child.pid"
    (path / "main.py").write_text(
        'import subprocess, sys, time\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])\n'
        f'open({str(child_file)!r}, "w").write(str(child.pid))\n'
        'print("child ready", flush=True)\nwhile True: time.sleep(.1)\n'
    )
    c.start()
    wait_for(lambda: "child ready" in "".join(logs))
    child = int(child_file.read_text())
    c.stop()
    wait_for(lambda: c.state == "stopped")

    def no_live_child():
        stat = Path(f"/proc/{child}/stat")
        return not stat.exists() or stat.read_text().split()[2] == "Z"

    wait_for(no_live_child)


def test_unresponsive_process_is_killed(server):
    c, logs, _, path = server
    (path / "main.py").write_text(
        'import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
        'print("ignoring signals", flush=True)\nwhile True: time.sleep(.1)\n'
    )
    c.start()
    wait_for(lambda: "ignoring signals" in "".join(logs))
    c.stop()
    c._kill_timer.start(80)
    wait_for(lambda: c.state == "stopped")
    assert "forcing shutdown" in "".join(logs)


def test_script_launch_forwards_quoted_flags(server):
    c, logs, _, path = server
    script = path / "launch script.sh"
    script.write_text(f'exec {sys.executable} -u main.py "$@"\n')
    (path / "main.py").write_text('import sys, time\nprint(repr(sys.argv), flush=True)\nwhile True: time.sleep(.1)\n')
    c.config.mode, c.config.script = "script", str(script)
    c.config.arguments = '--name "hello world"'
    c.start()
    wait_for(lambda: "['main.py', '--name', 'hello world']" in "".join(logs))
    c.stop()
    wait_for(lambda: c.state == "stopped")


def test_failed_start_returns_to_idle(server, monkeypatch):
    c, _, errors, _ = server
    monkeypatch.setattr(c.config, "command", lambda: ["/no/such/executable"])
    c.start()
    wait_for(lambda: c.state == "stopped")
    assert errors and "Could not start" in errors[0]
    assert c.process is None


def test_stop_during_start(server):
    c, _, _, _ = server
    c.start()
    c.stop()
    wait_for(lambda: c.state == "stopped")
    assert c.process is None


def git(directory, *arguments):
    return subprocess.run(["git", "-C", str(directory), *arguments], check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def repositories(tmp_path):
    origin, upstream, local = (tmp_path / name for name in ("origin.git", "upstream", "local"))
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(upstream)], check=True, capture_output=True)
    git(upstream, "config", "user.name", "Test")
    git(upstream, "config", "user.email", "test@example.invalid")
    (upstream / "main.py").write_text('import time\nprint("ready", flush=True)\nwhile True: time.sleep(.1)\n')
    git(upstream, "add", "main.py")
    git(upstream, "commit", "-m", "Initial")
    git(upstream, "push", "-u", "origin", "HEAD")
    subprocess.run(["git", "clone", str(origin), str(local)], check=True, capture_output=True)
    return upstream, local


def make_controller(app, path):
    c = Controller(Config(comfy_dir=str(path), python=sys.executable))
    logs, errors = [], []
    c.output.connect(logs.append)
    c.problem.connect(errors.append)
    return c, logs, errors


def test_update_fast_forwards_and_resumes(app, repositories):
    upstream, local = repositories
    (upstream / "version.txt").write_text("new version")
    git(upstream, "add", "version.txt")
    git(upstream, "commit", "-m", "Update")
    git(upstream, "push")
    c, logs, errors = make_controller(app, local)
    try:
        c.start()
        wait_for(lambda: "ready" in "".join(logs))
        old_pid = c._pid
        c.update()
        wait_for(lambda: c.state == "running" and c._pid != old_pid)
        assert (local / "version.txt").read_text() == "new version"
        assert "Update complete" in "".join(logs)
        assert not errors
    finally:
        c.shutdown()
        wait_for(lambda: c.state == "stopped")


@pytest.mark.parametrize("untracked", [False, True])
def test_update_preserves_changes_and_leaves_server_stopped(app, repositories, untracked):
    _, local = repositories
    path = local / ("notes.txt" if untracked else "main.py")
    original = "my local changes\n" if untracked else (local / "main.py").read_text() + "# my local changes\n"
    path.write_text(original)
    c, _, errors = make_controller(app, local)
    c.start()
    wait_for(lambda: c.state == "running")
    c.update()
    wait_for(lambda: c.state == "stopped" and bool(errors))
    assert "local changes" in errors[0]
    assert path.read_text() == original


def test_update_failure_does_not_restart(app, repositories):
    _, local = repositories
    git(local, "remote", "set-url", "origin", str(local / "missing-remote"))
    c, _, errors = make_controller(app, local)
    c.start()
    wait_for(lambda: c.state == "running")
    c.update()
    wait_for(lambda: c.state == "stopped" and bool(errors))
    assert "Pull ComfyUI" in errors[0]


def test_cannot_update_parent_repository(app, tmp_path):
    git(tmp_path, "init")
    nested = tmp_path / "ComfyUI"
    nested.mkdir()
    (nested / "main.py").touch()
    c, _, errors = make_controller(app, nested)
    c.update()
    wait_for(lambda: c.state == "stopped" and bool(errors))
    assert "root of its own Git checkout" in errors[0]


def test_requirement_install_uses_selected_python_and_reports_failure(app, repositories):
    _, local = repositories
    interpreter = local.parent / "comfy-python"
    arguments = local.parent / "pip-arguments.txt"
    interpreter.write_text(
        f'#!{sys.executable}\nimport sys\n'
        f'open({str(arguments)!r}, "w").write(repr(sys.argv[1:]))\n'
        'print("simulated dependency failure", flush=True)\nsys.exit(7)\n'
    )
    interpreter.chmod(0o755)
    c, logs, errors = make_controller(app, local)
    c.config.python = str(interpreter)
    c.config.install_requirements = True
    c.update()
    wait_for(lambda: c.state == "stopped" and bool(errors))
    assert arguments.read_text() == "['-m', 'pip', 'install', '-r', 'requirements.txt']"
    assert "Install requirements" in errors[0]
    assert "simulated dependency failure" in "".join(logs)
