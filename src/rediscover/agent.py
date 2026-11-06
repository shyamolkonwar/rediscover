"""Bounded Responses-API agent. Tools, not the model, own numerical truth."""
from __future__ import annotations

import json
import math
import os
import time
from urllib.parse import urlsplit

import httpx

from .service import Lab

SYSTEM = """You are a cautious gravitational-wave laboratory agent. Analyze only the provided run.
First check each detector's data quality, then use analyze_detector, then get_results.
You may not use memorized event values. Every measurement must exactly copy a numerical tool result
and cite its evidence_id. Masses are coarse detector-frame bank estimates, not Bayesian inference.
Peak SNR is NOT false-alarm probability or discovery significance. A demonstration candidate means
ALL available detectors have peak snr >= 8, not that a gravitational wave has been independently found.
Return ONLY JSON: {"candidate":true/false,"measurements":[{"detector":"H1", "evidence_id":"e-...",
"snr":number,"chirp_mass":number,"peak_gps":number}, ...]}. Include every available detector.
Do not include markdown or extra prose. If a tool fails, do not invent a replacement measurement.
"""


def validate_final(final: dict, results: dict, required_detectors: list[str] | None = None) -> dict:
    errors = []
    if not isinstance(final, dict):
        return {"valid": False, "errors": ["Final response must be an object"]}
    expected = results.get("detectors", {})
    required = set(required_detectors) if required_detectors is not None else set(expected)
    if set(expected) != required:
        errors.append("Not all prepared detectors were analyzed")
    measurements = final.get("measurements", [])
    if not isinstance(measurements, list):
        return {"valid": False, "errors": ["measurements must be a list"]}
    if not expected or len(measurements) != len(expected):
        errors.append("Missing or extra detector measurements")
    seen = set()
    for m in measurements:
        if not isinstance(m, dict):
            errors.append("Invalid measurement")
            continue
        d = m.get("detector")
        if not isinstance(d, str) or d not in expected or d in seen:
            errors.append("Unknown or duplicate detector")
            continue
        seen.add(d)
        e = expected[d]
        if m.get("evidence_id") != e["evidence_id"]:
            errors.append(f"{d}: wrong evidence ID")
        for field in ("snr", "chirp_mass", "peak_gps"):
            v = m.get(field)
            # Absolute timestamp precision, not relative-to-billion-second GPS tolerance.
            if (isinstance(v, bool) or not isinstance(v, (float, int))
                    or not math.isfinite(v)
                    or not math.isclose(v, e["result"][field], rel_tol=0, abs_tol=1e-5)):
                errors.append(f"{d}: {field} does not match evidence")
    candidate = bool(expected) and set(expected) == required and all(e["result"]["snr"] >= 8 for e in expected.values())
    if final.get("candidate") is not candidate:
        errors.append("Candidate flag does not match the stated demonstration threshold")
    return {"valid": not errors, "errors": errors,
            "scope": "Numerical fields, evidence IDs, detector coverage and threshold only"}


def tool_schemas(detectors: list[str]) -> list[dict]:
    schemas = []
    for name, description in [
        ("check_data_quality", "Check sampling, finite values and GWOSC quality flags."),
        ("analyze_detector", "Search finite nonspinning bank; returns SNR, masses, peak GPS and evidence ID."),
        ("get_results", "Read computed measurements and evidence IDs for all detectors.")]:
        properties = {} if name == "get_results" else {"detector": {"type": "string", "enum": detectors}}
        schemas.append({"type": "function", "name": name, "description": description,
                        "parameters": {"type": "object", "properties": properties,
                                       "required": list(properties), "additionalProperties": False},
                        "strict": True})
    return schemas


