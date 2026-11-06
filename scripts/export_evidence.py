"""Export actual local release runs; never creates synthetic success records.

Run on the machine where the analyses were executed:
    python scripts/export_evidence.py --runs .cache/release
"""
import argparse
import json
import shutil
from pathlib import Path

from rediscover.data import sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "examples" / "verified"
    assets = root / "docs" / "assets"
    output.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    rows = []
    for label in ("baseline", "gpt-6-sol", "gpt-5.5"):
        source = args.runs / f"{label}.json"
        result = json.loads(source.read_text())
        result.pop("path", None)
        actual_total = len(result["tasks"]) + len(result["setup_failures"])
        actual_passed = sum(t["passed"] for t in result["tasks"])
        assert result["total"] == actual_total and result["passed"] == actual_passed
        (output / f"{label}.json").write_text(json.dumps(result, indent=2) + "\n")
        agents = [t["agent"] for t in result["tasks"] if t.get("agent")]
        rows.append({"label": label, "passed": actual_passed, "total": actual_total,
                     "grounded": sum(a["status"] == "completed" for a in agents),
                     "tokens": sum(a["total_tokens"] for a in agents),
                     "tool_calls": sum(a["tool_calls"] for a in agents)})
    report_info = json.loads((args.runs / "report.json").read_text())
    report_path = Path(report_info["json"])
    report = json.loads(report_path.read_text())
    shutil.copyfile(report_path, output / "gw150914.json")
    shutil.copyfile(report_info["html"], output / "gw150914.html")
    run_dir = report_path.parent
    stem_suffix = report_path.stem.split("report-", 1)[1]
    shutil.copyfile(run_dir / f"H1-{stem_suffix}.png", assets / "gw150914-h1.png")
    shutil.copyfile(run_dir / f"L1-{stem_suffix}.png", assets / "gw150914-l1.png")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    for name, digest in manifest.items():
        assert sha256(run_dir / name) == digest, name
    shutil.copyfile(run_dir / "environment.json", output / "environment.json")
    evidence_dir = root / "release-assets"
    evidence_dir.mkdir(exist_ok=True)
    shutil.make_archive(str(evidence_dir / "gw150914-evidence"), "zip", run_dir)
    source_hashes = {str(p.relative_to(root)): sha256(p) for p in sorted((root / "src").rglob("*.py"))}
    (output / "source-sha256.json").write_text(json.dumps(source_hashes, indent=2) + "\n")
    markdown = """# Verified release results

These files contain real VM executions, not illustrative outputs. Public GWOSC strain was downloaded and processed with the code and environment recorded alongside this report. The Azure provider returned the named model identifiers; the raw numerical tool traces are included.

## Demonstration suite

| Runner | Tasks passing | Grounded model finals | Tool calls | Reported total tokens |
|---|---:|---:|---:|---:|
"""
    for row in rows:
        markdown += f"| {row['label']} | {row['passed']}/{row['total']} | {row['grounded'] if row['label'] != 'baseline' else 'N/A'} | {row['tool_calls']} | {row['tokens']} |\n"
    markdown += """
Tasks: GW150914-v3, GW170104, GW170814, two injected nonspinning waveforms and a no-added-signal control. All injected signals are added to actual H1 detector strain. The original GW150914 event remains elsewhere in the segment, outside the opaque search window, and may contribute to the PSD estimate.

This is a small functional test of tool orchestration, not a model ranking. Both models had the same tools. Their task instructions prescribe the scientific workflow. Success does not establish independent research ability, and there is no claim that either model improves on the deterministic numerical baseline.

## Rubric correction disclosed

The initial development run scored 5/6 for the baseline and both models. GW170814's catalog GPS was rounded to one decimal place (`1186741861.5`); the measured H1 peak differed by about 35 ms. A fixed 30-ms comparison falsely treated the rounded reference as exact.

Before the release run, the grader was corrected to respect the supplied reference precision: for named events, the allowed difference is the larger of 30 ms and half the reported time resolution plus 10.1 ms for inter-detector light-travel scale. Injected signals retain their exact reference and 30-ms timing limit. Injection chirp-mass error must be at most 20%, and all required detectors must exceed the uncalibrated SNR display threshold of 8 (or remain below it for the control). Regression tests cover both the rounding case and an injection that must still fail.

The release suite was then executed afresh on Python 3.12 with patched dependencies. The table above is from those executions, not a rewrite of the earlier scores. This correction is a reference-precision fix, not evidence of an improvement in either model.

## GW150914 measurements

"""
    for d, entry in report["detectors"].items():
        r = entry["result"]
        markdown += f"- **{d}:** SNR {r['snr']:.6f}; detector-frame chirp mass {r['chirp_mass']:.6f} solar masses; peak GPS {r['peak_gps']:.7f}.\n"
    markdown += "\n## Artifacts\n\n- `gw150914.html`: self-contained, offline report. Download it to view; GitHub does not render HTML files.\n- `gw150914.json`: numerical results and public catalog reference.\n- `baseline.json`, `gpt-6-sol.json`, `gpt-5.5.json`: complete task results and provider/tool traces.\n- `environment.json`: scientific runtime versions.\n- `source-sha256.json`: source identity at execution export.\n- Release asset `gw150914-evidence.zip`: original input arrays, checksums and tool evidence. Underlying data attribution follows GWOSC; software is MIT.\n\nThese files contain no API keys or private provider endpoints. No dollar cost is inferred from token counts.\n"
    (output / "RESULTS.md").write_text(markdown)
    print(json.dumps({"exported": str(output), "rows": rows, "source_files": len(source_hashes)}))


if __name__ == "__main__":
    main()
