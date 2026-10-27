"""Policy implementations with no access to future traces or true rates."""
from functools import lru_cache
from math import exp

from bundle import _partial_fill, cost, feasible, item_utility


def bundle_fast(snapshot, survival=True, partial_fallback=True):
    """Same choices as reference, with cached profits and integer set masks."""
    missing = []
    profits = []
    stale_mask = sum(1 << i for i in snapshot.stale)
    for task in snapshot.tasks:
        mask = sum(1 << i for i in task.inputs) & stale_mask
        missing.append(mask)
        q = exp(-task.delay * sum(snapshot.rates[i] for i in sorted(task.inputs))) if survival else 1.0
        profits.append(task.weight * q)

    @lru_cache(maxsize=None)
    def mask_cost(mask):
        total = 0.0
        while mask:
            bit = mask & -mask
            total += snapshot.costs[bit.bit_length() - 1]
            mask ^= bit
        return total

    def objective(mask):
        return sum(p for m, p in zip(missing, profits) if m and m & ~mask == 0)

    chosen = 0
    while True:
        current = objective(chosen)
        best, best_ratio = 0, -1.0
        seen = set()
        for mask in missing:
            added = mask & ~chosen
            if not added or added in seen:
                continue
            seen.add(added)
            candidate = chosen | added
            if mask_cost(candidate) > snapshot.budget + 1e-10:
                continue
            gain = objective(candidate) - current
            ratio = gain / mask_cost(added)
            if gain > 0 and ratio > best_ratio:
                best, best_ratio = added, ratio
        if not best:
            break
        chosen |= best
    best_value = objective(chosen)
    for mask in missing:
        if mask_cost(mask) <= snapshot.budget + 1e-10:
            v = objective(mask)
            if v > best_value:
                chosen, best_value = mask, v
    selected = frozenset(i for i in snapshot.stale if chosen & (1 << i))
    return _partial_fill(snapshot, selected, survival) if partial_fallback else selected


def select(snapshot, name, last_sync, rng):
    if name == "sabs_partial":
        return bundle_fast(snapshot)
    if name == "bundle_no_survival_partial":
        return bundle_fast(snapshot, survival=False)
    if name == "legacy_sabs":
        return bundle_fast(snapshot, partial_fallback=False)
    if name == "item_utility":
        return item_utility(snapshot)
    if name == "item_no_survival":
        return item_utility(snapshot, survival=False)
    if name == "always_sync_unconstrained":
        return snapshot.stale
    ordered = sorted(snapshot.stale)
    if name == "random":
        rng.shuffle(ordered)
    elif name == "oldest_first":
        ordered.sort(key=lambda i: (last_sync[i], i))
    else:
        raise ValueError("unknown policy " + name)
    chosen = set()
    for i in ordered:
        if feasible(snapshot, chosen | {i}):
            chosen.add(i)
    return frozenset(chosen)
