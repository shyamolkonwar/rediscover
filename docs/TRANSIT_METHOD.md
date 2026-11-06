# Bounded TESS numerical core

This module produces diagnostic candidate screens, not planet confirmations or novelty decisions. Search rules must be frozen before examining discovery flux. Catalog periods are not supplied to the search. Campaign orchestration must keep holdout flux inaccessible until the ephemeris is frozen, prevent holdout reuse, record all target/variant trials, and enforce empirical-calibration and contamination gates.

## Stable public APIs

```python
search_transits(time, flux, flux_err, config: dict | None = None) -> dict
validate_ephemeris(time, flux, flux_err, candidate: dict,
                   config: dict | None = None) -> dict
calibrate_null(time, flux, flux_err, config: dict | None = None,
               repeats: int = 64, seed: int = 0) -> dict
```

Inputs are matching one-dimensional arrays: BTJD = BJD_TDB - 2457000 in days, positive relative flux normalized near 1, and relative flux errors. Caller applies FITS quality == 0 and removes invalid rows first. Core rejects rather than silently clips/removes invalid samples; it never removes low-flux dips. It sorts times stably, rejects duplicate times, requires 30..30000 rows and a 0.5..1500-day baseline. Errors must lie in [1e-12, 1] to avoid numerical overflow; median flux must lie in [0.5, 1.5]. No binning is performed.

Only the following configuration keys are accepted; unknown keys are errors:

| Key | Default | Allowed |
|---|---:|---|
| period_min | 1.0 | >= 0.25 days, below period_max |
| period_max | 10.0 | <= 30 days |
| durations_days | [0.05, 0.1, 0.15] | 1..10 entries, each 0.02..min(0.3, period_min/5) days |
| detrend_window_days | 1.5 | 0.5..5 days |
| period_grid_size | 10000 | integer 100..20000 |
| min_transits | 3 | integer 2..30 |
| snr_threshold | 8.0 | 5..50 |

The documented campaign variants are windows 1.5 and 2.0 days. They are separate trials, not an adaptive choice. Do not change thresholds, durations, or period boundaries after seeing a result.

### Search result

Top-level keys: `candidate`, `config`, `preprocessing`, `search_trials`, `diagnostics`, `limitations`.

`candidate` always represents the best grid peak, even for noise. It contains `period_days`, `epoch_btjd`, `duration_days`, `depth`, `depth_error`, `depth_snr`, `n_transits`, `n_well_sampled_transits`, `n_in_transit`, `observed_transit_numbers`, `transit_coverage`, `coverage_truncated`, `odd_even_sigma`, `secondary_depth`, `secondary_snr`, `sinusoid_amplitude`, `sinusoid_snr`, `candidate_flag`, `flags`, `test_statuses`, `bls_power`, and `aliases`. A returned best peak is **not** a candidate unless `candidate_flag` is true; even that flag means only that the numerical screen passed, not that empirical calibration, holdout, or sky/pixel vetting passed.

`diagnostics.periodogram` contains `period_days` and `power` lists; `diagnostics.folded` contains `phase_days` and detrended `flux`. Each list has at most 1000 values. These are decimated visualization points, not sufficient statistics or a replacement for original observations. Transit-coverage lists are limited to 1000 entries with an explicit truncation flag; scalar counts are never truncated. Outputs use JSON-compatible scalars/lists and null for unavailable measurements.

### Holdout result

Pass the exact three frozen candidate fields `period_days`, `epoch_btjd`, `duration_days` and the discovery configuration. Additional candidate fields are ignored. The result returns those exact fields and the same depth/coverage/vetting measurements at top level, plus `ephemeris_fixed: true`, `passed`, `config`, and `preprocessing`. It does **not** search BLS, optimize period/epoch/duration, or fit alternative holdout aliases. Depth and out-of-transit sinusoidal nuisance diagnostics are measured at the frozen ephemeris. `passed` is the same screening decision as `candidate_flag`; it is not a discovery decision. Missing phase coverage yields null depth/error/SNR and a failed screen, not invented measurements.

## Algorithm and predeclared screens

1. Split at gaps greater than max(five median cadences, 0.2 days). Estimate a running median separately within each segment; use nearest-edge extension. Window width is based on median cadence, odd, limited to the segment size and 2001 samples. Divide flux and errors by this trend. No lower-flux clipping is applied. This approximate cadence-based filter can distort long-duration events, segment edges, irregularly sampled data, and broad variability; it does not propagate trend uncertainty.
2. Search a finite uniform-frequency grid using Astropy `BoxLeastSquares.power(objective="likelihood", method="fast")` with the declared durations and default phase oversampling 10. The returned power is a log-likelihood improvement, **not PSD, physical significance, or formal false-alarm probability**. A fixed grid is not a completeness guarantee: phase drift over long baselines can miss short transits. No local period refinement is performed.
3. Measure weighted out-minus-in depth. Primary and phase-0.5 secondary windows are excluded from the common baseline. Error is sqrt(1/sum(inverse variance inside) + 1/sum(inverse variance outside)); individual errors are floored by 1.4826 times out-of-transit MAD. This is an independent-sample error, not a red-noise or transit-parameter posterior. Positive depth is dimming.
4. Count actual sampled transit cycles using the frozen epoch, not baseline/period. `n_transits` counts cycles with at least one sample inside the event; `n_well_sampled_transits` counts cycles with at least two. Screening requires `min_transits` well-sampled cycles. Coverage includes sample count and min(1, sample_count * median_cadence / duration), an approximate sampled-duration fraction, not an exposure-integrated completeness claim.
5. Reject with `low_depth_snr` below the declared threshold or unavailable depth; `insufficient_observed_transits` below the well-sampled-cycle threshold; `odd_even_depth_mismatch` above 5 sigma; `significant_secondary` above 5 sigma and secondary depth > 10% of primary depth; or `deep_eclipse` for depth > 0.05. Odd/even baseline covariance is ignored, making the common-baseline error denominator conservative; these sigma values are diagnostics, not multiplicity-corrected probabilities.
6. Fit weighted constant/sine/cosine nuisance models outside primary/secondary windows at P and P/2. Flag `sinusoidal_variability` if the stronger amplitude exceeds 8 independent-sample sigma and 25% of measured transit depth. This is a limited diagnostic for obvious broad variability, not exhaustive stellar-model comparison.
7. Return nearest-grid powers at P/2 and 2P when within the declared range. These aliases remain unresolved; no second search or holdout alias test is performed. Pixel contamination and sky vetting always report `not_evaluated`.

