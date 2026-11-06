"""Numerical tests; run on the authorized remote compute host only."""
import importlib

import numpy as np
import pytest


def core():
    try:
        return importlib.import_module("rediscover.physics")
    except ModuleNotFoundError:
        pytest.fail("rediscover.physics numerical core is not implemented")


def noise(seed=42, sample_rate=1024, duration=32):
    return np.random.default_rng(seed).normal(0, 1e-21, sample_rate * duration)


def test_quality_validation():
    physics = core()
    q = physics.quality_check(noise(), 1024)
    assert q["valid"] is True
    assert q["duration"] == 32
    for bad in (np.zeros(32768), np.ones(32768), np.full(32768, np.nan),
                np.full(32768, np.inf), noise()[:100], noise().reshape(2, -1)):
        with pytest.raises(ValueError):
            physics.quality_check(bad, 1024)
    for rate in (0, -1, np.nan, 2, 1e9):
        with pytest.raises(ValueError):
            physics.quality_check(noise(), rate)
    gap = noise()
    gap[1000:2000] = 0
    with pytest.raises(ValueError, match="flat|gap"):
        physics.quality_check(gap, 1024)


def test_noise_only_search_and_bounds():
    physics = core()
    assert hasattr(physics, "analyze_detector"), "matched filter is not implemented"
    x = noise()
    result = physics.analyze_detector(x, 1024, 1000, 1016, masses=[30, 35])
    import json
    json.dumps(result, allow_nan=False)
    assert 0 < result["snr"] < 8
    assert result["candidate"] is False
    assert 1015.7 <= result["peak_gps"] <= 1016.3
    assert result["config"]["bank_size"] == 3
    assert result["mass_frame"] == "detector"
    assert result["snr_kind"] == "fixed-template matched-filter SNR"
    for kwargs in ({"search_center": 1001}, {"search_window": 0},
                   {"search_center": np.nan}, {"f_low": 0}, {"f_low": 512},
                   {"masses": []}, {"masses": [0, 35]},
                   {"masses": list(range(10, 100))}):
        options = {"search_center": 1016, "masses": [30, 35]}
        options.update(kwargs)
        with pytest.raises(ValueError):
            physics.analyze_detector(x, 1024, 1000, **options)


def test_injection_time_amplitude_mass_recovery():
    physics = core()
    assert hasattr(physics, "inject_signal"), "physical injection helper is not implemented"
    x = noise()
    original = x.copy()
    injected = physics.inject_signal(x, 1024, 1000, 1016, 35, 30, 24, seed=7)
    np.testing.assert_array_equal(x, original)
    np.testing.assert_array_equal(injected, physics.inject_signal(x, 1024, 1000, 1016, 35, 30, 24, seed=7))
    half = physics.inject_signal(x, 1024, 1000, 1016, 35, 30, 12, seed=7)
    np.testing.assert_allclose(injected - x, 2 * (half - x), rtol=1e-10, atol=1e-35)
    # A physical merger must be localized at the supplied coalescence GPS time.
    merger_time = 1000 + np.argmax(np.abs(injected - x)) / 1024
    assert abs(merger_time - 1016) < .03
    result = physics.analyze_detector(injected, 1024, 1000, 1016)
    assert result["candidate"] is True
    assert abs(result["peak_gps"] - 1016) < .01
    assert abs(result["snr"] - 24) < 4
    truth = (35 * 30)**.6 / 65**.2
    assert abs(result["chirp_mass"] / truth - 1) < .12
    assert not any(key in result for key in ("seed", "target_snr", "truth"))
    for args in ((1001, 35, 30, 24), (1016, -1, 30, 24),
                 (1016, 35, 30, 0), (1016, 35, 30, np.inf)):
        with pytest.raises(ValueError):
            physics.inject_signal(x, 1024, 1000, *args)


