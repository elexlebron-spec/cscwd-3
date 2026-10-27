"""Executable worked scenario, deliberately separate from empirical measurements."""
from bisect import bisect_right
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from simulation import Trace, snapshot_at, evaluate_action


def main():
    c = json.loads((ROOT / "configs/worked_design_case.json").read_text())
    inputs = tuple(frozenset(task["inputs"]) for task in c["tasks"])
    trace = Trace("constructed_design_case", 0, 1, tuple(c["costs"]), inputs,
                  (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), {0: 0.0},
                  tuple(tuple(e) for e in c["history_events"]),
                  tuple(tuple(e) for e in c["future_events"]),
                  (tuple(task["use_delay"] for task in c["tasks"]),))
    cache = list(c["initial_cache_counters"])
    snapshot, source = snapshot_at(trace, 0, cache, c["budget"] / sum(c["costs"]))
    outputs = []
    for label, action in [("fixed_budgeted_import", frozenset(c["fixed_budgeted_action"])),
                          ("all_boundary_import_unconstrained", snapshot.stale)]:
        updated, fresh = evaluate_action(trace, 0, cache, snapshot, action)
        task_rows = []
        for task, ok in zip(c["tasks"], fresh):
            at_use = [len(h) + bisect_right(f, task["use_delay"])
                      for h, f in zip(trace.history_events, trace.future_events)]
            task_rows.append({"task": task["name"], "use_delay": task["use_delay"], "fresh": ok,
                              "outdated_or_missing_inputs": [c["artifact_names"][i] for i in task["inputs"] if updated[i] != at_use[i]]})
        outputs.append({"action": label, "copied_inputs": [c["artifact_names"][i] for i in sorted(action)],
                        "cost": sum(c["costs"][i] for i in action), "checks": task_rows})
    assert [r["fresh"] for r in outputs[0]["checks"]] == [True, False, False]
    assert [r["fresh"] for r in outputs[1]["checks"]] == [True, False, False]
    result = {"status": c["status"], "purpose": "Illustrate application mapping, not measure algorithm performance",
              "rates": "No rates are estimated or used; events and action are explicitly constructed",
              "source_at_import": source, "assumptions": c["assumptions"], "actions": outputs}
    out = ROOT / "results/worked_design_case.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
