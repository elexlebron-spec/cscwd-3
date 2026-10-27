import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from bundle import Snapshot, Task
from run_budget_timing_intervention import adjusted_snapshot


class TimingTest(unittest.TestCase):
    def test_cap_uses_observed_hazard_and_leaves_other_tasks_unchanged(self):
        snapshot = Snapshot((1, 2), (1.0, 3.0), frozenset({0, 1}),
                            (Task(frozenset({0, 1}), 1, .8), Task(frozenset({0}), 1, .4)), 2)
        capped = adjusted_snapshot(snapshot, 0, True, .5)
        self.assertAlmostEqual(capped.tasks[0].delay, math.log(2) / 4)
        self.assertEqual(capped.tasks[1], snapshot.tasks[1])
        self.assertEqual(capped.rates, snapshot.rates)
        self.assertEqual(capped.budget, snapshot.budget)
        self.assertEqual(snapshot.tasks[0].delay, .8)

    def test_cap_never_postpones_and_zero_hazard_is_defined(self):
        snapshot = Snapshot((1,), (0.0,), frozenset(), (Task(frozenset({0}), 1, .1),), 0)
        self.assertEqual(adjusted_snapshot(snapshot, 0, True, .5), snapshot)
        positive = Snapshot((1,), (.1,), frozenset(), snapshot.tasks, 0)
        self.assertEqual(adjusted_snapshot(positive, 0, True, .5), positive)

    def test_disabled_arm_is_exact_identity(self):
        snapshot = Snapshot((1,), (100.0,), frozenset({0}), (Task(frozenset({0}), 1, .9),), 1)
        self.assertIs(adjusted_snapshot(snapshot, 0, False, .5), snapshot)


if __name__ == "__main__":
    unittest.main()
