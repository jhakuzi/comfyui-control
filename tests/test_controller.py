from pathlib import Path
import json
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


def test_update_preserves_changes_and_leaves_server_stopped(app, repositories):
    _, local = repositories
    path = local / "main.py"
    original = (local / "main.py").read_text() + "# my local changes\n"
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


@pytest.fixture
def cli_environment(tmp_path):
    prefix = tmp_path / "Comfy environment"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "python").symlink_to(sys.executable)
    (prefix / "pyvenv.cfg").touch()
    report = tmp_path / "cli-report.json"
    cli = prefix / "bin" / "comfy"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, subprocess\n"
        f"open({str(report)!r}, 'w').write(json.dumps(dict(argv=sys.argv[1:], cwd=os.getcwd(), "
        "venv=os.environ.get('VIRTUAL_ENV'), conda=os.environ.get('CONDA_PREFIX'), "
        "path=os.environ['PATH'], pythonhome=os.environ.get('PYTHONHOME'))))\n"
        "subprocess.run(['git', 'pull', '--ff-only'], check=True)\n"
        "print('CLI update finished', flush=True)\n"
        "sys.exit(int(os.environ.get('TEST_CLI_EXIT', '0')))\n"
    )
    cli.chmod(0o755)
    return prefix, cli, report


@pytest.mark.parametrize("exit_code", [0, 9])
def test_cli_update_uses_workspace_environment_and_resumes_only_on_success(app, repositories, cli_environment, monkeypatch, exit_code):
    _, local = repositories
    prefix, _, report = cli_environment
    c, logs, errors = make_controller(app, local)
    c.config.python = str(prefix / "bin" / "python")
    c.config.update_method = "cli"
    c.config.install_requirements = True  # Must not add a second pip step for CLI.
    monkeypatch.setenv("CONDA_PREFIX", "/wrong/conda")
    monkeypatch.setenv("TEST_CLI_EXIT", str(exit_code))
    try:
        c.start()
        wait_for(lambda: c.state == "running")
        first_pid = c._pid
        # Contaminate the parent environment only after the server has started.
        monkeypatch.setenv("VIRTUAL_ENV", "/wrong/gui-env")
        monkeypatch.setenv("PYTHONHOME", "/wrong/python")
        c.update()
        if exit_code:
            wait_for(lambda: c.state == "stopped" and bool(errors))
            assert "Update with Comfy CLI" in errors[0]
        else:
            # Restore Python's startup env before the server restarts; it should
            # keep its normal environment rather than the CLI-only overrides.
            monkeypatch.delenv("PYTHONHOME")
            wait_for(lambda: c.state == "running" and c._pid != first_pid)
            assert not errors
        recorded = json.loads(report.read_text())
        assert recorded["argv"] == ["--workspace", str(local), "--skip-prompt", "update"]
        assert recorded["cwd"] == str(local)
        assert recorded["venv"] == str(prefix)
        assert recorded["conda"] is None and recorded["pythonhome"] is None
        assert recorded["path"].split(":")[0] == str(prefix / "bin")
        assert "CLI update finished" in "".join(logs)
        assert "Install requirements" not in "".join(logs)
        assert "pull --ff-only" not in "".join(logs)
    finally:
        c.shutdown()
        wait_for(lambda: c.state == "stopped")


def test_missing_cli_keeps_running_server_and_does_not_fall_back(app, repositories, cli_environment):
    _, local = repositories
    prefix, _, report = cli_environment
    c, logs, errors = make_controller(app, local)
    c.config.python = str(prefix / "bin" / "python")
    c.config.update_method, c.config.comfy_cli = "cli", str(prefix / "missing-comfy")
    try:
        c.start()
        wait_for(lambda: c.state == "running")
        first_pid = c._pid
        c.update()
        assert c.state == "running" and c._pid == first_pid
        assert errors and "Comfy CLI was not found" in errors[0]
        assert not report.exists()
        assert "pull --ff-only" not in "".join(logs)
    finally:
        c.shutdown()
        wait_for(lambda: c.state == "stopped")


def test_cli_preserves_local_changes_without_invoking_cli(app, repositories, cli_environment):
    _, local = repositories
    prefix, _, report = cli_environment
    original = (local / "main.py").read_text() + "# personal changes\n"
    (local / "main.py").write_text(original)
    c, _, errors = make_controller(app, local)
    c.config.python = str(prefix / "bin" / "python")
    c.config.update_method = "cli"
    c.update()
    wait_for(lambda: c.state == "stopped" and bool(errors))
    assert "local changes" in errors[0]
    assert not report.exists()
    assert (local / "main.py").read_text() == original


@pytest.mark.parametrize("method", ["git", "cli"])
def test_untracked_config_and_gpu_dumps_do_not_block_update(app, repositories, cli_environment, method):
    upstream, local = repositories
    prefix, _, _ = cli_environment
    files = {".env": "DUMMY_VALUE=preserve-me\n", "gpucore.23211": "test dump", "gpucore.3609": "another dump"}
    for name, content in files.items():
        (local / name).write_text(content)
    (upstream / "revision.txt").write_text("updated")
    git(upstream, "add", "revision.txt")
    git(upstream, "commit", "-m", "Update")
    git(upstream, "push")
    c, logs, errors = make_controller(app, local)
    c.config.python = str(prefix / "bin/python")
    c.config.update_method = method
    c.update()
    wait_for(lambda: "Update complete" in "".join(logs) or bool(errors))
    assert not errors
    assert (local / "revision.txt").read_text() == "updated"
    for name, content in files.items():
        assert (local / name).read_text() == content


@pytest.mark.parametrize("method", ["git", "cli"])
def test_actual_untracked_collision_is_refused_by_git_without_losing_file(app, repositories, cli_environment, method):
    upstream, local = repositories
    prefix, _, _ = cli_environment
    (local / "conflict.txt").write_text("my local data")
    (upstream / "conflict.txt").write_text("upstream data")
    git(upstream, "add", "conflict.txt")
    git(upstream, "commit", "-m", "Conflicting addition")
    git(upstream, "push")
    c, _, errors = make_controller(app, local)
    c.config.python = str(prefix / "bin/python")
    c.config.update_method = method
    c.update()
    wait_for(lambda: c.state == "stopped" and bool(errors))
    assert (local / "conflict.txt").read_text() == "my local data"
