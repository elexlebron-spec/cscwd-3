"""Prospectively fixed supplementary budget/timing intervention; core stays frozen."""
import argparse
from bisect import bisect_right
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import hashlib
import json
from math import log
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import feasible
from policies import bundle_fast
from simulation import generate_trace, snapshot_at, evaluate_action
from run_confirmatory import code_hash
from analyze_pilot import paired_stats

CONFIG = ROOT / "configs/budget_timing_intervention_v1.json"
OUT = ROOT / "results/runs/budget_timing_intervention_v1"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def adjusted_snapshot(snapshot, target, enabled, target_probability):
    """Only observed rates are read here, never the future path or true rates."""
    if not enabled:
        return snapshot
    task = snapshot.tasks[target]
    hazard = sum(snapshot.rates[i] for i in task.inputs)
    delay = min(task.delay, -log(target_probability) / hazard) if hazard > 0 else task.delay
    tasks = list(snapshot.tasks)
    tasks[target] = replace(task, delay=delay)
    return replace(snapshot, tasks=tuple(tasks))


def arm(trace, target, method, shortened, config):
    cache = [len(h) for h in trace.history_events]
    records = []
    for window in range(config["windows"]):
        base, source = snapshot_at(trace, window, cache, config["budget_fraction"])
        snap = adjusted_snapshot(base, target, shortened, config["target_probability"])
        action = snap.stale if method == "all" else bundle_fast(snap, True)
        assert action <= snap.stale
        if method != "all":
            assert feasible(snap, action)
        before = list(cache)
        cache, fresh = evaluate_action(trace, window, cache, snap, action)
        covered = all(cache[i] == source[i] for i in trace.inputs[target])
        if fresh[target]:
            assert covered
        records.append({"window": window, "selected_files": sorted(action),
                        "cache_before": before, "cache_after": list(cache), "source_at_boundary": list(source),
                        "budget": snap.budget, "sync_cost": sum(trace.costs[i] for i in action),
                        "target_delay": snap.tasks[target].delay, "original_target_delay": base.tasks[target].delay,
                        "target_historical_hazard": sum(snap.rates[i] for i in trace.inputs[target]),
                        "target_boundary_covered": covered, "target_fresh": fresh[target],
                        "target_failure": "none" if fresh[target] else "post_import_update" if covered else "missing_at_boundary",
                        "fresh_task_ids": [j for j, ok in enumerate(fresh) if ok], "all_task_fresh_fraction": mean(fresh)})
    return {"seed": trace.seed, "method": method, "timing": "history_cap" if shortened else "original",
            "target_task_index": target, "target_input_count": len(trace.inputs[target]),
            "summary": {"target_fresh_percent": 100 * mean(r["target_fresh"] for r in records),
                        "target_boundary_coverage_percent": 100 * mean(r["target_boundary_covered"] for r in records),
                        "target_post_import_failure_percent": 100 * mean(r["target_failure"] == "post_import_update" for r in records),
                        "target_missing_at_boundary_percent": 100 * mean(r["target_failure"] == "missing_at_boundary" for r in records),
                        "mean_target_delay": mean(r["target_delay"] for r in records),
                        "all_task_fresh_percent": 100 * mean(r["all_task_fresh_fraction"] for r in records),
                        "total_sync_cost": sum(r["sync_cost"] for r in records)}, "windows": records}


def freeze():
    assert not CONFIG.exists() and not OUT.exists(), "Never overwrite a registered protocol or prior outputs"
    lock = json.loads((ROOT / "configs/confirmatory.lock.json").read_text())
    assert code_hash() == lock["code_sha256"]
    config = {"version": "budget_timing_intervention_v1", "status": "FROZEN_BEFORE_NEW_SEED_RUN",
              "frozen_utc": datetime.now(timezone.utc).isoformat(),
              "motivation": "Previous primary outcomes seen; this is a targeted supplementary intervention, not independent discovery or a replacement primary experiment",
              "seeds": list(range(1000, 1020)), "prior_main_and_pilot_seeds": list(range(5)) + list(range(100, 120)),
              "structure": "seismology", "windows": 30, "history_duration": 100.0,
              "mean_rate": 0.5, "cv": 1.0, "eta": 0.0, "delay_mode": "uniform", "budget_fraction": 0.1,
              "target_rule": "Largest input group, ties lowest task index, selected using topology only",
              "target_probability": 0.5,
              "timing_rule": "Only target delay becomes min(original delay, -log(0.5)/sum historical count-rate estimates); zero estimated hazard leaves delay unchanged",
              "arms": ["sabs_partial_original", "sabs_partial_history_cap", "all_original", "all_history_cap"],
              "shared_exogenous_events": True, "true_rates_visible_only_to_generator_evaluator": True,
              "primary_endpoint": "Target-group fresh-use percentage for each arm and paired timing effect under All",
              "secondary_endpoints": ["Target boundary coverage", "exclusive missing/post-import failure categories", "all-task freshness", "actual delay reduction"],
              "analysis": "20 paired seed means, bootstrap 10000; intervals per comparison; no task/window pseudoreplication",
              "guardrails": "No target/parameter/seed changes after results; report negative outcomes; All has unconstrained cost; no cost-free scheduling claim or deployment guarantee",
              "core_lock": lock, "script_sha256": digest(__file__),
              "structure_sha256": digest(ROOT / "data/public/seismology_structure.json")}
    write(CONFIG, config)
    print(json.dumps({"protocol": str(CONFIG), "status": config["status"], "sha256": digest(CONFIG)}))


