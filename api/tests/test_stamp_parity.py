"""The frontend's stamp.sh (runs at image build time) and app.py's build_info() must sanitise
build values IDENTICALLY, or card 6 would flag a "mixed release" that isn't one."""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

STAMP = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "stamp.sh"
FRONTEND = STAMP.parent

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")

CASES = [
    {},
    {"APP_VERSION": "2.3.1-abc123", "GIT_SHA": "ABCDEF0123456789ABCDEF0123456789ABCDEF01"},
    {"APP_VERSION": "feature/login page", "GIT_REF": "refs/heads/feature/login page", "BUILD_ID": "12 34"},
    {"APP_VERSION": "  v3.0.0+meta  ", "GIT_SHA": "abc12", "CI_SYSTEM": "Jenkins!"},
    {"BUILD_URL": "https://ci.example/job/x/42/?a=1&b=2", "SOURCE_URL": "https://github.com/u/r",
     "GIT_SHA": "0123456789abcdef0123456789abcdef01234567", "BUILD_TIME": "2026-10-11T09:30:00Z"},
    {"BUILD_URL": 'https://x/"><script>', "SOURCE_URL": "javascript:alert(1)", "BUILD_TIME": "yesterday"},
    {"APP_VERSION": "1.0|rm -rf /;&", "GIT_REF": "a\\b"},
]


@pytest.mark.parametrize("env", CASES)
def test_stamp_matches_api(load_app, tmp_path, env):
    run_env = {"PATH": os.environ["PATH"], **env}
    subprocess.run(["sh", str(STAMP), str(FRONTEND), str(tmp_path)], env=run_env, check=True)
    stamped = json.loads((tmp_path / "build.json").read_text())
    expected = load_app(**env).BUILD
    assert stamped == expected
    assert (tmp_path / "version.txt").read_text() == expected["version"] + "\n"
    assert f'data-version="{expected["version"]}"' in (tmp_path / "index.html").read_text()
