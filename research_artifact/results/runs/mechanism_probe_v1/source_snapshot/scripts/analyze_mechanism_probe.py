"""Post-hoc one-action interventions with a common continuation on saved traces."""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import feasible
from policies import bundle_fast
from simulation import Trace, snapshot_at, evaluate_action
from run_confirmatory import code_hash
from analyze_pilot import paired_stats

ORIGINAL = ROOT / "results/runs/confirmatory_v1"
OUT = ROOT / "results/runs/mechanism_probe_v1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def statistics(values, key):
    r = paired_stats(values, key)
    return {"mean": r["mean_pp"], "low": r["lo_pp"], "high": r["hi_pp"],
            "n_seeds": r["n_seeds"], "seed_values": r["per_seed_pp"],
            "unit": "fresh-task uses, cumulative count difference"}


def branch(trace, start, cache, initial, horizon, reference=None):
    cache = list(cache); rows = []
    for offset in range(horizon + 1):
        window = start + offset
        snap, source = snapshot_at(trace, window, cache, 0.1)
        action = initial if offset == 0 else bundle_fast(snap, True)
        assert feasible(snap, action) and action <= snap.stale
        before = list(cache)
        cache, fresh = evaluate_action(trace, window, cache, snap, action)
        if reference is not None:
            saved = reference[window]
            assert sorted(action) == saved["selected_files"]
            assert abs(mean(fresh) - saved["fresh_fraction"]) < 1e-12
        rows.append({"offset": offset, "window": window, "selected_files": sorted(action),
                     "sync_cost": sum(trace.costs[i] for i in action),
                     "fresh_task_ids": [j for j, ok in enumerate(fresh) if ok],
                     "fresh_count": sum(fresh), "cache_before": before, "cache_after": list(cache),
                     "current_before": sorted(set(range(len(cache))) - set(snap.stale)),
                     "stale_before": sorted(snap.stale), "budget": snap.budget})
    return rows