def run():
    c = json.loads(CONFIG.read_text())
    assert c["status"] == "FROZEN_BEFORE_NEW_SEED_RUN"
    assert c["script_sha256"] == digest(__file__) and code_hash() == c["core_lock"]["code_sha256"]
    assert not set(c["seeds"]) & set(c["prior_main_and_pilot_seeds"])
    assert digest(ROOT / "data/public/seismology_structure.json") == c["structure_sha256"]
    data = json.loads((ROOT / "data/public/seismology_structure.json").read_text())
    inputs = tuple(frozenset(v) for v in data["inputs"])
    target = max(range(len(inputs)), key=lambda j: (len(inputs[j]), -j))
    metadata = OUT / "metadata.json"
    binding = {"protocol_sha256": digest(CONFIG), "script_sha256": digest(__file__), "core_lock": c["core_lock"]}
    if metadata.exists():
        assert json.loads(metadata.read_text())["binding"] == binding
    else:
        write(metadata, {"binding": binding, "started_utc": datetime.now(timezone.utc).isoformat(), "target_task_index": target})
        for path in (CONFIG, Path(__file__)):
            saved = OUT / "source_snapshot" / path.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(path.read_bytes())
    summaries = []
    for seed in c["seeds"]:
        trace = generate_trace(seed, c["mean_rate"], c["cv"], c["delay_mode"], c["eta"],
                               c["windows"], c["history_duration"], inputs, data["stats"]["sync_files"], "seismology")
        payload = asdict(trace); payload["inputs"] = [sorted(v) for v in trace.inputs]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        path = OUT / "traces" / ("seed" + str(seed) + ".json.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assert gzip.decompress(path.read_bytes()) == encoded
        else:
            path.write_bytes(gzip.compress(encoded, mtime=0))
        trace_hash = hashlib.sha256(encoded).hexdigest()
        for method in ("sabs_partial", "all"):
            for shortened in (False, True):
                name = method + ("_history_cap" if shortened else "_original")
                record_path = OUT / "records" / ("seed" + str(seed) + "_" + name + ".json")
                if record_path.exists():
                    record = json.loads(record_path.read_text()); assert record["trace_sha256"] == trace_hash
                else:
                    record = arm(trace, target, method, shortened, c)
                    record.update({"arm": name, "trace_sha256": trace_hash})
                    write(record_path, record)
                summaries.append({k: record[k] for k in ("seed", "arm", "summary")})
        print("completed intervention seed", seed, flush=True)
    table = {}
    for name in c["arms"]:
        rows = [r["summary"] for r in summaries if r["arm"] == name]
        table[name] = {k: mean(r[k] for r in rows) for k in rows[0]}
    comparisons = {}
    for name, a, b in [("timing_under_all", "all_history_cap", "all_original"),
                       ("timing_under_budget", "sabs_partial_history_cap", "sabs_partial_original"),
                       ("capacity_original_timing", "all_original", "sabs_partial_original"),
                       ("capacity_capped_timing", "all_history_cap", "sabs_partial_history_cap")]:
        values = []
        for seed in c["seeds"]:
            row = {r["arm"]: r["summary"]["target_fresh_percent"] for r in summaries if r["seed"] == seed}
            values.append(row[a] - row[b])
        comparisons[name] = paired_stats(values, "budget_timing:" + name)
    write(OUT / "summary.json", {"status": "SUPPLEMENT_COMPLETE", "protocol": c, "policy_traces": len(summaries),
          "windows": len(summaries) * c["windows"], "target_task_index": target, "target_inputs": len(inputs[target]),
          "arm_means": table, "paired_target_effects_pp": comparisons, "per_seed": summaries,
          "completed_utc": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"arm_means": table, "paired_target_effects_pp": comparisons}, indent=2), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("action", choices=["freeze", "run"])
    {"freeze": freeze, "run": run}[p.parse_args().action]()
