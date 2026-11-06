"""Command-line interface for real data, reports and bounded model experiments."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

import httpx

from . import __version__, data
from .service import Lab


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rediscover", description="Evidence-first gravitational-wave analysis and TESS discovery campaigns")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--home", help="Cache and evidence directory; default ~/.rediscover")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check installed dependencies without downloading data")
    events = commands.add_parser("events", help="List one page of GWOSC events")
    events.add_argument("--page", type=int, default=1)
    for name in ("run", "fetch"):
        run = commands.add_parser(name, help="Full numerical report" if name == "run" else "Download real strain")
        run.add_argument("event", nargs="?", default="GW150914-v3")
        if name == "run":
            run.add_argument("--catalog", action="store_true", help="Fetch published values AFTER numerical analysis")
    analyze = commands.add_parser("analyze", help="Analyze a detector in a saved run")
    analyze.add_argument("run_id")
    analyze.add_argument("detector", choices=["H1", "L1"])
    analyze.add_argument("--f-low", type=float, default=30)
    analyze.add_argument("--masses", type=float, nargs="+", help="Bounded component-mass bank [solar masses]")
    for name in ("results", "report", "verify"):
        commands.add_parser(name).add_argument("run_id")
    agent = commands.add_parser("agent", help="Run a paid model over a prepared run (explicit opt-in)")
    agent.add_argument("run_id")
    agent.add_argument("--model", required=True, help="Your deployment name; no implicit paid fallback")
    agent.add_argument("--max-steps", type=int, default=8)
    agent.add_argument("--max-output-tokens", type=int, default=4096)
    bench = commands.add_parser("bench", help="Run known events, hidden injections and a negative control")
    bench.add_argument("--model", help="Optional model deployment; omit for numerical baseline")
    bench.add_argument("--events", nargs="*", default=None)
    bench.add_argument("--no-hidden", action="store_true")
    bench.add_argument("--seed", type=int, default=42)
    commands.add_parser("mcp", help="Start the stdio MCP server")
    from .tess_cli import add_commands
    add_commands(commands)
    return p


def main() -> None:
    args = parser().parse_args()
    if args.command == "mcp":
        from .mcp_server import create_server
        create_server(args.home).run(transport="stdio")
        return
    try:
        lab = Lab(args.home)
        if args.command == "tess":
            from .tess_cli import handle
            result = handle(args)
        elif args.command == "doctor":
            names = ["numpy", "scipy", "h5py", "pycbc", "gwpy", "mcp"]
            versions = {name: importlib.metadata.version(name) for name in names}
            result = {"version": __version__, "dependencies": versions,
                      "workspace": str(lab.workspace.root),
                      "model_configured": bool(os.environ.get("REDISCOVER_API_KEY") and os.environ.get("REDISCOVER_API_BASE")),
                      "scope": "Dependency presence only; run the example to verify numerical execution."}
        elif args.command == "events":
            result = data.list_events(args.page)
        elif args.command in ("run", "fetch"):
            result = lab.fetch(args.event)
            if args.command == "run":
                run_id = result["run_id"]
                for detector in result["detectors"]:
                    print(f"Analyzing {detector} in run {run_id}", file=sys.stderr)
                    lab.quality(run_id, detector)
                    lab.analyze(run_id, detector)
                if args.catalog:
                    lab.catalog(run_id)
                result = {"results": lab.results(run_id), "report": lab.report(run_id)}
        elif args.command == "analyze":
            result = lab.analyze(args.run_id, args.detector, args.f_low, args.masses)
        elif args.command == "results":
            result = lab.results(args.run_id)
        elif args.command == "report":
            result = lab.report(args.run_id)
        elif args.command == "verify":
            result = lab.workspace.verify(args.run_id)
        elif args.command == "agent":
            from .agent import run_agent
            result = run_agent(lab, args.run_id, args.model, args.max_steps, args.max_output_tokens)
        elif args.command == "bench":
            from .benchmark import benchmark
            result = benchmark(lab, args.model, args.seed, args.events, not args.no_hidden)
        print(json.dumps(result, indent=2, allow_nan=False))
        if args.command == "verify" and not result["valid"]:
            raise SystemExit(2)
        if args.command == "agent" and result["status"] != "completed":
            raise SystemExit(2)
        if args.command == "bench" and result["passed"] != result["total"]:
            raise SystemExit(2)
    except (ValueError, OSError, KeyError, httpx.HTTPError, importlib.metadata.PackageNotFoundError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
