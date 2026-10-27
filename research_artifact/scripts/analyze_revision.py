"""Post-hoc interpretation of preserved traces; no policy or simulation changes."""
import gzip
import hashlib
import json
from math import exp, log
from pathlib import Path
from statistics import mean

from analyze_pilot import paired_stats

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/runs/confirmatory_v1"


def main():
    analysis_path = RUN / "analysis/analysis.json"
    analysis = json.loads(analysis_path.read_text())
    local = {}
    for case in ("mechanism_cv0.0_fixed", "mechanism_cv0.0_uniform", "mechanism_cv1.0_fixed", "synthetic_mu0.5"):
        values = [r["same_snapshot_gain_pp"] for r in analysis["mechanism_by_seed"]
                  if r["case"] == case and r["budget_fraction"] == 0.1]
        # Same bootstrap key used by the already-published mechanism figure.
        local[case] = paired_stats(values, "local" + case)
    hazards, expected, thresholds, per_seed = [], [], [], []
    source_hashes = {}
    for seed in range(100, 120):
        path = RUN / "traces" / ("public_seismology_seed" + str(seed) + ".json.gz")
        raw = gzip.decompress(path.read_bytes()); trace = json.loads(raw)
        source_hashes[path.name] = hashlib.sha256(raw).hexdigest()
        task = next(j for j, inputs in enumerate(trace["inputs"]) if len(inputs) == 103)
        hazard = sum(trace["true_rates"][i] for i in trace["inputs"][task])
        qs = [exp(-ds[task] * hazard) for ds in trace["delays"]]
        target_delay = -log(0.5) / hazard
        hazards.append(hazard); expected.extend(qs); thresholds.append(target_delay)
        per_seed.append({"seed": seed, "task_index": task, "inputs": 103,
                         "true_hazard": hazard, "mean_unrestricted_survival": mean(qs),
                         "expected_fresh_uses": sum(qs), "delay_for_50_percent": target_delay})
    result = {"status": "POST_HOC_ANALYTICAL_INTERPRETATION",
              "scope": "Saved traces only; no new tested policy, fitting, parameter search or simulations",
              "rate_visibility": "True rates used only by offline evaluator; never supplied to ordinary policies",
              "example_target": "0.5 is an illustrative engineering target chosen after the main study, not a preregistered endpoint",
              "assumptions": "Independent Poisson revisions, atomic boundary copying, strict current-version check, no fetching until use",
              "analysis_sha256": hashlib.sha256(analysis_path.read_bytes()).hexdigest(),
              "trace_sha256": source_hashes, "local_effects": local,
              "large_group": {"hazard_min": min(hazards), "hazard_max": max(hazards),
                              "mean_survival_percent": mean(expected) * 100,
                              "expected_fresh_uses_over_600": sum(expected),
                              "target_delay_min": min(thresholds), "target_delay_max": max(thresholds),
                              "target": 0.5, "uses": len(expected), "per_seed": per_seed}}
    path = RUN / "analysis/revision_diagnostics.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    homogeneous = local["mechanism_cv0.0_uniform"]; group = result["large_group"]
    macros = {"HomLocalGain": (homogeneous["mean_pp"], 2),
              "HomLocalLow": (homogeneous["lo_pp"], 2), "HomLocalHigh": (homogeneous["hi_pp"], 2),
              "LargeCeilingPercent": (group["mean_survival_percent"], 3),
              "LargeExpectedUses": (group["expected_fresh_uses_over_600"], 3),
              "LargeHazardLow": (group["hazard_min"], 2), "LargeHazardHigh": (group["hazard_max"], 2),
              "LargeDelayLow": (group["target_delay_min"], 3), "LargeDelayHigh": (group["target_delay_max"], 3)}
    tex = "% Post-hoc analytical interpretation of saved traces; see revision_diagnostics.json.\n"
    tex += "\n".join("\\newcommand{\\" + k + "}{" + format(v, "." + str(digits) + "f") + "}"
                     for k, (v, digits) in macros.items()) + "\n"
    (ROOT / "paper/revision_macros.tex").write_text(tex)
    print(json.dumps({"local_homogeneous_varied": homogeneous, "large_group": {k: v for k, v in group.items() if k != "per_seed"}}, indent=2))


if __name__ == "__main__":
    main()
