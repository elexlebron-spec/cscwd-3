"""Audit preserved results; optionally replay frozen source in a clean directory."""
import argparse
from bisect import bisect_right
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from statistics import mean
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/runs/confirmatory_v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    config = json.loads((ROOT / "configs/confirmatory.json").read_text())
    lock = json.loads((ROOT / "configs/confirmatory.lock.json").read_text())
    meta = json.loads((RUN / "metadata.json").read_text())
    assert lock["config_sha256"] == sha(ROOT / "configs/confirmatory.json")
    assert lock["public_manifest_sha256"] == sha(ROOT / "data/public/manifest.json")
    manifest = json.loads((ROOT / "data/public/manifest.json").read_text())
    for selected in manifest["selected"]:
        assert sha(ROOT / selected["local_raw"]) == selected["sha256"]
        assert sha(ROOT / selected["local_structure"]) == selected["processed_sha256"]
    assert sha(ROOT / "data/public/raw/LICENSE") == manifest["license_sha256"]
    h = hashlib.sha256()
    paths = sorted((ROOT / "src").glob("*.py")) + [ROOT / "scripts/run_confirmatory.py"]
    for path in paths:
        h.update(str(path.relative_to(ROOT)).encode())
        h.update(path.read_bytes())
        assert path.read_bytes() == (RUN / "source_snapshot" / path.relative_to(ROOT)).read_bytes()
    assert h.hexdigest() == lock["code_sha256"]
    assert meta["lock"] == lock
    assert lock["frozen_utc"] < meta["started_utc"]
    assert not set(config["seeds"]) & set(config["excluded_validation_seeds"])
    streams, hashes = {}, {}
    for path in sorted((RUN / "traces").glob("*.json.gz")):
        raw = gzip.decompress(path.read_bytes())
        streams[path.name[:-8]] = json.loads(raw)
        hashes[path.name[:-8]] = hashlib.sha256(raw).hexdigest()
    expected, keys, windows, all_rows, grouped = [], set(), 0, {}, {}
    exact_outcomes = {}
    for case in config["cases"]:
        for seed in config["seeds"]:
            for budget in case["budgets"]:
                methods = list(config["methods"])
                if case["id"] in config["dynamic_solver"]["cases"] and budget == config["dynamic_solver"]["budget_fraction"]:
                    methods += ["milp_survival_dynamic", "milp_no_survival_dynamic"]
                expected.extend((case["id"], budget, seed, method) for method in methods)
    for path in sorted((RUN / "records").glob("*.json")):
        r = json.loads(path.read_text()); s = r["summary"]
        key = (r["case"], s["budget_fraction"], s["seed"], s["method"])
        assert key not in keys; keys.add(key)
        trace_key = r["case"] + "_seed" + str(s["seed"])
        trace = streams[trace_key]
        assert r["trace_sha256"] == hashes[trace_key]
        assert len(r["windows"]) == config["windows"]
        assert abs(mean(w["fresh_fraction"] for w in r["windows"]) - s["fresh_fraction"]) < 1e-12
        assert abs(sum(w["sync_cost"] for w in r["windows"]) - s["sync_cost"]) < 1e-9
        cache = [len(e) for e in trace["history_events"]]
        outcomes = []
        for t, w in enumerate(r["windows"]):
            assert w["window"] == t
            action = w["selected_files"]
            assert len(action) == len(set(action))
            assert all(0 <= i < len(trace["costs"]) for i in action)
            source = [len(h) + bisect_right(f, t) for h, f in zip(trace["history_events"], trace["future_events"])]
            assert all(cache[i] != source[i] for i in action)
            cost = sum(trace["costs"][i] for i in action)
            assert cost == w["sync_cost"]
            if s["method"] != "always_sync_unconstrained":
                assert cost <= s["budget_fraction"] * sum(trace["costs"]) + 1e-9
            for i in action:
                cache[i] = source[i]
            fresh = [all(cache[i] == len(trace["history_events"][i]) + bisect_right(trace["future_events"][i], t + delay)
                         for i in inputs) for inputs, delay in zip(trace["inputs"], trace["delays"][t])]
            assert abs(mean(fresh) - w["fresh_fraction"]) < 1e-12
            outcomes.append(fresh)
        exact_outcomes[key] = outcomes
        windows += len(r["windows"])
        g = key[:3]; grouped.setdefault(g, []).append(r)
        if s["method"] == "always_sync_unconstrained":
            all_rows[g] = r
    assert keys == set(expected)
    assert len(keys) == config["expected_policy_traces"]
    for group, records in grouped.items():
        reference = all_rows[group]["windows"]
        for r in records:
            assert all(a["fresh_fraction"] + 1e-12 >= b["fresh_fraction"]
                       for a, b in zip(reference, r["windows"]))
            key = group + (r["summary"]["method"],)
            optimal_key = group + ("always_sync_unconstrained",)
            assert all(not alternative or unrestricted
                       for a, b in zip(exact_outcomes[optimal_key], exact_outcomes[key])
                       for unrestricted, alternative in zip(a, b))
    return {"status": "PASS", "policy_traces": len(keys), "event_streams": len(streams),
            "policy_windows": windows, "frozen_hashes": lock,
            "checks": ["frozen_source_and_config", "raw_and_processed_data_hashes", "separate_seeds", "all_trace_hashes",
                       "all_actions_stale_and_feasible", "all_version_exact_freshness",
                       "all_window_aggregates", "all_sync_task_by_task_dominance", "complete_protocol_matrix"]}


