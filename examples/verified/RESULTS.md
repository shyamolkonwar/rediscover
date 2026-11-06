# Verified release results

These files contain real VM executions, not illustrative outputs. Public GWOSC strain was downloaded and processed with the code and environment recorded alongside this report. The Azure provider returned the named model identifiers; the raw numerical tool traces are included.

## Demonstration suite

| Runner | Tasks passing | Grounded model finals | Tool calls | Reported total tokens |
|---|---:|---:|---:|---:|
| baseline | 6/6 | N/A | 0 | 0 |
| gpt-6-sol | 6/6 | 6 | 24 | 38172 |
| gpt-5.5 | 6/6 | 6 | 24 | 38098 |

Tasks: GW150914-v3, GW170104, GW170814, two injected nonspinning waveforms and a no-added-signal control. All injected signals are added to actual H1 detector strain. The original GW150914 event remains elsewhere in the segment, outside the opaque search window, and may contribute to the PSD estimate.

This is a small functional test of tool orchestration, not a model ranking. Both models had the same tools. Their task instructions prescribe the scientific workflow. Success does not establish independent research ability, and there is no claim that either model improves on the deterministic numerical baseline.

## Rubric correction disclosed

The initial development run scored 5/6 for the baseline and both models. GW170814's catalog GPS was rounded to one decimal place (`1186741861.5`); the measured H1 peak differed by about 35 ms. A fixed 30-ms comparison falsely treated the rounded reference as exact.

Before the release run, the grader was corrected to respect the supplied reference precision: for named events, the allowed difference is the larger of 30 ms and half the reported time resolution plus 10.1 ms for inter-detector light-travel scale. Injected signals retain their exact reference and 30-ms timing limit. Injection chirp-mass error must be at most 20%, and all required detectors must exceed the uncalibrated SNR display threshold of 8 (or remain below it for the control). Regression tests cover both the rounding case and an injection that must still fail.

The release suite was then executed afresh on Python 3.12 with patched dependencies. The table above is from those executions, not a rewrite of the earlier scores. This correction is a reference-precision fix, not evidence of an improvement in either model.

## GW150914 measurements

- **H1:** SNR 19.439807; detector-frame chirp mass 32.558514 solar masses; peak GPS 1126259462.4274902.
- **L1:** SNR 14.022706; detector-frame chirp mass 30.469270 solar masses; peak GPS 1126259462.4216309.

## Artifacts

- `gw150914.html`: self-contained, offline report. Download it to view; GitHub does not render HTML files.
- `gw150914.json`: numerical results and public catalog reference.
- `baseline.json`, `gpt-6-sol.json`, `gpt-5.5.json`: complete task results and provider/tool traces.
- `environment.json`: scientific runtime versions.
- `source-sha256.json`: source identity at execution export.
- Release asset `gw150914-evidence.zip`: original input arrays, checksums and tool evidence. Underlying data attribution follows GWOSC; software is MIT.

These files contain no API keys or private provider endpoints. No dollar cost is inferred from token counts.
