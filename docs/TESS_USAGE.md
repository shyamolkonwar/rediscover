# TESS research workflow

## Scope and evidence tiers

Rediscover searches SPOC 120-second light curves from MAST using Astropy Box Least Squares. It freezes a cohort and search configuration before its own flux searches; then freezes candidate ephemerides before requesting reserved-sector flux. The AI planner and exploratory code cannot change the verifier's thresholds or approve a discovery.

The output states are **REJECTED**, **UNRESOLVED**, **KNOWN_SIGNAL_RECOVERED**, and **POTENTIALLY_UNCATALOGUED_CANDIDATE**. None means a new planet has been confirmed. Rejection is a screening outcome, not proof that the star has no planets. The first campaign found no survivors; the known pi Mensae c control recovered its period but failed the conservative vetoes. Read the actual results and do not treat unit-test success as scientific validation of sensitivity or specificity.

## Planning

`rediscover tess plan` queries one bounded metadata page per sector, intersects TIC IDs, sorts that snapshot numerically and selects the requested count. Archive pagination ordering can change, so rerunning metadata discovery is not guaranteed to select identical targets. The saved cohort, product identifiers and plan—not a later archive query—are the reproducibility input. This sample is not population-representative.

Defaults are discovery Sector 1, reserved Sector 4 and 12 targets. No reserved flux is needed for metadata selection. An explicit `--model DEPLOYMENT` requests a paid model proposal before the campaign is created. It can choose bounded periods, durations and two different detrending windows, but not relax SNR/repetition rules.

Configuration includes:
- `period_min`, `period_max`, `durations_days`, `period_grid_size`.
- Distinct `detrend_window_days` and `alternate_window_days`.
- Fixed screening floor: SNR 8 and three well-sampled transit cycles.
- `null_repeats` (16–1024) with a joint period-duration-surrogate work bound.
- A uint32 `seed`; never repeatedly choose favorable seeds.
- Integer `max_code_experiments` (0–5).
- `search_schedule_seconds`: a **soft between-target scheduling deadline**, not a hard execution timeout. An in-progress target may finish after it. The stored deadline survives resumption and includes downtime; skipped targets stay in the denominator. Development snapshots used the legacy name `max_seconds` for this same soft behavior.

Core arrays, grids, remote response sizes and generated-code runtime have separate enforced bounds. Null-review work is not covered by the soft search schedule.

## Research and held-out validation

```sh
rediscover tess plan --count 12 --model YOUR_DEPLOYMENT
rediscover tess search CAMPAIGN_ID
# Optional, requires a prepared Docker image and explicit consent:
rediscover tess research CAMPAIGN_ID --model YOUR_DEPLOYMENT --allow-code
rediscover tess freeze CAMPAIGN_ID
rediscover tess validate CAMPAIGN_ID
rediscover tess review CAMPAIGN_ID
rediscover tess report CAMPAIGN_ID
```

The built-in research runner reserves the requested remaining slots atomically before any paid proposal. Provider failures consume reservations rather than silently refunding retry opportunities. At most one critique is requested per reserved batch, and none for a batch with no successful experiment. Output caps and slot counts are not a guaranteed dollar spending cap; provider input tokens also cost money.

The sandbox receives only `time`, `flux` and `flux_err` from the discovery observation. It cannot see reserved observations, the verifier, credentials, the Docker socket or the rest of the run directory. Results are untrusted exploratory measurements, not proof that generated statistical code is correct. A model may choose an inappropriate test; its code and assumptions are retained for review.

Once hypotheses are frozen, new exploration is blocked. Validation records consumption before fetching the reserved data. If that phase is interrupted, it cannot be repeated in that campaign. A completed validation returns its saved result instead of recomputing. This is within-campaign protection; it cannot prevent a trusted person inspecting public data or creating a different campaign.

Review may be resumed from sealed review evidence to derive a missing verdict without new catalog calls, calibration or holdout access. Conflicting/unsealed artifacts fail integrity checks rather than being silently replaced.

## Scientific checks and unresolved issues

- Use BJD_TDB minus 2457000 (BTJD), from validated FITS metadata; do not mix UTC/JD conventions.
- Quality-zero finite flux/error rows are retained; no lower-flux clipping removes transit candidates.
- The highest BLS peak is tested under two predeclared detrending variants.
- Fixed-ephemeris validation measures the exact discovery period, epoch and duration; it does not rerun BLS or refine the ephemeris on the holdout.
- Odd/even depths, secondary eclipses, broad variability and depth/coverage checks are conservative diagnostics. Their simplified noise assumptions can reject real planets, as the recorded control demonstrates.
- Approximate centroid/crowding checks cannot replace pixel-level contamination analysis.
- NASA TOI and confirmed-planet tables are checked by TIC and period/alias. A TOI may itself be a false positive. Empty/error responses are distinguished. Catalog error never counts as novelty clearance.
- A bounded Crossref metadata query is only a literature starting point. Full-text/ExoFOP and expert review remain required.
- The moving-block surrogate procedure reruns the complete search. It preserves only limited correlations and does not establish a formal false-alarm probability. Its empirical floor is explicit. With the default 64 repeats, a 12-target/two-variant campaign cannot clear its multiplicity cutoff; it is a preliminary screen, not a significance claim.

## Reports and provenance

Every planned target remains in the denominator. Reports separately count completed searches, failed/skipped searches, holdout attempts, completed evaluations, and successful code experiments. A downloaded file or proposed experiment is not a successful scientific test. The dossier includes the actual frozen selection description, source URLs/checksums, catalog snapshots, raw numerical records, proposed tests, executable code, outcomes and limitations.

New plans record source hashes and environment versions at creation. Earlier development campaign snapshots are preserved as originally written; publication-time source hashes are labelled separately rather than backfilled as execution provenance.

The original LIGO CLI and MCP commands remain supported. TESS catalog checks do not imply LIGO discovery significance, and the original LIGO benchmark is not a TESS evaluation.