def replay():
    # The child sees only saved experiment source and explicit preserved inputs.
    code = r'''
from dataclasses import asdict
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "src"))
from simulation import generate_trace, run_policy
p = json.loads(Path("request.json").read_text()); c = p["case"]
inputs = None if p["inputs"] is None else tuple(frozenset(v) for v in p["inputs"])
t = generate_trace(100, c["mean_rate"], c["cv"], c["delay_mode"], c["eta"],
                   30, 100, inputs, p["n_files"], c["structure"])
d = asdict(t); d["inputs"] = [sorted(v) for v in t.inputs]
h = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
r, _ = run_policy(t, .1, "sabs_partial")
Path("reply.json").write_text(json.dumps({"trace_sha256": h, "windows": [
    {k: w[k] for k in ("selected_files", "fresh_fraction")} for w in r["windows"]]}))
'''
    config = json.loads((ROOT / "configs/confirmatory.json").read_text())
    cases = [c for c in config["cases"] if c["id"] in ("synthetic_mu0.5", "public_seismology", "public_montage")]
    with tempfile.TemporaryDirectory(prefix="cscwd-frozen-replay-") as directory:
        temp = Path(directory)
        shutil.copytree(RUN / "source_snapshot/src", temp / "src")
        for case in cases:
            data = None if case["structure"] == "synthetic" else json.loads(
                (ROOT / ("data/public/" + case["structure"] + "_structure.json")).read_text())
            request = {"case": case, "inputs": None if data is None else data["inputs"],
                       "n_files": None if data is None else data["stats"]["sync_files"]}
            (temp / "request.json").write_text(json.dumps(request))
            subprocess.run([sys.executable, "-c", code], cwd=temp, check=True, capture_output=True, text=True)
            actual = json.loads((temp / "reply.json").read_text())
            expected = json.loads((RUN / "records" / (case["id"] + "_b0.1_seed100_sabs_partial.json")).read_text())
            assert actual["trace_sha256"] == expected["trace_sha256"]
            assert actual["windows"] == [{k: w[k] for k in ("selected_files", "fresh_fraction")} for w in expected["windows"]]
    return {"seed": 100, "method": "sabs_partial", "cases": [c["id"] for c in cases],
            "actions_and_freshness_match": True, "timings_compared": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    result = audit()
    if args.replay:
        result["clean_directory_replays"] = replay()
    print(json.dumps(result, indent=2))
