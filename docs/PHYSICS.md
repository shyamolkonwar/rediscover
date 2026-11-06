# Numerical method and verified GW150914 reproduction

This is an event-centred educational reproduction, not an independent discovery
or an astrophysical significance calculation. All component and chirp masses below
are **detector-frame solar masses**. The finite nonspinning bank does not provide
posterior distributions, credible intervals, source-frame masses, or spin estimates.

## Public numerical API

```python
analyze_detector(strain, sample_rate, gps_start, search_center,
                 search_window=0.3, masses=None, f_low=30.0) -> dict
quality_check(strain, sample_rate) -> dict
condition_strain(strain, sample_rate) -> numpy.ndarray
inject_signal(noise, sample_rate, gps_start, peak_gps,
              mass1, mass2, target_snr, seed=0) -> numpy.ndarray
template_diagnostics(strain, sample_rate, gps_start,
                     mass1, mass2, f_low=30.0) -> dict
```

- `analyze_detector`: JSON-serializable result containing `snr`, `peak_gps`,
  `mass1`, `mass2`, `chirp_mass`, `candidate`, `mass_frame`, `snr_kind`, `warnings`,
  and `config`. **`search_window` is a half-width**, in seconds. `peak_gps` is
  the template coalescence time of the sampled peak; there is no subsample fit.
  Scalar results carry no arrays or hidden injection truth.
- `quality_check`: returns `valid`, `samples`, `duration`, `sample_rate`, `rms`
  (the mean-subtracted standard deviation), and warnings. Invalid inputs raise
  `ValueError`; invalid data are never silently repaired or interpolated.
- `condition_strain`: dimensionless whitened, bandpassed display array with the
  original shape and time origin. **The first/last eight seconds are zero
  placeholders for invalid filter edges: exclude them from figures/statistics.**
  The scientific matched filter operates independently on the input strain.
- `template_diagnostics`: arrays `time` (absolute GPS seconds) and `snr`
  (absolute two-phase matched-filter SNR), with corrupt edges removed. These are
  for the single named template, not a bank-maximized SNR time series. This
  array-valued result is deliberately separate from JSON analysis results.
- `inject_signal`: new noise-plus-signal array, without mutating its input.
  Uses nonspinning IMRPhenomD plus polarization; seed controls coalescence phase.
  This is one detector, not a sky-projected coherent detector network. Truth and
  grading belong outside the public result and agent-visible task metadata.

## Matched filtering

1. Validate finite one-dimensional strain, 24 seconds minimum, at most `2**24`
   samples, and sampling rates from 512 to 16384 Hz. Filtering also requires an
   even number of samples. Reject constant arrays, flat runs of at least 0.25 s,
   and extreme discontinuities/impulses relative to the robust first-difference
   scale. These conservative checks are not a complete glitch-identification
   algorithm and do not certify stationarity.
2. Subtract the sample mean. Estimate a one-sided noise PSD with PyCBC's
   bias-corrected median Welch estimator: 4 s Hann segments, 50% overlap.
   Interpolate to the full data frequency grid. Reject invalid PSD bins.
3. Apply PyCBC inverse-spectrum truncation using a 4 s Hann-truncated inverse
   ASD filter, with the requested lower frequency cutoff. Apply a 2 s Tukey
   taper at each data boundary. No event-dependent tuning is performed.
4. Generate a finite IMRPhenomD, zero-spin bank. Default component grid:
   `[20, 25, 30, 35, 40, 45, 50]`; retain `mass1 >= mass2`, yielding 28 templates.
   User grids accept at most 15 entries, each in `[10, 100]` solar masses;
   duplicates are removed. `f_low >= 20 Hz`; the upper cutoff is
   `min(1024 Hz, 0.45 * sample_rate)`.
5. For each template use the standard one-sided PSD normalization:

   `rho(t) = 4 integral[h*(f) s(f) exp(2 pi i f t) / S_n(f)] df / sigma`,

   `sigma^2 = 4 integral[|h(f)|^2 / S_n(f)] df`.

   Maximize `abs(rho)` over the requested samples and the finite bank. The two
   quadratures maximize over phase. The template FD time convention places
   coalescence at zero; injection translates it using `exp(-2 pi i f t_c)`.
6. Exclude at least 8 s from both ends. For longer custom templates, enlarge the
   guard to the ceiling of the longest PyCBC IMR duration plus the 4 s inverse
   filter and 2 s taper. Reject a search window that enters either guard.
7. Compute chirp mass as `(mass1*mass2)**(3/5)/(mass1+mass2)**(1/5)`.

The reported **fixed-template matched-filter SNR**, after maximization over the
finite bank and time window, is not a false-alarm probability. `candidate` uses
an **uncalibrated display threshold of 8** and is not a detection-significance
claim. A negative control still returns the largest noise peak and its best
matching masses, but marks `candidate=False`; those masses are not an inferred
binary. This package performs neither time-slide backgrounds nor a chi-square
signal-consistency veto nor calibrated false-alarm-rate estimation.

