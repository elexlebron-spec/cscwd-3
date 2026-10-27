"""Evaluator-side same-snapshot diagnostics, not a production policy input."""
from math import exp
from statistics import mean, pstdev

from bundle import bundle_greedy, item_utility, realized_increment


def compare_snapshot(snapshot, first_updates, bundle_selector=bundle_greedy):
    # All policy calls finish before the evaluator reads future update times.
    actions = {
        "sabs_partial": bundle_selector(snapshot),
        "bundle_no_survival_partial": bundle_selector(snapshot, survival=False),
        "item_utility": item_utility(snapshot),
        "item_no_survival": item_utility(snapshot, survival=False),
    }
    q_values = [exp(-task.delay * sum(snapshot.rates[i] for i in sorted(task.inputs)))
                for task in snapshot.tasks]
    q_mean = mean(q_values) if q_values else None
    dispersion = {"mean": q_mean, "std": pstdev(q_values) if q_values else None,
                  "cv": pstdev(q_values) / q_mean if q_mean else None}
    realized = {name: realized_increment(snapshot, action, first_updates)
                for name, action in actions.items()}
    total_weight = sum(task.weight for task in snapshot.tasks)
    pairs = {}
    for other in ("bundle_no_survival_partial", "item_utility"):
        left, right = actions["sabs_partial"], actions[other]
        union = left | right
        pairs[other] = {
            "action_differs": left != right,
            "jaccard_distance": 1 - len(left & right) / len(union) if union else 0.0,
            # Already-fresh tasks contribute identical constants, which cancel.
            "realized_freshness_delta":
                (realized["sabs_partial"] - realized[other]) / total_weight if total_weight else None,
        }
    return {"actions": {k: sorted(v) for k, v in actions.items()},
            "estimated_q": dispersion, "comparisons_to_sabs": pairs}
