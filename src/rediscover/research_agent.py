"""Research proposals and sandboxed experiments; never the scientific verifier."""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

import httpx

from .campaigns import Campaigns, validate_config
from .workspace import now


def request_json(model: str, instruction: str, context: dict, max_output_tokens: int = 4096) -> dict:
    base = os.environ.get("REDISCOVER_API_BASE", "").rstrip("/")
    key = os.environ.get("REDISCOVER_API_KEY", "")
    p = urlsplit(base)
    if not key or p.scheme != "https" or p.username or p.password or p.query or p.fragment:
        raise ValueError("Configure HTTPS REDISCOVER_API_BASE and REDISCOVER_API_KEY for paid model use")
    request = {"model": model, "store": False, "max_output_tokens": max_output_tokens,
               "reasoning": {"effort": "low"}, "input": [
                   {"role": "system", "content": instruction + " Return only a JSON object, without markdown."},
                   {"role": "user", "content": json.dumps(context, allow_nan=False)}]}
    with httpx.Client(timeout=180, follow_redirects=False) as client:
        response = client.post(base + "/responses", json=request,
                               headers={"api-key": key, "Authorization": "Bearer " + key})
        if response.status_code != 200:
            raise ValueError(f"Research provider returned HTTP {response.status_code}; no automatic paid retry")
        body = response.json()
    if body.get("status") != "completed":
        raise ValueError("Research model response was not completed")
    text = "".join(c.get("text", "") for o in body.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") == "output_text")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Research output must be a JSON object")
    return {"result": value, "model": body.get("model", model), "requested_model": model,
            "usage": body.get("usage", {}), "recorded_at": now()}


def propose_plan(cohort: dict, model: str) -> dict:
    allowed = {"period_min", "period_max", "durations_days", "detrend_window_days", "alternate_window_days"}
    instruction = """Design a bounded TESS transit search before inspecting any flux.
Return {objective: string, hypothesis: string, prediction: string, falsification: [strings],
parameters: {period_min:number, period_max:number, durations_days:[numbers],
detrend_window_days:number, alternate_window_days:number}, rationale:string}.
Choose periods within 0.5 to 10 days, durations within .02 to .15 days below period_min/4,
detrending windows from 1 to 4 days. Use two different reasonable detrending windows.
The fixed verifier requires at least 3 observed transits, SNR8, independent validation,
alternative-explanation checks, search-multiplicity handling, and known-catalog review.
You cannot relax those requirements. Do not claim an uncatalogued planet will be found.
Reserved validation sectors are not available for exploration. Do not choose targets based on known planets.
"""
    proposal = request_json(model, instruction, {"cohort": cohort, "data_available": "metadata only"})
    value = proposal["result"]
    parameters = value.get("parameters", {})
    if not isinstance(parameters, dict) or not set(parameters).issubset(allowed):
        raise ValueError("Planner attempted to change protected acceptance rules")
    config = validate_config(parameters)
    if config["detrend_window_days"] == config["alternate_window_days"]:
        raise ValueError("Planner must propose distinct detrending checks")
    for field in ("objective", "hypothesis", "prediction", "rationale"):
        if not isinstance(value.get(field), str) or not 1 <= len(value[field]) <= 2000:
            raise ValueError("Planner omitted a bounded research statement")
    if not isinstance(value.get("falsification"), list) or not 1 <= len(value["falsification"]) <= 8:
        raise ValueError("Planner must supply falsifiable alternatives")
    proposal["validated_config"] = config
    return proposal


def run_experiments(campaigns: Campaigns, cid: str, model: str, experiments: int = 2) -> dict:
    plan = campaigns.plan(cid)
    if not 1 <= experiments <= plan["config"]["max_code_experiments"]:
        raise ValueError("Requested experiments exceed the frozen budget")
    if campaigns._has(cid, "hypotheses.json"):
        raise ValueError("Research exploration is closed after freeze")
    results = campaigns.workspace.read(cid, "search.json")
    successful = [r for r in results["targets"] if not r.get("error")]
    if not successful:
        raise ValueError("No discovery data available for an experiment")
    # Strongest tentative signal is an exploration target, not a confirmed finding.
    chosen = max(successful, key=lambda r: (bool(r.get("candidate", {}).get("candidate_flag")), r.get("candidate", {}).get("depth_snr") or 0))
    tic = chosen["tic"]
    # Reserve durably before any paid proposal, including across concurrent callers.
    slots = campaigns.reserve_research(cid, experiments)
    previous = []
    for index, slot in enumerate(slots):
        context = {"objective": plan["objective"], "tic": tic,
                   "candidate": chosen.get("candidate"), "data_metadata": chosen.get("data"),
                   "previous_experiments": previous,
                   "input_file": "/input/lightcurve.npz", "available_arrays": ["time", "flux", "flux_err"],
                   "constraints": "Only discovery-sector data. Python+numpy+scipy+astropy; no network or writable input. 30 seconds, bounded JSON stdout."}
        instruction = """You are an experimental astrophysics assistant. Propose and implement one
small test that could undermine the tentative transit interpretation, using only the supplied discovery data.
Return {hypothesis:string, prediction:string, falsification_condition:string, code:string}.
Code must load /input/lightcurve.npz with allow_pickle=False; only time, flux and flux_err exist.
Print a small JSON object of ACTUAL computed measurements. Times are BTJD days.
Test an alternative such as stellar variability, instrumental trends, odd/even depths,
secondary eclipses, or dependence on a few isolated points. Choose a different test after seeing previous results.
Do not import rediscover, write files, use network, hardcode a result, retune primary acceptance
thresholds, or claim a planet. No arbitrary filesystem exploration. Avoid NaN/Infinity in JSON.
"""
        try:
            proposal = request_json(model, instruction, context)
            p = proposal["result"]
            for key in ("hypothesis", "prediction", "falsification_condition", "code"):
                if not isinstance(p.get(key), str) or not p[key]:
                    raise ValueError("Incomplete research experiment proposal")
            campaigns.workspace.record(cid, "experiment_proposal", {"index": index + 1}, proposal)
            executed = campaigns.explore(cid, tic, p["code"], reservation_id=slot)
            previous.append({"hypothesis": p["hypothesis"], "prediction": p["prediction"],
                             "falsification_condition": p["falsification_condition"], "execution": executed})
        except (ValueError, OSError, httpx.HTTPError) as exc:
            failed = {"index": index + 1, "error": f"{type(exc).__name__}: {exc}"}
            campaigns.workspace.record(cid, "research_failure", {}, failed)
            previous.append(failed)
            break
    critique, evidence_id = None, None
    executed = any(p.get("execution", {}).get("result", {}).get("result", {}).get("status") == "success" for p in previous)
    if executed:
        # At most one critique per reserved batch; no paid critique of a wholly failed batch.
        try:
            critique = request_json(model,
                "Review the measured experiments critically. Return {assessment:string, rejected_interpretations:[strings], unresolved_questions:[strings]}. "
                "These are exploratory tests, not planet confirmation. Do not invent measurements or declare discovery. "
                "Only the deterministic verifier may assign the final status; independent validation has not been accessed.",
                {"tic": tic, "experiments": previous})
            evidence_id = campaigns.workspace.record(cid, "research_critique", {}, critique)["evidence_id"]
        except (ValueError, OSError, httpx.HTTPError) as exc:
            critique = {"error": f"{type(exc).__name__}: {exc}"}
            campaigns.workspace.record(cid, "research_failure", {}, critique)
    return {"tic": tic, "experiments": previous, "critique": critique, "evidence_id": evidence_id,
            "role": "Hypothesis generation and falsification support; not authoritative classification"}