def run_agent(lab: Lab, run_id: str, model: str, max_steps: int = 8,
              max_output_tokens: int = 4096, max_tool_calls: int = 12) -> dict:
    if not 1 <= max_steps <= 12 or not 512 <= max_output_tokens <= 8192:
        raise ValueError("Agent budget outside allowed bounds")
    if not 1 <= max_tool_calls <= 24:
        raise ValueError("Tool budget outside allowed bounds")
    base = os.environ.get("REDISCOVER_API_BASE", "").rstrip("/")
    key = os.environ.get("REDISCOVER_API_KEY", "")
    if not base or not key:
        raise ValueError("Set REDISCOVER_API_BASE (ending /openai/v1 or /v1) and REDISCOVER_API_KEY")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Model endpoint must be HTTPS without embedded credentials or query")
    description = lab.describe(run_id)
    # The agent receives neither catalog parameters nor physical paths to benchmark truth.
    task = {"run_id": run_id, "detectors": description["detectors"],
            "task": "Analyze the prepared data and report tool-grounded measurements."}
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(task)}]
    tools = tool_schemas(task["detectors"])
    trace, total_tokens, calls = [], 0, 0
    final = None
    validation = None
    status = "budget_exhausted"
    started = time.monotonic()
    with httpx.Client(timeout=180, follow_redirects=False) as client:
        for step in range(max_steps):
            payload = {"model": model, "input": messages, "tools": tools,
                       "max_output_tokens": max_output_tokens, "store": False,
                       "include": ["reasoning.encrypted_content"],
                       "reasoning": {"effort": "low"}}
            try:
                response = client.post(base + "/responses", json=payload,
                                       headers={"api-key": key, "Authorization": "Bearer " + key})
                if response.status_code != 200:
                    # Do not echo response bodies, endpoint, or credentials into public traces.
                    status = f"provider_http_{response.status_code}"
                    trace.append({"step": step, "error": status})
                    break
                body = response.json()
            except httpx.HTTPError as exc:
                status = "provider_transport_error"
                trace.append({"step": step, "error": type(exc).__name__})
                break
            usage = body.get("usage") or {}
            total_tokens += int(usage.get("total_tokens", 0))
            outputs = body.get("output", [])
            messages.extend(outputs)
            trace.append({"step": step, "model": body.get("model", model),
                          "usage": usage, "response_status": body.get("status")})
            functions = [x for x in outputs if x.get("type") == "function_call"]
            if functions:
                for call in functions:
                    if calls >= max_tool_calls:
                        status = "tool_budget_exhausted"
                        break
                    calls += 1
                    name = call.get("name")
                    arguments = {}
                    try:
                        arguments = json.loads(call["arguments"])
                        if not isinstance(arguments, dict):
                            raise ValueError("Arguments must be an object")
                        allowed = set() if name == "get_results" else {"detector"}
                        if set(arguments) != allowed:
                            raise ValueError("Unexpected tool arguments")
                        if name == "get_results":
                            result = lab.results(run_id)
                        elif name in ("check_data_quality", "analyze_detector"):
                            if arguments["detector"] not in task["detectors"]:
                                raise ValueError("Unknown task detector")
                            method = lab.quality if name == "check_data_quality" else lab.analyze
                            result = method(run_id, arguments["detector"])
                        else:
                            raise ValueError("Tool is not permitted")
                    except (ValueError, KeyError, TypeError) as exc:
                        result = {"error": str(exc)}
                    trace.append({"tool": name, "arguments": arguments,
                                  "result": result})
                    messages.append({"type": "function_call_output", "call_id": call["call_id"],
                                     "output": json.dumps(result, allow_nan=False)})
                if status == "tool_budget_exhausted":
                    break
                continue
            text = "".join(c.get("text", "") for o in outputs if o.get("type") == "message"
                           for c in o.get("content", []) if c.get("type") == "output_text")
            try:
                final = json.loads(text)
                if not isinstance(final, dict):
                    raise ValueError("Expected a JSON object")
                validation = validate_final(final, lab.results(run_id), task["detectors"])
                status = "completed" if validation["valid"] else "ungrounded_final"
            except (ValueError, TypeError):
                status = "invalid_final_json"
            break
    result = {"run_id": run_id, "requested_model": model, "status": status,
              "total_tokens": total_tokens, "tool_calls": calls,
              "elapsed_seconds": time.monotonic() - started, "final": final,
              "validation": validation,
              "trace": trace, "budget": {"max_steps": max_steps,
              "max_output_tokens_per_step": max_output_tokens, "max_tool_calls": max_tool_calls},
              "note": "Provider errors are not retried automatically; retrying can incur additional charges."}
    evidence = lab.workspace.record(run_id, "agent_run", {"model": model}, result)
    result["evidence_id"] = evidence["evidence_id"]
    return result
