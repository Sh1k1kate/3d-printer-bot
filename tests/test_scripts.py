"""Запускает проверочные скрипты tests/*.py (assert-скрипты) как отдельные процессы."""
import glob, os, subprocess, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = sorted(p for p in glob.glob(os.path.join(HERE, "check_*.py"))
                 )


@pytest.mark.parametrize("path", SCRIPTS, ids=[os.path.basename(p) for p in SCRIPTS])
def test_script(path):
    env = dict(os.environ, BOT_TOKEN="123456:TEST-token", ADMIN_PASSWORD="secret")
    r = subprocess.run([sys.executable, path], cwd=os.path.dirname(HERE), env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
