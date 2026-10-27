"""Validation seeds only. Run reduced v2 conditions with complete provenance."""
import argparse
from dataclasses import asdict
import datetime
import gzip
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bundle import value
from optimization import solve_snapshot
from policies import bundle_fast
from simulation import generate_trace, run_policy


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def source_hash():
    digest = hashlib.sha256()
    files = sorted((ROOT / "src").glob("*.py")) + [Path(__file__)]
    for path in files:
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="phase1_pilot_v1")
    args = parser.parse_args()
    config_raw = (ROOT / "configs/protocol.json").read_bytes()
    config = json.loads(config_raw)
    seeds = config["validation_seeds"]
    assert not set(seeds) & set(config["test_seeds"])
    out = ROOT / "results/runs" / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    import numpy, scipy
    metadata = {"phase": "PILOT_VALIDATION_ONLY", "source_sha256": source_hash(),
                "protocol_sha256": hashlib.sha256(config_raw).hexdigest(),
                "public_manifest_sha256": hashlib.sha256((ROOT / "data/public/manifest.json").read_bytes()).hexdigest(),
                "seeds": seeds, "windows": config["main"]["windows"], "python": sys.version,
                "python_executable": sys.executable, "platform": platform.platform(),
                "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                "dependencies": {"numpy": numpy.__version__, "scipy": scipy.__version__}}
    meta_path = out / "metadata.json"
    if meta_path.exists():
        old = json.loads(meta_path.read_text())
        for key, val in metadata.items():
            if old[key] != val:
                raise ValueError("cannot resume changed run: " + key)
    else:
        metadata["started_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        atomic_json(meta_path, metadata)
    cases = []
    for mu in (0.1, 0.5):
        cases.append(("synthetic_mu" + str(mu), "synthetic", mu, 1.0, "uniform", 0.0, [0.05, 0.1, 0.25]))
    for cv, mode in ((0.0, "fixed"), (0.0, "uniform"), (1.0, "fixed")):
        cases.append(("mechanism_cv" + str(cv) + "_" + mode, "synthetic", 0.5, cv, mode, 0.0, [0.1]))
    cases.append(("common_shock_eta0.5", "synthetic", 0.5, 1.0, "uniform", 0.5, [0.1]))
    for family in ("seismology", "montage"):
        cases.append(("public_" + family, family, 0.5, 1.0, "uniform", 0.0, [0.1]))
    summary_rows = []
    for case_id, structure, mu, cv, mode, eta, budgets in cases:
        for seed in seeds:
            inputs, n_files = None, None
            if structure != "synthetic":
                data = json.loads((ROOT / ("data/public/" + structure + "_structure.json")).read_text())
                inputs = tuple(frozenset(v) for v in data["inputs"])
                n_files = data["stats"]["sync_files"]
            trace = generate_trace(seed, mu, cv, mode, eta, config["main"]["windows"],
                                   config["main"]["history_duration"], inputs, n_files, structure)
            encoded = asdict(trace); encoded["inputs"] = [sorted(v) for v in trace.inputs]
            canonical = json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode()
            trace_hash = hashlib.sha256(canonical).hexdigest()
            trace_path = out / "traces" / (case_id + "_seed" + str(seed) + ".json.gz")
            trace_path.parent.mkdir(exist_ok=True)
            if not trace_path.exists():
                trace_path.write_bytes(gzip.compress(canonical, mtime=0))
            elif gzip.decompress(trace_path.read_bytes()) != canonical:
                raise ValueError("trace changed during resume")
            for budget in budgets:
                label = case_id + "_b" + str(budget) + "_seed" + str(seed)
                for method in config["main_methods"]:
                    path = out / "records" / (label + "_" + method + ".json")
                    if path.exists():
                        record = json.loads(path.read_text())
                        if record["trace_sha256"] != trace_hash:
                            raise ValueError("cached result trace mismatch")
                        snapshots = None
                    else:
                        record, snapshots = run_policy(trace, budget, method, diagnostics=(method == "sabs_partial"))
                        record.update({"case": case_id, "trace_sha256": trace_hash,
                                       "mean_rate": mu, "population_cv": cv, "delay_mode": mode, "eta": eta})
                        atomic_json(path, record)
                    row = {k: v for k, v in record.items() if k not in ("summary", "windows", "diagnostics")}
                    row.update(record["summary"])
                    summary_rows.append(row)
                    if method == "sabs_partial" and case_id == "synthetic_mu0.5" and budget in (0.05, 0.1) and seed in (0, 1, 2):
                        milp_path = out / "milp" / (label + ".json")
                        if not milp_path.exists():
                            if snapshots is None:
                                _, snapshots = run_policy(trace, budget, method, diagnostics=True)
                            comparisons = []
                            for window, snapshot in enumerate(snapshots[:5]):
                                for survival in (True, False):
                                    result = solve_snapshot(snapshot, survival, config["milp_time_limit_seconds"])
                                    action = bundle_fast(snapshot, survival)
                                    result.update({"window": window, "survival": survival,
                                                   "heuristic_value": value(snapshot, action, survival)})
                                    comparisons.append(result)
                            atomic_json(milp_path, {"case": label, "comparisons": comparisons})
                print("completed", label, flush=True)
    atomic_json(out / "summary.json", summary_rows)
    atomic_json(out / "completion.json", {"status": "PILOT_COMPLETE", "records": len(summary_rows),
                                          "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print("PILOT_COMPLETE", len(summary_rows), "policy traces", flush=True)


if __name__ == "__main__":
    main()
