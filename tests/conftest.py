"""Tests run Home Assistant (pytest-homeassistant-custom-component) against the real bmp-control, started here as its
own process on a free port with the mock engine and daemon (control/test/harness.py), not against a mock of the API.
It is started at import time: Home Assistant's test plugin blocks non-127.0.0.1 sockets during tests."""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time

import pytest

HERE = os.path.dirname(__file__)
# the processor software (stageaudioworks/plus-audio-bmp): BMP_ROOT, or the checkout this folder sits in as a submodule
ROOT = os.environ.get("BMP_ROOT") or os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, ".."))
if not os.path.isfile(os.path.join(ROOT, "control", "bmp-control.py")):
    pytest.skip("set BMP_ROOT to a checkout of the processor software (plus-audio-bmp) to run these tests",
                allow_module_level=True)
sys.path.insert(0, os.path.join(ROOT, "control", "test"))
import harness  # noqa: E402
import tunein_mock  # noqa: E402  (a TuneIn directory on 127.0.0.1 and a fake mpc on PATH, for the radio and music player)

pytest_plugins = "pytest_homeassistant_custom_component"
PIN = "135790"


def _start_box():
    harness.ensure_mocks()
    d = tempfile.mkdtemp(prefix="bmp-ha-")
    json.dump({"installer_pin": PIN}, open(os.path.join(d, "access.json"), "w"))
    port = harness.free_port()
    env = {**os.environ, "BMP_CONTROL_PORT": str(port), "BMP_STATE": f"{d}/state.json", "BMP_ACCESS": f"{d}/access.json",
           "BMP_SOCK": harness.SOCK, "BMP_DAEMON": "http://127.0.0.1:18080", "BMP_PANEL_DIR": f"{d}/panels",
           "BMP_MSG_DIR": f"{d}/msgs", "BMP_PLAYLOG": f"{d}/playlog.csv", "BMP_SPEAKER_DIR": f"{d}/speakers",
           "BMP_SECRETS": f"{d}/secrets.json", "BMP_ALERT_LOG": f"{d}/alerts.jsonl", "BMP_AUDIT_LOG": f"{d}/audit.jsonl",
           "BMP_CLOUD_CONF": f"{d}/cloud.json", "BMP_SERIAL": "HA-TEST-1", "BMP_NET_DROPIN": f"{d}/net.conf",
           "BMP_SOLOIST": f"{d}/no-soloist", **tunein_mock.ENV, "PATH": f"{harness.MOCK_DIR}/bin:" + os.environ["PATH"]}
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "control", "bmp-control.py")], env=env, cwd=d,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            c.request("GET", "/api/whoami", headers={"Host": f"127.0.0.1:{port}"})
            if c.getresponse().status == 200:
                break
        except OSError:
            time.sleep(0.25)
    return p, port


PROC, PORT = _start_box()


def call(method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": f"127.0.0.1:{PORT}", "X-BMP-PIN": PIN}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


def pytest_sessionfinish(session, exitstatus):
    PROC.terminate()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    yield


_TOKEN = {}


@pytest.fixture
def box(socket_enabled):
    """(url, staff token, call): the running box, a staff token, and an installer-PIN API call for checks"""
    if not _TOKEN:
        st, j = call("POST", "/api/tokens", {"name": "Home Assistant", "scope": "staff"})
        assert st == 200, j
        _TOKEN["t"] = j["token"]
        for name in ("Lunch", "Dinner"):
            st, j = call("POST", "/api/scenes", {"name": name, "from_now": True})
            assert st == 200, j
    return f"http://127.0.0.1:{PORT}", _TOKEN["t"], call
