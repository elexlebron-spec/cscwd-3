"""Held-out analysis, paired by complete trace; emits paper tables and figures."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
import pandas as pd
from analyze_pilot import paired_stats, replay_strata

RUN = ROOT / "results/runs/confirmatory_v1"


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    assert json.loads((RUN / "completion.json").read_text())["status"] == "CONFIRMATORY_COMPLETE"
    config = json.loads((ROOT / "configs/confirmatory.json").read_text())
    rows = json.loads((RUN / "summary.json").read_text())
    df = pd.DataFrame(rows)
    assert len(df) == 1760 and sorted(df.seed.unique()) == list(range(100, 120))
    out = RUN / "analysis"; out.mkdir(exist_ok=True)
    figs = ROOT / "paper/figures"; figs.mkdir(exist_ok=True)
    df.drop(columns=["decision_seconds"]).to_csv(out / "trace_summary.csv", index=False)
    avg = df.groupby(["case", "budget_fraction", "method"]).fresh_fraction.mean().unstack() * 100
    avg.to_csv(out / "mean_freshness_percent.csv")
    pivot = df.pivot(index=["case", "budget_fraction", "seed"], columns="method", values="fresh_fraction")
    differences = []
    for (case, budget), frame in pivot.groupby(level=[0, 1]):
        pairs = [("sabs_partial", "bundle_no_survival_partial"), ("sabs_partial", "item_utility")]
        if frame.milp_survival_dynamic.notna().all():
            pairs += [("milp_survival_dynamic", "milp_no_survival_dynamic"), ("sabs_partial", "milp_survival_dynamic")]
        for left, right in pairs:
            vals = (frame[left] - frame[right]) * 100
            differences.append({"case": case, "budget_fraction": budget, "left": left, "right": right,
                                **paired_stats(vals, case + str(budget) + left + right)})
    pd.DataFrame(differences).drop(columns="per_seed_pp").to_csv(out / "paired_differences.csv", index=False)
    diagnostics, strata, paired_timing, solver_status = [], [], [], []
    for path in sorted((RUN / "records").glob("*.json")):
        r = json.loads(path.read_text()); method = r["summary"]["method"]
        if r["case"].startswith("public_"):
            strata.append({"case": r["case"], "method": method, "seed": r["summary"]["seed"],
                           "strata": replay_strata(RUN, r)})
        if method.startswith("milp_"):
            for w in r["windows"]:
                solver_status.append(w["solver"]["status"])
                if w["nonempty_stale_set"]:
                    paired_timing.append({"case": r["case"], "method": method, "seed": r["summary"]["seed"],
                                         "window": w["window"], "milp_ms": w["solver"]["seconds"] * 1000,
                                         "greedy_ms": w["heuristic_seconds_same_snapshot"] * 1000})
        if method != "sabs_partial":
            continue
        ds = r["diagnostics"]
        pair = [d["comparisons_to_sabs"]["bundle_no_survival_partial"] for d in ds]
        diagnostics.append({"case": r["case"], "budget_fraction": r["summary"]["budget_fraction"],
                            "seed": r["summary"]["seed"],
                            "action_difference_fraction": float(np.mean([p["action_differs"] for p in pair])),
                            "same_snapshot_gain_pp": float(np.mean([p["realized_freshness_delta"] for p in pair]) * 100),
                            "estimated_q_cv": float(np.mean([d["estimated_q"]["cv"] for d in ds])),
                            "true_q_cv": float(np.mean([d["true_q_cv_diagnostic"] for d in ds])),
                            "mean_unaffordable_missing_bundles": float(np.mean([d["unaffordable_missing_bundles"] for d in ds]))})
    pd.DataFrame(diagnostics).to_csv(out / "mechanism_by_seed.csv", index=False)
    pd.DataFrame(paired_timing).to_csv(out / "paired_solver_timing.csv", index=False)
    static = [r for path in (RUN / "milp").glob("*.json") for r in json.loads(path.read_text())["comparisons"]]
    gaps = []
    for survival in (True, False):
        selected = [r for r in static if r["survival"] == survival]
        relative = [(r["value"] - r["heuristic_value"]) / r["value"] for r in selected
                    if r["status"] == 0 and r["value"] > 1e-12]
        gaps.append({"survival": survival, "solves": len(selected),
                     "optimal": sum(r["status"] == 0 for r in selected), "nonzero_optima": len(relative),
                     "mean_gap_percent": float(np.mean(relative) * 100), "max_gap_percent": max(relative) * 100})
    result = {"phase": "HELD_OUT_CONFIRMATORY", "n_seeds": 20, "policy_traces": len(df),
              "differences": differences, "mechanism_by_seed": diagnostics, "public_strata": strata,
              "static_milp_gaps": gaps, "dynamic_solver_status_counts": {str(k): solver_status.count(k) for k in set(solver_status)},
              "paired_timing": {"snapshots": len(paired_timing),
                                "median_milp_ms": float(np.median([x["milp_ms"] for x in paired_timing])),
                                "median_greedy_ms": float(np.median([x["greedy_ms"] for x in paired_timing]))}}
    (out / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    def find_pair(case, right, left="sabs_partial", budget=0.1):
        return next(r for r in differences if r["case"] == case and r["budget_fraction"] == budget and r["left"] == left and r["right"] == right)
    def perf(case, method, budget=0.1):
        return avg.loc[(case, budget), method]
    macros = {}
    names = [("Synth", "synthetic_mu0.5"), ("Seismo", "public_seismology"), ("Montage", "public_montage")]
    for prefix, case in names:
        for suffix, method in [("Fresh", "sabs_partial"), ("NoSurv", "bundle_no_survival_partial"), ("Item", "item_utility")]:
            macros[prefix + suffix] = perf(case, method)
        for suffix, other in [("SurvGain", "bundle_no_survival_partial"), ("GroupGain", "item_utility")]:
            pair = find_pair(case, other); macros[prefix + suffix] = pair["mean_pp"]
            macros[prefix + suffix + "Low"] = pair["lo_pp"]; macros[prefix + suffix + "High"] = pair["hi_pp"]
    for prefix, case in [("FixedHom", "mechanism_cv0.0_fixed"), ("VarHom", "mechanism_cv0.0_uniform"), ("FixedHet", "mechanism_cv1.0_fixed")]:
        p = find_pair(case, "bundle_no_survival_partial")
        macros[prefix + "Gain"] = p["mean_pp"]; macros[prefix + "Low"] = p["lo_pp"]; macros[prefix + "High"] = p["hi_pp"]
        selected = [d for d in diagnostics if d["case"] == case]
        macros[prefix + "Disagreement"] = np.mean([d["action_difference_fraction"] for d in selected]) * 100
    macros["ShockGain"] = find_pair("common_shock_eta0.5", "bundle_no_survival_partial")["mean_pp"]
    macros["SaturationFresh"] = perf("synthetic_mu0.1", "sabs_partial", 0.25)
    for prefix, case in [("Synth", "synthetic_mu0.5"), ("Montage", "public_montage")]:
        macros[prefix + "MilpFresh"] = perf(case, "milp_survival_dynamic")
        macros[prefix + "MilpNoSurv"] = perf(case, "milp_no_survival_dynamic")
        macros[prefix + "MilpSurvGain"] = find_pair(case, "milp_no_survival_dynamic", left="milp_survival_dynamic")["mean_pp"]
    macros["SolverMedian"] = result["paired_timing"]["median_milp_ms"]
    macros["GreedyMedian"] = result["paired_timing"]["median_greedy_ms"]
    macros["MeanStaticGap"] = gaps[0]["mean_gap_percent"]; macros["MaxStaticGap"] = gaps[0]["max_gap_percent"]
    (ROOT / "paper/results_macros.tex").write_text("% Generated from held-out results; do not hand-edit.\n" +
        "\n".join("\\newcommand{\\" + k + "}{" + f"{v:.2f}" + "}" for k, v in macros.items()) + "\n")
    (out / "paper_numbers.json").write_text(json.dumps(macros, indent=2) + "\n")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 9,
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    styles = [("item_no_survival", "$I_0$", "#9a8a7b", ":"), ("item_utility", "$I_q$", "#7570b3", "-"),
              ("bundle_no_survival_partial", "$G_0$", "#d95f02", "-"), ("sabs_partial", "$G_q$", "#16766c", "-"),
              ("always_sync_unconstrained", "All", "#666666", "--")]
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.6))
    for ax, mu in zip(axes, (0.1, 0.5)):
        for method, label, color, line in styles:
            group = df[(df.case == "synthetic_mu" + str(mu)) & (df.method == method)]
            means = group.groupby("budget_fraction").fresh_fraction.mean()
            ax.plot(means.index * 100, means.values * 100, "o" + line, label=label, color=color, markersize=3, linewidth=1.2)
        ax.set(xlabel="Budget (% of all-file cost)", ylabel="Fresh task uses (%)", title="$\\mu=" + str(mu) + "$; heterogeneous source rates")
        ax.grid(axis="y", alpha=0.2)
    axes[1].legend(ncol=5, loc="lower center", bbox_to_anchor=(-0.1, 1.17), frameon=False, handlelength=1.5, columnspacing=1.0)
    fig.tight_layout();fig.savefig(figs / "budgets.pdf", bbox_inches="tight");fig.savefig(figs / "budgets.png", dpi=200, bbox_inches="tight")
    cases = ["mechanism_cv0.0_fixed", "mechanism_cv0.0_uniform", "mechanism_cv1.0_fixed", "synthetic_mu0.5"]
    labels = ["CV0\nfixed", "CV0\nvaried", "CV1\nfixed", "CV1\nvaried"]
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.25))
    for index, case in enumerate(cases):
        delta = find_pair(case, "bundle_no_survival_partial")
        vals = [d["same_snapshot_gain_pp"] for d in diagnostics if d["case"] == case and d["budget_fraction"] == 0.1]
        local = paired_stats(vals, "local" + case)
        for ax, r in zip(axes, (delta, local)):
            ax.errorbar(index, r["mean_pp"], yerr=[[r["mean_pp"] - r["lo_pp"]], [r["hi_pp"] - r["mean_pp"]]], fmt="o", capsize=3, color="#16766c")
    for ax, title in zip(axes, ("Whole-trajectory difference", "Same-snapshot realized difference")):
        ax.axhline(0, color="grey", linewidth=0.8);ax.set(xticks=range(4), xticklabels=labels,
            ylabel="$G_q-G_0$ (percentage points)", title=title);ax.grid(axis="y", alpha=0.2)
    fig.tight_layout();fig.savefig(figs / "mechanisms.pdf", bbox_inches="tight");fig.savefig(figs / "mechanisms.png", dpi=200, bbox_inches="tight")
    fig, ax = plt.subplots(figsize=(3.45, 2.05))
    for k, family in enumerate(("public_seismology", "public_montage")):
        methods = [("sabs_partial", -0.16, "#16766c", "$G_q$"), ("always_sync_unconstrained", 0.16, "#888888", "All")]
        for method, offset, color, label in methods:
            subset = [r for r in strata if r["case"] == family and r["method"] == method]
            for g, group in enumerate(("2-4", "5+")):
                values = [r["strata"][group]["fraction"] * 100 for r in subset]
                ax.bar(k * 3 + g + offset, np.mean(values), width=0.29, color=color,
                       label=label if k == 0 and g == 0 else None)
    ax.set(xticks=[0, 1, 3, 4], xticklabels=["S:2-4", "S:103", "M:2-4", "M:5+"],
           ylabel="Fresh task uses (%)", title="Input-group size can hide unserved tasks")
    ax.legend(frameon=False, fontsize=8);ax.grid(axis="y", alpha=0.2);fig.tight_layout()
    fig.savefig(figs / "group_sizes.pdf", bbox_inches="tight");fig.savefig(figs / "group_sizes.png", dpi=200, bbox_inches="tight")
    print(avg.round(3).to_string())
    print("PAIRED", json.dumps(differences, indent=2))
    print("STATIC/TIMING", gaps, result["paired_timing"])
    print("Analysis and paper figures saved.")


if __name__ == "__main__":
    main()
