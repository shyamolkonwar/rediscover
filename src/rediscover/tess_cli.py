"""CLI routing for TESS campaign operations."""
from __future__ import annotations

from .campaigns import Campaigns
from .tess_data import discover_cohort


def add_commands(commands):
    tess = commands.add_parser("tess", help="Search real TESS data and test frozen hypotheses")
    sub = tess.add_subparsers(dest="tess_command", required=True)
    for name in ("plan", "discover"):
        p = sub.add_parser(name)
        p.add_argument("--count", type=int, default=12)
        p.add_argument("--discovery-sector", type=int, default=1)
        p.add_argument("--validation-sector", type=int, default=4)
        p.add_argument("--model", help="Explicit paid Azure/Responses planner deployment")
        p.add_argument("--allow-code", action="store_true", help="Allow bounded Docker exploration; requires --model")
        p.add_argument("--null-repeats", type=int, default=64)
    for name in ("status", "search", "freeze", "validate", "review", "report", "run"):
        sub.add_parser(name).add_argument("campaign_id")
    p = sub.add_parser("research")
    p.add_argument("campaign_id")
    p.add_argument("--model", required=True)
    p.add_argument("--experiments", type=int, default=2)
    p.add_argument("--allow-code", action="store_true")


def handle(args):
    c = Campaigns(args.home)
    action = args.tess_command
    if action in ("plan", "discover"):
        if args.allow_code and not args.model:
            raise ValueError("--allow-code requires an explicit --model")
        cohort = discover_cohort(args.discovery_sector, args.validation_sector, args.count)
        config = {"null_repeats": args.null_repeats}
        proposal = None
        objective = "Search metadata-selected TESS targets for repeating transit-like signals"
        if args.model:
            from .research_agent import propose_plan
            proposal = propose_plan(cohort, args.model)
            config = {**proposal["validated_config"], **config}
            objective = proposal["result"]["objective"]
        result = c.create(cohort, config, objective, proposal)
        if action == "plan":
            return result
        cid = result["campaign_id"]
        c.search(cid)
        research = None
        if args.allow_code:
            from .research_agent import run_experiments
            research = run_experiments(c, cid, args.model)
        verdict = c.run(cid)
        from .tess_report import make_campaign_report
        return {"verdict": verdict, "research": research, "report": make_campaign_report(c, cid)}
    cid = args.campaign_id
    if action == "report":
        from .tess_report import make_campaign_report
        return make_campaign_report(c, cid)
    if action == "research":
        if not args.allow_code:
            raise ValueError("Generated Python execution requires explicit --allow-code")
        from .research_agent import run_experiments
        return run_experiments(c, cid, args.model, args.experiments)
    return getattr(c, action)(cid)