## Display conditioning and injections

Display whitening divides the Fourier strain by the estimated ASD, then
multiplies its inverse transform by `sqrt(2/sample_rate)` for dimensionless white
noise normalization. A fourth-order forward/backward Butterworth bandpass keeps
30–`min(350, 0.4*sample_rate)` Hz. Bandpassing reduces white-noise RMS below one.
The report layer may compute its own Q transform or spectrogram from strain;
the core supplies conditioning and separate fixed-template SNR diagnostics.

Injection amplitude is normalized to the **optimal signal-only SNR in the
pre-injection noise PSD**, using the same 30 Hz lower and sampling-dependent
upper cutoff. The actual recovered SNR varies due to noise, bank mismatch,
finite time sampling and re-estimated PSD. It is not forced to the target.
Target SNR must be finite and in `(0,100]`. Input noise is retained exactly, with
only the physical waveform added. Independent white-noise time-domain norm,
phase-seeded repeatability, amplitude linearity and coalescence timing are tested.

## Data quality responsibilities

The scalar array API cannot see GWOSC DQ masks, injection flags or missing time
metadata. The data/service layer must validate these and preserve their warnings.
Continuous-wave hardware injection flags must not be misrepresented as CBC
hardware injections or silently discarded. A valid array does not override a
failed detector-quality flag. The PSD uses the supplied segment, including any
short signal; robust median averaging mitigates but does not eliminate this
contamination. Longer off-source PSD estimation is outside this first version.

## Initial numerical validation (before release dependency upgrade)

Executed against official GWOSC GW150914 v3 32-second HDF5 strain, sampled at
4096 Hz, GPS start `1126259447`, search centre `1126259462.4`, half-width 0.3 s,
with the unchanged default bank and 30 Hz lower cutoff:

| Detector | Fixed-template SNR | Peak GPS | mass1 | mass2 | Chirp mass |
|---|---:|---:|---:|---:|---:|
| H1 | 19.4398071518 | 1126259462.4274902 | 40 | 35 | 32.5585135241 |
| L1 | 14.0227063420 | 1126259462.4216309 | 35 | 35 | 30.4692697154 |

At the off-source search centre `1126259457.3` (half-width 0.2 s), H1 and L1
returned SNR `4.0020288510` and `3.7563020082`, both `candidate=False`.
Adding a 35+30 solar-mass waveform there with target optimal SNR 18 and seed 11
recovered respectively SNR `18.8534606457` and `18.1276756123`. Both recovered
35+30 and peak GPS `1126259457.3000488`. These fixtures use an off-source window
within the same real 32 s segment: the original event remains elsewhere in the
segment and contributes to its PSD estimate. They are not pure signal-free
32-second archival segments.

Sources:
- [H1 official HDF5](https://gwosc.org/eventapi/json/GWTC-1-confident/GW150914/v3/H-H1_GWOSC_4KHZ_R1-1126259447-32.hdf5)
- [L1 official HDF5](https://gwosc.org/eventapi/json/GWTC-1-confident/GW150914/v3/L-L1_GWOSC_4KHZ_R1-1126259447-32.hdf5)
- [PyCBC GW150914 matched-filter tutorial](https://pycbc.org/pycbc/latest/html/gw150914.html)

Downloaded SHA-256:
- H1: `c5ea87beced5094b56b4d694f3a36e6d59f74d3a46e546b980a6a199d1f252a9`
- L1: `9d65bde82f7ec035bea4c02228bce4acb3dcaae774c047edce71ef2ad64f1cc4`

Reproduce with files in a local directory on the authorized compute host:

```sh
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
REDISCOVER_REAL_DATA=.cache/manual-core PYTHONPATH=src \
.venv/bin/python -m pytest tests/test_physics.py -q -s
```

Observed result: **13 passed, 1 warning in 4.33 s**. Numerical environment:
Python 3.10, NumPy 2.2.6, SciPy 1.15.3, PyCBC 2.9.0, LALSuite 7.26.16.
Coverage includes malformed
arrays, filter/parameter bounds, deterministic white-noise negative controls,
PSD scale invariance, independent white-noise signal norm, seeded injections,
merger time and coarse mass recovery, display whitening, SNR diagnostics, both
real detectors and injections in real off-source windows. Without the opt-in
real-data directory, the two real-detector tests are skipped.

The initial Python 3.10 environment needed an old setuptools for PyCBC 2.9's
`pkg_resources` use. A subsequent security audit rejected that environment for
release. The released project requires Python 3.12/3.13, PyCBC 2.11 or later,
setuptools 84.1 or later, Pillow 13 and patched filelock. All numerical tests and
the full real-data/model suite were rerun on Python 3.12. See
[`examples/verified/environment.json`](../examples/verified/environment.json)
and the verified results for the actual release environment. The package does
not monkeypatch PyCBC or replace physical waveform generation with fixtures.
