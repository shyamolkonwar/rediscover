"""Bounded, diagnostic-only transit searches; never a planet confirmation."""
from __future__ import annotations

import numpy as np
from astropy.timeseries import BoxLeastSquares
from scipy.ndimage import median_filter

_DEFAULTS = {
    "period_min": 1.0,
    "period_max": 10.0,
    "durations_days": [0.05, 0.1, 0.15],
    "detrend_window_days": 1.5,
    "period_grid_size": 10000,
    "min_transits": 3,
    "snr_threshold": 8.0,
}


def _config(config):
    cfg = {**_DEFAULTS, **(config or {})}
    if set(cfg) - set(_DEFAULTS):
        raise ValueError("Unknown search configuration keys")
    for key in ("period_min", "period_max", "detrend_window_days", "snr_threshold"):
        cfg[key] = float(cfg[key])
        if not np.isfinite(cfg[key]):
            raise ValueError(f"Non-finite {key}")
    if not 0.25 <= cfg["period_min"] < cfg["period_max"] <= 30:
        raise ValueError("Periods must satisfy 0.25 <= min < max <= 30 days")
    if not 0.5 <= cfg["detrend_window_days"] <= 5:
        raise ValueError("Detrending window must be 0.5..5 days")
    for key, lo, hi in (("period_grid_size", 100, 20000), ("min_transits", 2, 30)):
        value = cfg[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float, np.number))
                or not np.isfinite(value) or not lo <= value <= hi or int(value) != value):
            raise ValueError(f"Invalid {key}")
        cfg[key] = int(value)
    if not 5 <= cfg["snr_threshold"] <= 50:
        raise ValueError("SNR threshold must be 5..50")
    durations = np.asarray(cfg["durations_days"], dtype=float)
    if durations.ndim != 1 or not 1 <= len(durations) <= 10:
        raise ValueError("Supply 1..10 durations")
    if (not np.all(np.isfinite(durations)) or np.any(durations < 0.02)
            or np.any(durations > min(0.3, cfg["period_min"] / 5))):
        raise ValueError("Durations must be 0.02..0.3 days and <= period_min/5")
    cfg["durations_days"] = sorted(set(durations.tolist()))
    return cfg


def _prepare(time, flux, flux_err, cfg):
    arrays = [np.asarray(v, dtype=float) for v in (time, flux, flux_err)]
    if any(a.ndim != 1 for a in arrays) or len({len(a) for a in arrays}) != 1:
        raise ValueError("Time, flux and errors must be matching 1-D arrays")
    if not 30 <= len(arrays[0]) <= 30000:
        raise ValueError("Input must contain 30..30000 rows")
    t, y, e = arrays
    if (not all(np.all(np.isfinite(a)) for a in arrays)
            or np.any(e < 1e-12) or np.any(e > 1)):
        raise ValueError("All samples must be finite and errors in [1e-12, 1]")
    order = np.argsort(t, kind="stable")
    t, y, e = t[order], y[order], e[order]
    if np.any(np.diff(t) <= 0) or not 0.5 <= np.ptp(t) <= 1500:
        raise ValueError("Times must be unique with a 0.5..1500-day baseline")
    if not 0.5 <= np.median(y) <= 1.5 or np.any(y <= 0):
        raise ValueError("Flux must be positive and normalized near one")
    cadence = float(np.median(np.diff(t)))
    breaks = np.flatnonzero(np.diff(t) > max(5 * cadence, 0.2)) + 1
    trend = np.empty_like(y)
    for idx in np.split(np.arange(len(t)), breaks):
        width = min(2001, max(3, int(cfg["detrend_window_days"] / cadence) | 1))
        width = min(width, len(idx) if len(idx) % 2 else max(1, len(idx) - 1))
        trend[idx] = median_filter(y[idx], size=width, mode="nearest")
    return t, y / trend, e / trend, {"n_input": len(t), "n_used": len(t),
        "n_segments": len(breaks) + 1, "cadence_days": cadence,
        "detrending": "gap-separated running median; no flux clipping", "binned": False}


def _difference(y, e, inside, outside):
    if np.count_nonzero(inside) < 2 or np.count_nonzero(outside) < 5:
        return None, None
    wi, wo = 1 / e[inside] ** 2, 1 / e[outside] ** 2
    depth = np.average(y[outside], weights=wo) - np.average(y[inside], weights=wi)
    error = np.sqrt(1 / wi.sum() + 1 / wo.sum())
    return float(depth), float(error)


