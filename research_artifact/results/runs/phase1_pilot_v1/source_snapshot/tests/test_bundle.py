import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bundle import Snapshot, Task, bundle_greedy, cost, exhaustive, feasible, item_utility, realized_increment, value


class ModelTests(unittest.TestCase):
    def make(self, budget=2, rates=(0, 0, 0)):
        return Snapshot((1, 1, 1), rates, frozenset(range(3)),
                        (Task(frozenset((0, 1))), Task(frozenset((1, 2)))), budget)

    def test_bundle_complementarity(self):
        s = self.make()
        self.assertEqual(value(s, {0}), 0)
        self.assertEqual(value(s, {1}), 0)
        self.assertEqual(value(s, {0, 1}), 1)

    def test_shared_cost_and_multiple_task_gain(self):
        s = self.make(3)
        chosen = bundle_greedy(s)
        self.assertEqual(cost(s, chosen), 3)
        self.assertEqual(value(s, chosen), 2)

    def test_zero_budget_and_unaffordable_bundle(self):
        self.assertEqual(bundle_greedy(self.make(0)), frozenset())
        self.assertEqual(bundle_greedy(self.make(1), partial_fallback=False), frozenset())
        self.assertEqual(len(bundle_greedy(self.make(1))), 1)

    def test_two_windows_accumulate_inputs_instead_of_idling(self):
        tasks = (Task(frozenset({0, 1})),)
        for survival in (False, True):
            stale = frozenset({0, 1})
            actions = []
            for _ in range(2):
                s = Snapshot((1, 1), (0, 0), stale, tasks, 1)
                action = bundle_greedy(s, survival)
                self.assertTrue(feasible(s, action))
                actions.append(action)
                stale -= action  # no source updates between these windows
            self.assertEqual(actions, [frozenset({0}), frozenset({1})])
            self.assertFalse(stale)
        legacy = Snapshot((1, 1), (0, 0), frozenset({0, 1}), tasks, 1)
        self.assertEqual(bundle_greedy(legacy, partial_fallback=False), frozenset())
        self.assertEqual(item_utility(legacy), frozenset({0}))

    def test_partial_progress_can_be_invalidated_before_next_window(self):
        tasks = (Task(frozenset({0, 1})),)
        s = Snapshot((1, 1), (0, 0), frozenset({0, 1}), tasks, 1)
        first = bundle_greedy(s)
        stale_after_update = (s.stale - first) | first
        self.assertEqual(stale_after_update, s.stale)
        self.assertEqual(bundle_greedy(s), first)
        self.assertEqual(value(s, first), 0)  # no claim of guaranteed future success

    def test_equal_nonunit_survival_weights_preserve_choices(self):
        # Every two-input task has q=exp(-0.4), including during fallback.
        s = self.make(2, (0.2, 0.2, 0.2))
        self.assertEqual(bundle_greedy(s, True), bundle_greedy(s, False))
        partial = self.make(1, (0.2, 0.2, 0.2))
        self.assertEqual(bundle_greedy(partial, True), bundle_greedy(partial, False))
        self.assertEqual(item_utility(s, True), item_utility(s, False))

    def test_individually_unaffordable_input_is_not_hidden(self):
        s = Snapshot((2, 1), (0, 0), frozenset({0, 1}),
                     (Task(frozenset({0, 1})),), 1)
        first = bundle_greedy(s)
        self.assertEqual(first, frozenset({1}))
        s2 = Snapshot(s.costs, s.rates, frozenset({0}), s.tasks, 1)
        self.assertEqual(bundle_greedy(s2), frozenset())

    def test_fresh_inputs_can_become_stale(self):
        s = Snapshot((1, 1), (0, 2), frozenset({0}), (Task(frozenset({0, 1})),), 1)
        self.assertAlmostEqual(value(s, {0}), math.exp(-2))
        self.assertEqual(realized_increment(s, {0}, [math.inf, 0.5]), 0)

    def test_already_fresh_constant_excluded(self):
        s = Snapshot((1,), (0,), frozenset(), (Task(frozenset({0})),), 1)
        self.assertEqual(value(s, set()), 0)

    def test_update_at_use_time_invalidates(self):
        s = Snapshot((1,), (0,), frozenset({0}), (Task(frozenset({0})),), 1)
        self.assertEqual(realized_increment(s, {0}, [1]), 0)
        self.assertEqual(realized_increment(s, {0}, [1.01]), 1)

    def test_survival_changes_choice(self):
        s = Snapshot((1, 1, 1, 1), (2, 2, 0, 0), frozenset(range(4)),
                     (Task(frozenset({0, 1}), 3), Task(frozenset({2, 3}), 1)), 2)
        self.assertEqual(bundle_greedy(s, False), frozenset({0, 1}))
        self.assertEqual(bundle_greedy(s, True), frozenset({2, 3}))

    def test_random_tiny_exact_upper_bound(self):
        for seed in range(20):
            rng = random.Random(1000 + seed)
            s = Snapshot(tuple(rng.randint(1, 4) for _ in range(7)),
                         tuple(rng.random() for _ in range(7)), frozenset(range(7)),
                         tuple(Task(frozenset(rng.sample(range(7), rng.randint(1, 3))),
                                    rng.randint(1, 4), rng.random()) for _ in range(9)), 8)
            action = bundle_greedy(s)
            opt = exhaustive(s)
            self.assertTrue(feasible(s, action))
            self.assertLessEqual(value(s, action), value(s, opt) + 1e-9)
            legacy = bundle_greedy(s, partial_fallback=False)
            self.assertGreaterEqual(value(s, action) + 1e-9, value(s, legacy))

    def test_monte_carlo_matches_independent_expectation(self):
        s = self.make(3, (0.1, 0.3, 0.5))
        rng = random.Random(21)
        n = 20000
        total = sum(realized_increment(s, {0, 1, 2}, [rng.expovariate(r) for r in s.rates])
                    for _ in range(n))
        self.assertAlmostEqual(total / n, value(s, {0, 1, 2}), delta=0.03)

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            self.make(-1)
        with self.assertRaises(ValueError):
            self.make(2, (0, -1, 0))
        with self.assertRaises(ValueError):
            Snapshot((0,), (0,), frozenset(), (), 1)

    def test_empty_tasks(self):
        s = Snapshot((1,), (0,), frozenset({0}), (), 1)
        self.assertEqual(bundle_greedy(s), frozenset())


if __name__ == "__main__":
    unittest.main()
