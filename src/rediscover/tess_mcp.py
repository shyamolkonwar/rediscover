"""TESS MCP operations, with generated-code execution disabled by default."""
import os

from .campaigns import Campaigns
from .tess_data import discover_cohort


def register_tess(server, root, read, local, remote):
    c = Campaigns(root)

    @server.tool(annotations=remote)
    def tess_plan(count: int = 12, discovery_sector: int = 1, validation_sector: int = 4,
                  objective: str = "Search for repeating transit-like signals", parameters: dict | None = None) -> dict:
        """Freeze metadata-selected targets, search settings and reserved validation sector before accessing flux."""
        cohort = discover_cohort(discovery_sector, validation_sector, count)
        return c.create(cohort, parameters, objective)

    @server.tool(annotations=remote)
    def tess_search(campaign_id: str) -> dict:
        """Search discovery observations only. Reserved validation data cannot be accessed by this tool."""
        result = c.search(campaign_id)
        return {"total": result["total"], "failures": result["failures"],
                "targets": [{k: r[k] for k in ("tic", "candidate", "stable", "error") if k in r}
                            for r in result["targets"]]}

    @server.tool(annotations=local)
    def tess_freeze_hypotheses(campaign_id: str) -> dict:
        """Commit exact discovery ephemerides before independent observations are revealed. Ends exploration."""
        return c.freeze(campaign_id)

    @server.tool(annotations=remote)
    def tess_validate(campaign_id: str) -> dict:
        """Consume the held-out sector once, evaluating frozen period/epoch/duration without a new search."""
        return c.validate(campaign_id)

    @server.tool(annotations=remote)
    def tess_review(campaign_id: str) -> dict:
        """Review catalogs, contamination warnings and surrogate calibration. No automatic planet confirmation."""
        c.review(campaign_id)
        return c.workspace.read(campaign_id, "verdict.json")

    @server.tool(annotations=read)
    def tess_status(campaign_id: str) -> dict:
        """Read campaign phase and final statuses when available."""
        result = c.status(campaign_id)
        if result["state"] == "complete":
            result["verdict"] = c.workspace.read(campaign_id, "verdict.json")
        return result

    @server.tool(annotations=local)
    def tess_report(campaign_id: str) -> dict:
        """Create offline campaign dossiers from actual evidence, including rejected/unresolved findings."""
        from .tess_report import make_campaign_report
        return make_campaign_report(c, campaign_id)

    if os.environ.get("REDISCOVER_ENABLE_CODE_EXPERIMENTS") == "1":
        @server.tool(annotations=local)
        def tess_experiment(campaign_id: str, tic: str, code: str) -> dict:
            """Run exploratory Python in a restricted offline Docker container on discovery data only. Cannot change verifier rules."""
            return c.explore(campaign_id, tic, code)
