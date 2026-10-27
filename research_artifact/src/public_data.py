"""Strict WfFormat 1.6 task-input adapter; no subgraph sampling."""
from collections import Counter
from pathlib import Path
import json


def parse_instance(document):
    if str(document.get("schemaVersion")) != "1.6":
        raise ValueError("only inspected WfFormat 1.6 is supported")
    spec = document["workflow"]["specification"]
    files = spec["files"]
    file_ids = [f["id"] for f in files]
    if len(file_ids) != len(set(file_ids)):
        raise ValueError("duplicate file ID")
    known = set(file_ids)
    tasks = spec["tasks"]
    task_ids = [t["id"] for t in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("duplicate task ID")
    inputs = []
    for task in tasks:
        ids = task["inputFiles"]
        if len(ids) != len(set(ids)) or not set(ids) <= known:
            raise ValueError("duplicate or unknown input file")
        inputs.append(frozenset(ids))
    used = sorted(set().union(*inputs)) if inputs else []
    index = {file_id: i for i, file_id in enumerate(used)}
    counts = Counter(i for required in inputs for i in required)
    arities = [len(required) for required in inputs]
    return {
        "name": document.get("name"), "schema_version": str(document["schemaVersion"]),
        "source_task_ids": task_ids, "source_sync_file_ids": used,
        "inputs": [sorted(index[i] for i in required) for required in inputs],
        "stats": {
            "raw_files": len(files), "sync_files": len(used), "tasks": len(tasks),
            "zero_input_tasks": sum(n == 0 for n in arities),
            "mean_inputs": sum(arities) / len(arities) if arities else 0,
            "max_inputs": max(arities, default=0),
            "multi_input_tasks": sum(n >= 2 for n in arities),
            "shared_sync_files": sum(n >= 2 for n in counts.values()),
            "input_arity_histogram": dict(sorted(Counter(arities).items())),
        },
    }


def load_structure(path):
    return parse_instance(json.loads(Path(path).read_text()))
