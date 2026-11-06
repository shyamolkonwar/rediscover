"""Numerical controls: parameters/thresholds are fixed before execution."""
import importlib.util
import json

import numpy as np
import pytest

CONFIG = {"period_grid_size": 3000, "period_min": 1.0, "period_max": 6.0}
PERIOD, EPOCH, DURATION, DEPTH = 3.2, 1000.7, 0.1, 0.008


def control(start=1000.0, seed=123, depth=DEPTH):
    time = np.arange(start, start + 25, 10 / 1440)
    phase = (time - EPOCH + PERIOD / 2) % PERIOD - PERIOD / 2
    rng = np.random.default_rng(seed)
    flux = 1 - depth * (np.abs(phase) < DURATION / 2)
    flux = flux + rng.normal(0, 0.001, len(time))
    return time, flux, np.full(len(time), 0.001)


def core():
    assert importlib.util.find_spec("rediscover.transit") is not None, "numerical core missing"
    from rediscover import transit
    return transit


def test_recovers_known_box_and_json_diagnostics():
    result = core().search_transits(*control(), CONFIG)
    candidate = result["candidate"]
    assert candidate["candidate_flag"]
    assert abs(candidate["period_days"] - PERIOD) < 0.01
    assert abs(candidate["depth"] - DEPTH) < 0.0015
    assert candidate["depth_snr"] > 30
    assert candidate["n_transits"] == 8
    assert len(result["diagnostics"]["periodogram"]["period_days"]) <= 1000
    assert len(result["diagnostics"]["folded"]["phase_days"]) <= 1000
    assert result["config"]["snr_threshold"] == 8
    json.dumps(result, allow_nan=False)
    print("BOX", json.dumps(candidate, sort_keys=True))


def test_holdout_is_exact_and_independent_without_any_search(monkeypatch):
    transit = core()
    assert hasattr(transit, "validate_ephemeris"), "fixed-ephemeris evaluation missing"
    candidate = {"period_days": PERIOD, "epoch_btjd": EPOCH, "duration_days": DURATION}

    def forbidden(*args, **kwargs):
        raise AssertionError("holdout must never search BLS")

    monkeypatch.setattr(transit.BoxLeastSquares, "power", forbidden)
    result = transit.validate_ephemeris(*control(1040, 456), candidate, CONFIG)
    assert result["ephemeris_fixed"] is True
    assert result["passed"]
    for key, value in candidate.items():
        assert result[key] == value
    assert result["depth_snr"] > 30
    negative = transit.validate_ephemeris(*control(1040, 789, 0), candidate, CONFIG)
    assert not negative["passed"]
    assert negative["depth_snr"] < 8
    json.dumps(result, allow_nan=False)
    print("HOLDOUT", result["depth_snr"], "NEGATIVE", negative["depth_snr"])


def test_empirical_null_repeats_full_search_and_honors_resolution():
    transit = core()
    assert hasattr(transit, "calibrate_null"), "empirical calibration missing"
    cfg = {**CONFIG, "period_grid_size": 1000}
    result = transit.calibrate_null(*control(), cfg, repeats=7, seed=812)
    assert result["repeats"] == 7
    assert len(result["maxima"]) == 7
    assert result["p_floor"] == 1 / 8
    assert result["empirical_p"] == (1 + sum(v >= result["observed_statistic"]
                                            for v in result["maxima"])) / 8
    assert result["empirical_p"] >= result["p_floor"]
    assert result["formal_fap"] is None
    assert not result["adequate_for_discovery_claim"]
    assert result["total_searches"] == 8
    assert result == transit.calibrate_null(*control(), cfg, repeats=7, seed=812)
    json.dumps(result, allow_nan=False)
    print("NULL", json.dumps(result, sort_keys=True))


def test_sinusoidal_variability_is_explicitly_flagged():
    t, _, e = control()
    y = 1 + 0.02 * np.cos(2 * np.pi * (t - EPOCH) / PERIOD)
    y += np.random.default_rng(88).normal(0, e)
    ephemeris = {"period_days": PERIOD, "epoch_btjd": EPOCH + PERIOD / 2,
                 "duration_days": DURATION}
    result = core().validate_ephemeris(t, y, e, ephemeris, CONFIG)
    assert "sinusoidal_variability" in result["flags"]
    assert result["sinusoid_snr"] > 8
    assert result["test_statuses"]["sinusoid"] == "evaluated"
    assert not result["passed"]
    print("SINUSOID", result["sinusoid_snr"], result["flags"])


