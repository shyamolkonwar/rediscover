import importlib.util


def test_research_module_exists():
    assert importlib.util.find_spec("rediscover.research_agent") is not None


def test_planner_cannot_relax_acceptance_rules(monkeypatch):
    import pytest

    from rediscover.research_agent import propose_plan
    monkeypatch.setattr("rediscover.research_agent.request_json", lambda *a, **k: {
        "result": {"objective": "test", "hypothesis": "test", "parameters": {"snr_threshold": 1}},
        "model": "synthetic-test-provider", "usage": {}})
    with pytest.raises(ValueError):
        propose_plan({"targets": []}, "test")


def test_experiment_prompt_cannot_access_holdout(tmp_path):
    import pytest
    from test_campaigns import cohort

    from rediscover.campaigns import Campaigns
    c = Campaigns(tmp_path)
    cid = c.create(cohort())["campaign_id"]
    c.workspace.save(cid, "hypotheses.json", {"hypotheses": []})
    with pytest.raises(ValueError, match="freeze"):
        c.explore(cid, "123", "print('no')")
