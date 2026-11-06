"""Offline TESS dossiers, derived only from sealed campaign artifacts."""
from __future__ import annotations

import base64
import html
import json
import uuid
from collections import Counter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .workspace import now


def number(value, digits=3):
    return f"{value:.{digits}f}" if isinstance(value, (float, int)) and np.isfinite(value) else "not evaluated"


def make_campaign_report(campaigns, cid: str) -> dict:
    w = campaigns.workspace
    with campaigns._lock(cid):
        plan = campaigns.plan(cid)
        verdict = w.read(cid, "verdict.json")
        review = w.read(cid, "review.json")
        frozen = w.read(cid, "hypotheses.json")
        validation = w.read(cid, "validation.json")
        counts = dict(Counter(r["verdict"]["status"] for r in review["targets"]))
        if counts != verdict["counts"] or len(review["targets"]) != verdict["total_targets"]:
            raise ValueError("Campaign totals do not match the sealed target records")
        if not w.verify(cid)["valid"]:
            raise ValueError("Campaign integrity failed")
        token = uuid.uuid4().hex[:8]
        sections, table, markdown = [], [], []
        for row in review["targets"]:
            tic = row["tic"]
            search = row["search"]
            candidate = search.get("candidate", {})
            held = row.get("validation", {})
            status = row["verdict"]["status"]
            table.append(f'<tr><td><a href="#tic-{tic}">{tic}</a></td>'
                f'<td>{number(candidate.get("period_days"), 5)}</td>'
                f'<td>{number(candidate.get("depth_snr"), 2)}</td>'
                f'<td>{number(held.get("depth_snr"), 2)}</td>'
                f'<td>{html.escape(status.replace("_", " ").lower())}</td></tr>')
            markdown.append(f"| {tic} | {number(candidate.get('period_days'), 5)} | {number(candidate.get('depth_snr'), 2)} | {number(held.get('depth_snr'), 2)} | {status} |")
            image = ""
            if not search.get("error"):
                data = campaigns._load_data(cid, tic)
                with plt.rc_context({"figure.facecolor": "#101722", "axes.facecolor": "#101722",
                    "text.color": "#e6ecf4", "axes.labelcolor": "#b9c5d5", "xtick.color": "#b9c5d5",
                    "ytick.color": "#b9c5d5", "axes.edgecolor": "#344355", "font.size": 10}):
                    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
                    stride = max(1, len(data["time"]) // 6000)
                    axes[0, 0].scatter(data["time"][::stride], data["flux"][::stride], s=2, color="#9eb7e0", alpha=.6)
                    axes[0, 0].set(title=f"Discovery · sector {data['metadata']['sector']}", xlabel="BTJD [TDB days]", ylabel="Relative PDCSAP flux")
                    diagnostics = search["primary"]["diagnostics"]
                    pg = diagnostics["periodogram"]
                    axes[0, 1].plot(pg["period_days"], pg["power"], color="#54ddbf", lw=.8)
                    axes[0, 1].axvline(candidate["period_days"], ls="--", color="#ffc57a", lw=.8)
                    axes[0, 1].set(title="BLS search · display-decimated", xlabel="Period [days]", ylabel="Log-likelihood improvement")
                    folded = diagnostics["folded"]
                    axes[1, 0].scatter(folded["phase_days"], folded["flux"], s=4, color="#54ddbf", alpha=.6)
                    axes[1, 0].set(title="Discovery fold · detrended", xlabel="Phase offset [days]", ylabel="Relative flux", xlim=(-3 * candidate["duration_days"], 3 * candidate["duration_days"]))
                    if held and not held.get("error"):
                        vdata = campaigns._load_data(cid, tic, "v")
                        phase = (vdata["time"] - candidate["epoch_btjd"] + candidate["period_days"] / 2) % candidate["period_days"] - candidate["period_days"] / 2
                        keep = np.abs(phase) < 3 * candidate["duration_days"]
                        axes[1, 1].scatter(phase[keep], vdata["flux"][keep], s=3, color="#ffc57a", alpha=.5)
                        axes[1, 1].set(title=f"Reserved sector {vdata['metadata']['sector']} · raw PDCSAP fold", xlabel="Frozen phase offset [days]", ylabel="Relative flux")
                    else:
                        axes[1, 1].text(.08, .5, "Holdout not evaluated\nNo reserved flux was used for search", transform=axes[1, 1].transAxes, color="#b9c5d5")
                        axes[1, 1].set_axis_off()
                    name = f"tic-{tic}-{token}.png"
                    fig.savefig(w.file(cid, name), dpi=110)
                    plt.close(fig)
                w.seal(cid, name)
                encoded = base64.b64encode(w.file(cid, name).read_bytes()).decode()
                image = f'<img alt="TIC {tic} discovery, periodogram, folded signal and reserved observation" src="data:image/png;base64,{encoded}">'
            reasons = "; ".join(row["verdict"].get("reasons", []))
            detail = {"discovery": candidate, "search_error": search.get("error"),
                      "independent_validation": held, "validation_error": held.get("error"),
                      "catalog": row.get("catalog"), "contamination": row.get("auxiliary"),
                      "calibration": row.get("calibration"), "literature": row.get("literature"),
                      "verdict": row["verdict"], "source": search.get("data", {}).get("source")}
            sections.append(f'<section id="tic-{tic}"><h2>TIC {tic}</h2><p class="label">{html.escape(status.replace("_", " "))}</p><p>{html.escape(reasons.replace("_", " "))}</p>{image}<details><summary>Measurements, checks and sources</summary><pre>{html.escape(json.dumps(detail, indent=2))}</pre></details></section>')
        evidence = [e for e in w.evidence(cid) if e["tool"] in ("experiment_proposal", "research_experiment", "research_critique", "research_failure")]
        research_html = "".join(f'<details><summary>{html.escape(e["tool"].replace("_", " "))} · {e["evidence_id"]}</summary><pre>{html.escape(json.dumps(e, indent=2))}</pre></details>' for e in evidence)
        completed_searches = sum(not r["search"].get("error") for r in review["targets"])
        completed_validations = sum(r.get("ephemeris_fixed") is True and not r.get("error") for r in validation["targets"])
        successful_code = sum(e["tool"] == "research_experiment" and e.get("result", {}).get("result", {}).get("status") == "success" for e in evidence)
        p_floor = 1 / (plan["config"]["null_repeats"] + 1)
        cutoff = .05 / plan["search_family_size"]
        summary = {**verdict, "frozen_hypotheses": len(frozen["hypotheses"]),
                   "completed_searches": completed_searches,
                   "search_failures_or_skips": len(review["targets"]) - completed_searches,
                   "holdout_attempts": len(validation["targets"]),
                   "independent_tests": completed_validations,
                   "unavailable_holdouts": len(validation["targets"]) - completed_validations,
                   "successful_code_experiments": successful_code,
                   "calibration_p_floor": p_floor, "calibration_family_cutoff": cutoff,
                   "calibration_resolution_sufficient": p_floor <= cutoff,
                   "generated_at": now(), "research_evidence_ids": [e["evidence_id"] for e in evidence]}
        stem = "tess-report-" + token
        w.save(cid, stem + ".json", summary)
        document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TESS discovery campaign — Rediscover</title><style>
:root{{color-scheme:dark}}body{{margin:0;padding:3rem 1.25rem;background:#0b111b;color:#e6ecf4;font:1rem/1.6 system-ui,sans-serif}}main{{max-width:72rem;margin:auto}}p,li{{max-width:72ch;color:#b9c5d5;text-wrap:pretty}}h1{{font-size:clamp(2rem,5vw,3.5rem);line-height:1.1;letter-spacing:-.02em;text-wrap:balance}}h2{{font-size:1.7rem;line-height:1.3;margin-top:3rem}}a{{color:#54ddbf}}header{{border-bottom:1px solid #344355;padding-bottom:2rem}}.label{{font-size:.8rem;letter-spacing:.05em;color:#54ddbf}}.metrics{{display:flex;gap:2rem;flex-wrap:wrap;margin:2rem 0}}.metric strong{{font-size:2.4rem;display:block;line-height:1.2;font-variant-numeric:tabular-nums}}.metric span{{color:#b9c5d5;font-size:.85rem}}.notice{{border-left:3px solid #ffc57a;padding:1rem 1.25rem;background:#101722;max-width:70ch}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{text-align:left;padding:.8rem;border-bottom:1px solid #344355;white-space:nowrap}}img{{width:100%;height:auto}}pre{{font: .82rem/1.6 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;background:#101722}}details{{margin:1rem 0;border:1px solid #344355;padding:1rem}}summary{{cursor:pointer}}section{{padding-bottom:2rem;border-bottom:1px solid #344355}}code{{overflow-wrap:anywhere;font-size:.85rem}}</style></head><body><main>
<header><div class="label">REDISCOVER / TESS / RESEARCH DOSSIER</div><h1>Search. Test. Try to disprove.</h1><p>{html.escape(plan['objective'])}</p><code>{cid}</code></header>
<div class="metrics"><div class="metric"><strong>{verdict['total_targets']}</strong><span>Planned stars</span></div><div class="metric"><strong>{completed_searches}</strong><span>Completed searches</span></div><div class="metric"><strong>{completed_validations}</strong><span>Completed independent tests</span></div><div class="metric"><strong>{verdict['confirmed_new_planets']}</strong><span>New planets established</span></div></div>
<p class="notice">A rejected candidate failed these screening rules. That is not proof the star has no planets. An unresolved or uncatalogued signal is not a confirmed planet. Diagnostic significance assumes simplified noise; known planets can also trigger these conservative warnings.</p>
<h2>Campaign outcome</h2><div class="scroll"><table><thead><tr><th>TIC</th><th>Best period [days]</th><th>Discovery SNR</th><th>Reserved-sector SNR</th><th>Outcome</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<h2>What was fixed before the search</h2><p>Frozen selection description: {html.escape(str(plan['cohort'].get('selection', 'User-supplied cohort; selection provenance not verified')))}. This application saved the cohort and settings before its searches. It did not retrieve reserved-sector flux until hypotheses were frozen. Validation is one-shot: no period refinement or retuning on held-out observations. {len(frozen['hypotheses'])} hypotheses were frozen; {len(validation['targets'])} holdout attempts produced {completed_validations} completed evaluations.</p><p>Search scheduling is a soft between-target deadline, not a hard process timeout. An in-progress target may finish after it; resuming does not reset the deadline. Numerical grids and downloads have separate size bounds.</p>
<details><summary>Frozen plan and model proposal</summary><pre>{html.escape(json.dumps(plan, indent=2))}</pre></details>
<h2>Calibration limits</h2><p>The declared surrogate budget has a minimum empirical p-value of {p_floor:.6g}; the campaign screening cutoff is {cutoff:.6g}. {'This budget has sufficient numerical resolution for that cutoff, but not a guaranteed valid null model.' if p_floor <= cutoff else 'This preliminary budget cannot clear that cutoff. It must not yield a discovery-significance claim.'} Surrogate searches are only run for otherwise promising, noncatalogued candidates that survive independent testing. An omitted calibration is not a passing test.</p>
<h2>Agent-led exploratory tests</h2><p>These proposals, code and interpretations are recorded separately. This campaign records {successful_code} successful sandboxed code experiments. Proposals, startup failures and missing experiments are not counted as executed successes. Experiment results cannot change the primary verifier or establish a planet. The model’s statistical interpretations require review; they are not the campaign’s acceptance rules.</p>{research_html or '<p>No agent-written experiment was requested.</p>'}
{''.join(sections)}<footer><p>Public observations: NASA TESS / MAST. Catalog references: NASA Exoplanet Archive. Numerical search: Astropy Box Least Squares. Inspect <code>manifest.json</code> and verify artifacts with Rediscover. No discovery or institutional endorsement is implied.</p></footer></main></body></html>'''
        w.file(cid, stem + ".html").write_text(document)
        w.seal(cid, stem + ".html")
        text = "# TESS campaign\n\n" + plan["objective"] + "\n\n" + (
            "| TIC | Period [days] | Discovery SNR | Reserved-sector SNR | Outcome |\n|---|---:|---:|---:|---|\n") + "\n".join(markdown)
        text += "\n\nNo new planet is established. Rejection means failure of these screening rules, not proof of planetary absence.\n"
        text += f"\nCalibration p-floor: {p_floor}; family cutoff: {cutoff}. No formal false-alarm probability is claimed.\n"
        w.file(cid, stem + ".md").write_text(text)
        w.seal(cid, stem + ".md")
        return {"campaign_id": cid, "html": str(w.file(cid, stem + ".html")),
                "json": str(w.file(cid, stem + ".json")), "markdown": str(w.file(cid, stem + ".md")),
                "summary": summary, "integrity": w.verify(cid)}
