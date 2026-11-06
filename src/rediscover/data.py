"""Bounded, provenance-preserving access to the official GWOSC API."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import h5py
import httpx
import numpy as np

API = "https://gwosc.org/api/v2"
HOSTS = {"gwosc.org", "www.gwosc.org", "www.gw-openscience.org", "gw-openscience.org"}
MAX_DOWNLOAD = 16 * 1024 * 1024


def validate_event(event: str) -> str:
    if not re.fullmatch(r"GW\d{6}(?:_\d{6})?(?:-v\d{1,3})?", event):
        raise ValueError("Use a GWOSC event name such as GW150914 or GW150914-v3")
    return event


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise ValueError("Only official HTTPS GWOSC download URLs are permitted")
    return url


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_bytes(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    """Validate every redirect before requesting it; never fetch arbitrary hosts."""
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for _ in range(6):
            validate_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                result = bytearray()
                for chunk in response.iter_bytes():
                    result.extend(chunk)
                    if len(result) > limit:
                        raise ValueError("GWOSC response exceeds the download budget")
                return bytes(result)
    raise ValueError("Too many GWOSC redirects")


def get_json(url: str) -> dict:
    value = json.loads(get_bytes(url, limit=4 * 1024 * 1024))
    if not isinstance(value, dict):
        raise ValueError("Unexpected GWOSC response schema")
    return value


def list_events(page: int = 1) -> dict:
    if not 1 <= page <= 1000:
        raise ValueError("Page must be between 1 and 1000")
    result = get_json(f"{API}/events?format=json&page={page}")
    return {"events": [{"name": e["name"], "versions": e["versions"]}
                       for e in result["results"]],
            "page": result["page_number"], "has_more": bool(result["next"]),
            "total": result["results_count"], "source": f"{API}/events"}


def event_files(event: str) -> tuple[dict, list[dict]]:
    """Use latest event version with 32-second public H1/L1 strain; record version."""
    validate_event(event)
    if "-v" in event:
        urls = [f"{API}/event-versions/{event}?format=json"]
    else:
        info = get_json(f"{API}/events/{event}?format=json")
        versions = sorted(info["versions"], key=lambda v: v["version"], reverse=True)
        urls = [v["detail_url"] for v in versions]
    for url in urls:
        detail = get_json(url)
        strain_url = detail["strain_files_url"].split("?")[0]
        files = get_json(strain_url + "?format=json&sample-rate=4&duration=32&file-format=hdf5")
        rows = [r for r in files["results"]
                if r["duration"] == 32 and r["sample_rate_kHz"] == 4
                and r["detector"] in ("H1", "L1")
                and r["file_format"].lower() in ("hdf", "hdf5")]
        if {r["detector"] for r in rows} == {"H1", "L1"}:
            detail["source_url"] = url
            return detail, rows
    raise ValueError("This release requires 32-second, 4-kHz H1 and L1 public strain files")


def download(url: str, destination: Path) -> str:
    validate_url(url)
    digest_file = destination.with_suffix(".sha256")
    if destination.is_symlink() or digest_file.is_symlink():
        raise ValueError("Symlink cache artifacts are not permitted")
    if destination.exists():
        if not digest_file.exists() or sha256(destination) != digest_file.read_text().strip():
            raise ValueError("Cached file checksum mismatch; remove the corrupt cache entry")
        return sha256(destination)
    data = get_bytes(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".download-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        # Parse before accepting a downloaded artifact into the cache.
        read_strain(Path(name))
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    digest = sha256(destination)
    digest_file.write_text(digest + "\n")
    return digest


def read_strain(path: Path) -> dict:
    with h5py.File(path, "r") as f:
        ds = f["strain/Strain"]
        if ds.ndim != 1 or len(ds) > 4096 * 64:
            raise ValueError("Expected a short one-dimensional strain series")
        strain = np.asarray(ds[:], dtype=np.float64)
        if not np.isfinite(strain).all():
            raise ValueError("Strain must contain only finite samples")
        spacing = float(ds.attrs["Xspacing"])
        start = float(ds.attrs["Xstart"])
        if not np.isfinite([spacing, start]).all() or spacing <= 0:
            raise ValueError("Invalid strain sampling metadata")
        quality = {"available": "quality/simple/DQmask" in f,
                   "all_data_present": None, "all_cbc_category1": None,
                   "injection_metadata_available": "quality/injections/Injmask" in f}
        if quality["available"]:
            mask = np.asarray(f["quality/simple/DQmask"][:], dtype=int)
            quality["all_data_present"] = bool(len(mask) and np.all(mask & 1))
            # DATA bit is universal; report other bits with their published labels.
            if "quality/simple/DQShortnames" in f:
                names = [x.decode() if isinstance(x, bytes) else str(x)
                         for x in f["quality/simple/DQShortnames"][:]]
                quality["bits"] = {name: bool(np.all(mask & (1 << i)))
                                   for i, name in enumerate(names)}
                quality["all_cbc_category1"] = quality["bits"].get("CBC_CAT1")
        if quality["injection_metadata_available"]:
            mask = np.asarray(f["quality/injections/Injmask"][:], dtype=int)
            if "quality/injections/InjShortnames" in f:
                names = [x.decode() if isinstance(x, bytes) else str(x)
                         for x in f["quality/injections/InjShortnames"][:]]
                quality["injection_bits"] = {name: bool(np.all(mask & (1 << i)))
                                             for i, name in enumerate(names)}
    return {"strain": strain, "sample_rate": 1 / spacing, "gps_start": start,
            "data_quality": quality}


def fetch_event(event: str, cache: Path) -> tuple[dict, dict]:
    detail, files = event_files(event)
    name, version = detail.get("name"), detail.get("version")
    if not isinstance(name, str):
        raise ValueError("Invalid upstream event name")
    validate_event(name)
    if "-v" in name or type(version) is not int or not 1 <= version <= 999:
        raise ValueError("Invalid upstream event version")
    cache = cache.resolve()
    datasets = {}
    for row in files:
        detector = row["detector"]
        if detector not in {"H1", "L1"}:
            raise ValueError("Unexpected upstream detector")
        path = cache / f"{name}-v{version}-{detector}.hdf5"
        if path.is_symlink() or not path.resolve().is_relative_to(cache):
            raise ValueError("Cache artifact escaped its root")
        digest = download(row["download_url"], path)
        data = read_strain(path)
        data["source"] = {"url": row["download_url"], "sha256": digest,
                          "duration": row["duration"], "detector": detector}
        datasets[detector] = data
    return detail, datasets


def catalog_parameters(detail: dict) -> dict:
    url = detail["parameters_url"]
    raw = get_json(url)
    return {"source_url": url, "sets": raw["results"],
            "warning": "Catalog inference differs from this finite nonspinning template search. "
                       "Source-frame masses must not be compared directly to detector-frame masses."}
