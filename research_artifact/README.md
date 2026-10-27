# Reproduction entry point

Companion artifact for **From Priority Changes to Service Gains: Evaluating Task-Input Freshness**.

Repository target supplied by the author: <https://github.com/elexlebron-spec/cscwd-3>. The paper identifies the exact published commit once publication is verified. No DOI is claimed. This package omits the manuscript, author metadata files, local absolute paths, compiler binaries, and old manuscript versions. A public GitHub account and commit history are not anonymous; venue review requirements must still be checked. No separate open-source license has been assigned to the research code. Public input-data license files are retained.

Distribution note: the old pilot metadata's local Python executable path is redacted in this review distribution. The original record's SHA256 and the redacted field are recorded in that metadata. Core code, configuration, traces, actions, and held-out metadata are preserved byte for byte; the full local research package retains the original pilot metadata.

## Start here

Unpack `CSCWD2027_review_artifact.zip` and work in its `cscwd2027_artifact` folder. The original experiment used Python 3.9.18 on macOS arm64. Dependencies are pinned in `requirements.txt`; other platforms may have different solver tie choices and timings.

```sh
python3 -m pip install -r requirements.txt
python3 scripts/verify_confirmatory.py --replay
python3 scripts/verify_mechanism_probe.py
```

The second command verifies the frozen source/configuration/data hashes, separate validation/test seeds, complete 1,760-policy-trace matrix, all recorded actions and costs, every version-exact task outcome, and task-by-task dominance of the unrestricted boundary reference. It also copies the frozen source into a temporary directory and regenerates seed-100 actions/freshness for the synthetic, Seismology, and Montage structures. It does not overwrite raw experimental records or compare machine-dependent timings.

To regenerate analysis and the three figures:

```sh
python3 scripts/analyze_confirmatory.py
python3 scripts/analyze_revision.py
python3 scripts/analyze_mechanism_probe.py
python3 scripts/plot_evaluation_evidence.py
```

The first command reconstructs primary results. The additional commands retain the original survival-bound analysis, replay the post-hoc one-action interventions, and draw the combined evidence figure. They do not tune or change the tested policies. Correctness regressions can be run with python3 -m unittest discover -s tests -v.

## Paper-to-output map

| Paper item | Preserved outputs | Entry point |
|---|---|---|
| Table I: complete public structures | data/public/manifest.json, original JSONs/license, processed structures | scripts/fetch_public_data.py; files included for offline use |
| Table II: first positive-immediate intervention | results/runs/mechanism_probe_v1/summary.json representative field and seed100.json | scripts/analyze_mechanism_probe.py; scripts/plot_evaluation_evidence.py emits macros |
| Table III: primary 10% results | confirmatory_v1/analysis/{mean_freshness_percent,paired_differences,trace_summary}.csv | scripts/analyze_confirmatory.py |
| Fig. 1a,b: primary evaluation signals | confirmatory_v1/analysis/analysis.json | scripts/plot_evaluation_evidence.py |
| Fig. 1c: common-continuation probe | mechanism_probe_v1/summary.json, all 20 seed records | scripts/analyze_mechanism_probe.py; scripts/plot_evaluation_evidence.py |
| Fig. 2: budgets | confirmatory_v1/analysis/mean_freshness_percent.csv | scripts/analyze_confirmatory.py |
| Large-group outcomes and exact references | confirmatory_v1/analysis/analysis.json, milp/ and dynamic records | scripts/analyze_confirmatory.py |
| Post-hoc survival ceiling | confirmatory_v1/analysis/revision_diagnostics.json | scripts/analyze_revision.py |
| Version-contract comparison | results/worked_design_contract.json | scripts/run_design_contract.py |

Run directories above are under results/runs. The 480 interventions are 24 starts per seed on 20 previously seen test traces, not 480 independent samples or new confirmatory trials. At each start, only the initial choice differs; both branches subsequently run Gq on their own cache for five windows. Confidence intervals resample seed-level intervention averages. The first positive-immediate seed/window is selected without consulting later outcomes. All records remain available, including continued benefits and reversals. Equality of identical-action branches and exact replay of branch A against the preserved Gq trajectory are checked.

The official BIM documentation permits choosing consumed versions. The worked contract therefore compares latest-published and frozen-manifest rules on identical constructed events. It is not a calibrated field study, and passing a different criterion is not an improvement under the old metric.

## Experiment provenance

`configs/confirmatory.json` and `.lock.json` freeze the test matrix, seeds 100–119, and simulation/policy source hash before held-out generation. The code hash covers `src/*.py` plus `scripts/run_confirmatory.py`. Frozen copies are in `results/runs/confirmatory_v1/source_snapshot`. Validation seeds 0–4 informed the protocol and two solver conditions but are not pooled with the test results. The original pilot records are included separately for provenance.

`scripts/run_confirmatory.py` resumes matching saved records. For a full recomputation, make a separate copy of this package and move the saved `results/runs/confirmatory_v1` outside its run path before invoking that script. Keep the only original records intact. Do not edit the frozen config to relabel new work as unseen testing.

The post-hoc ceiling uses true saved generating rates exclusively as evaluator inputs. For independent revisions, any boundary-only policy has per-task success probability at most `exp(-delay * sum(input rates))`. The illustrative target of 0.5 was selected after the main study; it is not a preregistered endpoint or an executed intervention. The worked BIM mapping likewise is not industrial data or CAD-geometry validation.

`MANIFEST.sha256` lists all files in this companion package except itself. To verify it with common shell tools, run `shasum -a 256 -c MANIFEST.sha256` from the package root.
