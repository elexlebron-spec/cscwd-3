"""Reconstruct paired validation summaries and exploratory figures from raw runs."""
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
import pandas as pd
from simulation import Trace, evaluate_action, snapshot_at


def paired_stats(values, name):
    values = np.asarray(values, dtype=float)
    seed = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(10000, len(values)), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return {"mean_pp": float(values.mean()), "lo_pp": float(lo), "hi_pp": float(hi),
            "positive_seeds": int(sum(values > 1e-9)), "negative_seeds": int(sum(values < -1e-9)),
            "n_seeds": len(values), "per_seed_pp": values.tolist()}


def replay_strata(run, record):
    label = record["case"] + "_seed" + str(record["summary"]["seed"]) + ".json.gz"
    payload = json.loads(gzip.decompress((run / "traces" / label).read_bytes()))
    payload["inputs"] = tuple(frozenset(v) for v in payload["inputs"])
    payload["group_shock_rates"] = {int(k): v for k, v in payload["group_shock_rates"].items()}
    trace = Trace(**payload)
    cache = [len(h) for h in trace.history_events]
    totals = {}
    reconstructed = []
    for row in record["windows"]:
        w = row["window"]
        snap, _ = snapshot_at(trace, w, cache, record["summary"]["budget_fraction"])
        cache, fresh = evaluate_action(trace, w, cache, snap, frozenset(row["selected_files"]))
        reconstructed.append(sum(fresh) / len(fresh))
        for task, ok in zip(snap.tasks, fresh):
            arity = len(task.inputs)
            group = "0" if arity == 0 else "1" if arity == 1 else "2-4" if arity <= 4 else "5+"
            pair = totals.setdefault(group, [0, 0])
            pair[0] += int(ok); pair[1] += 1
    assert abs(float(np.mean(reconstructed)) - record["summary"]["fresh_fraction"]) < 1e-12
    return {group: {"fresh": v[0], "task_uses": v[1], "fraction": v[0] / v[1]}
            for group, v in totals.items()}


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    run = ROOT / "results/runs/phase1_pilot_v1"
    out = run / "analysis"
    out.mkdir(exist_ok=True)
    df = pd.DataFrame(json.loads((run / "summary.json").read_text()))
    assert len(df) == 420 and sorted(df.seed.unique()) == [0, 1, 2, 3, 4]
    df.drop(columns=["decision_seconds"]).to_csv(out / "trace_summary.csv", index=False)
    averages = df.groupby(["case", "budget_fraction", "method"]).fresh_fraction.mean().unstack() * 100
    averages.to_csv(out / "mean_freshness_percent.csv")
    pivot = df.pivot(index=["case", "budget_fraction", "seed"], columns="method", values="fresh_fraction")
    differences = []
    for (case, budget), frame in pivot.groupby(level=[0, 1]):
        for baseline in ("bundle_no_survival_partial", "item_utility"):
            values = (frame.sabs_partial - frame[baseline]) * 100
            differences.append({"case": case, "budget_fraction": budget, "baseline": baseline,
                                **paired_stats(values, case + str(budget) + baseline)})
    pd.DataFrame(differences).drop(columns="per_seed_pp").to_csv(out / "paired_differences.csv", index=False)
    diagnostics = []
    strata = []
    for path in sorted((run / "records").glob("*.json")):
        r = json.loads(path.read_text())
        if r["case"].startswith("public_"):
            strata.append({"case": r["case"], "method": r["summary"]["method"],
                           "seed": r["summary"]["seed"], "strata": replay_strata(run, r)})
        if r["summary"]["method"] != "sabs_partial":
            continue
        ds = r["diagnostics"]
        pair = [d["comparisons_to_sabs"]["bundle_no_survival_partial"] for d in ds]
        diagnostics.append({"case": r["case"], "budget_fraction": r["summary"]["budget_fraction"],
                            "seed": r["summary"]["seed"],
                            "action_difference_fraction": float(np.mean([p["action_differs"] for p in pair])),
                            "same_snapshot_gain_pp": float(np.mean([p["realized_freshness_delta"] for p in pair]) * 100),
                            "estimated_q_cv": float(np.mean([d["estimated_q"]["cv"] for d in ds])),
                            "true_q_cv": float(np.mean([d["true_q_cv_diagnostic"] for d in ds]))})
    pd.DataFrame(diagnostics).to_csv(out / "mechanism_by_seed.csv", index=False)
    milp = [r for p in sorted((run / "milp").glob("*.json")) for r in json.loads(p.read_text())["comparisons"]]
    gap_rows = []
    for survival in (True, False):
        group = [r for r in milp if r["survival"] == survival]
        gaps = [(r["value"] - r["heuristic_value"]) / r["value"]
                for r in group if r["status"] == 0 and r["value"] > 1e-12]
        gap_rows.append({"survival": survival, "n_solves": len(group),
                         "optimal_status_count": sum(r["status"] == 0 for r in group),
                         "nonzero_optimum_count": len(gaps),
                         "mean_relative_gap": float(np.mean(gaps)), "max_relative_gap": max(gaps),
                         "median_solver_ms": float(np.median([r["seconds"] for r in group]) * 1000)})
    times = []
    for method, frame in df.groupby("method"):
        all_times = [v for values in frame.decision_seconds for v in values]
        times.append({"method": method, "decisions": len(all_times),
                      "median_ms": float(np.median(all_times) * 1000),
                      "p95_ms": float(np.quantile(all_times, 0.95) * 1000)})
    output = {"scope": "EXPLORATORY_VALIDATION_ONLY_5_SEEDS", "differences": differences,
              "mechanism_by_seed": diagnostics, "milp": gap_rows, "timing": times,
              "public_strata": strata}
    (out / "analysis.json").write_text(json.dumps(output, indent=2) + "\n")
    # Raw seed points show the limited validation sample; no significance stars.
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.3))
    styles = [("sabs_partial", "SABS + partial", "#12666a"),
              ("bundle_no_survival_partial", "Bundle, no survival", "#d98723"),
              ("item_utility", "Item, same survival", "#6375a7")]
    sub = df[df.case == "synthetic_mu0.5"]
    for method, label, color in styles:
        g = sub[sub.method == method].groupby("budget_fraction").fresh_fraction.mean()
        axes[0].plot(g.index * 100, g.values * 100, "o-", color=color, label=label)
    axes[0].set(xlabel="Synchronization budget (%)", ylabel="Fresh task uses (%)", title="Heterogeneous rates: mean 0.5")
    axes[0].legend(fontsize=8)
    cases = ["mechanism_cv0.0_fixed", "mechanism_cv0.0_uniform", "mechanism_cv1.0_fixed", "synthetic_mu0.5"]
    labels = ["CV0 / fixed", "CV0 / varied", "CV1 / fixed", "CV1 / varied"]
    for k, case in enumerate(cases):
        item = next(x for x in differences if x["case"] == case and x["budget_fraction"] == 0.1
                    and x["baseline"] == "bundle_no_survival_partial")
        axes[1].scatter([k] * 5, item["per_seed_pp"], color="#12666a", alpha=0.6, s=20)
        axes[1].plot([k - 0.2, k + 0.2], [item["mean_pp"]] * 2, color="#173138", linewidth=2)
    axes[1].axhline(0, color="grey", linewidth=0.8)
    axes[1].set(xticks=range(4), xticklabels=labels, ylabel="SABS minus no-survival (pp)", title="Mechanism slice: per-seed differences")
    axes[1].tick_params(axis="x", labelrotation=25, labelsize=8)
    for k, family in enumerate(("seismology", "montage")):
        for offset, (method, label, color) in zip((-0.22, 0, 0.22), styles):
            vals = df[(df.case == "public_" + family) & (df.method == method)].fresh_fraction * 100
            axes[2].scatter([k + offset] * len(vals), vals, color=color, alpha=0.6, s=20)
            axes[2].plot([k + offset - 0.07, k + offset + 0.07], [vals.mean()] * 2, color=color, linewidth=3)
    axes[2].set(xticks=[0, 1], xticklabels=["Seismology", "Montage"], ylabel="Fresh task uses (%)", title="Complete public structures; synthetic updates")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("PILOT ONLY: validation seeds 0-4, 30 windows; no held-out test results", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "pilot_evidence.png", dpi=180)
    fig.savefig(out / "pilot_evidence.svg")
    print(json.dumps({"milp": gap_rows, "timing": times}, indent=2))
    print("Analysis saved to", out)


if __name__ == "__main__":
    main()
