"""Targeted validation supplement prompted by cheap exact pilot solves."""
import gzip
import hashlib
import json
import sys
from pathlib import Path
from statistics import mean, median
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import value
from optimization import solve_snapshot
from policies import bundle_fast
from simulation import Trace, evaluate_action, snapshot_at
from run_pilot import atomic_json, source_hash


def main():
    parent = ROOT / "results/runs/phase1_pilot_v1"
    out = ROOT / "results/runs/phase1_solver_supplement_v1"
    out.mkdir(exist_ok=True)
    raw = (ROOT / "configs/pilot_supplement.json").read_bytes()
    config = json.loads(raw)
    parent_meta = json.loads((parent / "metadata.json").read_text())
    if parent_meta["source_sha256"] != source_hash():
        raise ValueError("base implementation changed since pilot")
    metadata = {"phase": "VALIDATION_SUPPLEMENT_ONLY", "parent_source_sha256": source_hash(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "config_sha256": hashlib.sha256(raw).hexdigest(), "config": config}
    atomic_json(out / "metadata.json", metadata)
    summaries = []
    for case in config["cases"]:
        for seed in config["seeds"]:
            packed = (parent / "traces" / (case + "_seed" + str(seed) + ".json.gz")).read_bytes()
            payload = json.loads(gzip.decompress(packed))
            payload["inputs"] = tuple(frozenset(v) for v in payload["inputs"])
            payload["group_shock_rates"] = {int(k): v for k, v in payload["group_shock_rates"].items()}
            trace = Trace(**payload)
            for survival in (True, False):
                cache = [len(h) for h in trace.history_events]
                rows = []
                for window in range(config["windows"]):
                    snapshot, _ = snapshot_at(trace, window, cache, config["budget_fraction"])
                    result = solve_snapshot(snapshot, survival, config["solver_limit_seconds"])
                    if result["action"] is None:
                        raise RuntimeError("supplement has no feasible solver incumbent")
                    action = frozenset(result["action"])
                    cache, fresh = evaluate_action(trace, window, cache, snapshot, action)
                    timings, heuristic = [], None
                    for _ in range(config["same_snapshot_timing_repetitions"]):
                        t0 = perf_counter()
                        heuristic = bundle_fast(snapshot, survival)
                        timings.append(perf_counter() - t0)
                    # No lookahead; solver ties need not favor partial future progress.
                    rows.append({"window": window, "fresh_fraction": sum(fresh) / len(fresh),
                                 "solver": result, "action": sorted(action),
                                 "heuristic_action_same_snapshot": sorted(heuristic),
                                 "heuristic_value_same_snapshot": value(snapshot, heuristic, survival),
                                 "heuristic_seconds_same_snapshot": median(timings),
                                 "nonempty_stale_set": bool(snapshot.stale)})
                method = "milp_survival_dynamic" if survival else "milp_no_survival_dynamic"
                summary = {"case": case, "seed": seed, "method": method,
                           "fresh_fraction": mean(r["fresh_fraction"] for r in rows),
                           "all_optimal": all(r["solver"]["status"] == 0 for r in rows),
                           "nonempty_snapshots": sum(r["nonempty_stale_set"] for r in rows)}
                atomic_json(out / "records" / (case + "_seed" + str(seed) + "_" + method + ".json"),
                            {"summary": summary, "windows": rows,
                             "trace_gzip_sha256": hashlib.sha256(packed).hexdigest()})
                summaries.append(summary)
                print("completed", case, seed, method, summary["fresh_fraction"], flush=True)
    atomic_json(out / "summary.json", summaries)
    print("SUPPLEMENT_COMPLETE", len(summaries), flush=True)


if __name__ == "__main__":
    main()
