"""Regression cases from the independent release review."""
import json
from concurrent.futures import ProcessPoolExecutor

import httpx
import pytest

from rediscover.agent import run_agent, validate_final
from rediscover.service import Lab
from rediscover.workspace import Workspace


def result_h1():
    return {"detectors": {"H1": {"evidence_id": "e-good", "result": {
        "snr": 12.0, "chirp_mass": 30.0, "peak_gps": 100.0}}}}


def final_h1():
    return {"candidate": True, "measurements": [{"detector": "H1", "evidence_id": "e-good",
        "snr": 12.0, "chirp_mass": 30.0, "peak_gps": 100.0}]}


def test_requires_prepared_detectors():
    assert not validate_final(final_h1(), result_h1(), ["H1", "L1"])["valid"]


@pytest.mark.parametrize("detector", [[], {}, None, 1, True])
def test_all_json_detector_types_rejected(detector):
    final = final_h1()
    final["measurements"][0]["detector"] = detector
    assert not validate_final(final, result_h1())["valid"]


def test_rejected_model_final_is_persisted(tmp_path, monkeypatch):
    lab = Lab(tmp_path)
    run_id = lab.workspace.create({"metadata": {}, "detectors": {"H1": {}, "L1": {}}})
    monkeypatch.setattr(lab, "results", lambda _: result_h1())
    real_client = httpx.Client
    response = {"status": "completed", "model": "mock-test-model", "usage": {"total_tokens": 3},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(final_h1())}]}]}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    monkeypatch.setattr("rediscover.agent.httpx.Client", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setenv("REDISCOVER_API_BASE", "https://model.example/v1")
    monkeypatch.setenv("REDISCOVER_API_KEY", "synthetic-test-key-not-a-credential")
    result = run_agent(lab, run_id, "mock-test-model")
    assert result["status"] == "ungrounded_final"
    assert any(e["tool"] == "agent_run" for e in lab.workspace.evidence(run_id))


def test_http_and_hidden_setup_failures_are_counted(tmp_path, monkeypatch):
    from rediscover.benchmark import benchmark
    lab = Lab(tmp_path)
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout("test transport failure")
    monkeypatch.setattr(lab, "fetch", fail)
    monkeypatch.setattr("rediscover.benchmark.make_hidden_tasks", fail)
    result = benchmark(lab, events=["GW150914-v3"])
    assert result["passed"] == 0
    assert result["total"] == 4  # one named + all three opaque setup failures
    assert len(result["setup_failures"]) == 4
    assert json.loads(__import__("pathlib").Path(result["path"]).read_text())["total"] == 4


def write_evidence(args):
    root, run_id, index = args
    return Workspace(root).record(run_id, "test", {}, {"index": index})["evidence_id"]


def test_multiprocess_manifest_keeps_every_record(tmp_path):
    w = Workspace(tmp_path)
    run_id = w.create({"fixture": "concurrency"})
    import multiprocessing
    with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context("spawn")) as pool:
        ids = list(pool.map(write_evidence, [(str(tmp_path), run_id, i) for i in range(32)]))
    assert {e["evidence_id"] for e in w.evidence(run_id)} == set(ids)
    assert w.verify(run_id)["valid"]


@pytest.mark.parametrize("name,version", [("/outside", 1), ("../../outside", 1), ("GW150914", "../../x")])
def test_remote_metadata_cannot_escape_cache(tmp_path, monkeypatch, name, version):
    from rediscover.data import fetch_event
    monkeypatch.setattr("rediscover.data.event_files", lambda _: (
        {"name": name, "version": version}, [{"detector": "H1", "download_url": "https://gwosc.org/test", "duration": 32}]))
    monkeypatch.setattr("rediscover.data.download", lambda *_: pytest.fail("unsafe path reached downloader"))
    with pytest.raises(ValueError):
        fetch_event("GW150914-v3", tmp_path / "cache")


def test_cache_symlink_escape_is_rejected(tmp_path, monkeypatch):
    from rediscover.data import fetch_event
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "GW150914-v3-H1.hdf5").symlink_to(tmp_path / "outside.hdf5")
    monkeypatch.setattr("rediscover.data.event_files", lambda _: (
        {"name": "GW150914", "version": 3}, [{"detector": "H1", "download_url": "https://gwosc.org/test", "duration": 32}]))
    monkeypatch.setattr("rediscover.data.download", lambda *_: pytest.fail("unsafe path reached downloader"))
    with pytest.raises(ValueError):
        fetch_event("GW150914-v3", cache)
