"""Recovery safety with real owned QProcesses; deadlines advanced without sleeping."""
from dataclasses import replace
import os
import sys
import time

import pytest
from PySide6.QtTest import QTest

from comfyui_control.config import Config
from comfyui_control.controller import Controller


def wait(predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


@pytest.fixture
def owned(app, tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path/'settings'))
    (tmp_path/'main.py').write_text('import sys\nprint("failure context",flush=True)\nsys.exit(7)\n')
    c = Controller(Config(comfy_dir=str(tmp_path), python=sys.executable))
    notices, crashes = [], []
    c.recovery.connect(notices.append)
    c.crashed.connect(crashes.append)
    yield c, notices, crashes, tmp_path
    c.shutdown()
    wait(lambda: c.process is None)


def retry(c):
    assert c.state == 'restarting' and c.process is None
    c._deadline = time.monotonic()-1
    c._recovery_tick()


def test_crash_diagnostics_default_off_and_manual_restart(owned):
    c, notices, crashes, path = owned
    c.start()
    wait(lambda: c.state == 'crashed')
    assert len(crashes)==1 and crashes[0]['exit_code']==7
    assert 'failure context' in c.history.text() and str(path) in c.history.text()
    assert not c._recovery_timer.isActive() and 'disabled' in notices[-1]
    c.restart()
    wait(lambda: len(crashes)==2)
    assert c.state=='crashed' and c.process is None


def test_retry_backoff_limit_duplicate_prevention_and_manual_reset(owned):
    c, notices, crashes, path = owned
    c.config.auto_restart=True
    c.config.restart_limit=3
    c.start()
    for attempt, delay in enumerate((2,4,8),1):
        wait(lambda: len(crashes)==attempt and c.state=='restarting')
        assert c._attempts==attempt
        assert delay-.5 < c._deadline-time.monotonic() <= delay
        assert f'{attempt}/3' in notices[-1]
        retry(c)
        process=c.process
        c.start()  # Same starting/running QProcess must remain the sole owner.
        assert c.process is process
        assert c.config.command()==c._snapshot.command()
    wait(lambda: len(crashes)==4)
    assert c.state=='crashed' and not c._recovery_timer.isActive()
    assert 'limit reached (3 attempts)' in notices[-1]
    c.restart()
    wait(lambda: len(crashes)==5 and c.state=='restarting')
    assert c._attempts==1


@pytest.mark.parametrize('action', ['stop','shutdown','settings','mutated-settings','update'])
def test_pending_recovery_cancelled_by_lifecycle_actions(owned,monkeypatch,action):
    c, notices, crashes, path = owned
    c.config.auto_restart=True
    c.start()
    wait(lambda: c.state=='restarting')
    if action=='settings': c.set_config(replace(c.config,arguments='--new'))
    elif action=='mutated-settings':
        c.config.arguments='--different'
        retry(c)
        assert 'settings changed' in notices[-1]
    elif action=='update':
        monkeypatch.setattr(c,'_begin_update',lambda: c._state('updating'))
        c.update()
        assert c.state=='updating'
    else: getattr(c,action)()
    assert c.process is None and not c._recovery_timer.isActive()
    assert c._deadline is None
    QTest.qWait(40)
    assert len(crashes)==1 and c.process is None


def test_normal_exit_and_intentional_stop_restart_never_count_as_crashes(owned):
    c, notices, crashes, path = owned
    c.config.auto_restart=True
    (path/'main.py').write_text('pass\n')
    c.start()
    wait(lambda: c.process is None)
    assert c.state=='stopped' and not crashes
    (path/'main.py').write_text('import time\nwhile True: time.sleep(.1)\n')
    c.start()
    wait(lambda: c.state=='running')
    old=c._pid
    c.restart()
    wait(lambda: c.state=='running' and c._pid!=old)
    c.stop()
    wait(lambda: c.state=='stopped')
    assert not crashes and c._attempts==0


def test_signal_crash_and_stable_runtime_reset(owned):
    c, notices, crashes, path = owned
    c.config.auto_restart=True
    (path/'main.py').write_text('import os,signal\nos.kill(os.getpid(), signal.SIGKILL)\n')
    c.start()
    wait(lambda: c.state=='restarting')
    assert crashes[-1]['exit_status']=='CrashExit'
    (path/'main.py').write_text('import time\ntime.sleep(90)\n')
    retry(c)
    wait(lambda: c.state=='running')
    c._stable_timer.start(20)  # Exercise the production timer callback.
    wait(lambda: c._attempts==0)
    assert 'stable runtime' in notices[-1]
    os.kill(c._pid,9)
    wait(lambda: c.state=='restarting')
    assert c._attempts==1


def test_failed_recovery_launch_uses_retry_budget(owned):
    c, notices, crashes, path = owned
    c.config.auto_restart=True
    c.config.restart_limit=1
    executable=path/'selected-python'
    executable.write_text(f'#!{sys.executable}\nimport os,sys\nos.execv({sys.executable!r},[{sys.executable!r}]+sys.argv[1:])\n')
    executable.chmod(0o755)
    c.config.python=str(executable)
    c.start()
    wait(lambda: c.state=='restarting')
    # Launch was valid but the OS now cannot execute it. This is not a
    # configuration change and must still consume the bounded retry budget.
    executable.write_text('#!/no/such/interpreter\n')
    retry(c)
    wait(lambda: len(crashes)==2)
    assert c.state=='crashed' and c._attempts==1
    assert crashes[-1]['exit_status']=='FailedToStart'
    assert 'limit reached' in notices[-1]


def test_backoff_is_capped(owned):
    c, notices, crashes, path = owned
    c.config.auto_restart=True
    c.config.restart_backoff=40
    c.start()
    wait(lambda: c.state=='restarting')
    retry(c)
    wait(lambda: len(crashes)==2 and c.state=='restarting')
    assert 59 < c._deadline-time.monotonic() <= 60
