"""One application layer shared by the CLI, MCP server and agent harness."""
from __future__ import annotations

import math
import threading
from pathlib import Path

import numpy as np

from . import data
from .workspace import Workspace

LIMITATIONS = [
    "Event-centred educational reproduction, not an independent discovery search.",
    "Peak matched-filter SNR is not a false-alarm probability or detection significance.",
    "Masses are coarse, detector-frame, nonspinning bank estimates, not posterior intervals.",
    "Independent detector peak times are template-dependent, not a coherent localization fit.",
    "A short-segment PSD and finite template bank do not reproduce the collaboration pipeline.",
]


class Lab:
    def __init__(self, root: str | Path | None = None):
        self.workspace = Workspace(root)
        self.compute_lock = threading.Lock()

    def prepare(self, metadata: dict, datasets: dict) -> str:
        if not datasets or not set(datasets).issubset({"H1", "L1"}):
            raise ValueError("Only H1 and L1 datasets are supported")
        inputs = {"metadata": metadata, "detectors": {}, "limitations": LIMITATIONS}
        for detector, dataset in datasets.items():
            inputs["detectors"][detector] = {
                k: v for k, v in dataset.items() if k != "strain"}
        run_id = self.workspace.create(inputs)
        for detector, dataset in datasets.items():
            name = f"{detector}.npz"
            np.savez_compressed(self.workspace.file(run_id, name), strain=dataset["strain"])
            self.workspace.seal(run_id, name)
        self.workspace.record(run_id, "fetch_strain", {}, {
            "detectors": inputs["detectors"], "metadata": metadata})
        return run_id

    def fetch(self, event: str = "GW150914-v3") -> dict:
        detail, datasets = data.fetch_event(event, self.workspace.root / "cache")
        run_id = self.prepare(detail, datasets)
        return self.describe(run_id)

    def describe(self, run_id: str) -> dict:
        inputs = self.workspace.read(run_id, "input.json")
        return {"run_id": run_id, "metadata": inputs["metadata"],
                "detectors": list(inputs["detectors"]), "limitations": LIMITATIONS,
                "next": "check_data_quality, analyze_detector for each detector, then make_report"}

    def dataset(self, run_id: str, detector: str) -> dict:
        if detector not in {"H1", "L1"}:
            raise ValueError("Detector must be H1 or L1")
        if not self.workspace.verify(run_id)["valid"]:
            raise ValueError("Run artifact integrity check failed")
        inputs = self.workspace.read(run_id, "input.json")
        if detector not in inputs["detectors"]:
            raise ValueError("Detector is not available in this run")
        result = dict(inputs["detectors"][detector])
        with np.load(self.workspace.file(run_id, f"{detector}.npz"), allow_pickle=False) as f:
            result["strain"] = f["strain"]
        return result

    def quality(self, run_id: str, detector: str) -> dict:
        from .physics import quality_check
        ds = self.dataset(run_id, detector)
        result = quality_check(ds["strain"], ds["sample_rate"])
        result["gwosc_quality"] = ds["data_quality"]
        return self.workspace.record(run_id, "check_data_quality", {"detector": detector}, result)

    def analyze(self, run_id: str, detector: str, f_low: float = 30.0,
                masses: list[float] | None = None) -> dict:
        ds = self.dataset(run_id, detector)
        quality = ds["data_quality"]
        if quality.get("all_data_present") is not True or quality.get("all_cbc_category1") is False:
            raise ValueError("Data quality does not permit this analysis")
        injection_bits = quality.get("injection_bits", {})
        if injection_bits.get("NO_CBC_HW_INJ") is False:
            raise ValueError("CBC hardware injection flagged in this data")
        from .physics import analyze_detector
        metadata = self.workspace.read(run_id, "input.json")["metadata"]
        with self.compute_lock:
            result = analyze_detector(ds["strain"], ds["sample_rate"], ds["gps_start"],
                                      metadata["gps"], f_low=f_low, masses=masses)
        result["detector"] = detector
        result["data_quality"] = quality
        result["limitations"] = LIMITATIONS
        return self.workspace.record(run_id, "analyze_detector",
                                     {"detector": detector, "f_low": f_low, "masses": masses}, result)

    def results(self, run_id: str) -> dict:
        events = sorted(self.workspace.evidence(run_id), key=lambda x: x["recorded_at"])
        detectors = {}
        for e in events:
            if e["tool"] == "analyze_detector":
                detectors[e["result"]["detector"]] = e
        combined = {}
        if {"H1", "L1"}.issubset(detectors):
            hanford, livingston = (detectors[d]["result"] for d in ("H1", "L1"))
            delay = hanford["peak_gps"] - livingston["peak_gps"]
            combined = {"h1_minus_l1_seconds": delay,
                        "within_light_travel_time": abs(delay) <= 0.0101,
                        "quadrature_snr": math.hypot(hanford["snr"], livingston["snr"]),
                        "note": "Independent maxima; quadrature SNR is not a coherent network statistic."}
        return {"run_id": run_id, "detectors": detectors, "combined": combined,
                "limitations": LIMITATIONS}

    def catalog(self, run_id: str) -> dict:
        detail = self.workspace.read(run_id, "input.json")["metadata"]
        if "parameters_url" not in detail:
            raise ValueError("Catalog access is unavailable for opaque benchmark tasks")
        result = data.catalog_parameters(detail)
        return self.workspace.record(run_id, "catalog_comparison", {}, result)

    def report(self, run_id: str) -> dict:
        from .report import make_report
        with self.compute_lock:
            return make_report(self, run_id)
