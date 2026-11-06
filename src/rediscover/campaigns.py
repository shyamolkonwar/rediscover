"""Frozen, one-shot discovery campaigns with a verifier independent of the model."""
from __future__ import annotations

import hashlib
import math
import time
import uuid
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
from filelock import FileLock

from .tess_data import catalog_check, check_tic, check_uri, download_observation, literature_check
from .workspace import Workspace, dump, now

DEFAULT_CONFIG = {"period_min": 1.0, "period_max": 10.0, "durations_days": [0.05, 0.1, 0.15],
    "detrend_window_days": 1.5, "period_grid_size": 10000, "min_transits": 3,
    "snr_threshold": 8.0, "alternate_window_days": 2.0, "null_repeats": 64,
    "search_schedule_seconds": 3600, "max_code_experiments": 3, "seed": 42}


def validate_config(config: dict | None) -> dict:
    c = {**DEFAULT_CONFIG, **(config or {})}
    if set(c) != set(DEFAULT_CONFIG):
        raise ValueError("Unknown campaign configuration field")
    numeric = [c[k] for k in c if k != "durations_days"]
    if not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in numeric):
        raise ValueError("Configuration must contain finite numeric values")
    if not (0.5 <= c["period_min"] < c["period_max"] <= 15 and
            500 <= c["period_grid_size"] <= 20000 and isinstance(c["period_grid_size"], int) and
            1 <= c["detrend_window_days"] <= 4 and 1 <= c["alternate_window_days"] <= 4 and
            16 <= c["null_repeats"] <= 1024 and isinstance(c["null_repeats"], int) and
            60 <= c["search_schedule_seconds"] <= 14400 and 0 <= c["max_code_experiments"] <= 5 and
            c["min_transits"] == 3 and c["snr_threshold"] == 8):
        raise ValueError("Configuration outside frozen campaign safety/science bounds")
    ds = c["durations_days"]
    if not isinstance(ds, list) or not 1 <= len(ds) <= 6 or not all(isinstance(d, (float, int)) and 0.02 <= d <= 0.25 and d <= c["period_min"] / 5 for d in ds):
        raise ValueError("Invalid transit durations")
    if c["alternate_window_days"] == c["detrend_window_days"]:
        raise ValueError("Robustness check requires two distinct detrending windows")
    if type(c["max_code_experiments"]) is not int or type(c["seed"]) is not int or not 0 <= c["seed"] < 2**32:
        raise ValueError("Code quota must be integer; seed must be uint32")
    if c["period_grid_size"] * len(set(ds)) * (c["null_repeats"] + 1) > 40000000:
        raise ValueError("Combined null calibration work exceeds numerical core budget")
    return c


def numerical_config(c: dict, alternate: bool = False) -> dict:
    return {k: (c["alternate_window_days"] if k == "detrend_window_days" and alternate else c[k])
            for k in ("period_min", "period_max", "durations_days", "detrend_window_days",
                      "period_grid_size", "min_transits", "snr_threshold")}


def primary_candidate(result: dict) -> dict:
    value = result.get("candidate")
    return value if isinstance(value, dict) else {}


def has_repeating_signal(candidate: dict) -> bool:
    snr = candidate.get("depth_snr")
    n = candidate.get("n_well_sampled_transits", candidate.get("n_transits", 0))
    return isinstance(snr, (int, float)) and math.isfinite(snr) and snr >= 8 and n >= 3


def auxiliary_checks(data: dict, candidate: dict) -> dict:
    """Conservative warnings, not an on-target transit validation substitute."""
    metadata = data["metadata"]
    crowding = metadata.get("crowding")
    usable = crowding is not None and crowding >= 0.9
    output = {"usable": usable, "crowding": crowding, "pixel_level_vetting_complete": False,
              "limitation": "Crowding and aperture moments cannot exclude all blended eclipsing binaries."}
    if not candidate or not all(k in data for k in ("centroid_x", "centroid_y")):
        return {**output, "usable": False, "centroid_status": "unavailable"}
    t = data["time"]
    p, epoch, duration = (candidate[k] for k in ("period_days", "epoch_btjd", "duration_days"))
    phase = (t - epoch + p / 2) % p - p / 2
    inside = np.abs(phase) < duration / 2
    nearby = (np.abs(phase) > duration) & (np.abs(phase) < 3 * duration)
    sigmas = []
    for key in ("centroid_x", "centroid_y"):
        x = data[key]
        a, b = x[inside & np.isfinite(x)], x[nearby & np.isfinite(x)]
        if len(a) < 5 or len(b) < 10:
            return {**output, "usable": False, "centroid_status": "insufficient_samples"}
        noise = 1.4826 * np.median(np.abs(b - np.median(b)))
        error = noise * np.sqrt(1 / len(a) + 1 / len(b))
        sigmas.append(float(abs(np.median(a) - np.median(b)) / error) if error > 0 else None)
    output.update({"centroid_status": "approximate_aperture_moment_test", "shift_sigma_xy": sigmas,
                   "usable": usable and all(s is not None and s < 5 for s in sigmas)})
    return output


