"""Specified synthetic design helpers; true rates belong ONLY to generator/evaluator.

This module does not implement the production event simulator or estimator.
Policies in bundle.py never import it.
"""
import hashlib
import math
import random


def rng_stream(seed, name):
    encoded = (str(seed) + ":" + name).encode("utf-8")
    return random.Random(int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big"))


def task_inputs(seed):
    rng = rng_stream(seed, "structure")
    return tuple(frozenset(rng.sample(range(20), 2) + rng.sample(range(20, 100), 2))
                 for _ in range(100))


def true_rates(seed, mean_rate, population_cv, n=100):
    if not math.isfinite(mean_rate) or mean_rate < 0 or n < 1:
        raise ValueError("invalid mean rate or size")
    if not math.isfinite(population_cv) or population_cv < 0:
        raise ValueError("invalid coefficient of variation")
    rng = rng_stream(seed, "rates")
    sigma = math.sqrt(math.log1p(population_cv ** 2))
    samples = [math.exp(sigma * rng.gauss(0, 1) - sigma ** 2 / 2) for _ in range(n)]
    sample_mean = sum(samples) / n
    return tuple(mean_rate * z / sample_mean for z in samples)


def cost_vector(seed, n=100):
    rng = rng_stream(seed, "costs")
    return tuple(rng.randint(1, 5) for _ in range(n))


def common_shock_components(rates, eta, team_size=10):
    if not 0 <= eta <= 1 or team_size < 1 or any(r < 0 for r in rates):
        raise ValueError("invalid shock design")
    groups = {i // team_size for i in range(len(rates))}
    shock = {g: eta * min(r for i, r in enumerate(rates) if i // team_size == g)
             for g in groups}
    residual = tuple(r - shock[i // team_size] for i, r in enumerate(rates))
    return residual, shock


def true_joint_survival(inputs, delay, residual, shock, team_size=10):
    """Evaluator-only analytic reference: count each group shock ONCE."""
    groups = {i // team_size for i in inputs}
    return math.exp(-delay * (sum(residual[i] for i in inputs) + sum(shock[g] for g in groups)))