def test_conditioning_is_finite_dimensionless_and_edge_masked():
    physics = core()
    assert hasattr(physics, "condition_strain"), "whitening is not implemented"
    x = noise()
    original = x.copy()
    conditioned = physics.condition_strain(x, 1024)
    assert conditioned.shape == x.shape
    assert np.all(np.isfinite(conditioned))
    assert .4 < np.std(conditioned[8192:-8192]) < 1.2
    assert np.all(conditioned[:8192] == 0)
    assert np.all(conditioned[-8192:] == 0)
    np.testing.assert_array_equal(x, original)


def test_template_diagnostics_agrees_with_scalar_search():
    physics = core()
    assert hasattr(physics, "template_diagnostics"), "SNR diagnostics is not implemented"
    x = noise()
    result = physics.analyze_detector(x, 1024, 1000, 1016, masses=[35])
    diagnostic = physics.template_diagnostics(x, 1024, 1000, 35, 35)
    times, snr = diagnostic["time"], diagnostic["snr"]
    assert times.shape == snr.shape
    assert np.all(np.isfinite(snr))
    assert times.min() >= 1008 and times.max() < 1024
    region = (times >= 1015.7) & (times <= 1016.3)
    assert np.max(snr[region]) == pytest.approx(result["snr"])


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_noise_negative_controls(seed):
    result = core().analyze_detector(noise(seed), 1024, 1000, 1016)
    assert result["snr"] < 8
    assert result["candidate"] is False


def test_psd_scaling_invariance_and_independent_white_noise_norm():
    physics = core()
    x = noise()
    a = physics.analyze_detector(x, 1024, 1000, 1016, masses=[35])
    b = physics.analyze_detector(1000 * x, 1024, 1000, 1016, masses=[35])
    assert a["snr"] == pytest.approx(b["snr"], rel=1e-10)
    injected = physics.inject_signal(x, 1024, 1000, 1016, 35, 30, 24, seed=7)
    # Independent time-domain norm for iid Gaussian noise (Parseval's theorem).
    norm = float(np.sqrt(np.sum(((injected - x) / 1e-21)**2)))
    assert norm == pytest.approx(24, rel=.1)


@pytest.mark.parametrize("detector", ["H1", "L1"])
def test_real_gw150914_and_offsource_injection(detector):
    import json
    import os
    from pathlib import Path

    import h5py

    directory = os.environ.get("REDISCOVER_REAL_DATA")
    if not directory:
        pytest.skip("set REDISCOVER_REAL_DATA to a local directory of official GW150914 HDF5 files")
    path = Path(directory) / f"{detector[0]}-{detector}_GWOSC_4KHZ_R1-1126259447-32.hdf5"
    assert path.is_file(), f"missing real-data fixture: {path}"
    with h5py.File(path) as f:
        x = f["strain/Strain"][:]
        rate = 1. / float(f["strain/Strain"].attrs["Xspacing"])
        start = float(f["strain/Strain"].attrs["Xstart"])
    physics = core()
    event = physics.analyze_detector(x, rate, start, 1126259462.4)
    assert 10 < event["snr"] < 30
    assert abs(event["peak_gps"] - 1126259462.42) < .04
    assert 20 < event["chirp_mass"] < 45
    center = start + 10.3
    offsource = physics.analyze_detector(x, rate, start, center, search_window=.2)
    assert offsource["candidate"] is False
    injected = physics.inject_signal(x, rate, start, center, 35, 30, 18, seed=11)
    recovery = physics.analyze_detector(injected, rate, start, center, search_window=.2)
    assert recovery["candidate"] is True
    assert abs(recovery["peak_gps"] - center) < .02
    assert abs(recovery["snr"] - 18) < 5
    truth = (35 * 30)**.6 / 65**.2
    assert abs(recovery["chirp_mass"] / truth - 1) < .15
    print(json.dumps({"detector": detector, "event": event,
                      "offsource": offsource, "injection_recovery": recovery}, allow_nan=False))