def classify(row: dict, family_size: int) -> dict:
    reasons = []
    search = row.get("search", {})
    candidate = search.get("candidate", {})
    if search.get("error"):
        return {"status": "UNRESOLVED", "reasons": ["search_failed"]}
    if not has_repeating_signal(candidate):
        return {"status": "REJECTED", "reasons": ["no_adequate_repeating_signal"],
                "meaning": "No retained candidate in the searched range; not proof the star has no planets."}
    if candidate.get("candidate_flag") is False:
        return {"status": "REJECTED", "reasons": candidate.get("flags", ["failed_discovery_screen"])}
    validation = row.get("validation", {})
    if (validation.get("error") or validation.get("status") in ("unavailable", "insufficient_coverage")
            or "insufficient_observed_transits" in validation.get("flags", [])):
        reasons.append("independent_data_unavailable_or_insufficient")
    elif validation.get("passed") is False:
        return {"status": "REJECTED", "reasons": ["failed_independent_observation_test"]}
    elif not validation.get("passed"):
        reasons.append("independent_test_incomplete")
    catalog = row.get("catalog", {})
    if catalog.get("known_match") and validation.get("passed"):
        return {"status": "KNOWN_SIGNAL_RECOVERED", "reasons": ["catalog_period_or_alias_match"],
                "meaning": "Known catalogued signal; inspect catalog disposition, which may be a false positive."}
    if not catalog.get("complete"):
        reasons.append("catalog_unavailable")
    if not search.get("stable"):
        reasons.append("not_stable_across_predeclared_detrending")
    if candidate.get("odd_even_sigma", 0) is None or candidate.get("secondary_snr", 0) is None:
        reasons.append("binary_vetting_incomplete")
    elif candidate.get("odd_even_sigma", 0) >= 5 or candidate.get("secondary_snr", 0) >= 5:
        reasons.append("eclipsing_binary_or_secondary_warning")
    if not row.get("auxiliary", {}).get("usable"):
        reasons.append("contamination_or_centroid_checks_unresolved")
    calibration = row.get("calibration", {})
    p = calibration.get("empirical_p")
    if p is None or p > 0.05 / max(1, family_size):
        reasons.append("surrogate_calibration_or_search_multiplicity_unresolved")
    return {"status": "UNRESOLVED" if reasons else "POTENTIALLY_UNCATALOGUED_CANDIDATE",
            "reasons": reasons or ["survived_bounded_checks_no_catalog_period_match"],
            "remaining": ["Independent expert review", "Full literature and ExoFOP review",
                          "Pixel-level blend validation and follow-up as needed"],
            "claim": "Never a confirmed planet or guaranteed novel discovery."}


