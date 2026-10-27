"""Concrete version-gate contract; constructed example, never industrial evidence."""
from bisect import bisect_right
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from simulation import Trace, snapshot_at, evaluate_action


def main():
    c = json.loads((ROOT / "configs/worked_design_case.json").read_text())
    trace = Trace("constructed_design_contract", 0, 1, tuple(c["costs"]),
                  tuple(frozenset(t["inputs"]) for t in c["tasks"]),
                  (0, 0, 0), (0, 0, 0), {0: 0},
                  tuple(tuple(x) for x in c["history_events"]),
                  tuple(tuple(x) for x in c["future_events"]),
                  (tuple(t["use_delay"] for t in c["tasks"]),))
    cache = c["initial_cache_counters"]
    snap, publication_manifest = snapshot_at(trace, 0, cache, c["budget"] / sum(c["costs"]))
    actions = [("budgeted", frozenset(c["fixed_budgeted_action"])), ("all_unconstrained", snap.stale)]
    rows = []
    for name, action in actions:
        local, current_valid = evaluate_action(trace, 0, cache, snap, action)
        for j, task in enumerate(c["tasks"]):
            source_at_use = [len(h) + bisect_right(f, task["use_delay"])
                             for h, f in zip(trace.history_events, trace.future_events)]
            rows.append({"import_action": name, "review": task["name"], "use_time": task["use_delay"],
                         "local_versions": [local[i] for i in task["inputs"]],
                         "manifest_versions": [publication_manifest[i] for i in task["inputs"]],
                         "latest_versions": [source_at_use[i] for i in task["inputs"]],
                         "latest_published_gate": current_valid[j],
                         "frozen_manifest_gate": all(local[i] == publication_manifest[i] for i in task["inputs"]),
                         "copied_input_ids": sorted(action), "import_cost": sum(c["costs"][i] for i in action)})
    all_rows = [r for r in rows if r["import_action"] == "all_unconstrained"]
    assert [r["latest_published_gate"] for r in all_rows] == [True, False, False]
    assert all(r["frozen_manifest_gate"] for r in all_rows)
    result = {"status": "CONSTRUCTED_CONTRACT_COMPARISON_NOT_PERFORMANCE_DATA",
              "contract": {"payload_access": "Read-only local review cache; payload importer disabled between gates",
                           "metadata_access": "Published-version notifications remain visible; their cost is assumed separate",
                           "review_times": "Appointments fixed and announced at import, not predicted execution times",
                           "latest_rule": "Mark a review superseded when any eligible published input has advanced",
                           "frozen_rule": "Assess reproducibility against an agreed import manifest instead",
                           "rationale": "Explicit local batch-review policy. Product documentation does not impose it.",
                           "units": "Constructed window/cost units; not calibrated to a week, bytes or labor"},
              "results": rows}
    (ROOT / "results/worked_design_contract.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
