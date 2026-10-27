"""Plot primary evidence and the separately labeled post-hoc continuation probe."""
import json
import os
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
from analyze_pilot import paired_stats


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    analysis = json.loads((ROOT / "results/runs/confirmatory_v1/analysis/analysis.json").read_text())
    probe = json.loads((ROOT / "results/runs/mechanism_probe_v1/summary.json").read_text())
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 8,
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    fig, axes = plt.subplots(1, 3, figsize=(7.1, 2.25))
    cases = ["mechanism_cv0.0_fixed", "mechanism_cv0.0_uniform", "mechanism_cv1.0_fixed", "synthetic_mu0.5"]
    for index, case in enumerate(cases):
        overall = next(r for r in analysis["differences"] if r["case"] == case and r["budget_fraction"] == .1
                       and r["left"] == "sabs_partial" and r["right"] == "bundle_no_survival_partial")
        values = [r["same_snapshot_gain_pp"] for r in analysis["mechanism_by_seed"]
                  if r["case"] == case and r["budget_fraction"] == .1]
        local = paired_stats(values, "local" + case)
        for ax, r in zip(axes[:2], (overall, local)):
            ax.errorbar(index, r["mean_pp"], yerr=[[r["mean_pp"] - r["lo_pp"]], [r["hi_pp"] - r["mean_pp"]]],
                        fmt="o", color="#16766c", capsize=3, markersize=4)
    for ax, title in zip(axes[:2], ("(a) Full trajectories", "(b) Matched states")):
        ax.set(xticks=range(4), xticklabels=["CV0\nfixed", "CV0\nvar.", "CV1\nfixed", "CV1\nvar."],
               ylabel="Freshness difference (pp)", title=title)
    series = probe["groups"]["all_interventions"]["series"]
    axes[2].errorbar([r["offset"] for r in series], [r["mean"] for r in series],
                    yerr=[[r["mean"] - r["low"] for r in series], [r["high"] - r["mean"] for r in series]],
                    fmt="o-", color="#b35b20", capsize=3, markersize=3, linewidth=1)
    axes[2].set(xlabel="Windows after intervention", ylabel="Cumulative fresh-use difference",
                title="(c) Common continuation", xticks=[0, 1, 2, 3, 4, 5])
    for ax in axes:
        ax.axhline(0, color="grey", linewidth=.8); ax.grid(axis="y", alpha=.2)
    fig.tight_layout(pad=.8, w_pad=1.0)
    fig.savefig(ROOT / "paper/figures/evaluation_evidence.pdf", bbox_inches="tight")
    fig.savefig(ROOT / "paper/figures/evaluation_evidence.png", bbox_inches="tight", dpi=220)
    all_g = probe["groups"]["all_interventions"]
    pos = probe["groups"]["positive_immediate"]
    macros = {}
    for prefix, record in [("ProbeInitial", all_g["series"][0]), ("ProbeEnd", all_g["series"][-1]),
                           ("ProbeFuture", all_g["future_offsets_1_to_5"])]:
        for suffix, key in [("", "mean"), ("Low", "low"), ("High", "high")]:
            macros[prefix + suffix] = f"{record[key]:.2f}"
    macros.update({"ProbePositiveN": str(pos["pairs"]), "ProbeRetainedN": str(pos["end_positive_pairs"]),
                   "ProbeNotPositiveN": str(pos["end_zero_pairs"] + pos["end_negative_pairs"])})
    rep = probe["representative"]
    macros.update({"ProbeExampleSeed": str(rep["seed"]), "ProbeExampleWindow": str(rep["intervention_window"])})
    for suffix, i in [("Zero", 0), ("One", 1), ("End", 5)]:
        step = rep["steps"][i]
        macros["ProbeFreshA" + suffix] = str(step["weighted_initial_branch"]["fresh_count"])
        macros["ProbeFreshB" + suffix] = str(step["unweighted_initial_branch"]["fresh_count"])
        macros["ProbeDelta" + suffix] = f"{step['fresh_delta']:+d}"
        macros["ProbeCumulative" + suffix] = f"{step['cumulative_fresh_delta']:+d}"
        macros["ProbeCostA" + suffix] = f"{step['weighted_initial_branch']['sync_cost']:g}"
        macros["ProbeCostB" + suffix] = f"{step['unweighted_initial_branch']['sync_cost']:g}"
    import gzip
    trace_path = ROOT / "results/runs/confirmatory_v1/traces" / ("mechanism_cv0.0_uniform_seed" + str(rep["seed"]) + ".json.gz")
    trace = json.loads(gzip.decompress(trace_path.read_bytes()))
    step = rep["steps"][1]
    lost = step["lost_task_ids"][0]
    a, b = step["weighted_initial_branch"], step["unweighted_initial_branch"]
    blockers = [i for i in trace["inputs"][lost] if a["cache_after"][i] != b["cache_after"][i]]
    retained = [i for i in step["unweighted_only_current_inputs"] if i in a["selected_files"]]
    assert len(blockers) == len(retained) == 1
    file_id, retained_id = blockers[0], retained[0]
    macros.update({"ProbeLostTask": str(lost), "ProbeBlockingFile": str(file_id),
                   "ProbeBlockingCost": str(trace["costs"][file_id]),
                   "ProbeCacheAVersion": str(a["cache_after"][file_id]),
                   "ProbeCacheBVersion": str(b["cache_after"][file_id]),
                   "ProbeRetainedFile": str(retained_id), "ProbeRetainedCost": str(trace["costs"][retained_id]),
                   "ProbeExampleBudget": f"{a['budget']:.1f}"})
    (ROOT / "paper/probe_macros.tex").write_text("% Generated from the post-hoc probe; not a new confirmatory result.\n" +
        "\n".join("\\newcommand{\\" + key + "}{" + value + "}" for key, value in macros.items()) + "\n")
    (ROOT / "results/runs/mechanism_probe_v1/paper_numbers.json").write_text(json.dumps(macros, indent=2) + "\n")
    print("Combined evidence figure and", len(macros), "probe macros generated.")


if __name__ == "__main__":
    main()
