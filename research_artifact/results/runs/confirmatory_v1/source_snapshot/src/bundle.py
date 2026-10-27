"""Single-window reference model, NOT the full experiment simulator.

Rates are explicitly supplied model inputs. Production policies must obtain
them from past observations; they must never receive true future-event rates.
"""
from dataclasses import dataclass
from itertools import combinations
from math import exp, isfinite
from typing import FrozenSet, Tuple


@dataclass(frozen=True)
class Task:
    inputs: FrozenSet[int]
    weight: float = 1.0
    delay: float = 1.0


@dataclass(frozen=True)
class Snapshot:
    costs: Tuple[float, ...]
    rates: Tuple[float, ...]
    stale: FrozenSet[int]
    tasks: Tuple[Task, ...]
    budget: float

    def __post_init__(self):
        ids = set(range(len(self.costs)))
        if len(self.costs) != len(self.rates):
            raise ValueError("cost and rate lengths differ")
        if not isfinite(self.budget) or self.budget < 0:
            raise ValueError("budget must be finite and nonnegative")
        if any(not isfinite(c) or c <= 0 for c in self.costs):
            raise ValueError("costs must be finite and positive")
        if any(not isfinite(r) or r < 0 for r in self.rates):
            raise ValueError("rates must be finite and nonnegative")
        if not self.stale <= ids:
            raise ValueError("unknown stale file")
        for task in self.tasks:
            if not task.inputs <= ids:
                raise ValueError("unknown task input")
            if not isfinite(task.weight) or task.weight <= 0:
                raise ValueError("invalid weight")
            if not isfinite(task.delay) or task.delay < 0:
                raise ValueError("invalid delay")


def cost(snapshot, selected):
    return sum(snapshot.costs[i] for i in set(selected))


def value(snapshot, selected, survival=True):
    """Incremental expected value; already-fresh tasks are excluded constants."""
    selected = frozenset(selected)
    if not selected <= snapshot.stale:
        raise ValueError("select only stale files")
    total = 0.0
    for task in snapshot.tasks:
        missing = task.inputs & snapshot.stale
        if missing and missing <= selected:
            q = exp(-task.delay * sum(snapshot.rates[i] for i in sorted(task.inputs))) if survival else 1.0
            total += task.weight * q
    return total


def feasible(snapshot, selected):
    return set(selected) <= snapshot.stale and cost(snapshot, selected) <= snapshot.budget + 1e-10


def _item_scores(snapshot, selected, survival):
    """Share each unfinished task's profit over its remaining missing inputs."""
    scores = {i: 0.0 for i in sorted(snapshot.stale - frozenset(selected))}
    for task in snapshot.tasks:
        remaining = (task.inputs & snapshot.stale) - frozenset(selected)
        if not remaining:
            continue
        q = exp(-task.delay * sum(snapshot.rates[i] for i in sorted(task.inputs))) if survival else 1.0
        for i in sorted(remaining):
            scores[i] += task.weight * q / len(remaining)
    return scores


def _partial_fill(snapshot, selected, survival):
    """Observable-state progress heuristic; no long-horizon guarantee.

    Full bundles have already been considered. Spending leftover budget on
    partial inputs preserves current value but can still be wasted by updates.
    """
    selected = frozenset(selected)
    while True:
        scores = _item_scores(snapshot, selected, survival)
        candidates = [i for i in scores if scores[i] > 0
                      and feasible(snapshot, selected | {i})]
        if not candidates:
            return selected
        best = min(candidates, key=lambda i: (-scores[i] / snapshot.costs[i], i))
        selected |= {best}


def bundle_greedy(snapshot, survival=True, partial_fallback=True):
    """Bundle gain/cost, best-single guard, then optional partial progress.

    partial_fallback=False reproduces the original myopic policy. Both
    survival and no-survival revised variants use the SAME fallback rule.
    """
    selected = frozenset()
    while True:
        current = value(snapshot, selected, survival)
        best_added = None
        best_ratio = -1.0
        for task in snapshot.tasks:
            added = (task.inputs & snapshot.stale) - selected
            if not added or not feasible(snapshot, selected | added):
                continue
            gain = value(snapshot, selected | added, survival) - current
            ratio = gain / cost(snapshot, added)
            if gain > 0 and ratio > best_ratio:
                best_ratio, best_added = ratio, added
        if best_added is None:
            break
        selected |= best_added
    best_value = value(snapshot, selected, survival)
    for task in snapshot.tasks:
        candidate = task.inputs & snapshot.stale
        if feasible(snapshot, candidate):
            candidate_value = value(snapshot, candidate, survival)
            if candidate_value > best_value:
                selected, best_value = candidate, candidate_value
    if partial_fallback:
        selected = _partial_fill(snapshot, selected, survival)
    return frozenset(selected)


def item_utility(snapshot, survival=True):
    """Static additive ranking, optionally with the SAME survival weights."""
    scores = _item_scores(snapshot, frozenset(), survival)
    ordered = sorted(scores, key=lambda i: (-scores[i] / snapshot.costs[i], i))
    selected = set()
    for i in ordered:
        if scores[i] > 0 and feasible(snapshot, selected | {i}):
            selected.add(i)
    return frozenset(selected)


def exhaustive(snapshot, survival=True):
    """Exact for this estimated single-window objective, NOT a future oracle."""
    ids = sorted(snapshot.stale)
    if len(ids) > 18:
        raise ValueError("exhaustive is restricted to <=18 stale files")
    best, best_value = frozenset(), 0.0
    for n in range(len(ids) + 1):
        for items in combinations(ids, n):
            if feasible(snapshot, items):
                v = value(snapshot, items, survival)
                if v > best_value:
                    best, best_value = frozenset(items), v
    return best


def realized_increment(snapshot, selected, first_updates):
    """Evaluate one fixed future path; only evaluator may see first_updates.

    first_updates[i] is first update delay after sync (infinity if none).
    An update at exactly task use time invalidates the cached version.
    """
    if len(first_updates) != len(snapshot.costs):
        raise ValueError("wrong number of update times")
    if not feasible(snapshot, selected):
        raise ValueError("infeasible action")
    selected = frozenset(selected)
    return sum(task.weight for task in snapshot.tasks
               if (task.inputs & snapshot.stale)
               and (task.inputs & snapshot.stale) <= selected
               and all(first_updates[i] > task.delay for i in task.inputs))
