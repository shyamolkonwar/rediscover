"""Docker-isolated experiments. Results are untrusted, exploration-only data.

Only an operator-approved caller may supply discovery observations here. This
module deliberately has no campaign, verifier, model, or credential dependencies.
"""
from __future__ import annotations

import io
import json
import math
import os
import selectors
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

import numpy as np

IMAGE = "rediscover-research:0.2.0"
MAX_OUTPUT_BYTES = 64 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_POINTS = 1_000_000
_DOCKER = ("/usr/bin/docker", "--host", "unix:///var/run/docker.sock")


def _read_observations(path: Path) -> dict[str, np.ndarray]:
    """Bound archive and NPY headers before NumPy can allocate or deserialize."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError("input must be a regular NPZ file at most 32 MiB")
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds 32 MiB")
    keys = ("time", "flux", "flux_err")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 3 or {m.filename for m in members} != {f"{k}.npy" for k in keys}:
            raise ValueError("NPZ must contain exactly time, flux, flux_err")
        if sum(m.file_size for m in members) > MAX_INPUT_BYTES:
            raise ValueError("expanded NPZ exceeds 32 MiB")
        shapes = set()
        for member in members:
            with archive.open(member) as handle:
                version = np.lib.format.read_magic(handle)
                if version == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(handle)
                elif version == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(handle)
                else:
                    raise ValueError("only numeric NPY v1/v2 input is supported")
                if (len(shape) != 1 or not 1 <= shape[0] <= MAX_POINTS
                        or dtype.kind not in "fiu" or dtype.itemsize > 8):
                    raise ValueError("arrays must be real numeric 1D vectors of 1..1000000 points")
                if member.file_size != handle.tell() + shape[0] * dtype.itemsize:
                    raise ValueError("NPY header does not match payload length")
                shapes.add(shape)
        if len(shapes) != 1:
            raise ValueError("time, flux and flux_err must have identical shapes")
    with np.load(io.BytesIO(raw), allow_pickle=False) as source:
        return {key: source[key] for key in keys}


def _control(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    # Only trusted Docker control messages go through this path, never code output.
    return subprocess.run(
        [*_DOCKER, *args], env=env, capture_output=True, timeout=10, check=False
    )


def _capture(command: list[str], env: dict[str, str], timeout: int) -> tuple:
    """Drain both pipes fairly; never spool arbitrary experiment output to disk."""
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    status = None
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL) as process:
        try:
            with selectors.DefaultSelector() as selector:
                for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, name)
                total = 0
                while selector.get_map() or process.poll() is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        status = "timeout"
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, min(8192, MAX_OUTPUT_BYTES - total + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        available = MAX_OUTPUT_BYTES - total
                        streams[key.data].extend(chunk[:available])
                        total += min(len(chunk), available)
                        if len(chunk) > available:
                            status = "output_limit"
                            break
                    if status:
                        break
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
    return (status, process.returncode,
            streams["stdout"].decode("utf-8", errors="ignore"),
            streams["stderr"].decode("utf-8", errors="ignore"))


def execute_python(
    code: str, input_npz: Path, output_dir: Path, timeout_seconds: int = 30
) -> dict:
    """Run code against /input/lightcurve.npz; stdout must be one JSON object.

    ``output_dir`` is operator-owned temporary staging, not a container mount.
    No files from the container are imported. See docs/RESEARCH_SANDBOX.md.
    """
    result = {"status": "execution_error", "result": None, "stdout": "", "stderr": "",
              "returncode": None, "cleanup_confirmed": None,
              "exploration_only": True, "artifacts": []}
    if (not isinstance(code, str) or not code.strip()
            or len(code.encode("utf-8", errors="surrogatepass")) > 64 * 1024
            or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60):
        result.update(status="invalid_input", stderr="code must be 1..65536 UTF-8 bytes; "
                      "timeout_seconds must be an integer from 1 through 60")
        return result
    try:
        code.encode("utf-8")
        observations = _read_observations(Path(input_npz))
        output_dir = Path(output_dir).resolve()
        if "," in str(output_dir):
            raise ValueError("staging path cannot contain commas (Docker mount syntax)")
        output_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError, TypeError, EOFError, zipfile.BadZipFile) as exc:
        result.update(status="invalid_input", stderr=str(exc)[:4096])
        return result
    with tempfile.TemporaryDirectory(prefix="research-", dir=output_dir) as temporary:
        stage = Path(temporary)
        code_path = stage / "experiment.py"
        code_path.write_text(code, encoding="utf-8")
        code_path.chmod(0o444)
        data_path = stage / "lightcurve.npz"
        np.savez(data_path, **observations)
        data_path.chmod(0o444)
        # Never inherit host secrets, Docker contexts, proxy settings, or config.
        env = {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": str(stage / "docker-config")}
        name = f"rediscover-research-{uuid.uuid4().hex}"
        create = [
            "create", "--name", name, "--pull", "never", "--log-driver", "none",
            "--network", "none", "--memory", "512m", "--memory-swap", "512m",
            "--cpus", "1", "--pids-limit", "64", "--read-only", "--user", "65534:65534",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--ipc", "none", "--ulimit", "nofile=128:128", "--ulimit", "core=0:0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--workdir", "/work", "--env", "OPENBLAS_NUM_THREADS=1",
            "--env", "OMP_NUM_THREADS=1", "--env", "MKL_NUM_THREADS=1",
            "--mount", f"type=bind,src={data_path},dst=/input/lightcurve.npz,readonly",
            "--mount", f"type=bind,src={code_path},dst=/work/experiment.py,readonly",
            "--entrypoint", "python", IMAGE, "-I", "-B", "-u", "/work/experiment.py",
        ]
        try:
            created = _control(create, env)
            if created.returncode:
                result["stderr"] = created.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", "ignore")
            else:
                status, returncode, stdout, stderr = _capture(
                    [*_DOCKER, "start", "--attach", name], env, timeout_seconds
                )
                result.update(stdout=stdout, stderr=stderr, returncode=returncode)
                if status:
                    result["status"] = status
                elif returncode:
                    result["status"] = "execution_error"
                else:
                    try:
                        parsed = json.loads(stdout, parse_constant=_reject_nonfinite,
                                            parse_float=_finite_float)
                        if not isinstance(parsed, dict):
                            raise TypeError("stdout must be one JSON object")
                        result.update(status="success", result=parsed)
                    except (ValueError, TypeError, RecursionError):
                        result["status"] = "invalid_output"
        except subprocess.TimeoutExpired as exc:
            result.update(status="timeout", stderr=str(exc)[:4096])
        except (OSError, subprocess.SubprocessError) as exc:
            result["stderr"] = str(exc)[:4096]
        finally:
            # Killing a docker client alone leaves its container alive. Remove
            # exactly this UUID-owned container, even after interrupted create/start.
            cleanup_timeout = False
            try:
                _control(["rm", "--force", name], env)
            except subprocess.TimeoutExpired:
                cleanup_timeout = True
            except (OSError, subprocess.SubprocessError):
                pass  # Read back state even if the remove acknowledgement was lost.
            result["cleanup_confirmed"] = False
            try:
                check = _control(["container", "ls", "--all", "--quiet", "--filter",
                                  f"name=^/{name}$"], env)
                result["cleanup_confirmed"] = check.returncode == 0 and not check.stdout.strip()
            except subprocess.TimeoutExpired:
                cleanup_timeout = True
            except (OSError, subprocess.SubprocessError):
                pass
            if cleanup_timeout or result["status"] == "timeout":
                result.update(status="timeout", result=None)
            elif not result["cleanup_confirmed"]:
                result.update(status="cleanup_error", result=None)
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON number overflows a finite float")
    return parsed


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")
