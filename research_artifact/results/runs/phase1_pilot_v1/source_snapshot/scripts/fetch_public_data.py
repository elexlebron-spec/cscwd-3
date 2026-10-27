"""Fetch fixed public sources, audit all family candidates, keep full winners.

Only reads HTTPS GitHub endpoints and writes this project's data/public folder.
"""
import concurrent.futures
import datetime
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from public_data import parse_instance

COMMIT = "4c3958e94f99e12c2663d4e093eb41731ca7496c"
REPO = "https://github.com/wfcommons/WfInstances"
OUT = ROOT / "data/public"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "CSCWD-reproducible-research"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def raw_url(path):
    return "https://raw.githubusercontent.com/wfcommons/WfInstances/" + COMMIT + "/" + path


def audit(entry):
    path = entry["path"]
    raw = fetch(raw_url(path))
    parsed = parse_instance(json.loads(raw))
    info = {"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
            "url": raw_url(path), "schema_version": parsed["schema_version"], **parsed["stats"]}
    return info, raw, parsed


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tree_path = OUT / "repository_tree.json"
    if tree_path.exists():
        tree = json.loads(tree_path.read_text())
    else:
        tree = json.loads(fetch("https://api.github.com/repos/wfcommons/WfInstances/git/trees/" + COMMIT + "?recursive=1"))
        tree_path.write_text(json.dumps(tree, indent=2))
    if tree["sha"] != COMMIT or tree.get("truncated"):
        raise ValueError("repository tree is not complete at the pinned commit")
    manifest = {"repository": REPO, "commit": COMMIT,
                "retrieved_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "selection": "minimum (sync_files, tasks, path) within 2000 inputs/1000 tasks",
                "license": "LGPL-3.0 repository license; no per-instance license asserted",
                "candidates": [], "selected": []}
    license_raw = fetch(raw_url("LICENSE"))
    (OUT / "raw").mkdir(exist_ok=True)
    (OUT / "raw/LICENSE").write_bytes(license_raw)
    manifest["license_sha256"] = hashlib.sha256(license_raw).hexdigest()
    for family in ("pegasus/seismology", "pegasus/montage"):
        entries = [e for e in tree["tree"] if e["path"].startswith(family + "/") and e["path"].endswith(".json")]
        best = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for info, raw, parsed in pool.map(audit, entries):
                manifest["candidates"].append(info)
                print(info["path"], info["tasks"], info["sync_files"], flush=True)
                if info["tasks"] > 1000 or info["sync_files"] > 2000:
                    continue
                key = (info["sync_files"], info["tasks"], info["path"])
                if best is None or key < best[0]:
                    best = (key, info, raw, parsed)
        if best is None:
            raise ValueError("no eligible complete instance in " + family)
        _, info, raw, parsed = best
        target = OUT / "raw" / info["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        name = family.split("/")[-1]
        processed = OUT / (name + "_structure.json")
        processed.write_text(json.dumps(parsed, indent=2) + "\n")
        manifest["selected"].append({**info, "family": family,
                                     "local_raw": str(target.relative_to(ROOT)),
                                     "local_structure": str(processed.relative_to(ROOT)),
                                     "processed_sha256": hashlib.sha256(processed.read_bytes()).hexdigest()})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("SELECTED", json.dumps(manifest["selected"], indent=2), flush=True)


if __name__ == "__main__":
    main()
