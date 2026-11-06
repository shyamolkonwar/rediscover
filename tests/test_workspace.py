import importlib.util


def test_workspace_exists():
    assert importlib.util.find_spec("rediscover.workspace") is not None


def test_immutable_evidence_and_tamper_detection(tmp_path):
    import pytest

    from rediscover.workspace import Workspace
    w = Workspace(tmp_path)
    run_id = w.create({"event": "GW150914"})
    evidence = w.record(run_id, "check", {}, {"snr": 12.0})
    assert evidence["evidence_id"]
    assert w.verify(run_id)["valid"]
    (w.path(run_id) / "input.json").write_text("{}")
    assert not w.verify(run_id)["valid"]
    with pytest.raises(ValueError):
        w.read(run_id, "input.json")


def test_run_id_traversal_rejected(tmp_path):
    import pytest

    from rediscover.workspace import Workspace
    w = Workspace(tmp_path)
    for run_id in ["../x", "/etc", "abc", "a" * 32 + "/x"]:
        with pytest.raises(ValueError):
            w.path(run_id)


def test_nonfinite_json_rejected(tmp_path):
    import pytest

    from rediscover.workspace import Workspace
    with pytest.raises(ValueError):
        Workspace(tmp_path).create({"value": float("nan")})
