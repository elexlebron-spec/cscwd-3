"""Generate manuscript numbers only from audited supplementary results."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/runs/budget_timing_intervention_v1"
data = json.loads((RUN / "summary.json").read_text())
audit = json.loads((RUN / "INTEGRITY.json").read_text())
assert audit["status"] == "PASS"
effect = data["paired_target_effects_pp"]["timing_under_all"]
values = {"InterventionAllFresh": format(data["arm_means"]["all_history_cap"]["target_fresh_percent"], ".2f"),
          "InterventionAllLow": format(effect["lo_pp"], ".2f"), "InterventionAllHigh": format(effect["hi_pp"], ".2f"),
          "InterventionDelay": format(data["arm_means"]["all_history_cap"]["mean_target_delay"], ".5f")}
for label, arm in (("BudgetOriginal", "sabs_partial_original"), ("BudgetCap", "sabs_partial_history_cap"),
                   ("AllOriginal", "all_original"), ("AllCap", "all_history_cap")):
    values["Intervention" + label + "Count"] = str(audit["target_fresh_counts_all_600"][arm])
    values["Intervention" + label + "Later"] = str(audit["target_fresh_counts_after_initial_580"][arm])
    values["Intervention" + label + "Coverage"] = str(round(6 * data["arm_means"][arm]["target_boundary_coverage_percent"]))
(RUN / "paper_numbers.json").write_text(json.dumps(values, indent=2) + "\n")
(ROOT / "paper/intervention_macros.tex").write_text("% Generated from the audited prospectively fixed supplement; not the original primary experiment.\n" +
    "\n".join("\\newcommand{\\" + key + "}{" + value + "}" for key, value in values.items()) + "\n")
print(json.dumps(values, indent=2))
