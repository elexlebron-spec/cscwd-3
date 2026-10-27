"""Replay the review counterexample, including cache carried across windows."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import Snapshot, Task, bundle_greedy, item_utility, feasible


def replay(policy):
    source_versions = (1, 1)
    cache_versions = [0, 0]
    rows = []
    for window in range(2):
        stale = frozenset(i for i in range(2) if source_versions[i] != cache_versions[i])
        snapshot = Snapshot((1, 1), (0, 0), stale, (Task(frozenset({0, 1})),), 1)
        action = policy(snapshot)
        assert feasible(snapshot, action)
        for i in action:
            cache_versions[i] = source_versions[i]
        rows.append({"window": window + 1, "action": sorted(action),
                     "cache_versions": list(cache_versions),
                     "task_fresh": tuple(cache_versions) == source_versions})
    return rows


policies = {
    "legacy_bundle": lambda s: bundle_greedy(s, partial_fallback=False),
    "revised_sabs": bundle_greedy,
    "revised_no_survival": lambda s: bundle_greedy(s, survival=False),
    "item_utility": item_utility,
}
results = {name: replay(policy) for name, policy in policies.items()}
assert not results["legacy_bundle"][-1]["task_fresh"]
assert all(results[name][-1]["task_fresh"] for name in policies if name != "legacy_bundle")
out = {"status": "REVIEW_REGRESSION_ONLY_NOT_PAPER_RESULTS", "results": results}
(ROOT / "results/review_regressions.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
