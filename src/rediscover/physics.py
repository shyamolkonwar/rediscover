"""Bounded educational gravitational-wave analysis (detector-frame masses)."""
from __future__ import annotations

import numpy as np

DEFAULT_MASSES = (20., 25., 30., 35., 40., 45., 50.)
PSD_SECONDS = 4.0
CANDIDATE_SNR = 8.0  # Display heuristic only, never a calibrated significance.


def _prepare(strain, sample_rate, f_low=30.0):
    from pycbc.psd import interpolate, inverse_spectrum_truncation, welch
    from pycbc.types import TimeSeries
    from scipy.signal.windows import tukey

    quality_check(strain, sample_rate)
    x = np.array(strain, dtype=np.float64, copy=True)
    if x.size % 2:
        raise ValueError("an even number of strain samples is required")
    f_high = min(1024., .45 * sample_rate)
    if not np.isfinite(f_low) or not 20 <= f_low < f_high:
        raise ValueError("f_low must be at least 20 Hz and below the upper filter bound")
    x -= np.mean(x)
    raw = TimeSeries(x, delta_t=1. / sample_rate)
    psd = welch(raw, seg_len=int(PSD_SECONDS * sample_rate),
                seg_stride=int(PSD_SECONDS * sample_rate / 2), avg_method="median")
    psd = interpolate(psd, 1. / raw.duration)
    psd.resize(x.size // 2 + 1)
    # Welch is strictly positive for valid noise; fail rather than hide bad bins.
    if np.any(~np.isfinite(psd.numpy())) or np.any(psd.numpy() <= 0):
        raise ValueError("estimated PSD has nonpositive or nonfinite bins")
    psd = inverse_spectrum_truncation(psd, int(PSD_SECONDS * sample_rate),
                                     low_frequency_cutoff=f_low, trunc_method="hann")
    data = TimeSeries(x * tukey(x.size, alpha=4. / raw.duration),
                      delta_t=1. / sample_rate)
    return data, psd, f_high


def _bank(masses):
    values = np.asarray(DEFAULT_MASSES if masses is None else masses, dtype=float)
    if (values.ndim != 1 or not 1 <= values.size <= 15
            or not np.all(np.isfinite(values)) or np.any(values < 10)
            or np.any(values > 100)):
        raise ValueError("mass grid must contain 1–15 finite masses from 10 to 100 solar masses")
    values = sorted(set(values.tolist()))
    return [(m1, m2) for m1 in values for m2 in values if m1 >= m2]


def _guard(bank, f_low):
    from pycbc.pnutils import get_imr_duration
    longest = max(float(get_imr_duration(a, b, 0, 0, f_low, approximant="IMRPhenomD"))
                  for a, b in bank)
    # PSD inverse filter, taper and waveform support all need uncontaminated padding.
    return max(8., float(np.ceil(longest + PSD_SECONDS + 2.)))


def _template(m1, m2, data, f_low, f_high, phase=0.):
    from pycbc.waveform import get_fd_waveform
    hp, _ = get_fd_waveform(approximant="IMRPhenomD", mass1=m1, mass2=m2,
                            spin1z=0., spin2z=0., distance=1., coa_phase=phase,
                            delta_f=data.delta_f, f_lower=f_low, f_final=f_high)
    hp.resize(len(data) // 2 + 1)
    return hp


def _interval(n, sample_rate, gps_start, center, window, guard):
    if not all(np.isfinite(v) for v in (gps_start, center, window)) or window <= 0:
        raise ValueError("GPS times must be finite and search_window must be positive")
    relative = center - gps_start
    if relative - window < guard or relative + window > n / sample_rate - guard:
        raise ValueError("search interval overlaps filter edges; provide more strain padding")
    lo = int(np.ceil((relative - window) * sample_rate))
    hi = int(np.floor((relative + window) * sample_rate)) + 1
    if hi <= lo:
        raise ValueError("search interval contains no sample")
    return lo, hi


def analyze_detector(strain: np.ndarray, sample_rate: float, gps_start: float,
                     search_center: float, search_window: float = .3,
                     masses: list[float] | None = None, f_low: float = 30.) -> dict:
    """Maximize two-phase matched-filter SNR over a finite bank and local time window.

    search_window is a HALF-width in seconds. Component and chirp masses are
    detector-frame solar masses, not posterior estimates. No significance is inferred.
    """
    from pycbc.filter import matched_filter

    quality = quality_check(strain, sample_rate)
    bank = _bank(masses)
    data, psd, f_high = _prepare(strain, sample_rate, f_low)
    guard = _guard(bank, f_low)
    lo, hi = _interval(len(data), sample_rate, gps_start, search_center, search_window, guard)
    best = None
    for m1, m2 in bank:
        hp = _template(m1, m2, data, f_low, f_high)
        rho = matched_filter(hp, data, psd=psd, low_frequency_cutoff=f_low,
                             high_frequency_cutoff=f_high)
        magnitude = np.abs(rho.numpy()[lo:hi])
        if not np.all(np.isfinite(magnitude)):
            raise ValueError("matched filter produced nonfinite SNR")
        index = int(np.argmax(magnitude))
        snr = float(magnitude[index])
        if best is None or snr > best["snr"]:
            best = {"snr": snr, "peak_gps": float(gps_start + (lo + index) / sample_rate),
                    "mass1": float(m1), "mass2": float(m2),
                    "chirp_mass": float((m1 * m2)**.6 / (m1 + m2)**.2)}
    warnings = list(quality["warnings"]) + [
        "Fixed-template SNR maximized over this finite bank/time window is not a false-alarm probability.",
        "Masses are coarse detector-frame nonspinning template estimates, not Bayesian credible intervals.",
        "PSD is estimated from this segment and may include the signal; no glitch veto is applied."]
    candidate = best["snr"] >= CANDIDATE_SNR
    if not candidate:
        warnings.append("No candidate above the uncalibrated display threshold; the returned peak can be noise.")
    best.update({"candidate": bool(candidate), "mass_frame": "detector",
                 "snr_kind": "fixed-template matched-filter SNR", "warnings": warnings,
                 "config": {"approximant": "IMRPhenomD", "spins": "zero",
                            "bank_size": len(bank), "masses": sorted(set(a for a, _ in bank)),
                            "f_low": float(f_low), "f_high": float(f_high),
                            "sample_rate": float(sample_rate), "psd_method": "median Welch",
                            "psd_segment_seconds": PSD_SECONDS, "psd_overlap_fraction": .5,
                            "inverse_spectrum_seconds": PSD_SECONDS,
                            "inverse_spectrum_window": "hann", "edge_guard_seconds": guard,
                            "taper_seconds_each_edge": 2., "search_center": float(search_center),
                            "search_window_half_width": float(search_window),
                            "candidate_threshold": CANDIDATE_SNR}})
    return best


def template_diagnostics(strain: np.ndarray, sample_rate: float, gps_start: float,
                         mass1: float, mass2: float, f_low: float = 30.) -> dict:
    """Return edge-cropped arrays ``time`` (GPS seconds), ``snr`` (absolute rho).

    This is the fixed named template across all valid times, not bank-maximized
    SNR, and not a JSON result. Do not use these arrays as a significance estimate.
    """
    from pycbc.filter import matched_filter

    _bank([mass1, mass2])
    if not np.isfinite(gps_start):
        raise ValueError("gps_start must be finite")
    data, psd, f_high = _prepare(strain, sample_rate, f_low)
    guard = _guard([(mass1, mass2)], f_low)
    edge = int(np.ceil(guard * sample_rate))
    if 2 * edge >= len(data):
        raise ValueError("insufficient strain padding for template diagnostics")
    hp = _template(mass1, mass2, data, f_low, f_high)
    rho = matched_filter(hp, data, psd=psd, low_frequency_cutoff=f_low,
                         high_frequency_cutoff=f_high)
    times = gps_start + np.arange(edge, len(data) - edge) / sample_rate
    return {"time": times, "snr": np.abs(rho.numpy()[edge:-edge])}


def condition_strain(strain: np.ndarray, sample_rate: float) -> np.ndarray:
    """Dimensionless whitened 30–min(350, 0.4*fs) Hz strain for figures only.

    Shape and time origin are preserved; invalid first/last eight seconds are ZERO
    placeholders and must be excluded from plots/statistics. Filtering for SNR is
    independent and uses the original strain, never this display array.
    """
    from scipy.signal import butter, sosfiltfilt

    data, psd, _ = _prepare(strain, sample_rate)
    white = data.to_frequencyseries() / psd**.5
    white[:int(np.ceil(30. / data.delta_f))] = 0
    y = white.to_timeseries().numpy() * np.sqrt(2. / sample_rate)
    sos = butter(4, [30., min(350., .4 * sample_rate)], btype="bandpass",
                 fs=sample_rate, output="sos")
    y = sosfiltfilt(sos, y)
    guard = int(8 * sample_rate)
    y[:guard] = 0
    y[-guard:] = 0
    if not np.all(np.isfinite(y)):
        raise ValueError("whitening produced nonfinite samples")
    return y


def inject_signal(noise: np.ndarray, sample_rate: float, gps_start: float,
                  peak_gps: float, mass1: float, mass2: float, target_snr: float,
                  seed: int = 0) -> np.ndarray:
    """Add a nonspinning IMRPhenomD plus-polarization waveform to supplied noise.

    target_snr is the optimal signal-only SNR in the pre-injection estimated PSD,
    not a promise about the noisy recovered maximum. The seed controls phase only.
    This is a single-detector injection, not a coherent sky-projected network signal.
    """
    from pycbc.filter import sigma

    _bank([mass1, mass2])
    if not np.isfinite(target_snr) or not 0 < target_snr <= 100:
        raise ValueError("target_snr must be finite and in (0, 100]")
    data, psd, f_high = _prepare(noise, sample_rate)
    guard = _guard([(mass1, mass2)], 30.)
    _interval(len(data), sample_rate, gps_start, peak_gps, 1. / sample_rate, guard)
    phase = float(np.random.default_rng(seed).uniform(0, 2 * np.pi))
    hp = _template(mass1, mass2, data, 30., f_high, phase)
    norm = float(sigma(hp, psd=psd, low_frequency_cutoff=30., high_frequency_cutoff=f_high))
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError("injection waveform has invalid PSD norm")
    # FD templates use coalescence at t=0. Negative Fourier phase translates to +t.
    shifted = hp * np.exp(-2j * np.pi * hp.sample_frequencies.numpy() * (peak_gps - gps_start))
    signal = shifted.to_timeseries(delta_t=1. / sample_rate).numpy()
    return np.asarray(noise, dtype=np.float64) + signal * (target_snr / norm)


def quality_check(strain: np.ndarray, sample_rate: float) -> dict:
    """Validate a contiguous strain array; GWOSC data-quality flags are separate."""
    if not np.isfinite(sample_rate) or not 512 <= sample_rate <= 16384:
        raise ValueError("sample_rate must be finite and between 512 and 16384 Hz")
    x = np.asarray(strain, dtype=np.float64)
    if x.ndim != 1 or x.size > 2**24 or x.size / sample_rate < 24:
        raise ValueError("strain must be one-dimensional, at least 24 s, at most 2**24 samples")
    if not np.all(np.isfinite(x)):
        raise ValueError("strain contains nonfinite samples")
    scale = float(np.std(x))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("strain is constant or numerically invalid")
    changes = np.flatnonzero(np.diff(x) != 0)
    runs = np.diff(np.r_[-1, changes, x.size - 1])
    if np.max(runs) >= sample_rate / 4:
        raise ValueError("strain contains a flat gap of at least 0.25 s")
    dx = np.diff(x)
    robust_diff = float(np.median(np.abs(dx - np.median(dx))))
    if robust_diff <= 0 or np.max(np.abs(dx)) > 100 * robust_diff:
        raise ValueError("strain contains an extreme discontinuity or impulse")
    warnings = ["Array checks do not replace detector data-quality flags or stationarity tests."]
    if np.max(np.abs(x - np.median(x))) > 12 * scale:
        warnings.append("Large strain excursion: a transient or glitch may bias the analysis.")
    return {"valid": True, "samples": int(x.size), "duration": float(x.size / sample_rate),
            "sample_rate": float(sample_rate), "rms": scale, "warnings": warnings}
