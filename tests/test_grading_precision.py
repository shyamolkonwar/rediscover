"""Timestamp precision is part of the reference, not a model error."""
from rediscover.benchmark import grade


def test_catalog_rounding_interval():
    truth = {"signal": True, "peak_gps": 1186741861.5,
             "reference_time_resolution_seconds": 0.1}
    # A one-decimal timestamp cannot distinguish .500 from .535.
    assert grade({"snr": 10, "peak_gps": 1186741861.535}, truth)["passed"]
    assert not grade({"snr": 10, "peak_gps": 1186741861.7}, truth)["passed"]


def test_injection_precision_remains_strict():
    truth = {"signal": True, "peak_gps": 10.3, "chirp_mass": 30}
    assert not grade({"snr": 14, "peak_gps": 10.34, "chirp_mass": 30}, truth)["passed"]
