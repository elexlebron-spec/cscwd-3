"""Pre-generated exogenous traces and version-exact multi-window evaluation."""
from bisect import bisect_right
from dataclasses import dataclass
from math import exp, inf
from statistics import mean, pstdev
from time import perf_counter
from typing import Tuple

from bundle import Snapshot, Task, cost, feasible
from diagnostics import compare_snapshot
from policies import bundle_fast, select
from workload_design import common_shock_components, cost_vector, rng_stream, task_inputs, true_joint_survival, true_rates


@dataclass(frozen=True)
class Trace:
    name: str
    seed: int
    history_duration: float
    costs: Tuple[float, ...]
    inputs: Tuple[frozenset, ...]
    true_rates: Tuple[float, ...]
    residual_rates: Tuple[float, ...]
    group_shock_rates: dict
    history_events: Tuple[tuple, ...]
    future_events: Tuple[tuple, ...]
    delays: Tuple[tuple, ...]


def poisson_events(rate, start, end, rng):
    if rate <= 0:
        return ()
    t = start
    events = []
    while True:
        t += rng.expovariate(rate)
        if t > end:
            return tuple(events)
        events.append(t)


def generate_trace(seed, mean_rate=0.5, cv=1.0, delay_mode="uniform", eta=0.0,
                   windows=30, history_duration=100.0, inputs=None, n_files=None,
                   name="synthetic"):
    inputs = tuple(task_inputs(seed) if inputs is None else inputs)
    n = 100 if n_files is None else n_files
    rates = true_rates(seed, mean_rate, cv, n)
    residual, shocks = common_shock_components(rates, eta)
    hist_shocks = {g: poisson_events(r, -history_duration, 0, rng_stream(seed, "history_events:shock:" + str(g)))
                   for g, r in shocks.items()}
    future_shocks = {g: poisson_events(r, 0, windows, rng_stream(seed, "future_events:shock:" + str(g)))
                     for g, r in shocks.items()}
    histories, futures = [], []
    for i in range(n):
        histories.append(tuple(sorted(poisson_events(residual[i], -history_duration, 0,
                               rng_stream(seed, "history_events:independent:" + str(i))) + hist_shocks[i // 10])))
        futures.append(tuple(sorted(poisson_events(residual[i], 0, windows,
                             rng_stream(seed, "future_events:independent:" + str(i))) + future_shocks[i // 10])))
    delay_rng = rng_stream(seed, "delays")
    if delay_mode not in ("uniform", "fixed"):
        raise ValueError("unknown delay mode")
    delays = tuple(tuple(0.5 if delay_mode == "fixed" else delay_rng.uniform(0.1, 0.9)
                         for _ in inputs) for _ in range(windows))
    return Trace(name, seed, history_duration, cost_vector(seed, n), inputs, rates,
                 residual, shocks, tuple(histories), tuple(futures), delays)


def snapshot_at(trace, window, cache, budget_fraction):
    # At this boundary ALL observations <=window are already public.
    source = tuple(len(h) + bisect_right(f, window)
                   for h, f in zip(trace.history_events, trace.future_events))
    estimates = tuple(v / (trace.history_duration + window) for v in source)
    stale = frozenset(i for i, v in enumerate(source) if v != cache[i])
    tasks = tuple(Task(inputs, 1.0, delay)
                  for inputs, delay in zip(trace.inputs, trace.delays[window]))
    return Snapshot(trace.costs, estimates, stale, tasks,
                    budget_fraction * sum(trace.costs)), source


def evaluate_action(trace, window, cache, snapshot, action):
    new_cache = list(cache)
    for i in action:
        new_cache[i] = len(trace.history_events[i]) + bisect_right(trace.future_events[i], window)
    fresh = []
    for task in snapshot.tasks:
        fresh.append(all(new_cache[i] == len(trace.history_events[i]) +
                         bisect_right(trace.future_events[i], window + task.delay)
                         for i in task.inputs))
    return new_cache, fresh


def run_policy(trace, budget_fraction, method, diagnostics=False):
    n = len(trace.costs)
    cache = [len(h) for h in trace.history_events]
    last_sync = [0.0] * n
    # Pending synchronization is closed at first update; used marks any fresh task.
    pending = {}
    spent = wasted = 0.0
    rows, diagnostic_rows, snapshots = [], [], []
    rng = rng_stream(trace.seed, "policy_random:" + method)
    for window in range(len(trace.delays)):
        snapshot, source = snapshot_at(trace, window, cache, budget_fraction)
        start = perf_counter()
        action = select(snapshot, method, tuple(last_sync), rng)
        decision_seconds = perf_counter() - start
        if method != "always_sync_unconstrained" and not feasible(snapshot, action):
            raise AssertionError("policy budget violation")
        if not action <= snapshot.stale:
            raise AssertionError("policy refreshed a current file")
        first_updates = []
        for times in trace.future_events:
            k = bisect_right(times, window)
            first_updates.append(times[k] - window if k < len(times) else inf)
        if diagnostics:
            d = compare_snapshot(snapshot, first_updates, bundle_selector=bundle_fast)
            true_q = [true_joint_survival(t.inputs, t.delay, trace.residual_rates, trace.group_shock_rates)
                      for t in snapshot.tasks]
            mu = mean(true_q) if true_q else 0
            d.update({"window": window, "true_q_mean_diagnostic": mu,
                      "true_q_cv_diagnostic": pstdev(true_q) / mu if mu else None,
                      "unaffordable_missing_bundles": sum(bool(t.inputs & snapshot.stale) and
                          cost(snapshot, t.inputs & snapshot.stale) > snapshot.budget + 1e-10
                          for t in snapshot.tasks)})
            diagnostic_rows.append(d)
            snapshots.append(snapshot)
        for i in action:
            last_sync[i] = window
            pending[i] = False
        cache, fresh = evaluate_action(trace, window, cache, snapshot, action)
        for task, ok in zip(snapshot.tasks, fresh):
            if ok:
                for i in task.inputs:
                    if i in pending:
                        pending[i] = True
        for i in list(pending):
            if bisect_right(trace.future_events[i], window + 1) > bisect_right(trace.future_events[i], window):
                if not pending[i]:
                    wasted += trace.costs[i]
                del pending[i]
        window_cost = cost(snapshot, action)
        spent += window_cost
        inputs_nonempty = [ok for t, ok in zip(snapshot.tasks, fresh) if t.inputs]
        rows.append({"window": window, "fresh_fraction": sum(fresh) / len(fresh) if fresh else 1,
                     "nonempty_fresh_fraction": mean(inputs_nonempty) if inputs_nonempty else None,
                     "sync_cost": window_cost, "selected_files": sorted(action),
                     "stale_files": len(snapshot.stale), "decision_seconds": decision_seconds,
                     "zero_current_gain_action": bool(action) and not any(
                         ok and t.inputs & snapshot.stale for t, ok in zip(snapshot.tasks, fresh))})
    summary = {"method": method, "seed": trace.seed, "structure": trace.name,
               "budget_fraction": budget_fraction,
               "fresh_fraction": mean(r["fresh_fraction"] for r in rows),
               "nonempty_fresh_fraction": mean(r["nonempty_fresh_fraction"] for r in rows
                                               if r["nonempty_fresh_fraction"] is not None),
               "sync_cost": spent, "invalidated_unused_cost": wasted,
               "invalidated_unused_cost_fraction": wasted / spent if spent else None,
               "pending_unused_cost_at_end": sum(trace.costs[i] for i, used in pending.items() if not used),
               "decision_seconds": [r["decision_seconds"] for r in rows]}
    return {"summary": summary, "windows": rows, "diagnostics": diagnostic_rows}, snapshots
