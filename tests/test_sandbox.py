"""Real Docker integration tests; run on the authorized research VM only."""
import importlib.util
import io
import json
import subprocess
import time
import zipfile

import numpy as np
import pytest

from rediscover import sandbox
from rediscover.sandbox import execute_python


def test_numeric_fit(tmp_path):
    source = tmp_path / "observation.npz"
    time = np.arange(100, dtype=float)
    np.savez(source, time=time, flux=2.5 * time + 7.0, flux_err=np.ones(100))
    result = execute_python('''
import json
import numpy as np
from scipy.optimize import curve_fit
from astropy.time import Time
with np.load('/input/lightcurve.npz', allow_pickle=False) as data:
    fit, _ = curve_fit(lambda x, a, b: a*x+b, data['time'], data['flux'])
print(json.dumps({'slope': float(fit[0]), 'intercept': float(fit[1]),
                  'time_scale': Time(2457000, format='jd', scale='tdb').scale}))
''', source, tmp_path / "outputs")
    assert result["status"] == "success", result
    assert abs(result["result"]["slope"] - 2.5) < 1e-10
    assert abs(result["result"]["intercept"] - 7.0) < 1e-10
    assert result["result"]["time_scale"] == "tdb"
    assert result["exploration_only"] is True
    assert result["artifacts"] == []
    assert json.loads(result["stdout"]) == result["result"]


@pytest.fixture
def observation(tmp_path):
    path = tmp_path / "observation.npz"
    np.savez(path, time=np.arange(10.), flux=np.ones(10), flux_err=np.ones(10))
    return path


@pytest.mark.parametrize("code, timeout", [
    ("x" * 65537, 30), ("é" * 32769, 30), ("", 30), (None, 30),
    ("print('{}')", 0), ("print('{}')", 61), ("print('{}')", True),
    ("print('{}')", 1.5),
])
def test_invalid_execution_request(observation, tmp_path, code, timeout):
    result = execute_python(code, observation, tmp_path / "outputs", timeout)
    assert result["status"] == "invalid_input", result
    assert result["result"] is None


@pytest.mark.parametrize("kind", ["missing", "extra", "object", "shape", "symlink", "bad_zip"])
def test_invalid_observations(tmp_path, kind):
    source = tmp_path / "invalid.npz"
    data = {"time": np.arange(10.), "flux": np.ones(10), "flux_err": np.ones(10)}
    if kind == "missing":
        data.pop("flux_err")
    elif kind == "extra":
        data["secret"] = np.array(["never expose this"])
    elif kind == "object":
        data["flux"] = np.array([{}] * 10, dtype=object)
    elif kind == "shape":
        data["flux"] = np.ones(11)
    np.savez(source, **data)
    if kind == "symlink":
        link = tmp_path / "link.npz"
        link.symlink_to(source)
        source = link
    if kind == "bad_zip":
        source.write_bytes(b"not an archive")
    result = execute_python("print('{}')", source, tmp_path / "outputs")
    assert result["status"] == "invalid_input", result
    assert result["result"] is None


def _containers():
    completed = subprocess.run([
        "/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "container", "ls",
        "--all", "--quiet", "--filter", "name=rediscover-research-",
    ], check=True, capture_output=True, text=True, timeout=10)
    return set(completed.stdout.split())


