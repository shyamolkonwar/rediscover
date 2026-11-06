import importlib.util


def test_data_api_exists():
    assert importlib.util.find_spec("rediscover.data") is not None, "Data ingestion not implemented"


def test_hdf5_quality_and_time(tmp_path):
    import h5py
    import numpy as np

    from rediscover.data import read_strain
    path = tmp_path / "strain.hdf5"
    with h5py.File(path, "w") as f:
        d = f.create_dataset("strain/Strain", data=np.arange(8192, dtype=float))
        d.attrs["Xspacing"] = 1 / 4096
        d.attrs["Xstart"] = 1126259462.0
        f.create_dataset("quality/simple/DQmask", data=[1, 1])
        f.create_dataset("quality/injections/Injmask", data=[3, 3])
    s = read_strain(path)
    assert s["sample_rate"] == 4096
    assert s["gps_start"] == 1126259462.0
    assert s["data_quality"]["all_data_present"] is True
    assert len(s["strain"]) == 8192


def test_bad_data_and_unsafe_urls(tmp_path):
    import h5py
    import numpy as np
    import pytest

    from rediscover.data import read_strain, validate_event, validate_url
    for url in ["http://gwosc.org/x", "https://evil.test/x", "https://gwosc.org@evil.test/x", "https://gwosc.org:444/x"]:
        with pytest.raises(ValueError):
            validate_url(url)
    for event in ["../etc/passwd", "GW150914/../x", "bad?query=1"]:
        with pytest.raises(ValueError):
            validate_event(event)
    p = tmp_path / "bad.h5"
    with h5py.File(p, "w") as f:
        d = f.create_dataset("strain/Strain", data=[0.0, np.nan])
        d.attrs["Xspacing"] = 1 / 4096
        d.attrs["Xstart"] = 0
    with pytest.raises(ValueError, match="finite"):
        read_strain(p)


def test_cache_integrity(tmp_path):
    import pytest

    from rediscover.data import download
    p = tmp_path / "fake.hdf5"
    p.write_bytes(b"tampered")
    p.with_suffix(".sha256").write_text("0" * 64)
    with pytest.raises(ValueError, match="checksum"):
        download("https://gwosc.org/fake.hdf5", p)
