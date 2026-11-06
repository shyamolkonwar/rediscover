import importlib.util

import pytest


def test_campaign_module_exists():
    assert importlib.util.find_spec("rediscover.campaigns") is not None


def cohort():
    return {"selection": "synthetic state-machine fixture", "targets": [{"tic": "123",
        "discovery": {"tic": "123", "sector": 1, "uri": "mast:TESS/product/tess2018206045859-s0001-0000000000000123-0120-s_lc.fits"},
        "validation": {"tic": "123", "sector": 4, "uri": "mast:TESS/product/tess2018292075959-s0004-0000000000000123-0124-s_lc.fits"}}]}


def test_holdout_gate_and_frozen_plan(tmp_path):
    from rediscover.campaigns import Campaigns
    c = Campaigns(tmp_path)
    result = c.create(cohort())
    campaign_id = result["campaign_id"]
    with pytest.raises(ValueError, match="frozen"):
        c.validate(campaign_id)
    with pytest.raises(ValueError, match="search"):
        c.freeze(campaign_id)
    assert c.status(campaign_id)["state"] == "planned"
    plan = c.workspace.read(campaign_id, "plan.json")
    assert plan["cohort"]["targets"][0]["validation"]["sector"] == 4
    with pytest.raises(FileExistsError):
        c.workspace.save(campaign_id, "plan.json", {})


def test_plan_validation(tmp_path):
    from rediscover.campaigns import Campaigns
    c = Campaigns(tmp_path)
    bad = cohort()
    bad["targets"][0]["validation"]["sector"] = 1
    with pytest.raises(ValueError):
        c.create(bad)
    with pytest.raises(ValueError):
        c.create(cohort(), {"period_grid_size": 999999999})


def test_verifier_never_claims_discovery_or_catalog_clearance():
    from rediscover.campaigns import classify
    row = {"search": {"candidate": {"depth_snr": 15, "n_transits": 4}, "stable": True},
           "validation": {"passed": True}, "calibration": {"empirical_p": 0.0001},
           "catalog": {"complete": False, "known_match": False}, "auxiliary": {"usable": True}}
    v = classify(row, family_size=12)
    assert v["status"] == "UNRESOLVED"
    assert "catalog_unavailable" in v["reasons"]
