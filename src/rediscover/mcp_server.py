"""Stdio MCP tools. No HTTP listener, arbitrary code execution or shell tools."""
from __future__ import annotations

import os

# Avoid oversubscribing a user's CPU before numerical imports.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

from . import __version__, data
from .service import LIMITATIONS, Lab


def guide() -> dict:
    return {"workflow": ["fetch_strain(event='GW150914-v3')", "check_data_quality for H1 and L1",
                         "analyze_detector for each detector", "get_results",
                         "optionally get_catalog AFTER analysis", "make_report"],
            "meaning": "Find a known binary-black-hole signal in actual public strain, not from memory.",
            "mass_bank": "Default component masses 20–50 solar masses, nonspinning, detector frame.",
            "limits": LIMITATIONS,
            "data": "32-second 4096-Hz H1/L1 GWOSC segments; not all catalog events have these.",
            "privacy": "Data and artifacts are stored locally. Your MCP host controls what reaches its model.",
            "safety": "No arbitrary URL, shell, code, upload, or deletion tool is exposed."}


def create_server(root=None):
    lab = Lab(root)
    server = MCPServer("rediscover", version=__version__,
                       instructions="Use tool outputs for every measurement. "
                       "Never claim discovery significance or Bayesian mass uncertainties. "
                       "Start with get_guide. Reports are generated from evidence, not model prose.")
    local = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    remote = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)

    @server.tool(annotations=read)
    def get_guide() -> dict:
        """Get the workflow, physics scope, privacy and interpretation limits."""
        return guide()

    @server.tool(annotations=remote)
    def list_events(page: int = 1) -> dict:
        """List one page of the official GWOSC catalog; follow has_more explicitly."""
        return data.list_events(page)

    @server.tool(annotations=remote)
    def fetch_strain(event: str = "GW150914-v3") -> dict:
        """Download a bounded official H1/L1 strain pair and create an immutable run."""
        return lab.fetch(event)

    @server.tool(annotations=local)
    def check_data_quality(run_id: str, detector: str) -> dict:
        """Check finite samples, signal quality and GWOSC flags; returns evidence ID."""
        return lab.quality(run_id, detector)

    @server.tool(annotations=local)
    def analyze_detector(run_id: str, detector: str, f_low: float = 30.0,
                         masses: list[float] | None = None) -> dict:
        """PSD-weighted bounded template-bank search. Coarse detector-frame masses, no significance."""
        return lab.analyze(run_id, detector, f_low, masses)

    @server.tool(annotations=read)
    def get_results(run_id: str) -> dict:
        """Return computed detector measurements and cross-detector timing with evidence IDs."""
        return lab.results(run_id)

    @server.tool(annotations=remote)
    def get_catalog(run_id: str) -> dict:
        """Fetch published inference AFTER analysis. Source-frame masses are not detector-frame masses."""
        return lab.catalog(run_id)

    @server.tool(annotations=local)
    def make_report(run_id: str) -> dict:
        """Render raw/whitened strain and Q-transform plots plus an offline HTML evidence report."""
        return lab.report(run_id)

    @server.tool(annotations=read)
    def verify_artifacts(run_id: str) -> dict:
        """Verify saved artifact checksums; this checks integrity, not scientific correctness."""
        return lab.workspace.verify(run_id)

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
