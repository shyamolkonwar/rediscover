# TESS discovery campaigns — approved implementation plan

## Goal
Extend Rediscover into a bounded research runtime that searches actual TESS observations, freezes a falsifiable hypothesis, evaluates independent observations, checks known catalogs/literature, and records negative as well as positive outcomes. No confirmed/new planet claim is automated.

## Execution and isolation
Existing code and v0.1 history stay intact on a fresh feature branch. Source edits and Git operations occur in the working folder. All installs, builds, tests, numerical searches, generated-code experiments and model calls run on the authorized Linux VM in a separate project directory and environment. Generated code runs in a non-root, network-disabled Docker container with read-only inputs, no host secrets/docker socket, dropped capabilities, resource/time/output limits. Do not change unrelated applications.

## Modules
- tess_data.py: bounded MAST metadata discovery, verified SPOC FITS downloads, identifiers, provenance/quality, checksummed immutable observation snapshots; NASA Exoplanet Archive TOI/confirmed catalog and dated literature-search evidence.
- transit.py: quality cleaning, gap-aware detrending, finite BLS search, observed-transit checks, odd/even and secondary/eclipse variability diagnostics, fixed-ephemeris holdout validation, sensitivity/negative controls and explicit empirical-null limitations.
- campaigns.py: validated plan and frozen target/sector cohort; immutable operation records; plan -> search -> freeze hypotheses -> consume holdout once -> catalog/novelty review -> verifier -> dossier. No model tool exposes holdout data before freeze. Search failures remain in denominator. Catalog failure never means uncatalogued.
- research_agent.py: Azure Responses planner and experimentalist proposing bounded plans and alternative explanations; code experiments cannot rewrite primary acceptance rules or approve their own outcomes. Core research work remains executable without a paid model.
- sandbox.py: Docker-backed restricted Python execution for exploration-only analysis. Human/operator opt-in required outside CLI explicit request. No generated-code output may silently become verifier evidence.
- tess_report.py: offline campaign overview and per-target dossier with light curves, periodograms, folded transit, holdout and known-source evidence, hypothesis/disproof history and all limitations.
- cli.py and mcp_server.py: add TESS discovery operations without breaking LIGO commands.

## Scientific contract
Freeze cohort, search periods/durations, detrending methods, thresholds, null count, budgets and discovery/validation sectors BEFORE any flux search. Targets selected using metadata only, with known controls separated from search cohort. Validation observations are reserved, not searched or used for tuning. Hypotheses freeze exact period/epoch/duration/config before validation; reusing validation is explicitly disallowed by the campaign state machine. Never enlarge thresholds post hoc to rescue a result.

Search and validation use BTJD (BJD_TDB - 2457000), preserving FITS BJDREF/TIMESYS. Check repeated dips, alternating transit depths, secondary eclipses, plausible durations and periodic variability. Compare reasonable predeclared detrending variants. Examine SAP/PDCSAP and centroid/crowding information where available; missing pixel/contamination evidence prevents a strong novelty label. Catalog crossmatches need period/alias context and dated source snapshots; a missing TIC match is not exhaustive literature clearance. Search multiplicity is explicit; finite surrogate controls do not yield arbitrarily small p values. No p-value/discovery claim if null calibration is inadequate. Zero credible candidates is a valid outcome.

Statuses: KNOWN_SIGNAL_RECOVERED, REJECTED, UNRESOLVED, POTENTIALLY_UNCATALOGUED_CANDIDATE. No automated CONFIRMED_PLANET or DISCOVERY.

## Delivery steps
1. Verify MAST and catalog access from VM; freeze a small real metadata-selected campaign plus separate known-transit controls.
2. Tests first: numerical injection/noise/binary controls and recovery; immutable holdout gating; network/path bounds; sandbox isolation.
3. Implement numerical core and data/campaign runtime; expose CLI/MCP.
4. Implement bounded model planner and isolated generated-code experiment, then exercise it with Azure against discovery data only.
5. Run real search + holdout + known-catalog review without tuning on results. Produce actual dossiers and honest null/unresolved outcomes.
6. Full remote test/lint/security/build, clean installation, actual MCP and report rendering. Review and fix concrete issues once.
7. Commit and push a new PR with code, methodology and verified artifacts. Existing v0.1 release is not overwritten. Merge/release is a separate approval boundary unless explicitly requested.
