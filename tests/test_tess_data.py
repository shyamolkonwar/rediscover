import importlib.util


def test_tess_data_exists():
    assert importlib.util.find_spec("rediscover.tess_data") is not None


def test_fits_quality_time_and_identity(tmp_path):
    import numpy as np
    import pytest
    from astropy.io import fits

    from rediscover.tess_data import read_lightcurve
    cols = [fits.Column(name="TIME", array=[1., 2., 3., 4.], format="D"),
            fits.Column(name="PDCSAP_FLUX", array=[100., 99., np.nan, 101.], format="E"),
            fits.Column(name="PDCSAP_FLUX_ERR", array=[1., 1., 1., 1.], format="E"),
            fits.Column(name="SAP_FLUX", array=[100., 99., 100., 101.], format="E"),
            fits.Column(name="QUALITY", array=[0, 1, 0, 0], format="J")]
    hdu = fits.BinTableHDU.from_columns(cols)
    hdu.header["BJDREFI"] = 2457000
    hdu.header["BJDREFF"] = 0.
    hdu.header["TIMESYS"] = "TDB"
    hdu.header["TIMEUNIT"] = "d"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TICID"] = 123
    primary.header["SECTOR"] = 1
    p = tmp_path / "test.fits"
    fits.HDUList([primary, hdu]).writeto(p)
    result = read_lightcurve(p, expected_tic=123, expected_sector=1)
    assert result["metadata"]["removed_rows"] == 2
    assert result["metadata"]["time_system"] == "BTJD_TDB"
    assert result["time"].tolist() == [1., 4.]
    assert np.median(result["flux"]) == 1
    with pytest.raises(ValueError, match="identity"):
        read_lightcurve(p, expected_tic=456, expected_sector=1)


def test_identifiers_and_remote_url_bounds():
    import pytest

    from rediscover.tess_data import check_tic, check_uri, validate_space_url
    for bad in ["../123", "12;DROP", "0", "123abc"]:
        with pytest.raises(ValueError):
            check_tic(bad)
    for url in ["http://mast.stsci.edu/x", "https://evil.test/x", "https://mast.stsci.edu:443@evil.test/x"]:
        with pytest.raises(ValueError):
            validate_space_url(url)
    with pytest.raises(ValueError):
        check_uri("mast:TESS/product/../../key")


def test_catalog_error_is_not_no_match(monkeypatch):
    import httpx

    from rediscover.tess_data import catalog_check
    def fail(*a, **k):
        raise httpx.ReadTimeout("synthetic test timeout")
    monkeypatch.setattr("rediscover.tess_data.space_json", fail)
    result = catalog_check("123", 3.0)
    assert result["complete"] is False
    assert result["status"] == "unavailable"
