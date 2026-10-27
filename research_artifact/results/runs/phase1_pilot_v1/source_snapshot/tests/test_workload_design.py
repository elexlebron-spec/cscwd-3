import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from workload_design import common_shock_components, cost_vector, rng_stream, task_inputs, true_joint_survival, true_rates


class DesignTests(unittest.TestCase):
    def test_rate_means_and_homogeneous_control(self):
        rates = true_rates(0, 0.5, 1)
        self.assertAlmostEqual(sum(rates) / len(rates), 0.5)
        self.assertGreater(max(rates), min(rates))
        self.assertEqual(len(set(true_rates(0, 0.5, 0))), 1)

    def test_structure_and_named_streams_are_reproducible(self):
        structure = task_inputs(0)
        for inputs in structure:
            self.assertEqual(len(inputs), 4)
            self.assertEqual(sum(i < 20 for i in inputs), 2)
        rng = rng_stream(0, "policy_random")
        for _ in range(100):
            rng.random()
        self.assertEqual(task_inputs(0), structure)
        self.assertEqual(cost_vector(0), cost_vector(0))

    def test_common_shock_preserves_marginals(self):
        rates = true_rates(0, 0.5, 1)
        residual, shock = common_shock_components(rates, 0.5)
        for i, r in enumerate(rates):
            self.assertGreaterEqual(residual[i], 0)
            self.assertAlmostEqual(residual[i] + shock[i // 10], r)

    def test_independent_product_double_counts_shared_shock(self):
        rates = (0.5,) * 10
        residual, shock = common_shock_components(rates, 0.5)
        joint = true_joint_survival({0, 1}, 1, residual, shock)
        independent = math.exp(-sum(rates[:2]))
        self.assertAlmostEqual(joint, math.exp(-0.75))
        self.assertGreater(joint, independent)
        residual0, shock0 = common_shock_components(rates, 0)
        self.assertAlmostEqual(true_joint_survival({0, 1}, 1, residual0, shock0), independent)

    def test_protocol_has_no_undefined_design_or_test_seed_overlap(self):
        raw = (ROOT / "configs/protocol.json").read_text()
        protocol = json.loads(raw)
        self.assertNotIn("TO_DEFINE", raw)
        self.assertFalse(set(protocol["validation_seeds"]) & set(protocol["test_seeds"]))
        self.assertEqual(protocol["main"]["windows"], 30)
        self.assertIn(0.05, protocol["main"]["budget_fraction_of_all_file_costs"])


if __name__ == "__main__":
    unittest.main()
