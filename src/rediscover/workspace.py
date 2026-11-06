"""Run storage and independently checkable artifact checksums.

Checksums detect accidental edits, not a malicious owner who can rewrite the manifest.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from .data import sha256


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


class Workspace:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or os.environ.get("REDISCOVER_HOME", "~/.rediscover")).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("Invalid run ID")
        p = self.root / "runs" / run_id
        if not p.resolve().is_relative_to(self.root) or p.is_symlink():
            raise ValueError("Run path escaped workspace")
        return p

    def file(self, run_id: str, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(json|npz|png|html|md|wav)", name):
            raise ValueError("Invalid artifact name")
        root = self.path(run_id)
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError("Artifact path escaped workspace")
        return p

    def create(self, inputs: dict) -> str:
        # Validate before allocating a directory.
        dump(inputs)
        run_id = uuid.uuid4().hex
        self.path(run_id).mkdir(parents=True)
        self.save(run_id, "input.json", inputs)
        versions = {}
        for name in ["numpy", "scipy", "pycbc", "gwpy", "mcp", "rediscover-physics"]:
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "source-checkout"
        self.save(run_id, "environment.json", {"python": platform.python_version(),
                   "platform": platform.system(), "versions": versions, "created_at": now()})
        return run_id

    def save(self, run_id: str, name: str, value: dict) -> None:
        content = dump(value)
        with self.lock:
            with self.file(run_id, name).open("x") as stream:
                stream.write(content)
            self.seal(run_id, name)

    def seal(self, run_id: str, name: str) -> None:
        manifest_path = self.file(run_id, "manifest.json")
        with self.lock, FileLock(str(manifest_path) + ".lock", timeout=30):
            p = self.file(run_id, name)
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            if name in manifest:
                if manifest[name] != sha256(p):
                    raise ValueError("Attempted to replace a sealed artifact")
                return
            manifest[name] = sha256(p)
            fd, temporary = tempfile.mkstemp(dir=manifest_path.parent, prefix=".manifest-")
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(dump(manifest))
                os.replace(temporary, manifest_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def read(self, run_id: str, name: str) -> dict:
        manifest = json.loads(self.file(run_id, "manifest.json").read_text())
        p = self.file(run_id, name)
        if name not in manifest or manifest[name] != sha256(p):
            raise ValueError(f"Artifact checksum mismatch: {name}")
        return json.loads(p.read_text())

    def record(self, run_id: str, tool: str, arguments: dict, result: dict) -> dict:
        evidence_id = "e-" + uuid.uuid4().hex[:16]
        value = {"evidence_id": evidence_id, "tool": tool, "arguments": arguments,
                 "result": result, "recorded_at": now()}
        self.save(run_id, evidence_id + ".json", value)
        return value

    def evidence(self, run_id: str) -> list[dict]:
        manifest = json.loads(self.file(run_id, "manifest.json").read_text())
        return [self.read(run_id, name) for name in sorted(manifest)
                if name.startswith("e-") and name.endswith(".json")]

    def verify(self, run_id: str) -> dict:
        manifest = json.loads(self.file(run_id, "manifest.json").read_text())
        failed = []
        for name, expected in manifest.items():
            p = self.file(run_id, name)
            if not p.exists() or sha256(p) != expected:
                failed.append(name)
        return {"valid": not failed, "checked": len(manifest), "failed": failed,
                "scope": "Artifact integrity, not proof of scientific correctness or authorship"}
