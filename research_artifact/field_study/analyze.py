"""Audit and replay recorded participant events; never fabricates field observations."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import sys

from model import canonical, check, digest, task_definitions, validate

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "engine"))
from bundle import Snapshot, Task, feasible, item_utility
from policies import bundle_fast


def versions_at(initial, publications, at):
    models = {key: {"version": obj["version"], "payload": obj["payload"].copy()} for key, obj in initial.items()}
    for event in publications:
        if event["elapsed"] > at:
            break
        models[event["file_id"]] = {"version": event["version"], "payload": event["payload"]}
    return models


def audit(folder):
    folder = Path(folder)
    metadata = json.loads((folder / "metadata.json").read_text())
    assert digest(metadata["protocol"]) == metadata["protocol_sha256"]
    if metadata["mode"] == "FORMAL":
        assert metadata["kit_lock"] is not None
        assert digest(json.loads((folder / "source_snapshot/protocol.json").read_text())) == metadata["protocol_sha256"]
        assert json.loads((folder / "source_snapshot/LOCK.json").read_text()) == metadata["kit_lock"]
        for name in ("model.py", "analyze.py", "engine/bundle.py", "engine/policies.py"):
            assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == metadata["kit_lock"]["sha256"][name]
    for name, expected in metadata["source_sha256"].items():
        assert hashlib.sha256((folder / "source_snapshot" / name).read_bytes()).hexdigest() == expected
    assert (folder / "source_snapshot/model.py").read_bytes() == (HERE / "model.py").read_bytes(), "Analyze with the matching model source"
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    assert events and events[0]["kind"] == "start"
    previous, elapsed = "0" * 64, -1
    source = {key: dict(value) for key, value in metadata["initial_models"].items()}
    for key, obj in source.items():
        assert obj["version"] == 1
        assert json.loads((folder / "versions" / (key + "_v1.json")).read_text()) == obj["payload"]
    gates = {}
    for seq, event in enumerate(events):
        payload = {key: value for key, value in event.items() if key != "hash"}
        assert event["seq"] == seq and event["prev_hash"] == previous and digest(payload) == event["hash"]
        assert event["elapsed"] >= elapsed and event["mode"] == metadata["mode"]
        previous, elapsed = event["hash"], event["elapsed"]
        if event["kind"] == "publish":
            key = event["file_id"]
            validate(key, event["payload"])
            assert event["role"] == key.split("_", 1)[1]
            assert event["version"] == source[key]["version"] + 1
            assert event["payload"] != source[key]["payload"]
            assert digest(event["payload"]) == event["payload_sha256"]
            assert len(canonical(event["payload"]) + b"\n") == event["payload_bytes"]
            saved = json.loads((folder / "versions" / (key + "_v" + str(event["version"]) + ".json")).read_text())
            assert saved == event["payload"]
            source[key] = {"version": event["version"], "payload": event["payload"]}
        elif event["kind"] == "gate":
            assert event["window"] == len(gates)
            assert event["imported_versions"] == {key: obj["version"] for key, obj in source.items()}
            assert event["imported_sha256"] == {key: digest(obj["payload"]) for key, obj in source.items()}
            assert event["imported_files"] == len(source)
            assert event["payload_bytes"] == sum(len(canonical(obj["payload"]) + b"\n") for obj in source.values())
            gates[event["window"]] = {"event": event, "cache": {key: dict(obj) for key, obj in source.items()}}
        elif event["kind"] == "check":
            gate = gates[event["window"]]
            assert len(event["tasks"]) == len(task_definitions())
            assert event["elapsed"] >= gate["event"]["elapsed"] + metadata["protocol"]["live_delay_seconds"]
            for task, saved in zip(task_definitions(), event["tasks"]):
                cache = gate["cache"]
                cv = {key: cache[key]["version"] for key in task["inputs"]}
                sv = {key: source[key]["version"] for key in task["inputs"]}
                cc = check(task, {key: obj["payload"] for key, obj in cache.items()})
                sc = check(task, {key: obj["payload"] for key, obj in source.items()})
                assert saved["task"] == task["id"] and saved["cached_versions"] == cv and saved["current_versions"] == sv
                assert saved["fresh"] == (cv == sv) and saved["cached_check"] == cc and saved["current_check"] == sc
                assert saved["predicate_verdict_agrees"] == (cc["pass"] == sc["pass"])
                assert saved["issue_set_agrees"] == (cc["issues"] == sc["issues"])
    if metadata["status"] in ("COMPLETE", "ABORTED"):
        assert events[-1]["kind"] == "end" and metadata["last_event_hash"] == previous
    if metadata["status"] == "COMPLETE":
        assert len(gates) == metadata["protocol"]["windows"]
        checks = [event for event in events if event["kind"] == "check"]
        assert [event["window"] for event in checks] == list(range(metadata["protocol"]["windows"]))
    return metadata, events


def replay(metadata, events, method, delay):
    initial = metadata["initial_models"]
    publications = [event for event in events if event["kind"] == "publish"]
    gates = [event for event in events if event["kind"] == "gate"]
    actual_checks = {event["window"]: event for event in events if event["kind"] == "check"}
    keys = sorted(initial); ids = {key: i for i, key in enumerate(keys)}
    definitions = task_definitions()
    cache = {key: dict(obj) for key, obj in initial.items()}
    rows = []
    for gate in gates:
        if gate["window"] not in actual_checks:
            continue
        boundary = gate["elapsed"]
        use = actual_checks[gate["window"]]["elapsed"] if delay == metadata["protocol"]["live_delay_seconds"] else boundary + delay
        source = versions_at(initial, publications, boundary)
        counts = Counter(event["file_id"] for event in publications if event["elapsed"] <= boundary)
        rates = tuple(counts[key] / boundary if boundary > 0 else 0 for key in keys)
        stale = frozenset(ids[key] for key in keys if cache[key]["version"] != source[key]["version"])
        snap = Snapshot(tuple(1 for _ in keys), rates, stale,
                        tuple(Task(frozenset(ids[key] for key in task["inputs"]), 1, use - boundary) for task in definitions),
                        metadata["protocol"]["offline_file_quota"])
        if method == "All":
            action = stale
        elif method == "Gq":
            action = bundle_fast(snap, True)
        elif method == "G0":
            action = bundle_fast(snap, False)
        elif method == "Iq":
            action = item_utility(snap, True)
        else:
            raise ValueError(method)
        assert action <= stale and (method == "All" or feasible(snap, action))
        for i in action:
            key = keys[i]; cache[key] = dict(source[key])
        current = versions_at(initial, publications, use)
        results = []
        for task in definitions:
            cached_result = check(task, {key: obj["payload"] for key, obj in cache.items()})
            current_result = check(task, {key: obj["payload"] for key, obj in current.items()})
            results.append({"task": task["id"], "fresh": all(cache[key]["version"] == current[key]["version"] for key in task["inputs"]),
                            "cached_check": cached_result, "current_check": current_result,
                            "predicate_verdict_agrees": cached_result["pass"] == current_result["pass"],
                            "issue_set_agrees": cached_result["issues"] == current_result["issues"],
                            "false_pass": cached_result["pass"] and not current_result["pass"],
                            "false_alarm": not cached_result["pass"] and current_result["pass"]})
        if method == "All" and delay == metadata["protocol"]["live_delay_seconds"]:
            live = actual_checks[gate["window"]]["tasks"]
            for saved, result in zip(live, results):
                assert all(saved[key] == result[key] for key in ("task", "fresh", "cached_check", "current_check", "predicate_verdict_agrees", "issue_set_agrees"))
        rows.append({"window": gate["window"], "boundary": boundary, "use": use,
                     "selected_files": [keys[i] for i in sorted(action)], "copied_file_quota_cost": len(action), "tasks": results})
    flat = [result for row in rows for result in row["tasks"]]
    return {"method": method, "delay_seconds": delay, "windows": rows,
            "summary": {"task_opportunities": len(flat), "fresh_percent": 100 * mean(v["fresh"] for v in flat) if flat else None,
                        "predicate_agreement_percent": 100 * mean(v["predicate_verdict_agrees"] for v in flat) if flat else None,
                        "issue_set_agreement_percent": 100 * mean(v["issue_set_agrees"] for v in flat) if flat else None,
                        "false_pass_count": sum(v["false_pass"] for v in flat), "false_alarm_count": sum(v["false_alarm"] for v in flat),
                        "stale_but_predicate_agrees_count": sum(not v["fresh"] and v["predicate_verdict_agrees"] for v in flat),
                        "copied_files_total": sum(row["copied_file_quota_cost"] for row in rows)}}


def analyze(folder):
    metadata, events = audit(folder)
    publications = [event for event in events if event["kind"] == "publish"]
    by_role = dict(Counter(event["role"] for event in publications))
    intervals = [b["elapsed"] - a["elapsed"] for a, b in zip(publications, publications[1:])]
    arms = [replay(metadata, events, method, delay) for method in ("All", "Gq", "G0", "Iq")
            for delay in metadata["protocol"]["offline_delays_seconds"]]
    long, short = (next(arm for arm in arms if arm["method"] == "All" and arm["delay_seconds"] == delay)
                   for delay in (metadata["protocol"]["live_delay_seconds"], min(metadata["protocol"]["offline_delays_seconds"])))
    result = {"status": "AUDIT_AND_REPLAY_PASS", "mode": metadata["mode"], "session_status": metadata["status"],
              "eligible_as_completed_controlled_case": metadata["mode"] == "FORMAL" and metadata["status"] == "COMPLETE",
              "participant_count_declared": metadata["participant_count"], "independent_teams": 1,
              "event_count": len(events), "publications": len(publications), "publications_by_role": by_role,
              "interpublication_median_seconds": median(intervals) if intervals else None,
              "live_import_bytes": sum(e["payload_bytes"] for e in events if e["kind"] == "gate"),
              "max_gate_lateness_seconds": max((e["elapsed"] - e["scheduled_elapsed"] for e in events if e["kind"] == "gate"), default=None),
              "max_check_lateness_seconds": max((e["elapsed"] - e["scheduled_elapsed"] for e in events if e["kind"] == "check"), default=None),
              "main_descriptive_timing_difference_pp": (short["summary"]["fresh_percent"] - long["summary"]["fresh_percent"])
                                                       if short["summary"]["fresh_percent"] is not None else None,
              "limits": ["One team's controlled numerical prototype; not industrial BIM or independent teams",
                         "Offline counterfactuals hold observed publication behavior fixed",
                         "Six-file quota is experimental, not measured network scarcity",
                         "Predicate agreement is limited to explicit numerical checks, not overall engineering correctness",
                         "No task/window-level statistical significance or population claims"],
              "checks": ["event_hash_chain", "immutable_payloads", "version_sequence", "role_ownership", "actual_import_manifest",
                         "actual_numerical_checks", "live_All_replay_agreement", "offline_budget_feasibility"], "arms": arms}
    (Path(folder) / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("session", type=Path)
    result = analyze(parser.parse_args().session)
    print(json.dumps({key: value for key, value in result.items() if key != "arms"}, indent=2))
    print("\nmethod delay fresh% predicate-agreement% false-pass false-alarm")
    for arm in result["arms"]:
        s = arm["summary"]
        print(arm["method"], arm["delay_seconds"], s["fresh_percent"], s["predicate_agreement_percent"], s["false_pass_count"], s["false_alarm_count"])
