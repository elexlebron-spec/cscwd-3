"""Frozen held-out experiment. No model tuning or validation seeds allowed."""
import argparse
from dataclasses import asdict
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
from statistics import mean, median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import feasible, value
from optimization import solve_snapshot
from policies import bundle_fast
from simulation import generate_trace, run_policy, snapshot_at, evaluate_action


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def code_files():
    return sorted((ROOT / "src").glob("*.py")) + [Path(__file__).resolve()]


def code_hash():
    h = hashlib.sha256()
    for path in code_files():
        h.update(str(path.relative_to(ROOT)).encode()); h.update(path.read_bytes())
    return h.hexdigest()


def run_solver(trace, budget, survival, time_limit, repetitions):
    cache = [len(h) for h in trace.history_events]
    rows = []
    for window in range(len(trace.delays)):
        snapshot, _ = snapshot_at(trace, window, cache, budget)
        result = solve_snapshot(snapshot, survival, time_limit)
        # Prespecified failure rule: empty action; record failed incumbent.
        action = frozenset(result["action"] or [])
        if not feasible(snapshot, action):
            raise AssertionError("infeasible dynamic MILP action")
        cache, fresh = evaluate_action(trace, window, cache, snapshot, action)
        timings = []
        for _ in range(repetitions):
            t0 = perf_counter(); heuristic = bundle_fast(snapshot, survival)
            timings.append(perf_counter() - t0)
        rows.append({"window": window, "fresh_fraction": mean(fresh),
                     "selected_files": sorted(action),
                     "sync_cost": sum(trace.costs[i] for i in action),
                     "solver": result, "nonempty_stale_set": bool(snapshot.stale),
                     "heuristic_seconds_same_snapshot": median(timings),
                     "heuristic_value_same_snapshot": value(snapshot, heuristic, survival)})
    method = "milp_survival_dynamic" if survival else "milp_no_survival_dynamic"
    return {"summary": {"method": method, "seed": trace.seed, "structure": trace.name,
                        "budget_fraction": budget, "fresh_fraction": mean(r["fresh_fraction"] for r in rows),
                        "sync_cost": sum(r["sync_cost"] for r in rows),
                        "decision_seconds": [r["solver"]["seconds"] for r in rows],
                        "solver_optimal_windows": sum(r["solver"]["status"] == 0 for r in rows),
                        "solver_missing_incumbent_windows": sum(r["solver"]["action"] is None for r in rows)},
            "windows": rows, "diagnostics": [],
            "partial_fallback": False, "tie_policy": "raw_HiGHS_incumbent_no_extra_tie_break"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/confirmatory.json")
    args = parser.parse_args()
    config_path = ROOT / args.config
    raw_config = config_path.read_bytes(); config = json.loads(raw_config)
    lock_path = config_path.with_suffix(".lock.json")
    lock = json.loads(lock_path.read_text())
    if config["status"] != "FROZEN_BEFORE_HELD_OUT_RUN":
        raise ValueError("protocol is not frozen")
    assert lock["config_sha256"] == hashlib.sha256(raw_config).hexdigest()
    assert lock["code_sha256"] == code_hash()
    assert not set(config["seeds"]) & set(config["excluded_validation_seeds"])
    manifest = ROOT / "data/public/manifest.json"
    assert lock["public_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    out = ROOT / "results/runs" / config["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    import numpy, scipy
    meta_path = out / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        assert meta["lock"] == lock
    else:
        atomic_json(meta_path, {"phase": "HELD_OUT_CONFIRMATORY", "lock": lock,
                    "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "python": sys.version, "platform": platform.platform(), "cpus": os.cpu_count(),
                    "dependencies": {"numpy": numpy.__version__, "scipy": scipy.__version__},
                    "seeds": config["seeds"], "prior_validation_seeds_excluded": config["excluded_validation_seeds"]})
        for path in code_files() + [config_path, lock_path, ROOT / "requirements.txt"]:
            dest = out / "source_snapshot" / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
    summaries = []
    for case in config["cases"]:
        for seed in config["seeds"]:
            inputs, n_files = None, None
            if case["structure"] != "synthetic":
                data = json.loads((ROOT / ("data/public/" + case["structure"] + "_structure.json")).read_text())
                inputs = tuple(frozenset(v) for v in data["inputs"]); n_files = data["stats"]["sync_files"]
            trace = generate_trace(seed, case["mean_rate"], case["cv"], case["delay_mode"], case["eta"],
                                   config["windows"], config["history_duration"], inputs, n_files, case["structure"])
            payload = asdict(trace); payload["inputs"] = [sorted(v) for v in trace.inputs]
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            sha = hashlib.sha256(encoded).hexdigest()
            trace_path = out / "traces" / (case["id"] + "_seed" + str(seed) + ".json.gz")
            trace_path.parent.mkdir(exist_ok=True)
            if trace_path.exists():
                assert gzip.decompress(trace_path.read_bytes()) == encoded
            else:
                trace_path.write_bytes(gzip.compress(encoded, mtime=0))
            for budget in case["budgets"]:
                label = case["id"] + "_b" + str(budget) + "_seed" + str(seed)
                methods = list(config["methods"])
                solver_case = case["id"] in config["dynamic_solver"]["cases"] and budget == config["dynamic_solver"]["budget_fraction"]
                if solver_case:
                    methods += ["milp_survival_dynamic", "milp_no_survival_dynamic"]
                for method in methods:
                    path = out / "records" / (label + "_" + method + ".json")
                    snapshots = None
                    if path.exists():
                        record = json.loads(path.read_text()); assert record["trace_sha256"] == sha
                    else:
                        if method.startswith("milp_"):
                            record = run_solver(trace, budget, method == "milp_survival_dynamic",
                                                 config["solver_limit_seconds"], config["timing_repetitions"])
                        else:
                            record, snapshots = run_policy(trace, budget, method, diagnostics=(method == "sabs_partial"))
                        record.update({"case": case["id"], "trace_sha256": sha,
                                       "mean_rate": case["mean_rate"], "population_cv": case["cv"],
                                       "delay_mode": case["delay_mode"], "eta": case["eta"]})
                        atomic_json(path, record)
                    row = {k: v for k, v in record.items() if k not in ("summary", "windows", "diagnostics")}
                    row.update(record["summary"]); summaries.append(row)
                    scope = config["static_solver_slice"]
                    if method == "sabs_partial" and case["id"] == scope["case"] and budget in scope["budgets"] and seed in scope["seeds"]:
                        target = out / "milp" / (label + ".json")
                        if not target.exists():
                            if snapshots is None:
                                _, snapshots = run_policy(trace, budget, method, diagnostics=True)
                            comparisons = []
                            for window, snapshot in enumerate(snapshots[:scope["windows"]]):
                                for survival in (True, False):
                                    result = solve_snapshot(snapshot, survival, config["solver_limit_seconds"])
                                    result.update({"window": window, "survival": survival,
                                                   "heuristic_value": value(snapshot, bundle_fast(snapshot, survival), survival)})
                                    comparisons.append(result)
                            atomic_json(target, {"case": label, "comparisons": comparisons})
                print("completed", label, flush=True)
    atomic_json(out / "summary.json", summaries)
    assert len(summaries) == config["expected_policy_traces"]
    atomic_json(out / "completion.json", {"status": "CONFIRMATORY_COMPLETE", "policy_traces": len(summaries),
                "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print("CONFIRMATORY_COMPLETE", len(summaries), flush=True)


if __name__ == "__main__":
    main()
