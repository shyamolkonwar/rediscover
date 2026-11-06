"""Bounded public TESS observations and dated catalog/literature snapshots."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
import numpy as np
from astropy.io import fits
from filelock import FileLock

HOSTS = {"mast.stsci.edu", "stpubdata.s3.us-east-1.amazonaws.com",
         "stpubdata.s3.amazonaws.com", "exoplanetarchive.ipac.caltech.edu",
         "api.crossref.org"}
MAX_FITS = 8 * 1024 * 1024


def check_tic(value: str | int) -> str:
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,11}", text):
        raise ValueError("TIC must be a positive numeric catalog identifier")
    return text


def check_uri(uri: str) -> str:
    if not re.fullmatch(r"mast:TESS/product/tess[0-9]{13}-s[0-9]{4}-[0-9]{16}-[0-9]{4}-s_lc\.fits", uri):
        raise ValueError("Only canonical SPOC light-curve FITS products are supported")
    return uri


def validate_space_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in HOSTS or p.port not in (None, 443) or p.username or p.password:
        raise ValueError("Only approved public astronomy HTTPS endpoints are permitted")
    return url


def space_bytes(url: str, limit: int = MAX_FITS) -> bytes:
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for _ in range(6):
            validate_space_url(url)
            with client.stream("GET", url, headers={"User-Agent": "Rediscover/0.2 scientific research"}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                output = bytearray()
                for part in response.iter_bytes():
                    output.extend(part)
                    if len(output) > limit:
                        raise ValueError("Astronomy response exceeds byte budget")
                return bytes(output)
    raise ValueError("Too many astronomy download redirects")


def space_json(url: str):
    return json.loads(space_bytes(url, limit=4 * 1024 * 1024))


def _observation(row) -> dict:
    tic = check_tic(str(row["target_name"]))
    uri = check_uri(str(row["dataURL"]))
    sector = int(row["sequence_number"])
    if not 1 <= sector <= 200:
        raise ValueError("Sector outside supported range")
    return {"tic": tic, "sector": sector, "uri": uri, "obs_id": str(row["obs_id"]),
            "exposure_seconds": float(row["t_exptime"]),
            "ra_deg": float(row["s_ra"]), "dec_deg": float(row["s_dec"])}


def observation(tic: str, sector: int) -> dict:
    from astroquery.mast import Observations
    check_tic(tic)
    if not 1 <= sector <= 200:
        raise ValueError("Invalid sector")
    Observations.TIMEOUT = 45
    table = Observations.query_criteria(obs_collection="TESS", provenance_name="SPOC",
        target_name=str(tic), dataproduct_type="timeseries", sequence_number=sector,
        pagesize=100, page=1)
    rows = [_observation(r) for r in table if float(r["t_exptime"]) == 120]
    if not rows:
        raise ValueError(f"No 120-second SPOC light curve for TIC {tic}, sector {sector}")
    return sorted(rows, key=lambda r: r["obs_id"])[-1]


def discover_cohort(discovery_sector: int = 1, validation_sector: int = 4,
                    limit: int = 12, page_size: int = 1000) -> dict:
    """Metadata-only selection. Does not download either sector's flux."""
    from astroquery.mast import Observations
    if not (1 <= discovery_sector <= 200 and 1 <= validation_sector <= 200
            and discovery_sector != validation_sector and 1 <= limit <= 50
            and 50 <= page_size <= 2000):
        raise ValueError("Invalid sector/cohort budget")
    Observations.TIMEOUT = 45
    catalogs = []
    for sector in (discovery_sector, validation_sector):
        table = Observations.query_criteria(obs_collection="TESS", provenance_name="SPOC",
            dataproduct_type="timeseries", sequence_number=sector, pagesize=page_size, page=1)
        rows = {}
        for raw in table:
            if float(raw["t_exptime"]) != 120:
                continue
            try:
                row = _observation(raw)
                rows[row["tic"]] = row
            except ValueError:
                continue
        catalogs.append(rows)
    common = sorted(set(catalogs[0]) & set(catalogs[1]), key=int)
    selected = common[:limit]
    if len(selected) < limit:
        raise ValueError(f"Metadata page intersection contains only {len(selected)} eligible targets; lower limit explicitly")
    return {"selected_at": datetime.now(timezone.utc).isoformat(),
            "selection": "First archive page per sector, intersection, numeric TIC sort, first requested count. Metadata only; not population-representative.",
            "discovery_sector": discovery_sector, "validation_sector": validation_sector,
            "page_size": page_size, "pages_per_sector": 1,
            "metadata_counts": [len(c) for c in catalogs], "intersection_count": len(common),
            "targets": [{"tic": tic, "discovery": catalogs[0][tic], "validation": catalogs[1][tic]}
                        for tic in selected]}