class Campaigns:
    def __init__(self, root: str | Path | None = None):
        self.workspace = Workspace(root)

    def create(self, cohort: dict, config: dict | None = None, objective: str = "Search for repeating transit-like signals not matched to known catalogs", proposal: dict | None = None) -> dict:
        c = validate_config(config)
        targets = cohort.get("targets", [])
        if not 1 <= len(targets) <= 50 or len(objective) > 2000:
            raise ValueError("Campaign needs 1–50 targets and a bounded objective")
        seen = set()
        for target in targets:
            tic = check_tic(target["tic"])
            if tic in seen:
                raise ValueError("Duplicate TIC in frozen cohort")
            seen.add(tic)
            for role in ("discovery", "validation"):
                obs = target[role]
                check_uri(obs["uri"])
                if str(obs["tic"]) != tic or type(obs["sector"]) is not int or not 1 <= obs["sector"] <= 200:
                    raise ValueError("Observation identity mismatch")
            if target["discovery"]["sector"] == target["validation"]["sector"]:
                raise ValueError("Discovery and holdout sectors must differ")
        implementation = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("campaigns.py", "transit.py", "tess_data.py", "research_agent.py")}
        plan = {"kind": "tess_campaign", "schema_version": 1, "created_at": now(),
                "implementation_sha256": implementation,
                "objective": objective, "cohort": cohort, "config": c, "proposal": proposal,
                "search_family_size": len(targets) * 2,
                "rules": {"holdout": "one-shot fixed-ephemeris evaluation after freeze",
                    "novelty": "No catalog match is not exhaustive novelty clearance",
                    "significance": "Surrogate p-values depend on the null model; no validated astrophysical FAP"}}
        cid = self.workspace.create({"kind": "tess_campaign"})
        self.workspace.save(cid, "plan.json", plan)
        return {"campaign_id": cid, "state": "planned", "targets": len(targets),
                "plan_sha256": hashlib.sha256(dump(plan).encode()).hexdigest()}

    def _has(self, cid: str, name: str) -> bool:
        path = self.workspace.file(cid, name)
        if path.exists():
            self.workspace.read(cid, name)
            return True
        return False

    def plan(self, cid: str) -> dict:
        plan = self.workspace.read(cid, "plan.json")
        if plan.get("kind") != "tess_campaign":
            raise ValueError("Not a TESS campaign")
        return plan

    def _lock(self, cid: str):
        return FileLock(str(self.workspace.path(cid) / ".campaign.lock"), timeout=5)

    def status(self, cid: str) -> dict:
        plan = self.plan(cid)
        state = "planned"
        for name, label in [("search.json", "searched"), ("hypotheses.json", "hypotheses_frozen"),
                            ("validation-claim.json", "holdout_consumed"), ("validation.json", "validated"),
                            ("review.json", "reviewed"), ("verdict.json", "complete")]:
            if self._has(cid, name):
                state = label
        return {"campaign_id": cid, "state": state, "targets": len(plan["cohort"]["targets"]),
                "objective": plan["objective"]}

    def _store_data(self, cid: str, tic: str, role: str, obs: dict) -> dict:
        name = f"{role}-{tic}"
        if self._has(cid, name + ".json"):
            return self._load_data(cid, tic, role)
        value = download_observation(obs, self.workspace.root / "tess-cache")
        np.savez_compressed(self.workspace.file(cid, name + ".npz"), **{k: v for k, v in value.items() if k != "metadata"})
        self.workspace.seal(cid, name + ".npz")
        self.workspace.save(cid, name + ".json", value["metadata"])
        return value

    def _load_data(self, cid: str, tic: str, role: str = "d") -> dict:
        check_tic(tic)
        if role not in {"d", "v"}:
            raise ValueError("Invalid observation role")
        if not self.workspace.verify(cid)["valid"]:
            raise ValueError("Campaign artifact checksum failed")
        metadata = self.workspace.read(cid, f"{role}-{tic}.json")
        with np.load(self.workspace.file(cid, f"{role}-{tic}.npz"), allow_pickle=False) as f:
            arrays = {k: f[k] for k in f.files}
        return {**arrays, "metadata": metadata}

    def search(self, cid: str) -> dict:
        from .transit import search_transits
        with self._lock(cid):
            plan = self.plan(cid)
            if self._has(cid, "search.json"):
                return self.workspace.read(cid, "search.json")
            if self._has(cid, "hypotheses.json"):
                raise ValueError("Cannot search after hypotheses are frozen")
            started = time.monotonic()
            if not self._has(cid, "search-schedule.json"):
                # Legacy development plans used max_seconds for this same soft scheduling limit.
                budget = plan["config"].get("search_schedule_seconds", plan["config"].get("max_seconds", 3600))
                self.workspace.save(cid, "search-schedule.json", {"started_at": now(),
                    "deadline_unix": time.time() + budget, "scope": "soft_between_targets",
                    "contract": "Do not start another target after deadline; an in-progress target may overrun. Includes downtime on resume."})
            schedule = self.workspace.read(cid, "search-schedule.json")
            rows = []
            for target in plan["cohort"]["targets"]:
                tic = target["tic"]
                filename = f"search-{tic}.json"
                if self._has(cid, filename):
                    rows.append(self.workspace.read(cid, filename))
                    continue
                try:
                    if time.time() > schedule["deadline_unix"]:
                        raise ValueError("Soft search scheduling deadline exhausted; target not started")
                    data = self._store_data(cid, tic, "d", target["discovery"])
                    args = (data["time"], data["flux"], data["flux_err"])
                    primary = search_transits(*args, numerical_config(plan["config"]))
                    alternate = search_transits(*args, numerical_config(plan["config"], alternate=True))
                    a, b = primary_candidate(primary), primary_candidate(alternate)
                    stable = bool(a and b and abs(a["period_days"] / b["period_days"] - 1) < 0.02)
                    row = {"tic": tic, "candidate": a, "stable": stable, "primary": primary,
                           "alternate": alternate, "data": data["metadata"], "completed_at": now()}
                except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
                    row = {"tic": tic, "error": f"{type(exc).__name__}: {exc}", "completed_at": now()}
                self.workspace.save(cid, filename, row)
                rows.append(row)
            result = {"targets": rows, "total": len(rows), "failures": sum("error" in r for r in rows),
                      "elapsed_seconds": time.monotonic() - started}
            self.workspace.save(cid, "search.json", result)
            return result

    def freeze(self, cid: str) -> dict:
        with self._lock(cid):
            self.plan(cid)
            if self._has(cid, "hypotheses.json"):
                return self.workspace.read(cid, "hypotheses.json")
            if not self._has(cid, "search.json"):
                raise ValueError("Complete discovery search before freezing")
            results = self.workspace.read(cid, "search.json")
            hypotheses = []
            for row in results["targets"]:
                candidate = row.get("candidate", {})
                if has_repeating_signal(candidate):
                    hypotheses.append({"tic": row["tic"], "candidate": candidate,
                        "prediction": "The fixed period, epoch and duration predict dips in the reserved sector.",
                        "alternatives": ["Eclipsing binary", "Stellar variability", "Instrumental artifact", "Blended neighboring star"]})
            result = {"frozen_at": now(), "hypotheses": hypotheses,
                      "search_sha256": hashlib.sha256(dump(results).encode()).hexdigest()}
            self.workspace.save(cid, "hypotheses.json", result)
            return result

    def validate(self, cid: str) -> dict:
        with self._lock(cid):
            plan = self.plan(cid)
            if not self._has(cid, "hypotheses.json"):
                raise ValueError("Hypotheses must be frozen before holdout access")
            if self._has(cid, "validation.json"):
                return self.workspace.read(cid, "validation.json")
            if self._has(cid, "validation-claim.json"):
                raise ValueError("Holdout was already consumed; interrupted validation cannot be retuned or repeated")
            from .transit import validate_ephemeris
            frozen = self.workspace.read(cid, "hypotheses.json")
            self.workspace.save(cid, "validation-claim.json", {"consumed_at": now(),
                "hypotheses_sha256": hashlib.sha256(dump(frozen).encode()).hexdigest()})
            target_map = {t["tic"]: t for t in plan["cohort"]["targets"]}
            rows = []
            for hypothesis in frozen["hypotheses"]:
                tic = hypothesis["tic"]
                try:
                    data = self._store_data(cid, tic, "v", target_map[tic]["validation"])
                    result = validate_ephemeris(data["time"], data["flux"], data["flux_err"],
                                               hypothesis["candidate"], numerical_config(plan["config"]))
                    row = {"tic": tic, **result, "data": data["metadata"]}
                except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
                    row = {"tic": tic, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
                self.workspace.save(cid, f"validation-{tic}.json", row)
                rows.append(row)
            value = {"targets": rows, "total": len(rows), "one_shot": True, "completed_at": now()}
            self.workspace.save(cid, "validation.json", value)
            return value

    def review(self, cid: str) -> dict:
        from .transit import calibrate_null
        with self._lock(cid):
            plan = self.plan(cid)
            if self._has(cid, "review.json"):
                existing = self.workspace.read(cid, "review.json")
                self._finalize_review(cid, existing, plan)
                return existing
            if not self._has(cid, "validation.json"):
                raise ValueError("Independent validation must precede review")
            search = self.workspace.read(cid, "search.json")
            validation = {r["tic"]: r for r in self.workspace.read(cid, "validation.json")["targets"]}
            rows = []
            for result in search["targets"]:
                tic = result["tic"]
                candidate = result.get("candidate", {})
                row = {"tic": tic, "search": result, "validation": validation.get(tic, {})}
                if has_repeating_signal(candidate):
                    row["catalog"] = catalog_check(tic, candidate["period_days"])
                    data = self._load_data(cid, tic)
                    row["auxiliary"] = auxiliary_checks(data, candidate)
                    if row["validation"].get("passed") and not row["catalog"].get("known_match"):
                        row["literature"] = literature_check(tic)
                        try:
                            row["calibration"] = calibrate_null(data["time"], data["flux"], data["flux_err"],
                                numerical_config(plan["config"]), repeats=plan["config"]["null_repeats"], seed=plan["config"]["seed"])
                        except (ValueError, RuntimeError) as exc:
                            row["calibration"] = {"error": str(exc)}
                row["verdict"] = classify(row, plan["search_family_size"])
                rows.append(row)
            review = {"targets": rows, "completed_at": now()}
            self.workspace.save(cid, "review.json", review)
            self._finalize_review(cid, review, plan)
            return review

    def _finalize_review(self, cid: str, review: dict, plan: dict) -> dict:
        if self._has(cid, "verdict.json"):
            return self.workspace.read(cid, "verdict.json")
        rows = review["targets"]
        required = {t["tic"] for t in plan["cohort"]["targets"]}
        if len(rows) != len(required) or {r["tic"] for r in rows} != required:
            raise ValueError("Sealed review does not cover the entire frozen cohort")
        verdict = {"campaign_id": cid, "objective": plan["objective"], "total_targets": len(rows),
                       "counts": dict(Counter(r["verdict"]["status"] for r in rows)),
                       "confirmed_new_planets": 0,
                       "targets": [{"tic": r["tic"], **r["verdict"]} for r in rows],
                       "limitations": ["Bounded preliminary search; no automated discovery claim",
                           "Surrogate calibration is approximate and may lack multiplicity resolution",
                           "Catalog metadata and aperture moments are not exhaustive novelty/blend clearance"]}
        self.workspace.save(cid, "verdict.json", verdict)
        return verdict

    def run(self, cid: str) -> dict:
        self.search(cid)
        self.freeze(cid)
        self.validate(cid)
        self.review(cid)
        return self.workspace.read(cid, "verdict.json")

    def reserve_research(self, cid: str, count: int) -> list[str]:
        with self._lock(cid):
            plan = self.plan(cid)
            if self._has(cid, "hypotheses.json"):
                raise ValueError("Research reservations are closed after freeze")
            if not self._has(cid, "search.json"):
                raise ValueError("Complete discovery search before reserving experiments")
            legacy = sum(e["tool"] == "research_attempt" for e in self.workspace.evidence(cid))
            manifest = self.workspace.file(cid, "manifest.json")
            import json
            names = json.loads(manifest.read_text())
            reserved = sum(name.startswith("research-slot-") and "-consumed" not in name for name in names)
            if type(count) is not int or count < 1 or count > plan["config"]["max_code_experiments"] - legacy - reserved:
                raise ValueError("Requested batch exceeds remaining research slots")
            slots = []
            for _ in range(count):
                slot = uuid.uuid4().hex
                self.workspace.save(cid, f"research-slot-{slot}.json", {"slot_id": slot, "reserved_at": now()})
                slots.append(slot)
            return slots

    def explore(self, cid: str, tic: str, code: str, reservation_id: str | None = None) -> dict:
        from .sandbox import execute_python
        if reservation_id is None:
            reservation_id = self.reserve_research(cid, 1)[0]
        with self._lock(cid):
            plan = self.plan(cid)
            if self._has(cid, "hypotheses.json"):
                raise ValueError("Exploratory code is disabled after hypothesis freeze")
            allowed = {t["tic"] for t in plan["cohort"]["targets"]}
            if check_tic(tic) not in allowed:
                raise ValueError("TIC not in campaign")
            slot = self.workspace.read(cid, f"research-slot-{reservation_id}.json")
            if slot["slot_id"] != reservation_id or self._has(cid, f"research-slot-{reservation_id}-consumed.json"):
                raise ValueError("Research slot already consumed or invalid")
            self.workspace.save(cid, f"research-slot-{reservation_id}-consumed.json", {"consumed_at": now(), "tic": tic})
            data = self._load_data(cid, tic, "d")
            projection = self.workspace.file(cid, f"experiment-input-{tic}.npz")
            if not projection.exists():
                np.savez_compressed(projection, **{k: data[k] for k in ("time", "flux", "flux_err")})
                self.workspace.seal(cid, projection.name)
            result = execute_python(code, projection,
                                    self.workspace.path(cid) / f"exploration-{reservation_id}")
            return self.workspace.record(cid, "research_experiment", {"tic": tic, "code": code},
                {"result": result, "role": "Exploratory only; cannot change frozen acceptance rules or verify a candidate"})
