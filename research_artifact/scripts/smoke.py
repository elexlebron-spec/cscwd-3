"""Run a deliberately small mathematical demonstration; not paper evidence."""
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import Snapshot, Task, bundle_greedy, cost, exhaustive, item_utility, value

s = Snapshot((1, 1, 1, 1), (2, 2, 0, 0), frozenset(range(4)),
             (Task(frozenset({0, 1}), 3), Task(frozenset({2, 3}), 1)), 2)
methods = {
    "bundle_no_survival_partial": bundle_greedy(s, False),
    "item_utility": item_utility(s),
    "sabs_partial": bundle_greedy(s),
    "exact_estimated_single_window": exhaustive(s),
}
result = {
    "status": "SMOKE_ONLY_NOT_PAPER_RESULTS",
    "interpretation": "Constructed counterexample; supplied rates are mathematical inputs, not estimated data.",
    "python": platform.python_version(),
    "source_sha256": hashlib.sha256((ROOT / "src/bundle.py").read_bytes()).hexdigest(),
    "rows": [{"method": name, "files": sorted(action), "cost": cost(s, action),
              "expected_increment": value(s, action)} for name, action in methods.items()],
}
out = ROOT / "results/smoke.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