## Empirical null and honest multiplicity

`calibrate_null` accepts 1..1024 repeats, a uint32 seed, and at most 40 million total period-duration combinations across observed plus surrogate searches. It resamples raw flux/error pairs in circular moving blocks separately within observed segments. Block size is max(0.5 days, twice the largest declared duration), converted to rows using median cadence. Each surrogate repeats the entire detrending and frozen BLS grid; the statistic is the maximum BLS likelihood improvement, **not** the depth SNR at a preselected phase.

Result keys include `method`, `statistic`, `observed_statistic`, `maxima`, `repeats`, `seed`, `block_days`, `block_rows`, `exceedances`, `empirical_p`, `p_floor`, `formal_fap`, `adequate_for_discovery_claim`, `total_searches`, `period_duration_trials`, `config`, `limitations`.

With B surrogates, `empirical_p = (1 + count(null_max >= observed_max)) / (B + 1)` and `p_floor = 1 / (B + 1)`. `formal_fap` is always null and `adequate_for_discovery_claim` is always false. Blocks preserve short-range correlation only; irregular cadence, nonstationarity, long correlations, signal contamination, and uncertain detrending can invalidate a formal null interpretation. Raw signals are not removed, so injected/real transits may contaminate surrogate maxima. Counting period-duration combinations is bookkeeping, not a count of statistically independent trials (phase is also optimized).

Calibration is per target/variant. The parent must account for the entire frozen cohort and both detrending variants, even if calibration is run only on otherwise promising peaks. A 64-repeat preliminary null cannot clear a cutoff of 0.05/(12*2); increasing repeats must follow a predeclared rule, not repeated favorable-seed fishing. Even satisfying an empirical cutoff does not overcome missing pixel/sky/catalog evidence or turn this into a confirmed discovery.

## Remote-only verification and measured controls

Tests and numerical execution run only in `/home/hackyard/builds/rediscover-tess` on the authorized VM with Python 3.12 and `PYTHONPATH=src OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2`. Source edits are local; only this module, its test file, and this document are transferred. Existing VM project directories are untouched.

TDD cycles observed missing functionality/incorrect coverage fail before implementation, then passed. Controls fix random seeds, periods, shapes, and thresholds before execution. Additional tests independently calculate analytic box depth/error, forbid any BLS call during holdout, check gaps and missing coverage, validate invalid arrays/work budgets, inspect JSON, and exercise the 1024-surrogate endpoint.

Measured synthetic results:

- Injected box P=3.2 days, depth=0.008: recovered P=3.1995021337, depth=0.0077176676, depth SNR=80.4041, eight sampled transits.
- Independent fixed-ephemeris positive holdout SNR=85.0645; independent noise-only holdout SNR=0.6462, rejected.
- Trapezoid: recovered P=3.1995021337 for both 1.5/2.0-day windows; SNR=64.8808/64.8955.
- Three white-noise seeds: best-peak SNR=5.6790, 4.9270, 5.3809; all rejected.
- Primary/secondary binary: best peak at half period 1.6003201708; odd/even sigma=105.6038, rejected.
- Sinusoidal control: nuisance amplitude SNR=64.6878, flagged and rejected.
- Seven surrogate injected-signal calibration: observed maximum=3283.0971; surrogate maxima 339.6338..568.9917; empirical p and floor both 0.125, explicitly inadequate.
- 1024-surrogate short-correlated-noise field: empirical p=0.1619512195, floor=0.0009756097561; no formal FAP or discovery claim.

A separate real-data control was read in memory from NASA's public S3 FITS URL below on the VM. Only finite, quality-zero PDCSAP rows were normalized; the **unchanged default 1..10-day blind search** was used, not a catalog-centered grid. TIC 261136679 sector 1 contained 18264 usable rows. Search took 1.009 seconds and recovered P=6.2662154540 days, epoch BTJD=1325.5119604951, duration=0.1 days, depth=0.0002615716, depth SNR=40.2197, five observed transits; odd/even sigma=3.7319, secondary SNR=-2.2075, sinusoid SNR=4.2340, numerical candidate flag true. The independently supplied control expectation was P approximately 6.2678 days. This is a known-signal recovery control, not novelty evidence, and no real holdout/null assessment was performed here.

Source: https://stpubdata.s3.us-east-1.amazonaws.com/tess/public/tid/s0001/0000/0002/6113/6679/tess2018206045859-s0001-0000000261136679-0120-s_lc.fits

Run the focused suite remotely with `.venv/bin/python -m pytest tests/test_transit.py -q -W error`; lint only owned files with `.venv/bin/ruff check src/rediscover/transit.py tests/test_transit.py`.