def read_lightcurve(path: Path, expected_tic: int | str, expected_sector: int) -> dict:
    with fits.open(path, memmap=False) as hdul:
        header, ext = hdul[0].header, hdul[1]
        if str(header.get("TICID")) != str(expected_tic) or header.get("SECTOR") != expected_sector:
            raise ValueError("FITS identity does not match frozen observation")
        if header.get("TELESCOP") != "TESS":
            raise ValueError("Expected a TESS light curve")
        reference = float(ext.header.get("BJDREFI", 0)) + float(ext.header.get("BJDREFF", 0))
        if (reference != 2457000 or ext.header.get("TIMESYS") != "TDB"
                or ext.header.get("TIMEUNIT") not in ("d", "day")):
            raise ValueError("Unsupported time basis; require BTJD in TDB days")
        if not 1 <= len(ext.data) <= 50000:
            raise ValueError("Light curve exceeds row budget")
        values = ext.data
        time = np.array(values["TIME"], dtype=float)
        flux = np.array(values["PDCSAP_FLUX"], dtype=float)
        error = np.array(values["PDCSAP_FLUX_ERR"], dtype=float)
        good = np.isfinite(time) & np.isfinite(flux) & np.isfinite(error) & (error > 0) & (values["QUALITY"] == 0)
        if not good.any() or np.median(flux[good]) <= 0:
            raise ValueError("No valid positive-flux observations")
        norm = float(np.median(flux[good]))
        arrays = {"time": time[good], "flux": flux[good] / norm, "flux_err": error[good] / norm}
        for column, name in [("SAP_FLUX", "sap_flux"), ("MOM_CENTR1", "centroid_x"), ("MOM_CENTR2", "centroid_y")]:
            if column in values.names:
                data = np.array(values[column], dtype=float)[good]
                if name == "sap_flux" and np.isfinite(data).any() and np.nanmedian(data) > 0:
                    data = data / np.nanmedian(data)
                arrays[name] = data
        metadata = {"tic": str(expected_tic), "sector": expected_sector, "time_system": "BTJD_TDB",
                    "bjd_reference": reference, "raw_rows": len(time), "valid_rows": int(good.sum()),
                    "removed_rows": int((~good).sum()), "quality_policy": "QUALITY == 0; finite time/flux; finite positive error",
                    "crowding": float(ext.header["CROWDSAP"]) if "CROWDSAP" in ext.header else None,
                    "flux_fraction": float(ext.header["FLFRCSAP"]) if "FLFRCSAP" in ext.header else None}
    return {**arrays, "metadata": metadata}


def download_observation(obs: dict, cache: Path) -> dict:
    tic = check_tic(obs["tic"])
    uri = check_uri(obs["uri"])
    sector = int(obs["sector"])
    if not 1 <= sector <= 200:
        raise ValueError("Invalid sector")
    cache = cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    basename = hashlib.sha256(uri.encode()).hexdigest() + ".fits"
    dest = cache / basename
    checksum = dest.with_suffix(".sha256")
    if dest.is_symlink() or checksum.is_symlink() or not dest.resolve().is_relative_to(cache):
        raise ValueError("Cache path escaped root")
    url = "https://mast.stsci.edu/api/v0.1/Download/file?" + urlencode({"uri": uri})
    with FileLock(str(dest) + ".lock", timeout=90):
        if dest.exists():
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            if not checksum.exists() or checksum.read_text().strip() != digest:
                raise ValueError("Cached FITS checksum mismatch")
        else:
            payload = space_bytes(url)
            fd, temporary = tempfile.mkstemp(dir=cache, prefix=".tess-")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(payload)
                read_lightcurve(Path(temporary), tic, sector)
                os.replace(temporary, dest)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            digest = hashlib.sha256(payload).hexdigest()
            checksum.write_text(digest + "\n")
    result = read_lightcurve(dest, tic, sector)
    result["metadata"]["source"] = {"url": url, "uri": uri, "sha256": digest,
                                        "retrieved_at": datetime.now(timezone.utc).isoformat()}
    return result


def catalog_check(tic: str, period_days: float) -> dict:
    check_tic(tic)
    if not np.isfinite(period_days) or period_days <= 0:
        raise ValueError("Invalid period")
    queries = {
        "toi": f"select top 100 toi,tid,tfopwg_disp,pl_orbper from toi where tid={tic}",
        "confirmed": f"select top 100 pl_name,tic_id,pl_orbper from pscomppars where tic_id='TIC {tic}'"}
    snapshots = {}
    for name, query in queries.items():
        url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?" + urlencode({"query": query, "format": "json"})
        try:
            rows = space_json(url)
            if not isinstance(rows, list) or len(rows) >= 100:
                raise ValueError("Incomplete or invalid catalog response")
            matches = []
            for row in rows:
                p = row.get("pl_orbper")
                if isinstance(p, (int, float)) and p > 0:
                    aliases = [factor for factor in (0.5, 1.0, 2.0)
                               if abs(period_days / (p * factor) - 1) < 0.02]
                    if aliases:
                        matches.append({"row": row, "period_multipliers": aliases})
            snapshots[name] = {"source_url": url, "rows": rows, "period_matches": matches,
                               "retrieved_at": datetime.now(timezone.utc).isoformat(), "complete": True}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            snapshots[name] = {"source_url": url, "complete": False, "error": type(exc).__name__}
    complete = all(s["complete"] for s in snapshots.values())
    known = any(s.get("period_matches") for s in snapshots.values())
    return {"complete": complete, "status": "known_period_match" if known else "no_catalog_period_match" if complete else "unavailable",
            "snapshots": snapshots, "known_match": known,
            "limitations": ["TIC and 0.5/1/2 period matches in two NASA tables only; not exhaustive novelty clearance.",
                            "A TOI may be a candidate or false positive, not a confirmed planet."]}


def literature_check(tic: str) -> dict:
    """Record a bounded scholarly metadata search; never calls an empty result clearance."""
    tic = check_tic(tic)
    url = "https://api.crossref.org/works?" + urlencode({"query": f'"TIC {tic}"', "rows": 10})
    try:
        result = space_json(url)
        records = [{"title": item.get("title", []), "doi": item.get("DOI"), "url": item.get("URL")}
                   for item in result["message"]["items"]]
        return {"status": "metadata_search_completed", "source_url": url, "records": records,
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "review_complete": False,
                "limitation": "Relevance-ranked metadata, not full-text coverage. Human literature/ExoFOP review remains required."}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "source_url": url, "error": type(exc).__name__, "review_complete": False}
