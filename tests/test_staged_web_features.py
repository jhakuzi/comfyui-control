"""Optional Node checks for unloaded components; no frontend build dependency."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_unloaded_feature_state_transport_and_action_races():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is optional; use the browser feature fixture instead.')
    result = subprocess.run([node, str(Path(__file__).with_name('staged_web_features.cjs'))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
