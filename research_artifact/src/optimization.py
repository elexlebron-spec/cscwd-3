"""MILP for the estimated single-window SUKP objective; no future oracle."""
from math import exp
from time import perf_counter
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from bundle import feasible, value


def solve_snapshot(snapshot, survival=True, time_limit=1.0):
    started = perf_counter()
    ids = sorted(snapshot.stale)
    tasks = [t for t in snapshot.tasks if t.inputs & snapshot.stale]
    if not ids or not tasks:
        return {"action": [], "value": 0.0, "upper_bound": 0.0, "solver_gap": 0.0,
                "status": 0, "message": "empty decision objective", "seconds": perf_counter() - started}
    pos = {i: k for k, i in enumerate(ids)}
    n, m = len(ids), len(tasks)
    objective = np.zeros(n + m)
    for j, task in enumerate(tasks):
        q = exp(-task.delay * sum(snapshot.rates[i] for i in sorted(task.inputs))) if survival else 1.0
        objective[n + j] = -task.weight * q
    rr, cc, vv = [], [], []
    for i in ids:
        rr.append(0); cc.append(pos[i]); vv.append(snapshot.costs[i])
    row = 1
    for j, task in enumerate(tasks):
        for i in sorted(task.inputs & snapshot.stale):
            rr.extend([row, row]); cc.extend([n + j, pos[i]]); vv.extend([1.0, -1.0])
            row += 1
    matrix = coo_matrix((vv, (rr, cc)), shape=(row, n + m)).tocsc()
    upper = np.zeros(row); upper[0] = snapshot.budget
    result = milp(objective, integrality=np.ones(n + m), bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix, np.full(row, -np.inf), upper),
                  options={"time_limit": time_limit, "mip_rel_gap": 0.0})
    action = frozenset(ids[k] for k in range(n) if result.x is not None and result.x[k] > 0.5)
    if result.x is not None and not feasible(snapshot, action):
        raise AssertionError("solver returned infeasible rounded action")
    dual = getattr(result, "mip_dual_bound", None)
    return {"action": sorted(action) if result.x is not None else None,
            "value": value(snapshot, action, survival) if result.x is not None else None,
            "upper_bound": -float(dual) if dual is not None and np.isfinite(dual) else None,
            "solver_gap": float(result.mip_gap) if getattr(result, "mip_gap", None) is not None
                          and np.isfinite(result.mip_gap) else None,
            "status": int(result.status), "message": str(result.message),
            "seconds": perf_counter() - started}
