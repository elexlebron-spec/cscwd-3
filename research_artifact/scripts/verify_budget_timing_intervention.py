"""Independent version-exact audit of the supplementary intervention records."""
from bisect import bisect_right
import gzip
import hashlib
import json
from math import log
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from run_confirmatory import code_hash


def main():
    out = ROOT / "results/runs/budget_timing_intervention_v1"
    c = json.loads((ROOT / "configs/budget_timing_intervention_v1.json").read_text())
    assert code_hash() == c["core_lock"]["code_sha256"]
    assert hashlib.sha256((ROOT / "scripts/run_budget_timing_intervention.py").read_bytes()).hexdigest() == c["script_sha256"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["policy_traces"] == 80 and summary["windows"] == 2400
    totals, followup = {}, {}
    checked = 0
    for seed in c["seeds"]:
        raw = gzip.decompress((out / "traces" / ("seed" + str(seed) + ".json.gz")).read_bytes())
        trace = json.loads(raw)
        target = max(range(len(trace["inputs"])), key=lambda j: (len(trace["inputs"][j]), -j))
        for name in c["arms"]:
            record = json.loads((out / "records" / ("seed" + str(seed) + "_" + name + ".json")).read_text())
            assert record["trace_sha256"] == hashlib.sha256(raw).hexdigest()
            cache = [len(h) for h in trace["history_events"]]
            for window, row in enumerate(record["windows"]):
                assert row["cache_before"] == cache and row["window"] == window
                current = [len(h) + bisect_right(f, window) for h, f in zip(trace["history_events"], trace["future_events"])]
                assert row["source_at_boundary"] == current
                hazard = sum(current[i] / (trace["history_duration"] + window) for i in trace["inputs"][target])
                original_delay = trace["delays"][window][target]
                expected_delay = min(original_delay, -log(c["target_probability"]) / hazard) if name.endswith("history_cap") and hazard > 0 else original_delay
                assert abs(row["target_delay"] - expected_delay) < 1e-12
                assert abs(row["target_historical_hazard"] - hazard) < 1e-12
                selected = row["selected_files"]
                assert len(selected) == len(set(selected))
                assert all(cache[i] != current[i] for i in selected)
                spent = sum(trace["costs"][i] for i in selected)
                assert abs(spent - row["sync_cost"]) < 1e-10
                if name.startswith("sabs"):
                    assert spent <= c["budget_fraction"] * sum(trace["costs"]) + 1e-10
                for i in selected:
                    cache[i] = current[i]
                assert row["cache_after"] == cache
                fresh = []
                for j, inputs in enumerate(trace["inputs"]):
                    delay = expected_delay if j == target else trace["delays"][window][j]
                    if all(cache[i] == len(trace["history_events"][i]) + bisect_right(trace["future_events"][i], window + delay) for i in inputs):
                        fresh.append(j)
                assert fresh == row["fresh_task_ids"] and (target in fresh) == row["target_fresh"]
                covered = all(cache[i] == current[i] for i in trace["inputs"][target])
                category = "none" if target in fresh else "post_import_update" if covered else "missing_at_boundary"
                assert row["target_boundary_covered"] == covered and row["target_failure"] == category
                checked += 1
            actual = 100 * mean(row["target_fresh"] for row in record["windows"])
            assert abs(actual - record["summary"]["target_fresh_percent"]) < 1e-12
            totals[name] = totals.get(name, 0) + sum(row["target_fresh"] for row in record["windows"])
            followup[name] = followup.get(name, 0) + sum(row["target_fresh"] for row in record["windows"][1:])
    result = {"status": "PASS", "records": 80, "windows": checked, "seeds": 20,
              "target_fresh_counts_all_600": totals, "target_fresh_counts_after_initial_580": followup,
              "initial_cache_caveat": "The nine budgeted capped-timing successes all occur at window zero with the initially current cache; no sustained recovery under the tested budget",
              "checks": ["frozen_core_and_script_hash", "complete_matrix", "past_only_delay_cap", "cache_continuity",
                         "all_budgets", "version_exact_every_task", "exclusive_failure_partition", "summary_values"]}
    (out / "INTEGRITY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
