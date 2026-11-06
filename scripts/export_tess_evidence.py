"""Export actual TESS campaign evidence without inventing success or backfilling provenance."""
import argparse
import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

from rediscover.campaigns import Campaigns
from rediscover.tess_report import make_campaign_report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--home", required=True)
    p.add_argument("--campaign", required=True)
    p.add_argument("--control", required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = root / "examples" / "tess"
    out.mkdir(parents=True, exist_ok=True)
    c = Campaigns(args.home)
    publications = {}
    for label, cid in [("campaign", args.campaign), ("known-control", args.control)]:
        report = make_campaign_report(c, cid)
        source = c.workspace.path(cid)
        records = {name: c.workspace.read(cid, name + ".json") for name in
                   ("plan", "search", "hypotheses", "validation", "review", "verdict", "environment")}
        evidence = c.workspace.evidence(cid)
        for name, value in records.items():
            (out / f"{label}-{name}.json").write_text(json.dumps(value, indent=2) + "\n")
        (out / f"{label}-research.json").write_text(json.dumps(evidence, indent=2) + "\n")
        shutil.copyfile(report["html"], out / f"{label}.html")
        shutil.copyfile(report["markdown"], out / f"{label}.md")
        publications[label] = {"report_summary": report["summary"], "records": records}
        ids = {t["tic"] for t in records["plan"]["cohort"]["targets"]}
        assert {t["tic"] for t in records["review"]["targets"]} == ids
        assert records["verdict"]["total_targets"] == len(ids)
        assert c.workspace.verify(cid)["valid"]
        if label == "campaign":
            suffix = Path(report["html"]).stem.split("tess-report-", 1)[1]
            first = records["plan"]["cohort"]["targets"][0]["tic"]
            image = source / f"tic-{first}-{suffix}.png"
            if image.exists():
                shutil.copyfile(image, root / "docs" / "assets" / "tess-candidate.png")
    verification_environment = {name: importlib.metadata.version(name) for name in
                                ("rediscover-physics", "numpy", "scipy", "astropy", "astroquery", "mcp")}
    (out / "verification-environment.json").write_text(json.dumps(verification_environment, indent=2) + "\n")
    hashes = {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in sorted((root / "src").rglob("*.py"))}
    (out / "publication-source-sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    run = publications["campaign"]
    control = publications["known-control"]
    v = run["report_summary"]
    cs = control["records"]["search"]["targets"][0]["candidate"]
    cv = control["records"]["validation"]["targets"][0]
    model = run["records"]["plan"].get("proposal", {})
    text = f'''# Actual TESS campaign results

This is an experimental search-and-falsification workflow, not a new-planet announcement.

## Real campaign

- Planned stars: **{v['total_targets']}**.
- Completed discovery searches: **{v['completed_searches']}**.
- Frozen follow-up ephemerides: **{v['frozen_hypotheses']}**.
- Completed independent-sector tests: **{v['independent_tests']}** of {v['holdout_attempts']} attempts.
- Successful agent-written sandbox experiments: **{v['successful_code_experiments']}**.
- Final status counts: `{json.dumps(v['counts'])}`.
- New planets established: **{v['confirmed_new_planets']}**.

The planner was the actual Azure deployment `{model.get('model', 'not used')}`. It proposed settings before flux inspection. The frozen cohort was selected from bounded MAST metadata-page intersections, not chosen because the stars were known to contain planets. Archive page order can change: use the saved plan/product IDs to reproduce this particular selection.

Sector 1 was used for discovery. Sector 4 was reserved until exact ephemerides were frozen. Each follow-up failed the independent-sector screening rule. No holdout was retuned or rerun to rescue a candidate.

For TIC 25079777, the agent proposed and implemented an event-depth consistency test and a point-outlier robustness test. Both actually executed in the restricted container. The first suggested inconsistent event depths under a simplified error model; the second removed no points under its chosen clipping rule. These exploratory interpretations are not calibrated discovery probabilities and did not determine the authoritative campaign verdict.

## Known positive control — important limitation

A separate pi Mensae c control (TIC 261136679), excluded from the discovery denominator, recovered period **{cs['period_days']:.9f} days**. Its discovery depth SNR was **{cs['depth_snr']:.3f}** and the independent-sector value at the unchanged ephemeris was **{cv['depth_snr']:.3f}**.

However, the discovery diagnostic flags were `{cs['flags']}` and the holdout flags were `{cv['flags']}`. The strict screen therefore rejected the known planet. **This is not a successful end-to-end positive control.** Period recovery and a strong repeated dip are not equivalent to a validated vetting pipeline. The sensitivity and false-rejection rate need further scientific calibration. The thresholds and the recorded outcome were not changed after seeing the result.

## What the software evidence establishes

- Real MAST downloads, FITS identity/time/quality validation and source checksums.
- Actual bounded BLS searches and two predeclared detrending variants.
- Hypotheses frozen before one-shot, fixed-ephemeris independent tests.
- Actual Azure-generated exploratory code with isolated execution and saved results.
- Catalog snapshots and honest failed/null outcomes.
- Not completeness, a calibrated astrophysical false-alarm probability, or validated autonomous discovery.

The default 64-surrogate budget has insufficient p-value resolution for this cohort's multiplicity cutoff. Null calibration was not treated as passed when omitted; no noncatalogued candidate survived the earlier independent-data gate.

## Provenance and files

`campaign-*.json` and `known-control-*.json` contain the immutable plans, searches, hypotheses, validation, review and creation-time environment records. The corresponding HTML files are self-contained dossiers; download them to view in a browser. `*-research.json` preserves model proposals, generated code, execution results and critique.

These are development-run snapshots. `verification-environment.json` describes the later package-verification environment; it is not backfilled as the original run's environment. `publication-source-sha256.json` identifies code at export, not a retroactive signature on the earlier execution. The new campaign API records source hashes at creation for future runs. Non-scientific review fixes to quotas, soft scheduling, finalization and report labels did not rerun the reserved observations or rewrite the sealed scientific verdicts.

The research image's pip installer was security-updated after the recorded experiments; its pinned numerical libraries were unchanged, and sandbox tests were rerun. The image tag is operator-managed, not a cryptographic execution attestation.

All application execution, tests and builds for this work occurred on the authorized Azure VM. No analysis or tests were run on the source-editing laptop. No credentials or private model endpoint are included in these artifacts.
'''
    (out / "RESULTS.md").write_text(text)
    print(json.dumps({label: item["report_summary"] for label, item in publications.items()}, indent=2))


if __name__ == "__main__":
    main()
