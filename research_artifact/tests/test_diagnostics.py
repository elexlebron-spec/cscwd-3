import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bundle import Snapshot, Task
from diagnostics import compare_snapshot


class DiagnosticTests(unittest.TestCase):
    def test_equal_q_has_zero_group_disagreement(self):
        s = Snapshot((1, 1, 1), (0.2, 0.2, 0.2), frozenset(range(3)),
                     (Task(frozenset({0, 1})), Task(frozenset({1, 2}))), 2)
        d = compare_snapshot(s, [math.inf] * 3)
        self.assertEqual(d["estimated_q"]["cv"], 0)
        self.assertFalse(d["comparisons_to_sabs"]["bundle_no_survival_partial"]["action_differs"])

    def test_future_changes_measured_gain_but_never_policy_action(self):
        s = Snapshot((1, 1, 1, 1), (2, 2, 0, 0), frozenset(range(4)),
                     (Task(frozenset({0, 1}), 3), Task(frozenset({2, 3}), 1)), 2)
        favorable = compare_snapshot(s, [0.5, 0.5, math.inf, math.inf])
        unfavorable = compare_snapshot(s, [math.inf, math.inf, 0.5, 0.5])
        self.assertEqual(favorable["actions"], unfavorable["actions"])
        pair = "bundle_no_survival_partial"
        self.assertTrue(favorable["comparisons_to_sabs"][pair]["action_differs"])
        self.assertGreater(favorable["comparisons_to_sabs"][pair]["realized_freshness_delta"], 0)
        self.assertLess(unfavorable["comparisons_to_sabs"][pair]["realized_freshness_delta"], 0)

    def test_empty_snapshot_diagnostics_do_not_divide_by_zero(self):
        d = compare_snapshot(Snapshot((), (), frozenset(), (), 0), [])
        self.assertIsNone(d["estimated_q"]["mean"])
        self.assertEqual(d["comparisons_to_sabs"]["item_utility"]["jaccard_distance"], 0)


if __name__ == "__main__":
    unittest.main()
