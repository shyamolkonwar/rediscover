"""Deterministic, offline-readable scientific reports; no LLM-authored numbers."""
from __future__ import annotations

import base64
import html
import json
import uuid

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from gwpy.timeseries import TimeSeries

from .service import LIMITATIONS


def make_report(lab, run_id: str) -> dict:
    summary = lab.results(run_id)
    if not summary["detectors"]:
        raise ValueError("Analyze at least one detector before creating a report")
    w = lab.workspace
    inputs = w.read(run_id, "input.json")
    metadata = inputs["metadata"]
    center = metadata["gps"]
    token = uuid.uuid4().hex[:8]
    stem = "report-" + token
    from .physics import template_diagnostics

    plots = []
    plot_warnings = []
    for detector, entry in summary["detectors"].items():
        dataset = lab.dataset(run_id, detector)
        strain, fs, gps = (dataset[k] for k in ("strain", "sample_rate", "gps_start"))
        series = TimeSeries(strain, sample_rate=fs, t0=gps)
        with plt.rc_context({"figure.facecolor": "#101722", "axes.facecolor": "#101722",
                             "text.color": "#e6ecf4", "axes.labelcolor": "#b9c5d5",
                             "xtick.color": "#b9c5d5", "ytick.color": "#b9c5d5",
                             "axes.edgecolor": "#344355", "font.size": 10}):
            fig, axes = plt.subplots(4, 1, figsize=(10, 10), constrained_layout=True)
            time = np.arange(len(strain)) / fs + gps - center
            nearby = np.abs(time) < 0.5
            axes[0].plot(time[nearby], strain[nearby], color="#88aaff", lw=0.7)
            axes[0].set(title=f"{detector} · raw detector strain", ylabel="Strain [dimensionless]")
            conditioned = series.whiten(fftlength=4, overlap=2).bandpass(35, 350)
            axes[1].plot(time[nearby], conditioned.value[nearby], color="#54ddbf", lw=1)
            axes[1].set(title="Whitened and bandpassed · 35–350 Hz", ylabel="Whitened amplitude")
            try:
                q = series.q_transform(qrange=(4, 32), frange=(30, 400),
                                       outseg=(center - 0.5, center + 0.3),
                                       whiten=True, fftlength=4, overlap=2)
                image = axes[2].pcolormesh(q.times.value - center, q.frequencies.value,
                                          q.value.T, shading="auto", cmap="magma")
                axes[2].set_yscale("log")
                axes[2].set(title="Q-transform · normalized energy", ylabel="Frequency [Hz]")
                fig.colorbar(image, ax=axes[2], label="Normalized energy")
            except (ValueError, RuntimeError) as exc:
                # A missing plot is explicit, never a synthetic replacement.
                plot_warnings.append(f"{detector} Q-transform unavailable: {type(exc).__name__}")
                axes[2].text(0.1, 0.5, "Q-transform unavailable; see report warning",
                             transform=axes[2].transAxes)
            r = entry["result"]
            diagnostics = template_diagnostics(strain, fs, gps, r["mass1"], r["mass2"],
                                               r["config"]["f_low"])
            relative = diagnostics["time"] - center
            region = np.abs(relative) <= 0.5
            axes[3].plot(relative[region], diagnostics["snr"][region], color="#ffc57a")
            axes[3].axvline(r["peak_gps"] - center, color="#54ddbf", ls="--", lw=0.8)
            axes[3].set(title="Selected-template matched-filter SNR · not detection significance",
                        ylabel="Absolute SNR")
            for ax in axes:
                ax.set_xlabel("Time relative to task centre [s]")
            name = f"{detector}-{token}.png"
            fig.savefig(w.file(run_id, name), dpi=130)
            plt.close(fig)
        w.seal(run_id, name)
        plots.append((detector, name))
    rows, markdown_rows = [], []
    for detector, e in summary["detectors"].items():
        r = e["result"]
        rows.append(f"<tr><td>{detector}</td><td>{r['snr']:.3f}</td>"
                    f"<td>{r['chirp_mass']:.3f}</td><td>{r['mass1']:.1f} / {r['mass2']:.1f}</td>"
                    f"<td>{r['peak_gps']:.6f}</td><td><code>{e['evidence_id']}</code></td></tr>")
        markdown_rows.append(f"| {detector} | {r['snr']:.3f} | {r['chirp_mass']:.3f} | "
                             f"{r['mass1']:.1f} / {r['mass2']:.1f} | {r['peak_gps']:.6f} | {e['evidence_id']} |")
    combined = summary["combined"]
    notes = list(LIMITATIONS) + plot_warnings
    for e in summary["detectors"].values():
        notes.extend(e["result"].get("warnings", []))
    sources = [d.get("source", {}) for d in inputs["detectors"].values()]
    catalogs = [e for e in w.evidence(run_id) if e["tool"] == "catalog_comparison"]
    report = {**summary, "sources": sources, "plot_warnings": plot_warnings,
              "catalog": catalogs[-1]["result"] if catalogs else None}
    w.save(run_id, stem + ".json", report)
    title = str(metadata.get("name", "Opaque physics task"))
    escaped = html.escape
    plots_html = "".join(f'<figure><img alt="{d} raw strain, conditioned strain and Q-transform" '
                         f'src="data:image/png;base64,{base64.b64encode(w.file(run_id, n).read_bytes()).decode()}">'
                         f'<figcaption>{d} · real input samples; conditioning is for visualization.</figcaption></figure>'
                         for d, n in plots)
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escaped(title)} — Rediscover</title>
<style>body{{background:#0b111b;color:#e6ecf4;font:16px/1.65 system-ui,sans-serif;margin:0;padding:40px 24px}}
main{{max-width:1100px;margin:auto}}header{{border-bottom:1px solid #344355;padding-bottom:30px}}
.eyebrow{{color:#54ddbf;letter-spacing:.14em;font-size:12px;text-transform:uppercase}}h1{{font-size:clamp(32px,6vw,64px);line-height:1.1;margin:16px 0}}h2{{margin-top:40px}}
p,li,figcaption{{color:#b9c5d5}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}td,th{{padding:12px;border-bottom:1px solid #344355;text-align:left;white-space:nowrap}}
img{{width:100%;height:auto}}figure{{margin:32px 0}}code,pre{{font-size:13px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#101722;padding:20px;border:1px solid #344355}}
a{{color:#54ddbf}}.notice{{border-left:3px solid #54ddbf;padding-left:20px}}</style></head><body><main>
<header><div class="eyebrow">Rediscover / open physics / evidence report</div><h1>{escaped(title)}</h1>
<p>From public detector strain to a checkable numerical result.</p><code>Run {run_id}</code></header>
<p class="notice">This is a reproduction of a known-event analysis. It is not a new discovery, a significance measurement, or a Bayesian parameter estimate.</p>
<h2>What the calculation returned</h2><div class="scroll"><table><thead><tr><th>Detector</th><th>Peak SNR</th><th>Chirp mass [M☉, detector frame]</th><th>Bank masses [M☉]</th><th>Peak GPS [s]</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Cross-detector check</h2><pre>{escaped(json.dumps(combined, indent=2))}</pre>
<h2>Read the signal</h2>{plots_html}
<h2>Limits and quality warnings</h2><ul>{''.join('<li>'+escaped(str(n))+'</li>' for n in dict.fromkeys(notes))}</ul>
<h2>Sources and input checksums</h2><pre>{escaped(json.dumps(sources, indent=2))}</pre>
<h2>Catalog reference (different inference method)</h2><pre>{escaped(json.dumps(report['catalog'], indent=2)) if report['catalog'] else 'Not fetched. The numerical analysis does not need catalog mass values.'}</pre>
<h2>Reproduce and inspect</h2><p>The companion JSON, input snapshots, environment record and evidence files are in this run directory. Verify checksums with <code>rediscover verify {run_id}</code>. Checksums detect edits, not scientific truth.</p>
<details><summary>Analysis configuration</summary><pre>{escaped(json.dumps({d:e['result'].get('config',{}) for d,e in summary['detectors'].items()}, indent=2))}</pre></details>
<footer><p>Built with GWOSC, GWPy and PyCBC. <a href="https://github.com/shyamolkonwar/rediscover">Source and methodology</a></p></footer>
</main></body></html>'''
    w.file(run_id, stem + ".html").write_text(document)
    w.seal(run_id, stem + ".html")
    markdown = f"# {title} — Rediscover\n\nRun `{run_id}`\n\n" + (
        "| Detector | Peak SNR | Detector-frame chirp mass [M_sun] | Bank masses | Peak GPS | Evidence |\n"
        "|---|---:|---:|---|---:|---|\n") + "\n".join(markdown_rows)
    markdown += "\n\n## Cross-detector check\n```json\n" + json.dumps(combined, indent=2) + "\n```\n"
    markdown += "\n".join(f"\n![{d} strain and Q-transform]({name})\n" for d, name in plots)
    markdown += "\n## Limitations\n" + "\n".join("- " + str(n) for n in dict.fromkeys(notes))
    markdown += "\n\n## Sources\n```json\n" + json.dumps(sources, indent=2) + "\n```\n"
    w.file(run_id, stem + ".md").write_text(markdown)
    w.seal(run_id, stem + ".md")
    return {"run_id": run_id, "html": str(w.file(run_id, stem + ".html")),
            "markdown": str(w.file(run_id, stem + ".md")),
            "json": str(w.file(run_id, stem + ".json")), "plot_warnings": plot_warnings,
            "integrity": w.verify(run_id)}