def _evaluate(t, y, e, period, epoch, duration, cfg):
    phase = (t - epoch + period / 2) % period - period / 2
    inside = np.abs(phase) < duration / 2
    secondary = np.abs(np.abs(phase) - period / 2) < duration / 2
    outside = ~(inside | secondary)
    # Quoted errors never smaller than robust point-to-point residual scatter.
    residual = y[outside]
    scatter = 1.4826 * np.median(np.abs(residual - np.median(residual))) if len(residual) else 0
    e = np.maximum(e, scatter)
    depth, error = _difference(y, e, inside, outside)
    cycles = np.floor((t - epoch) / period + 0.5).astype(np.int64)
    ids, counts = np.unique(cycles[inside], return_counts=True)
    observed = ids[counts >= 2]
    cadence = float(np.median(np.diff(t)))
    coverage = [{"transit_number": int(number), "n_samples": int(count),
                 "sampled_duration_fraction": float(min(1, count * cadence / duration))}
                for number, count in zip(ids[:1000], counts[:1000], strict=True)]
    snr = depth / error if depth is not None else None
    secdepth, secerr = _difference(y, e, secondary, outside)
    odd, oe = _difference(y, e, inside & (cycles % 2 == 1), outside)
    even, ee = _difference(y, e, inside & (cycles % 2 == 0), outside)
    odd_even = abs(odd - even) / np.hypot(oe, ee) if odd is not None and even is not None else None
    secsnr = secdepth / secerr if secdepth is not None else None
    sinusoid_amplitude, sinusoid_snr = None, None
    if np.count_nonzero(outside) >= 10:
        for harmonic in (1, 2):
            angle = 2 * np.pi * harmonic * phase[outside] / period
            design = np.column_stack((np.ones(len(angle)), np.sin(angle), np.cos(angle)))
            weighted = design / e[outside, None]
            if np.linalg.matrix_rank(weighted) < 3:
                continue
            covariance = np.linalg.inv(weighted.T @ weighted)
            coefficients = np.linalg.lstsq(weighted, (y[outside] - 1) / e[outside], rcond=None)[0]
            amplitude = float(np.hypot(*coefficients[1:]))
            direction = coefficients[1:] / amplitude if amplitude > 0 else np.array([1.0, 0.0])
            uncertainty = float(np.sqrt(direction @ covariance[1:, 1:] @ direction))
            significance = amplitude / uncertainty
            if sinusoid_snr is None or significance > sinusoid_snr:
                sinusoid_amplitude, sinusoid_snr = amplitude, significance
    flags = []
    if (sinusoid_snr is not None and sinusoid_snr > 8
            and sinusoid_amplitude > 0.25 * max(depth or 0, 0)):
        flags.append("sinusoidal_variability")
    if snr is None or snr < cfg["snr_threshold"]:
        flags.append("low_depth_snr")
    if len(observed) < cfg["min_transits"]:
        flags.append("insufficient_observed_transits")
    if odd_even is not None and odd_even > 5:
        flags.append("odd_even_depth_mismatch")
    if secsnr is not None and secsnr > 5 and secdepth > 0.1 * max(depth or 0, 0):
        flags.append("significant_secondary")
    if depth is not None and depth > 0.05:
        flags.append("deep_eclipse")
    return {"period_days": float(period), "epoch_btjd": float(epoch),
        "duration_days": float(duration), "depth": depth, "depth_error": error,
        "depth_snr": snr, "n_transits": len(ids), "n_well_sampled_transits": len(observed),
        "n_in_transit": int(inside.sum()), "observed_transit_numbers": ids[:1000].tolist(),
        "transit_coverage": coverage, "coverage_truncated": len(ids) > 1000,
        "odd_even_sigma": float(odd_even) if odd_even is not None else None,
        "secondary_depth": secdepth, "secondary_snr": secsnr,
        "sinusoid_amplitude": sinusoid_amplitude, "sinusoid_snr": sinusoid_snr,
        "candidate_flag": not flags, "flags": flags,
        "test_statuses": {"sinusoid": "evaluated" if sinusoid_snr is not None else "insufficient_data",
            "odd_even": "evaluated" if odd_even is not None else "insufficient_data",
            "secondary": "evaluated" if secsnr is not None else "insufficient_data",
            "pixel_contamination": "not_evaluated", "sky_vetting": "not_evaluated"}}


