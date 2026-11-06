import importlib.util


def test_service_exists():
    assert importlib.util.find_spec("rediscover.service") is not None


def test_prepared_run_is_scoped_and_quality_gated(tmp_path):
    import numpy as np
    import pytest

    from rediscover.service import Lab
    lab = Lab(tmp_path)
    run = lab.prepare({"name": "test", "gps": 16.0}, {"H1": {
        "strain": np.zeros(32768), "sample_rate": 1024.0, "gps_start": 0,
        "data_quality": {"available": True, "all_data_present": False},
        "source": {"type": "synthetic-test-only"}}})
    assert lab.describe(run)["detectors"] == ["H1"]
    with pytest.raises(ValueError, match="quality"):
        lab.analyze(run, "H1")
    with pytest.raises(ValueError):
        lab.analyze(run, "../H1")
    assert lab.workspace.verify(run)["valid"]


def test_prepared_arrays_are_checked(tmp_path):
    import numpy as np
    import pytest

    from rediscover.service import Lab
    lab = Lab(tmp_path)
    run = lab.prepare({"name": "test", "gps": 16.0}, {"H1": {
        "strain": np.zeros(32768), "sample_rate": 1024.0, "gps_start": 0,
        "data_quality": {"available": True, "all_data_present": True},
        "source": {"type": "synthetic-test-only"}}})
    lab.workspace.file(run, "H1.npz").write_bytes(b"broken")
    with pytest.raises(ValueError, match="integrity"):
        lab.dataset(run, "H1")