def main():
    config_path = ROOT / "configs/mechanism_probe_v1.json"
    c = json.loads(config_path.read_text())
    lock = json.loads((ROOT / "configs/confirmatory.lock.json").read_text())
    assert code_hash() == lock["code_sha256"]
    OUT.mkdir(exist_ok=True)
    source_hash = digest(Path(__file__))
    metadata_path = OUT / "metadata.json"
    binding = {"probe_code_sha256": source_hash, "config_sha256": digest(config_path), "original_lock": lock}
    if metadata_path.exists():
        assert json.loads(metadata_path.read_text())["binding"] == binding
    else:
        metadata_path.write_text(json.dumps({"phase": "POST_HOC_MECHANISM_PROBE", "binding": binding,
            "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "primary_test_outcomes_already_seen": True}, indent=2) + "\n")
        for path in (Path(__file__), config_path):
            dest = OUT / "source_snapshot" / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
    all_pairs = []
    for seed in c["seeds"]:
        target = OUT / ("seed" + str(seed) + ".json")
        payload_bytes = gzip.decompress((ORIGINAL / "traces" / (c["case"] + "_seed" + str(seed) + ".json.gz")).read_bytes())
        payload = json.loads(payload_bytes)
        payload["inputs"] = tuple(frozenset(v) for v in payload["inputs"])
        payload["group_shock_rates"] = {int(k): v for k, v in payload["group_shock_rates"].items()}
        trace = Trace(**payload)
        original = json.loads((ORIGINAL / "records" / (c["case"] + "_b0.1_seed" + str(seed) + "_sabs_partial.json")).read_text())
        if target.exists():
            data = json.loads(target.read_text())
            assert data["trace_sha256"] == hashlib.sha256(payload_bytes).hexdigest()
            all_pairs.extend(data["pairs"]); continue
        cache = [len(h) for h in trace.history_events]; pairs = []
        for window, saved in enumerate(original["windows"]):
            snap, _ = snapshot_at(trace, window, cache, c["budget_fraction"])
            weighted = bundle_fast(snap, True)
            assert sorted(weighted) == saved["selected_files"]
            if window in c["intervention_windows"]:
                unweighted = bundle_fast(snap, False)
                a = branch(trace, window, cache, weighted, c["followup_windows"], original["windows"])
                b = branch(trace, window, cache, unweighted, c["followup_windows"])
                steps = []
                cumulative = 0
                for ra, rb in zip(a, b):
                    delta = ra["fresh_count"] - rb["fresh_count"]; cumulative += delta
                    ca, cb = set(ra["current_before"]), set(rb["current_before"])
                    steps.append({"offset": ra["offset"], "window": ra["window"], "weighted_initial_branch": ra,
                                  "unweighted_initial_branch": rb, "fresh_delta": delta,
                                  "cumulative_fresh_delta": cumulative,
                                  "weighted_only_current_inputs": sorted(ca - cb),
                                  "unweighted_only_current_inputs": sorted(cb - ca),
                                  "gained_task_ids": sorted(set(ra["fresh_task_ids"]) - set(rb["fresh_task_ids"])),
                                  "lost_task_ids": sorted(set(rb["fresh_task_ids"]) - set(ra["fresh_task_ids"]))})
                if weighted == unweighted:
                    assert a == b
                pairs.append({"seed": seed, "intervention_window": window,
                              "initial_action_differs": weighted != unweighted,
                              "initial_fresh_delta": steps[0]["fresh_delta"], "steps": steps})
            cache, fresh = evaluate_action(trace, window, cache, snap, weighted)
            assert abs(mean(fresh) - saved["fresh_fraction"]) < 1e-12
        target.write_text(json.dumps({"seed": seed, "trace_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                                     "pairs": pairs}, indent=2) + "\n")
        all_pairs.extend(pairs)
        print("probe completed seed", seed, flush=True)
    assert len(all_pairs) == 480
    groups = {}
    for label in ("all_interventions", "positive_immediate"):
        selected = [p for p in all_pairs if label == "all_interventions" or p["initial_fresh_delta"] > 0]
        series = []
        eligible_seeds = [s for s in c["seeds"] if any(p["seed"] == s for p in selected)]
        for h in range(c["followup_windows"] + 1):
            vals = [mean(p["steps"][h]["cumulative_fresh_delta"] for p in selected if p["seed"] == s)
                    for s in eligible_seeds]
            series.append({"offset": h, **statistics(vals, "probe:" + label + ":" + str(h))})
        later = [mean(sum(p["steps"][h]["fresh_delta"] for h in range(1, 6))
                      for p in selected if p["seed"] == s) for s in eligible_seeds]
        groups[label] = {"pairs": len(selected), "seeds": len(eligible_seeds), "series": series,
                         "future_offsets_1_to_5": statistics(later, "probe:" + label + ":future"),
                         "end_positive_pairs": sum(p["steps"][-1]["cumulative_fresh_delta"] > 0 for p in selected),
                         "end_zero_pairs": sum(p["steps"][-1]["cumulative_fresh_delta"] == 0 for p in selected),
                         "end_negative_pairs": sum(p["steps"][-1]["cumulative_fresh_delta"] < 0 for p in selected)}
    representative = next(p for p in sorted(all_pairs, key=lambda p: (p["seed"], p["intervention_window"]))
                          if p["initial_fresh_delta"] > 0)
    summary = {"status": "POST_HOC_PROBE_COMPLETE", "protocol": c, "pairs": len(all_pairs),
               "identical_initial_actions": sum(not p["initial_action_differs"] for p in all_pairs),
               "groups": groups, "representative": representative,
               "checks": {"weighted_branch_matches_preserved_on_policy_actions_and_outcomes": True,
                          "all_budgets_feasible": True, "identical_initial_actions_have_identical_followups": True}}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"status": summary["status"], "groups": groups,
                      "representative_seed": representative["seed"], "representative_window": representative["intervention_window"],
                      "representative_deltas": [p["fresh_delta"] for p in representative["steps"]]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
