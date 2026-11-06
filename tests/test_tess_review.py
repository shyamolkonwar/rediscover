"""Release-review regressions; tests execute only on the authorized compute host."""
import copy

import pytest
from test_campaigns import cohort

from rediscover.campaigns import Campaigns, validate_config


@pytest.mark.parametrize("patch", [
    {"alternate_window_days": 1.5}, {"max_code_experiments": 2.5},
    {"seed": -1}, {"seed": 1.5}, {"seed": 2**32},
    {"period_grid_size": 20000, "durations_days": [.02, .04, .06, .08, .1, .12], "null_repeats": 1024},
])
def test_invalid_frozen_budgets_rejected(patch):
    with pytest.raises(ValueError):
        validate_config(patch)


def test_exhausted_budget_makes_no_paid_call(tmp_path, monkeypatch):
    from rediscover.research_agent import run_experiments
    c = Campaigns(tmp_path)
    cid = c.create(cohort(), {"max_code_experiments": 1})["campaign_id"]
    c.workspace.save(cid, "search.json", {"targets": [{"tic": "123", "candidate": {"depth_snr": 9}}]})
    c.workspace.record(cid, "research_attempt", {}, {"attempt": 1})
    calls = []
    monkeypatch.setattr("rediscover.research_agent.request_json", lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match="remaining"):
        run_experiments(c, cid, "mock", 1)
    assert calls == []


def test_atomic_research_reservations_and_freeze(tmp_path):
    c = Campaigns(tmp_path)
    cid = c.create(cohort(), {"max_code_experiments": 2})["campaign_id"]
    c.workspace.save(cid, "search.json", {"targets": []})
    slots = c.reserve_research(cid, 2)
    assert len(set(slots)) == 2
    with pytest.raises(ValueError, match="remaining"):
        c.reserve_research(cid, 1)
    c.freeze(cid)
    with pytest.raises(ValueError, match="freeze"):
        c.reserve_research(cid, 1)


def test_review_finalization_can_resume_without_new_analysis(tmp_path, monkeypatch):
    c = Campaigns(tmp_path)
    cid = c.create(cohort())["campaign_id"]
    c.workspace.save(cid, "review.json", {"targets": [{"tic": "123", "verdict": {"status": "REJECTED", "reasons": ["fixture"]}}]})
    def prohibited(*args, **kwargs):
        pytest.fail("sealed review must not perform more analysis or external requests")
    monkeypatch.setattr("rediscover.campaigns.catalog_check", prohibited)
    c.review(cid)
    assert c.workspace.read(cid, "verdict.json")["counts"] == {"REJECTED": 1}


def test_soft_schedule_deadline_survives_resume(tmp_path, monkeypatch):
    c = Campaigns(tmp_path)
    ids = cohort()
    second = copy.deepcopy(ids["targets"][0])
    second["tic"] = "456"
    for role in ("discovery", "validation"):
        second[role]["tic"] = "456"
        second[role]["uri"] = second[role]["uri"].replace("0000000000000123", "0000000000000456")
    ids["targets"].append(second)
    cid = c.create(ids, {"search_schedule_seconds": 60})["campaign_id"]
    c.workspace.save(cid, "search-schedule.json", {"deadline_unix": 0, "scope": "soft_between_targets"})
    c.workspace.save(cid, "search-123.json", {"tic": "123", "error": "earlier failed attempt"})
    monkeypatch.setattr(c, "_store_data", lambda *a, **k: pytest.fail("expired schedule must not fetch"))
    result = c.search(cid)
    assert result["total"] == 2 and result["failures"] == 2
    assert "deadline" in result["targets"][1]["error"].lower()


def test_soft_schedule_allows_inflight_target_but_starts_no_next(tmp_path, monkeypatch):
    import numpy as np
    c = Campaigns(tmp_path)
    ids = cohort()
    second = copy.deepcopy(ids["targets"][0])
    second["tic"] = "456"
    for role in ("discovery", "validation"):
        second[role]["tic"] = "456"
        second[role]["uri"] = second[role]["uri"].replace("0000000000000123", "0000000000000456")
    ids["targets"].append(second)
    cid = c.create(ids, {"search_schedule_seconds": 60})["campaign_id"]
    clock, calls = [1000.0], []
    monkeypatch.setattr("rediscover.campaigns.time.time", lambda: clock[0])
    def fetch(*a, **k):
        clock[0] = 1200.0
        return {"time": np.arange(10.), "flux": np.ones(10), "flux_err": np.ones(10), "metadata": {}}
    def search(*a, **k):
        calls.append(1)
        return {"candidate": {"period_days": 3.0}}
    monkeypatch.setattr(c, "_store_data", fetch)
    monkeypatch.setattr("rediscover.transit.search_transits", search)
    result = c.search(cid)
    assert calls == [1, 1]
    assert result["total"] == 2 and result["failures"] == 1


def test_report_counts_attempts_not_successes(tmp_path):
    from rediscover.tess_report import make_campaign_report
    c = Campaigns(tmp_path)
    cid = c.create(cohort())["campaign_id"]
    row = {"tic": "123", "search": {"tic": "123", "error": "fetch failed"},
           "validation": {"tic": "123", "status": "unavailable", "error": "timeout"},
           "verdict": {"status": "UNRESOLVED", "reasons": ["fixture"]}}
    c.workspace.save(cid, "review.json", {"targets": [row]})
    c.workspace.save(cid, "verdict.json", {"total_targets": 1, "counts": {"UNRESOLVED": 1}, "confirmed_new_planets": 0})
    c.workspace.save(cid, "hypotheses.json", {"hypotheses": []})
    c.workspace.save(cid, "validation.json", {"targets": [row["validation"]]})
    report = make_campaign_report(c, cid)
    assert report["summary"]["completed_searches"] == 0
    assert report["summary"]["independent_tests"] == 0
    assert report["summary"]["holdout_attempts"] == 1
    assert report["summary"]["successful_code_experiments"] == 0
    text = __import__("pathlib").Path(report["html"]).read_text()
    assert "synthetic state-machine fixture" in text
    assert "Generated code ran against discovery data" not in text

def test_concurrent_reservation_does_not_overspend(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    c = Campaigns(tmp_path)
    cid = c.create(cohort(), {"max_code_experiments": 1})["campaign_id"]
    c.workspace.save(cid, "search.json", {"targets": []})
    def reserve(_):
        try:
            return Campaigns(tmp_path).reserve_research(cid, 1)
        except ValueError:
            return []
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, [0, 1]))
    assert sum(len(x) for x in results) == 1


def test_provider_failure_consumes_reserved_slots_without_critique(tmp_path, monkeypatch):
    from rediscover.research_agent import run_experiments
    c = Campaigns(tmp_path)
    cid = c.create(cohort(), {"max_code_experiments": 2})["campaign_id"]
    c.workspace.save(cid, "search.json", {"targets": [{"tic": "123", "candidate": {"depth_snr": 9}}]})
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise ValueError("Synthetic provider failure")
    monkeypatch.setattr("rediscover.research_agent.request_json", fail)
    result = run_experiments(c, cid, "mock", 2)
    assert calls == [1]
    assert result["critique"] is None
    with pytest.raises(ValueError, match="remaining"):
        c.reserve_research(cid, 1)

