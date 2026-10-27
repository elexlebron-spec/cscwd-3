# Reproduction entry point

Companion artifact for **When Priority Changes Fail to Improve Task-Input Freshness**.

Repository target supplied by the author: <https://github.com/elexlebron-spec/cscwd-3>. The paper identifies the exact published commit once publication is verified. No DOI is claimed. This package omits the manuscript, author metadata files, local absolute paths, compiler binaries, and old manuscript versions. A public GitHub account and commit history are not anonymous; venue review requirements must still be checked. No separate open-source license has been assigned to the research code. Public input-data license files are retained.

Distribution note: the old pilot metadata's local Python executable path is redacted in this review distribution. The original record's SHA256 and the redacted field are recorded in that metadata. Core code, configuration, traces, actions, and held-out metadata are preserved byte for byte; the full local research package retains the original pilot metadata.

## Start here

Unpack `CSCWD2027_review_artifact.zip` and work in its `cscwd2027_artifact` folder. The original experiment used Python 3.9.18 on macOS arm64. Dependencies are pinned in `requirements.txt`; other platforms may have different solver tie choices and timings.

```sh
python3 -m pip install -r requirements.txt
python3 scripts/verify_confirmatory.py --replay
```

The second command verifies the frozen source/configuration/data hashes, separate validation/test seeds, complete 1,760-policy-trace matrix, all recorded actions and costs, every version-exact task outcome, and task-by-task dominance of the unrestricted boundary reference. It also copies the frozen source into a temporary directory and regenerates seed-100 actions/freshness for the synthetic, Seismology, and Montage structures. It does not overwrite raw experimental records or compare machine-dependent timings.

To regenerate analysis and the three figures:

```sh
python3 scripts/analyze_confirmatory.py
python3 scripts/analyze_revision.py
```

The first command reconstructs confirmatory results from saved records, writes numerical macros, and saves vector/PNG figures in `paper/figures`. The second adds a clearly labeled post-hoc analytical interpretation of those same traces, not new simulations or a revised policy. Correctness regressions can be run with `python3 -m unittest discover -s tests -v`.

## Paper-to-output map

| Paper item | Preserved outputs | Reproduction entry point |
|---|---|---|
| Table I: complete public structures | `data/public/manifest.json`, `*_structure.json`, raw source JSONs and license | `scripts/fetch_public_data.py` records the fixed upstream commit; existing files are included for offline use |
| Table II: three 10% conditions | `results/runs/confirmatory_v1/analysis/{mean_freshness_percent,paired_differences,trace_summary}.csv` | `scripts/analyze_confirmatory.py` |
| Fig. 1: mechanism slice | `analysis/mechanism_by_seed.csv`, `analysis/analysis.json` within the run | `scripts/analyze_confirmatory.py` |
| Fig. 2: budgets | `analysis/mean_freshness_percent.csv`, individual records | `scripts/analyze_confirmatory.py` |
| Fig. 3: input-size strata | `analysis/analysis.json` field `public_strata`, original traces/actions | `scripts/analyze_confirmatory.py` replays input-level service |
| Exact-reference results | run `milp/*.json`, dynamic-MILP `records/*.json`, `analysis/paired_solver_timing.csv` | `scripts/analyze_confirmatory.py` |
| Joint-survival ceiling and illustrative delay target | `analysis/revision_diagnostics.json`, `paper/revision_macros.tex` | `scripts/analyze_revision.py` |
| Worked design scenario | `configs/worked_design_case.json`, `results/worked_design_case.json` | `scripts/run_design_case.py`; constructed, not empirical |

All `analysis/` paths in the table are under `results/runs/confirmatory_v1/`. `RESULTS_MAP.json` supplies the corresponding machine-readable map. Differences are absolute percentage points from unrounded trace means. Confidence intervals resample the 20 paired complete traces; tasks/windows are not independent replicates.

## Experiment provenance

`configs/confirmatory.json` and `.lock.json` freeze the test matrix, seeds 100–119, and simulation/policy source hash before held-out generation. The code hash covers `src/*.py` plus `scripts/run_confirmatory.py`. Frozen copies are in `results/runs/confirmatory_v1/source_snapshot`. Validation seeds 0–4 informed the protocol and two solver conditions but are not pooled with the test results. The original pilot records are included separately for provenance.

`scripts/run_confirmatory.py` resumes matching saved records. For a full recomputation, make a separate copy of this package and move the saved `results/runs/confirmatory_v1` outside its run path before invoking that script. Keep the only original records intact. Do not edit the frozen config to relabel new work as unseen testing.

The post-hoc ceiling uses true saved generating rates exclusively as evaluator inputs. For independent revisions, any boundary-only policy has per-task success probability at most `exp(-delay * sum(input rates))`. The illustrative target of 0.5 was selected after the main study; it is not a preregistered endpoint or an executed intervention. The worked BIM mapping likewise is not industrial data or CAD-geometry validation.

`MANIFEST.sha256` lists all files in this companion package except itself. To verify it with common shell tools, run `shasum -a 256 -c MANIFEST.sha256` from the package root.
