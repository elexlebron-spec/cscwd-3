"""Independent version-level audit of saved branch records (no policy re-fitting)."""
from bisect import bisect_right
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/runs/mechanism_probe_v1"
PRIMARY = ROOT / "results/runs/confirmatory_v1"


def main():
    c = json.loads((ROOT / "configs/mechanism_probe_v1.json").read_text())
    meta = json.loads((RUN / "metadata.json").read_text())
    assert c["recorded_utc"] < meta["started_utc"] and c["primary_test_outcomes_already_seen"]
    for relative, key in [("scripts/analyze_mechanism_probe.py", "probe_code_sha256"),
                          ("configs/mechanism_probe_v1.json", "config_sha256")]:
        data = (ROOT / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == meta["binding"][key]
        assert data == (RUN / "source_snapshot" / relative).read_bytes()
    pairs, keys, evaluated = [], set(), 0
    for seed in c["seeds"]:
        raw = gzip.decompress((PRIMARY / "traces" / (c["case"] + "_seed" + str(seed) + ".json.gz")).read_bytes())
        trace = json.loads(raw); r = json.loads((RUN / ("seed" + str(seed) + ".json")).read_text())
        assert r["trace_sha256"] == hashlib.sha256(raw).hexdigest()
        saved = json.loads((PRIMARY / "records" / (c["case"] + "_b0.1_seed" + str(seed) + "_sabs_partial.json")).read_text())["windows"]
        base_cache = [len(h) for h in trace["history_events"]]; states = []
        for window, row in enumerate(saved):
            states.append(list(base_cache))
            for i in row["selected_files"]:
                base_cache[i] = len(trace["history_events"][i]) + bisect_right(trace["future_events"][i], window)
        for pair in r["pairs"]:
            key = (seed, pair["intervention_window"]);assert key not in keys;keys.add(key)
            total = 0; previous = {"weighted_initial_branch": list(states[key[1]]), "unweighted_initial_branch": list(states[key[1]])}
            assert len(pair["steps"]) == c["followup_windows"] + 1
            for offset, step in enumerate(pair["steps"]):
                t = key[1] + offset; assert step["window"] == t and step["offset"] == offset
                for name in previous:
                    row = step[name]; assert row["cache_before"] == previous[name]
                    source = [len(h) + bisect_right(f, t) for h, f in zip(trace["history_events"], trace["future_events"])]
                    stale = [i for i in range(len(source)) if row["cache_before"][i] != source[i]]
                    assert row["stale_before"] == stale
                    action = row["selected_files"]; assert len(action) == len(set(action)) and set(action) <= set(stale)
                    cost = sum(trace["costs"][i] for i in action)
                    assert cost == row["sync_cost"] and cost <= .1 * sum(trace["costs"]) + 1e-9
                    cache = list(row["cache_before"])
                    for i in action: cache[i] = source[i]
                    assert cache == row["cache_after"]
                    fresh = [j for j, inputs in enumerate(trace["inputs"]) if all(
                        cache[i] == len(trace["history_events"][i]) + bisect_right(trace["future_events"][i], t + trace["delays"][t][j]) for i in inputs)]
                    assert fresh == row["fresh_task_ids"] and len(fresh) == row["fresh_count"]
                    if name == "weighted_initial_branch":
                        assert action == saved[t]["selected_files"] and abs(len(fresh) / len(trace["inputs"]) - saved[t]["fresh_fraction"]) < 1e-12
                    previous[name] = cache; evaluated += 1
                delta = step["weighted_initial_branch"]["fresh_count"] - step["unweighted_initial_branch"]["fresh_count"]
                total += delta; assert delta == step["fresh_delta"] and total == step["cumulative_fresh_delta"]
            if not pair["initial_action_differs"]:
                assert all(step["weighted_initial_branch"] == step["unweighted_initial_branch"] for step in pair["steps"])
            pairs.append(pair)
    assert keys == {(seed, window) for seed in c["seeds"] for window in c["intervention_windows"]}
    summary = json.loads((RUN / "summary.json").read_text())
    for label, group in summary["groups"].items():
        chosen = [p for p in pairs if label == "all_interventions" or p["initial_fresh_delta"] > 0]
        assert group["pairs"] == len(chosen)
        for h, stat in enumerate(group["series"]):
            vals = [mean(p["steps"][h]["cumulative_fresh_delta"] for p in chosen if p["seed"] == seed) for seed in c["seeds"]]
            assert vals == stat["seed_values"] and abs(mean(vals) - stat["mean"]) < 1e-12
    selected = next(p for p in sorted(pairs, key=lambda p: (p["seed"], p["intervention_window"])) if p["initial_fresh_delta"] > 0)
    assert selected == summary["representative"]
    result = {"status": "PASS", "paired_interventions": len(pairs), "branch_windows": evaluated,
              "checks": ["protocol_before_execution_with_seen_outcomes_disclosed", "probe_code_and_config_snapshots",
                         "complete_seed_window_matrix", "cache_continuity", "all_budgets_and_stale_actions",
                         "version_exact_fresh_task_ids", "weighted_branch_matches_original", "cumulative_deltas",
                         "identical_actions_identical_followups", "seed_level_aggregates", "representative_selection_rule"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
