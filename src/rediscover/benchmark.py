"""Reproducible demonstration tasks, not a statistically powered model ranking."""
from __future__ import annotations

import math
import uuid
from decimal import Decimal

import httpx
import numpy as np

from .agent import run_agent
from .data import fetch_event
from .service import Lab
from .workspace import dump, now


def grade(result: dict, truth: dict) -> dict:
    """Predeclared demo thresholds. No Bayesian interval or significance claims."""
    candidate = result.get("snr", 0) >= 8
    checks = {"candidate": candidate == truth["signal"]}
    if truth["signal"]:
        resolution = truth.get("reference_time_resolution_seconds", 0.0)
        tolerance = max(0.03, resolution / 2 + 0.0101)
        key = "peak_within_reference_precision" if resolution else "peak_within_30ms"
        checks[key] = abs(result.get("peak_gps", math.inf) - truth["peak_gps"]) <= tolerance
        if "chirp_mass" in truth:
            checks["chirp_mass_within_20pct"] = abs(result.get("chirp_mass", math.inf) / truth["chirp_mass"] - 1) <= 0.2
    return {"passed": all(checks.values()), "checks": checks,
            "interpretation": "Educational recovery criteria; SNR >= 8 is not astrophysical significance."}


def make_hidden_tasks(lab: Lab, seed: int = 42) -> list[tuple[str, dict]]:
    from .physics import inject_signal
    _, datasets = fetch_event("GW150914-v3", lab.workspace.root / "cache")
    base = datasets["H1"]
    fs = base["sample_rate"]
    rng = np.random.default_rng(seed)
    tasks = []
    # Event is at t=15.4 in this segment. Search t=10.3, outside the known chirp.
    # We retain the rest of the real segment for PSD estimation; disclose this interference.
    specifications = [None, (35.0, 30.0), (45.0, 25.0)]
    rng.shuffle(specifications)
    for spec in specifications:
        peak = 10.3
        strain = base["strain"].copy()
        truth = {"signal": spec is not None, "peak_gps": peak}
        if spec:
            m1, m2 = spec
            strain = inject_signal(strain, fs, 0.0, peak, m1, m2, 14.0, seed=seed)
            truth.update({"mass1": m1, "mass2": m2,
                          "chirp_mass": (m1 * m2) ** (3 / 5) / (m1 + m2) ** (1 / 5),
                          "target_snr": 14.0})
        run_id = lab.prepare({"name": "Opaque task", "gps": peak}, {"H1": {
            "strain": strain, "sample_rate": fs, "gps_start": 0.0,
            "data_quality": base["data_quality"],
            "source": {"type": "benchmark data; provenance disclosed by grader"}}})
        truth["source"] = base["source"]
        truth["noise_note"] = "Real H1 strain; search at relative 10.3 s, known GW150914 at 15.4 s outside search window."
        tasks.append((run_id, truth))
    return tasks


def benchmark(lab: Lab, model: str | None = None, seed: int = 42,
              events: list[str] | None = None, hidden: bool = True) -> dict:
    events = events if events is not None else ["GW150914-v3", "GW170104", "GW170814"]
    tasks, failures = [], []
    for event in events:
        try:
            fetched = lab.fetch(event)
            gps = fetched["metadata"]["gps"]
            resolution = float(Decimal(10) ** Decimal(str(gps)).as_tuple().exponent)
            tasks.append((fetched["run_id"], {"signal": True, "peak_gps": gps,
                "reference_time_resolution_seconds": resolution,
                "event": event, "kind": "known-event"}))
        except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
            failures.append({"event": event, "error": str(exc), "passed": False})
    if hidden:
        try:
            tasks.extend(make_hidden_tasks(lab, seed))
        except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
            failures.extend({"event": f"opaque-{i + 1}", "error": str(exc), "passed": False}
                            for i in range(3))
    if not tasks and not failures:
        raise ValueError("Select at least one benchmark task")
    rows = []
    for run_id, truth in tasks:
        try:
            agent = run_agent(lab, run_id, model) if model else None
            if model is None:
                for detector in lab.describe(run_id)["detectors"]:
                    lab.quality(run_id, detector)
                    lab.analyze(run_id, detector)
            results = lab.results(run_id)
            grades = {d: grade(e["result"], truth) for d, e in results["detectors"].items()}
            required = set(lab.describe(run_id)["detectors"])
            passed = (set(grades) == required and all(g["passed"] for g in grades.values())
                      and (agent is None or agent["status"] == "completed"))
            rows.append({"run_id": run_id, "truth_revealed_after_run": truth, "grades": grades,
                         "passed": passed, "results": results, "agent": agent})
        except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
            rows.append({"run_id": run_id, "truth_revealed_after_run": truth,
                         "passed": False, "error": str(exc)})
    result = {"created_at": now(), "model": model or "deterministic-tools", "seed": seed,
              "tasks": rows, "setup_failures": failures,
              "passed": sum(r["passed"] for r in rows), "total": len(rows) + len(failures),
              "limitations": ["Small demonstration suite, not a model leaderboard.",
                  "Named events may be memorized; opaque injections test use of provided numerical tools.",
                  "Injection truth is unavailable through agent tools, not secret from the machine operator.",
                  "Fixed finite bank with low-spin high-mass systems; does not cover the full GW population.",
                  "No background time-slide study; threshold results are not false-alarm probabilities."]}
    path = lab.workspace.root / ("benchmark-" + uuid.uuid4().hex + ".json")
    path.write_text(dump(result))
    return {"path": str(path), **result}