def test_observed_transit_counts_ignore_gaps_and_report_coverage():
    t, y, e = control()
    cycles = np.floor((t - EPOCH) / PERIOD + 0.5).astype(int)
    keep = np.isin(cycles, [0, 4, 7])
    ephemeris = {"period_days": PERIOD, "epoch_btjd": EPOCH, "duration_days": DURATION}
    result = core().validate_ephemeris(t[keep], y[keep], e[keep], ephemeris, CONFIG)
    assert result["n_transits"] == 3
    assert result["observed_transit_numbers"] == [0, 4, 7]
    assert len(result["transit_coverage"]) == 3
    assert all(row["n_samples"] >= 10 for row in result["transit_coverage"])
    assert result["preprocessing"]["n_segments"] == 3


def test_independent_analytic_depth_and_error():
    t, _, e = control()
    phase = (t - EPOCH + PERIOD / 2) % PERIOD - PERIOD / 2
    inside = np.abs(phase) < DURATION / 2
    outside = ~(inside | (np.abs(np.abs(phase) - PERIOD / 2) < DURATION / 2))
    y = 1 - DEPTH * inside
    candidate = {"period_days": PERIOD, "epoch_btjd": EPOCH, "duration_days": DURATION}
    result = core().validate_ephemeris(t, y, e, candidate, CONFIG)
    assert result["depth"] == pytest.approx(DEPTH, abs=1e-12)
    expected = 0.001 * np.sqrt(1 / inside.sum() + 1 / outside.sum())
    assert result["depth_error"] == pytest.approx(expected, rel=0.01)


@pytest.mark.parametrize("seed", [10, 20, 30])
def test_noise_only_never_promoted(seed):
    result = core().search_transits(*control(seed=seed, depth=0), CONFIG)["candidate"]
    assert not result["candidate_flag"]
    assert result["depth_snr"] < 8
    print("NOISE", seed, result["depth_snr"])


def test_trapezoid_recovery_with_predeclared_window_variants():
    t, _, e = control()
    phase = np.abs((t - EPOCH + PERIOD / 2) % PERIOD - PERIOD / 2)
    trapezoid = np.clip((DURATION / 2 - phase) / 0.02, 0, 1)
    y = 1 - DEPTH * trapezoid + np.random.default_rng(567).normal(0, e)
    for window in (1.5, 2.0):
        result = core().search_transits(t, y, e, {**CONFIG, "detrend_window_days": window})["candidate"]
        assert result["candidate_flag"]
        assert abs(result["period_days"] - PERIOD) < 0.01
        print("TRAPEZOID", window, result["period_days"], result["depth_snr"])


def test_binary_primary_secondary_and_odd_even_rejected():
    t, _, e = control()
    phase = (t - EPOCH + PERIOD / 2) % PERIOD - PERIOD / 2
    primary = np.abs(phase) < DURATION / 2
    secondary = np.abs(np.abs(phase) - PERIOD / 2) < DURATION / 2
    y = 1 - 0.03 * primary - 0.015 * secondary + np.random.default_rng(34).normal(0, e)
    result = core().search_transits(t, y, e, CONFIG)["candidate"]
    assert not result["candidate_flag"]
    assert {"significant_secondary", "odd_even_depth_mismatch"} & set(result["flags"])
    print("BINARY", result["period_days"], result["odd_even_sigma"], result["secondary_snr"], result["flags"])


@pytest.mark.parametrize("config", [
    {"period_grid_size": 10000000}, {"period_min": 0}, {"period_max": 100},
    {"durations_days": [0.0]}, {"durations_days": [0.1] * 11},
    {"detrend_window_days": 0.01}, {"unrecognized": 1}, {"snr_threshold": float("nan")},
])
def test_invalid_work_config_rejected(config):
    with pytest.raises(ValueError):
        core().search_transits(*control(), config)