def test_read_only_and_secret_isolation(observation, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_HOST_SECRET", "must-not-be-inherited")
    adjacent = observation.parent / "credentials.txt"
    adjacent.write_text("must-not-be-mounted")
    before = observation.read_bytes()
    result = execute_python('''
import json, os
from pathlib import Path
blocked = []
for target in ['/input/lightcurve.npz', '/work/experiment.py', '/work/new', '/etc/new']:
    try:
        Path(target).write_text('tampered')
    except OSError:
        blocked.append(target)
Path('/tmp/local').write_text('allowed ephemeral output')
Path('/tmp/escape').symlink_to('/input/lightcurve.npz')
print(json.dumps({'blocked': blocked, 'uid': os.getuid(),
                  'inputs': sorted(os.listdir('/input')),
                  'secret': os.getenv('SANDBOX_HOST_SECRET'),
                  'socket': Path('/var/run/docker.sock').exists(),
                  'home_credentials': os.access('/root/.ssh', os.R_OK),
                  'tmp_ok': Path('/tmp/local').read_text()}))
''', observation, tmp_path / "outputs")
    assert result["status"] == "success", result
    assert len(result["result"]["blocked"]) == 4
    assert result["result"]["uid"] == 65534
    assert result["result"]["inputs"] == ["lightcurve.npz"]
    assert result["result"]["secret"] is None
    assert result["result"]["socket"] is False
    assert result["result"]["home_credentials"] is False
    assert observation.read_bytes() == before
    assert list((tmp_path / "outputs").iterdir()) == []
    assert result["artifacts"] == []


def test_network_and_resource_isolation(observation, tmp_path):
    result = execute_python('''
import json, os, socket
from pathlib import Path
blocked = False
try:
    with socket.create_connection(('1.1.1.1', 53), timeout=1):
        pass
except OSError:
    blocked = True
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
fs = os.statvfs('/tmp')
print(json.dumps({'network_blocked': blocked, 'capabilities': status['CapEff'].strip(),
 'no_new_privileges': status['NoNewPrivs'].strip(), 'seccomp': status['Seccomp'].strip(),
 'memory': Path('/sys/fs/cgroup/memory.max').read_text().strip(),
 'swap': Path('/sys/fs/cgroup/memory.swap.max').read_text().strip(),
 'pids': Path('/sys/fs/cgroup/pids.max').read_text().strip(),
 'cpu': Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
 'tmp_bytes': fs.f_blocks * fs.f_frsize}))
''', observation, tmp_path / "outputs")
    assert result["status"] == "success", result
    info = result["result"]
    assert info["network_blocked"] is True
    assert int(info["capabilities"], 16) == 0
    assert info["no_new_privileges"] == "1"
    assert info["seccomp"] == "2"
    assert int(info["memory"]) == 512 * 1024 * 1024
    assert int(info["swap"]) == 0
    assert int(info["pids"]) == 64
    quota, period = map(int, info["cpu"].split())
    assert quota == period
    assert info["tmp_bytes"] <= 64 * 1024 * 1024


@pytest.mark.parametrize("code", [
    "while True: pass",
    ("import subprocess, time; subprocess.Popen(['python', '-c', 'import time; time.sleep(60)']); "
     "print('{}', flush=True); time.sleep(60)"),
])
def test_timeout_stops_container(observation, tmp_path, code):
    before = _containers()
    started = time.monotonic()
    result = execute_python(code, observation, tmp_path / "outputs", timeout_seconds=1)
    assert result["status"] == "timeout", result
    assert result["result"] is None
    assert time.monotonic() - started < 10
    assert _containers() == before


@pytest.mark.parametrize("fd", [1, 2])
def test_output_limit_stops_container(observation, tmp_path, fd):
    before = _containers()
    result = execute_python(f"import os\nwhile True: os.write({fd}, b'x' * 8192)",
                            observation, tmp_path / "outputs")
    assert result["status"] == "output_limit", result
    assert result["result"] is None
    assert len(result["stdout"].encode()) + len(result["stderr"].encode()) <= 65536
    assert _containers() == before


def test_nonzero_exit_is_not_success(observation, tmp_path):
    result = execute_python("print('{}'); raise SystemExit(17)", observation, tmp_path / "outputs")
    assert result["status"] == "execution_error", result
    assert result["returncode"] == 17
    assert result["result"] is None


@pytest.mark.parametrize("output", ["not JSON", "[]", '{"n":NaN}', '{"n":1e309}'])
def test_invalid_output(observation, tmp_path, output):
    result = execute_python(f"print({output!r})", observation, tmp_path / "outputs")
    assert result["status"] == "invalid_output", result
    assert result["result"] is None


def test_untrusted_array_header_rejected_before_allocation(tmp_path):
    source = tmp_path / "malicious.npz"
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(header, {
        "descr": "<f8", "fortran_order": False, "shape": (10**12,),
    })
    with zipfile.ZipFile(source, "w") as archive:
        for key in ("time", "flux", "flux_err"):
            archive.writestr(f"{key}.npy", header.getvalue())
    result = execute_python("print('{}')", source, tmp_path / "outputs")
    assert result["status"] == "invalid_input"


def test_create_timeout_cleans_actual_created_container(observation, tmp_path, monkeypatch):
    # Inject only the lost acknowledgement; creation and cleanup use real Docker.
    original = sandbox._control
    before = _containers()

    def lost_acknowledgement(args, env):
        response = original(args, env)
        if args[0] == "create":
            assert response.returncode == 0
            raise subprocess.TimeoutExpired("docker create", 10)
        return response

    monkeypatch.setattr(sandbox, "_control", lost_acknowledgement)
    result = execute_python("print('{}')", observation, tmp_path / "outputs")
    assert result["status"] == "timeout", result
    assert result["result"] is None
    assert _containers() == before


def test_cleanup_timeout_cannot_return_success(observation, tmp_path, monkeypatch):
    original = sandbox._control
    before = _containers()

    def lost_acknowledgement(args, env):
        response = original(args, env)
        if args[0] == "rm":
            assert response.returncode == 0
            raise subprocess.TimeoutExpired("docker rm", 10)
        return response

    monkeypatch.setattr(sandbox, "_control", lost_acknowledgement)
    result = execute_python("print('{}')", observation, tmp_path / "outputs")
    assert result["status"] == "timeout", result
    assert result["result"] is None
    assert _containers() == before


def test_sandbox_api_exists():
    assert importlib.util.find_spec("rediscover.sandbox") is not None
