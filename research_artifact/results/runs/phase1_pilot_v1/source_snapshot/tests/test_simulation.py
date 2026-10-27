from dataclasses import replace
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import Snapshot, Task, bundle_greedy, exhaustive, value
from optimization import solve_snapshot
from policies import bundle_fast
from public_data import parse_instance
from simulation import Trace, generate_trace, run_policy, snapshot_at


class IntegrationTests(unittest.TestCase):
    def test_optimized_selector_preserves_reference_choices(self):
        for seed in range(20):
            rng = random.Random(2000 + seed)
            s = Snapshot(tuple(rng.randint(1, 5) for _ in range(10)),
                         tuple(rng.random() for _ in range(10)),
                         frozenset(rng.sample(range(10), 8)),
                         tuple(Task(frozenset(rng.sample(range(10), rng.randint(1, 4))),
                                    rng.randint(1, 3), rng.random()) for _ in range(15)), 10)
            for survival in (True, False):
                for partial in (True, False):
                    self.assertEqual(bundle_fast(s, survival, partial), bundle_greedy(s, survival, partial))

    def test_milp_matches_exhaustive_tiny_objective(self):
        for seed in range(8):
            rng = random.Random(3000 + seed)
            s = Snapshot(tuple(rng.randint(1, 3) for _ in range(7)),
                         tuple(rng.random() for _ in range(7)), frozenset(range(7)),
                         tuple(Task(frozenset(rng.sample(range(7), 2)), rng.randint(1, 4))
                               for _ in range(8)), 6)
            for survival in (True, False):
                opt = exhaustive(s, survival)
                result = solve_snapshot(s, survival, time_limit=2)
                self.assertEqual(result["status"], 0)
                self.assertAlmostEqual(result["value"], value(s, opt, survival), places=7)

    def test_real_multiwindow_replay_accumulates_without_free_refresh(self):
        # Both files update at .9; windows 1 and 2 must refill one file each.
        trace = Trace("fixture", 0, 1, (1, 1), (frozenset({0, 1}),), (0, 0),
                      (0, 0), {0: 0}, ((), ()), ((0.9,), (0.9,)), ((0.5,),) * 3)
        revised, _ = run_policy(trace, 0.5, "sabs_partial")
        legacy, _ = run_policy(trace, 0.5, "legacy_sabs")
        self.assertEqual([r["selected_files"] for r in revised["windows"]], [[], [0], [1]])
        self.assertEqual([r["fresh_fraction"] for r in revised["windows"]], [1, 0, 1])
        self.assertEqual([r["fresh_fraction"] for r in legacy["windows"]], [1, 0, 0])

    def test_window_boundary_update_precedes_sync_and_use(self):
        trace = Trace("fixture", 0, 1, (1,), (frozenset({0}),), (0,), (0,), {0: 0},
                      ((),), ((1.0, 1.5),), ((0.5,), (0.5,)))
        result, _ = run_policy(trace, 1, "sabs_partial")
        self.assertEqual(result["windows"][1]["selected_files"], [0])
        self.assertEqual(result["windows"][1]["fresh_fraction"], 0)  # update exactly at use

    def test_future_suffix_does_not_change_current_policy(self):
        trace = generate_trace(0, windows=2)
        changed = replace(trace, future_events=tuple((0.01,) for _ in trace.costs))
        a, _ = run_policy(trace, 0.1, "sabs_partial")
        b, _ = run_policy(changed, 0.1, "sabs_partial")
        self.assertEqual(a["windows"][0]["selected_files"], b["windows"][0]["selected_files"])
        cache = [len(h) for h in trace.history_events]
        self.assertEqual(snapshot_at(trace, 0, cache, 0.1), snapshot_at(changed, 0, cache, 0.1))

    def test_policy_order_cannot_mutate_exogenous_trace(self):
        trace = generate_trace(0, windows=2)
        a, _ = run_policy(trace, 0.1, "random")
        run_policy(trace, 0.1, "sabs_partial")
        b, _ = run_policy(trace, 0.1, "random")
        self.assertEqual([r["selected_files"] for r in a["windows"]],
                         [r["selected_files"] for r in b["windows"]])

    def test_real_structures_keep_large_join_and_shared_inputs(self):
        for family in ("seismology", "montage"):
            p = ROOT / ("data/public/" + family + "_structure.json")
            self.assertTrue(p.exists())
        s = json.loads((ROOT / "data/public/seismology_structure.json").read_text())
        m = json.loads((ROOT / "data/public/montage_structure.json").read_text())
        self.assertEqual(s["stats"]["max_inputs"], 103)
        self.assertEqual(s["stats"]["sync_files"], 303)
        self.assertEqual(m["stats"]["shared_sync_files"], 47)

    def test_unknown_input_fails_instead_of_silent_dropping(self):
        d = {"schemaVersion": "1.6", "workflow": {"specification": {
            "files": [{"id": "a"}], "tasks": [{"id": "t", "inputFiles": ["missing"]}]}}}
        with self.assertRaises(ValueError):
            parse_instance(d)


if __name__ == "__main__":
    unittest.main()