@pytest.mark.parametrize("kind", ["nan", "duplicate", "errors", "shape", "huge", "empty"])
def test_invalid_arrays_rejected(kind):
    t, y, e = control()
    if kind == "nan":
        y[0] = np.nan
    elif kind == "duplicate":
        t[1] = t[0]
    elif kind == "errors":
        e[0] = 0
    elif kind == "shape":
        e = e[:-1]
    elif kind == "huge":
        t, y, e = np.arange(30001) / 100, np.ones(30001), np.ones(30001)
    else:
        t, y, e = [], [], []
    with pytest.raises(ValueError):
        core().search_transits(t, y, e, CONFIG)


def test_null_accepts_predeclared_1024_surrogates_on_small_red_noise_field():
    t = np.arange(1000, 1010, 0.1)
    white = np.random.default_rng(19).normal(0, 0.001, len(t))
    red = np.convolve(white, np.ones(3) / 3, mode="same")
    result = core().calibrate_null(t, 1 + red, np.full(len(t), 0.001),
                                   {**CONFIG, "period_grid_size": 100}, repeats=1024, seed=33)
    assert len(result["maxima"]) == 1024
    assert result["p_floor"] == 1 / 1025
    assert result["empirical_p"] >= result["p_floor"]
    assert not result["adequate_for_discovery_claim"]
    print("RED_NOISE_NULL", result["empirical_p"], result["p_floor"])


def test_no_transit_coverage_returns_null_measurements_without_warnings():
    t, y, e = control()
    phase = (t - EPOCH + PERIOD / 2) % PERIOD - PERIOD / 2
    keep = np.abs(phase) > 0.2
    candidate = {"period_days": PERIOD, "epoch_btjd": EPOCH, "duration_days": DURATION}
    result = core().validate_ephemeris(t[keep], y[keep], e[keep], candidate, CONFIG)
    assert result["n_transits"] == 0
    assert result["depth"] is None
    assert not result["passed"]
    json.dumps(result, allow_nan=False)


def test_extreme_numeric_input_rejected_before_overflow():
    t, y, e = control()
    e[0] = 1e-200
    with pytest.raises(ValueError, match="errors"):
        core().search_transits(t, y, e, CONFIG)


def test_all_samples_inside_transits_is_insufficient_data_not_nan():
    t = np.concatenate([EPOCH + cycle * PERIOD + np.linspace(-0.04, 0.04, 12)
                        for cycle in range(4)])
    result = core().validate_ephemeris(t, np.ones(len(t)), np.full(len(t), 0.001),
        {"period_days": PERIOD, "epoch_btjd": EPOCH, "duration_days": DURATION}, CONFIG)
    assert result["depth"] is None
    assert not result["passed"]
    json.dumps(result, allow_nan=False)


def test_alias_powers_are_diagnostics_not_second_search():
    result = core().search_transits(*control(), CONFIG)
    assert len(result["candidate"]["aliases"]) == 2
    assert result["candidate"]["aliases"][0]["factor"] == 0.5
    assert result["candidate"]["aliases"][1]["in_search_range"] is False


@pytest.mark.parametrize("key", ["period_grid_size", "min_transits"])
def test_nonfinite_integer_config_raises_valueerror(key):
    with pytest.raises(ValueError):
        core().search_transits(*control(), {key: float("inf")})


def test_single_sample_transits_count_but_cannot_pass_coverage_gate():
    t = np.arange(1000, 1025, 0.01)
    phase = (t - EPOCH + PERIOD / 2) % PERIOD - PERIOD / 2
    keep = np.abs(phase) > 0.2
    t = np.sort(np.concatenate([t[keep], EPOCH + PERIOD * np.arange(3)]))
    result = core().validate_ephemeris(t, np.ones(len(t)), np.full(len(t), 0.001),
        {"period_days": PERIOD, "epoch_btjd": EPOCH, "duration_days": DURATION}, CONFIG)
    assert result["n_transits"] == 3
    assert result["n_well_sampled_transits"] == 0
    assert "insufficient_observed_transits" in result["flags"]


def test_default_null_budget_is_preliminary_64():
    import inspect
    assert inspect.signature(core().calibrate_null).parameters["repeats"].default == 64
