# Actual TESS campaign results

This is an experimental search-and-falsification workflow, not a new-planet announcement.

## Real campaign

- Planned stars: **12**.
- Completed discovery searches: **12**.
- Frozen follow-up ephemerides: **6**.
- Completed independent-sector tests: **6** of 6 attempts.
- Successful agent-written sandbox experiments: **2**.
- Final status counts: `{"REJECTED": 12}`.
- New planets established: **0**.

The planner was the actual Azure deployment `gpt-6-sol`. It proposed settings before flux inspection. The frozen cohort was selected from bounded MAST metadata-page intersections, not chosen because the stars were known to contain planets. Archive page order can change: use the saved plan/product IDs to reproduce this particular selection.

Sector 1 was used for discovery. Sector 4 was reserved until exact ephemerides were frozen. Each follow-up failed the independent-sector screening rule. No holdout was retuned or rerun to rescue a candidate.

For TIC 25079777, the agent proposed and implemented an event-depth consistency test and a point-outlier robustness test. Both actually executed in the restricted container. The first suggested inconsistent event depths under a simplified error model; the second removed no points under its chosen clipping rule. These exploratory interpretations are not calibrated discovery probabilities and did not determine the authoritative campaign verdict.

## Known positive control — important limitation

A separate pi Mensae c control (TIC 261136679), excluded from the discovery denominator, recovered period **6.267000940 days**. Its discovery depth SNR was **41.970** and the independent-sector value at the unchanged ephemeris was **36.129**.

However, the discovery diagnostic flags were `['odd_even_depth_mismatch']` and the holdout flags were `['sinusoidal_variability', 'significant_secondary']`. The strict screen therefore rejected the known planet. **This is not a successful end-to-end positive control.** Period recovery and a strong repeated dip are not equivalent to a validated vetting pipeline. The sensitivity and false-rejection rate need further scientific calibration. The thresholds and the recorded outcome were not changed after seeing the result.

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
