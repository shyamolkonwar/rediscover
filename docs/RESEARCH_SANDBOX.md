# Research Python sandbox

`rediscover.sandbox.execute_python(code: str, input_npz: Path, output_dir: Path,
timeout_seconds: int = 30) -> dict` runs one standalone exploratory experiment
in the fixed local Docker image `rediscover-research:0.2.0`. It never executes
model-generated code directly on the host. It does not accept an image override,
Docker endpoint, environment additions, mounts, packages, or shell commands.

## Caller and scientific contract

The calling CLI must have an explicit human request; other callers must obtain
operator opt-in before invoking this API. The function itself is a low-level
executor, not a consent or campaign authorization layer. The caller must provide
**discovery data only**, never reserved holdout data. It must retain the approved
plan, frozen hypotheses, provenance, and acceptance rules outside this sandbox.

Every response contains `exploration_only: true`. Generated JSON, stdout and
stderr are untrusted content, not instructions, verifier evidence, approvals,
confirmed discoveries, or permission to alter a plan. A successful computation
only means that the process exited cleanly and emitted a finite JSON object.

## Input and output

- `code`: nonempty Python source, at most 65,536 UTF-8 bytes.
- `timeout_seconds`: an integer from 1 through 60; booleans are rejected. This
  bounds the attached execution, including startup. Docker control and cleanup
  commands have separate 10-second deadlines; overall API latency may exceed the
  execution limit. A deadline failure never returns success.
- `input_npz`: a regular, non-symlink NPZ file with exactly `time`, `flux`, and
  `flux_err`. Each is a same-length one-dimensional real integer/float array,
  with 1–1,000,000 samples and item size at most eight bytes. Nonfinite input
  samples are permitted for explicit cleaning in the experiment. No object
  arrays/pickle, structured dtypes, extra metadata, or extra archive members.
  Stored and expanded archive sizes are each limited to 32 MiB. NPY version 1/2
  headers, shapes, and payload sizes are checked **before** NumPy allocation.
- The executor creates a fresh sanitized NPZ snapshot. Only that snapshot is
  mounted read-only at `/input/lightcurve.npz`; the original path, adjacent
  files, credentials, source tree, and campaign state are never mounted.
- `output_dir`: an operator-selected staging directory. It is **not** mounted in
  the container. A private temporary subdirectory contains the two bounded
  input files and is removed when execution finishes. Paths containing commas
  are rejected because commas are Docker mount-option separators.
- The code must print exactly one JSON **object** to stdout. Diagnostics may go
  to stderr. NaN, Infinity, overflowing numeric literals, malformed JSON, and
  non-object results are rejected. stdout and stderr share a 65,536-byte cap,
  drained incrementally through selectors, never spooled to an unbounded file.
  Exceeding the cap terminates the experiment, not merely truncates a success.
- `/tmp` may hold ephemeral intermediate files. **No output files are imported**;
  `artifacts` is always empty. A symlink created inside the container therefore
  cannot cause a host artifact read or write. Return small numeric summaries
  through stdout instead of writing figures or large arrays.

Example standalone code supplied to the API:

```python
import json
import numpy as np

with np.load('/input/lightcurve.npz', allow_pickle=False) as data:
    median = float(np.nanmedian(data['flux']))
print(json.dumps({'median_flux': median}, allow_nan=False))
```

The response shape is:

```text
{
  "status": "success | invalid_input | execution_error | timeout | output_limit | invalid_output | cleanup_error",
  "result": <parsed object on success, otherwise null>,
  "stdout": <bounded text>,
  "stderr": <bounded text>,
  "returncode": <Docker-attached process exit code, or null>,
  "cleanup_confirmed": <true/false after a Docker attempt, otherwise null>,
  "exploration_only": true,
  "artifacts": []
}
```

`execution_error` covers nonzero Python exits and Docker/image startup failures.
An absent image is never pulled automatically. The exit code following forced
termination is diagnostic only. `cleanup_error` means container removal could
not be confirmed; treat it as an operational fault and never accept its result.
Timeouts in execution, creation, or cleanup always retain status `timeout`; check
`cleanup_confirmed` as well. A false cleanup flag requires operator attention,
even when the original failure was a timeout.
Host staging filesystem failures can raise `OSError`; callers should handle
infrastructure failures without converting them to scientific success.

## Isolation

- Fixed local daemon `/var/run/docker.sock` used **only by the host launcher**;
  never mounted inside the experiment. Host Docker contexts and environment are
  not inherited; the client uses an empty private configuration location.
- UID/GID `65534:65534`, read-only root filesystem, all capabilities dropped,
  `no-new-privileges`, Docker's default seccomp profile, no privileged mode.
- `--network none`, no host network/PID/IPC namespace; IPC disabled.
- Memory 512 MiB with no additional swap, one CPU, 64 processes, 128 open-file
  limit, no core dumps, and one-thread numerical library settings.
- `/tmp` is a 64 MiB capped `noexec,nosuid,nodev` tmpfs.
- Exactly two explicit absolute read-only file mounts: sanitized NPZ and
  `/work/experiment.py`. No writable host mount, Docker socket, host environment
  secrets, or repository mounts.
- Logging driver `none`; bounded live stdout/stderr are the only result channel.
- Create a unique `rediscover-research-<UUID>` container, then attach/start it.
  In `finally`, forcibly remove exactly that name and read back an exact-name
  container listing to confirm absence. Killing the Docker client alone is not
  considered cleanup. This also handles an interrupted create acknowledgement.
  No global prune, stop, or deletion of other applications is performed.

This is defense in depth, not a virtual machine boundary. Containers share the
host kernel: keep Docker/kernel patched and use a dedicated VM for hostile
multi-tenant workloads. A killed host launcher, unavailable daemon, or machine
failure can prevent cleanup; operators should inspect UUID-named research
containers after such incidents. The local image and host operator are trusted;
protect the fixed tag from replacement. Build-time downloads require network,
but runtime does not. Base-image and transitive dependency digests are not
locked by this Dockerfile; record the built image ID for deployment provenance.

## Authorized VM build and verification

Run these commands **only on the authorized Azure VM**, in
`/home/hackyard/builds/rediscover-tess`, not on the local workstation:

```sh
# Stdin Dockerfile supplies no repository build context or secrets.
docker build --network default --memory 768m --cpu-quota 100000 \
  --tag rediscover-research:0.2.0 - < docker/research.Dockerfile

PYTHONPATH=src .venv/bin/python3.12 -m pytest tests/test_sandbox.py -q
.venv/bin/python3.12 -m ruff check src/rediscover/sandbox.py tests/test_sandbox.py

docker image inspect rediscover-research:0.2.0 --format '{{.Id}}'
docker container ls --all --filter name=rediscover-research-
```

The tests require real local Docker and the prebuilt image; they do not silently
skip missing infrastructure. They exercise a SciPy fit with NumPy input and an
Astropy import, read-only input/code/root filesystems, absent secrets/socket,
non-root identity, outbound-network failure, actual cgroup/privilege limits,
timeout including child processes, stdout/stderr overflow, nonzero exit status,
strict result parsing, NPZ validation, and container cleanup. The create-timeout
race test injects a lost acknowledgement **after real Docker creation**; cleanup
still runs against the real daemon. Other execution tests use real containers.