def validate_ephemeris(time, flux, flux_err, candidate: dict, config: dict | None = None) -> dict:
    """Evaluate exactly the frozen ephemeris; never optimize on holdout samples.

    Campaign orchestration, not this pure function, enforces one-use holdout access.
    """
    cfg = _config(config)
    try:
        period, epoch, duration = (float(candidate[k]) for k in
                                  ("period_days", "epoch_btjd", "duration_days"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Candidate requires finite period, epoch and duration") from exc
    if (not np.all(np.isfinite([period, epoch, duration]))
            or not 0.25 <= period <= 30 or not 0.02 <= duration <= min(0.3, period / 5)):
        raise ValueError("Invalid frozen ephemeris")
    t, y, e, prep = _prepare(time, flux, flux_err, cfg)
    result = _evaluate(t, y, e, period, epoch, duration, cfg)
    result.update({"ephemeris_fixed": True, "passed": result["candidate_flag"],
                   "preprocessing": prep, "config": cfg})
    return result


def calibrate_null(time, flux, flux_err, config: dict | None = None,
                   repeats: int = 64, seed: int = 0) -> dict:
    """Small moving-block bootstrap calibration, not a formal false-alarm test.

    Resample raw flux/error pairs within each observed segment, then repeat the
    entire detrending and grid search. Existing signals are intentionally not fit
    away; signal contamination and stationarity violations limit interpretation.
    """
    cfg = _config(config)
    if isinstance(repeats, bool) or not isinstance(repeats, (int, np.integer)) or not 1 <= repeats <= 1024:
        raise ValueError("Null repeats must be an integer in 1..1024")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or not 0 <= seed < 2**32:
        raise ValueError("Seed must be a uint32 integer")
    trials = cfg["period_grid_size"] * len(cfg["durations_days"]) * (repeats + 1)
    if trials > 40000000:
        raise ValueError("Null calibration exceeds forty million period-duration trials")
    t, _, _, prep = _prepare(time, flux, flux_err, cfg)
    order = np.argsort(np.asarray(time), kind="stable")
    raw, errors = np.asarray(flux, dtype=float)[order], np.asarray(flux_err, dtype=float)[order]
    splits = np.flatnonzero(np.diff(t) > max(5 * prep["cadence_days"], 0.2)) + 1
    segments = np.split(np.arange(len(t)), splits)
    block_days = max(0.5, 2 * max(cfg["durations_days"]))
    block_rows = max(2, int(np.ceil(block_days / prep["cadence_days"])))
    rng = np.random.default_rng(seed)
    observed = search_transits(t, raw, errors, cfg)["candidate"]["bls_power"]
    maxima = []
    for _ in range(repeats):
        sample = np.empty(len(t), dtype=int)
        for idx in segments:
            width = min(block_rows, len(idx))
            starts = rng.integers(0, len(idx), size=int(np.ceil(len(idx) / width)))
            source = (starts[:, None] + np.arange(width)) % len(idx)
            sample[idx] = idx[source.ravel()[:len(idx)]]
        maxima.append(search_transits(t, raw[sample], errors[sample], cfg)["candidate"]["bls_power"])
    exceedances = sum(value >= observed for value in maxima)
    return {"method": "within-segment circular moving-block bootstrap of raw flux/error pairs",
        "statistic": "maximum BLS log-likelihood improvement across the full frozen grid",
        "observed_statistic": observed, "maxima": maxima, "repeats": int(repeats),
        "seed": int(seed), "block_days": block_days, "block_rows": block_rows,
        "exceedances": exceedances, "empirical_p": (1 + exceedances) / (repeats + 1),
        "p_floor": 1 / (repeats + 1), "formal_fap": None,
        "adequate_for_discovery_claim": False, "total_searches": int(repeats + 1),
        "period_duration_trials": int(trials), "config": cfg,
        "limitations": ["Empirical calibration only; finite surrogates do not establish a formal FAP.",
            "Blocks preserve short-range correlations only; stationarity is not established.",
            "Signals present in raw flux contaminate these surrogates.",
            "Calibration covers this target and variant only, not campaign-wide multiplicity."]}


def search_transits(time, flux, flux_err, config: dict | None = None) -> dict:
    """Search a fixed frequency grid and return a bounded JSON best-peak diagnostic."""
    cfg = _config(config)
    t, y, e, prep = _prepare(time, flux, flux_err, cfg)
    periods = 1 / np.linspace(1 / cfg["period_max"], 1 / cfg["period_min"], cfg["period_grid_size"])
    model = BoxLeastSquares(t, y, e)
    power = model.power(periods, cfg["durations_days"], objective="likelihood", method="fast")
    best = int(np.argmax(power.power))
    candidate = _evaluate(t, y, e, power.period[best], power.transit_time[best],
                          power.duration[best], cfg)
    candidate["bls_power"] = float(power.power[best])
    aliases = []
    for factor in (0.5, 2.0):
        target = candidate["period_days"] * factor
        in_range = cfg["period_min"] <= target <= cfg["period_max"]
        nearest = int(np.argmin(np.abs(periods - target)))
        aliases.append({"factor": factor, "target_period_days": target,
                        "in_search_range": in_range,
                        "nearest_grid_period_days": float(periods[nearest]) if in_range else None,
                        "bls_power": float(power.power[nearest]) if in_range else None,
                        "interpretation": "nearest grid power only; alias not ruled out"})
    candidate["aliases"] = aliases
    pi = np.unique(np.linspace(0, len(periods) - 1, min(1000, len(periods))).astype(int))
    phase = (t - candidate["epoch_btjd"] + candidate["period_days"] / 2) % candidate["period_days"] - candidate["period_days"] / 2
    order = np.argsort(phase)
    fi = order[np.linspace(0, len(t) - 1, min(1000, len(t))).astype(int)]
    return {"candidate": candidate, "config": cfg, "preprocessing": prep,
        "search_trials": {"periods": len(periods), "durations": len(cfg["durations_days"]),
            "phase_optimized": True, "grid": "uniform_frequency"},
        "diagnostics": {"periodogram": {"period_days": periods[pi].tolist(),
            "power": np.asarray(power.power)[pi].tolist()},
            "folded": {"phase_days": phase[fi].tolist(), "flux": y[fi].tolist()}},
        "limitations": ["BLS likelihood improvement is not physical significance or a false-alarm probability.",
            "Depth errors assume independent samples; correlated noise requires empirical controls.",
            "Best peak only; aliases and contamination remain unresolved.",
            "No confirmed planet or novelty inference is made."]}
