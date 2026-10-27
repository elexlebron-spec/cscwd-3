"""Local/LAN human-operated experiment recorder. Python standard library only."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import signal
import threading
import time
from urllib.parse import parse_qs, urlparse

from model import ROLES, canonical, check, digest, initial_models, task_definitions, validate

HERE = Path(__file__).resolve().parent


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(data) + b"\n")
    temporary.replace(path)


class Study:
    def __init__(self, output, mode, protocol=None):
        self.output = Path(output)
        kit_lock = json.loads((HERE / "LOCK.json").read_text()) if (HERE / "LOCK.json").exists() else None
        if mode == "FORMAL":
            if kit_lock is None:
                raise ValueError("Formal sessions require the sealed distribution LOCK.json")
            for name, expected in kit_lock["sha256"].items():
                if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
                    raise ValueError("Kit source changed after sealing: " + name)
        self.output.mkdir(parents=True, exist_ok=False)
        self.protocol = json.loads((HERE / "protocol.json").read_text()) if protocol is None else protocol
        self.mode = mode
        self.tokens = {role: secrets.token_urlsafe(20) for role in (*ROLES, "coordinator")}
        self.lock = threading.RLock()
        self.source = {key: {"version": 1, "payload": value} for key, value in initial_models().items()}
        self.cache = {key: {"version": 1, "payload": value.copy()} for key, value in initial_models().items()}
        self.origin = None
        self.seq = 0
        self.last_hash = "0" * 64
        self.gates = []
        self.checks = []
        self.pending = []
        self.publications = 0
        self.state = "READY"
        self.alive = True
        for folder in ("versions", "published", "review_cache", "source_snapshot"):
            (self.output / folder).mkdir()
        for key, obj in self.source.items():
            self.store_version(key, obj)
        for path in (HERE / "server.py", HERE / "model.py", HERE / "protocol.json", HERE / "web/index.html"):
            shutil.copy2(path, self.output / "source_snapshot" / path.name)
        if kit_lock is not None:
            shutil.copy2(HERE / "LOCK.json", self.output / "source_snapshot/LOCK.json")
        self.metadata = {"created_utc": utc(), "mode": mode, "status": self.state,
                         "protocol": self.protocol, "protocol_sha256": digest(self.protocol),
                         "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                           for path in (HERE / "server.py", HERE / "model.py", HERE / "web/index.html")},
                         "initial_models": copy.deepcopy(self.source), "participant_count": None,
                         "kit_lock": kit_lock,
                         "evidence": "No participant observations until human-operated FORMAL session is completed"}
        atomic(self.output / "metadata.json", self.metadata)

    def elapsed(self):
        return 0.0 if self.origin is None else time.monotonic() - self.origin

    def emit(self, kind, **data):
        row = {"seq": self.seq, "elapsed": self.elapsed(), "utc": utc(), "kind": kind,
               "mode": self.mode, "prev_hash": self.last_hash, **data}
        row["hash"] = digest(row)
        with (self.output / "events.jsonl").open("ab") as log:
            log.write(canonical(row) + b"\n"); log.flush()
        self.seq += 1
        self.last_hash = row["hash"]
        return row

    def store_version(self, key, obj):
        path = self.output / "versions" / (key + "_v" + str(obj["version"]) + ".json")
        if path.exists():
            raise ValueError("immutable version already exists")
        path.write_bytes(canonical(obj["payload"]) + b"\n")
        atomic(self.output / "published" / (key + ".json"), obj["payload"])

    def start(self, participant_count, confirmed):
        with self.lock:
            if self.state != "READY" or participant_count not in (2, 3) or confirmed is not True:
                raise ValueError("Start requires 2 or 3 voluntary participants and a new ready session")
            self.origin = time.monotonic()
            self.state = "RUNNING"
            self.metadata.update({"status": self.state, "participant_count": participant_count,
                                  "started_utc": utc(), "voluntary_participation_confirmed_by_coordinator": True})
            atomic(self.output / "metadata.json", self.metadata)
            self.emit("start", participant_count=participant_count)

    def publish(self, role, key, expected_version, payload):
        with self.lock:
            if self.state != "RUNNING":
                raise ValueError("Session must be running")
            validate(key, payload)
            if key.split("_", 1)[1] != role:
                raise ValueError("Role cannot publish this file")
            if expected_version != self.source[key]["version"]:
                raise ValueError("Version conflict: reload before publishing")
            if payload == self.source[key]["payload"]:
                raise ValueError("Unchanged payload: no release recorded")
            obj = {"version": expected_version + 1, "payload": payload}
            self.store_version(key, obj)
            self.source[key] = obj
            self.publications += 1
            return self.emit("publish", role=role, file_id=key, version=obj["version"], payload=payload,
                             payload_sha256=digest(payload), payload_bytes=len(canonical(payload) + b"\n"))

    def gate(self, window, scheduled):
        started = self.elapsed()
        for key, obj in self.source.items():
            stored = self.output / "versions" / (key + "_v" + str(obj["version"]) + ".json")
            copied = self.output / "review_cache" / (key + ".json")
            shutil.copyfile(stored, copied)
            copied_payload = json.loads(copied.read_text())
            assert digest(copied_payload) == digest(obj["payload"])
            self.cache[key] = {"version": obj["version"], "payload": copied_payload}
        row = self.emit("gate", window=window, scheduled_elapsed=scheduled, import_started_elapsed=started,
                        imported_versions={key: obj["version"] for key, obj in self.cache.items()},
                        imported_sha256={key: digest(obj["payload"]) for key, obj in self.cache.items()},
                        payload_bytes=sum(len(canonical(obj["payload"]) + b"\n") for obj in self.cache.values()),
                        imported_files=len(self.cache), policy="all_actual_file_copies")
        self.gates.append(row)
        self.pending.append((row["elapsed"] + self.protocol["live_delay_seconds"], window))

    def perform_checks(self, window, scheduled):
        started = self.elapsed()
        cached_payloads = {key: obj["payload"] for key, obj in self.cache.items()}
        current_payloads = {key: obj["payload"] for key, obj in self.source.items()}
        result = []
        for task in task_definitions():
            cached = check(task, cached_payloads)
            current = check(task, current_payloads)
            versions = {key: self.cache[key]["version"] for key in task["inputs"]}
            latest = {key: self.source[key]["version"] for key in task["inputs"]}
            result.append({"task": task["id"], "cached_versions": versions, "current_versions": latest,
                           "fresh": versions == latest, "cached_check": cached, "current_check": current,
                           "predicate_verdict_agrees": cached["pass"] == current["pass"],
                           "issue_set_agrees": cached["issues"] == current["issues"]})
        row = self.emit("check", window=window, scheduled_elapsed=scheduled, check_started_elapsed=started,
                        computation_seconds=self.elapsed() - started, tasks=result)
        self.checks.append(row)

    def tick(self):
        with self.lock:
            if self.state != "RUNNING":
                return
            elapsed = self.elapsed()
            # Process overdue checks before the next import to retain that gate's cache.
            for due, window in list(self.pending):
                if elapsed >= due:
                    self.perform_checks(window, due)
                    self.pending.remove((due, window))
            if len(self.gates) < self.protocol["windows"] and not self.pending:
                scheduled = self.protocol["warmup_seconds"] + len(self.gates) * self.protocol["period_seconds"]
                if elapsed >= scheduled:
                    self.gate(len(self.gates), scheduled)
            end = self.protocol["warmup_seconds"] + self.protocol["windows"] * self.protocol["period_seconds"]
            if elapsed >= end and not self.pending and len(self.checks) == self.protocol["windows"]:
                self.finish("COMPLETE", "planned duration completed")

    def finish(self, status, reason):
        with self.lock:
            if self.state in ("COMPLETE", "ABORTED"):
                return
            self.emit("end", status=status, reason=reason)
            self.state = status
            self.metadata.update({"status": status, "ended_utc": utc(), "reason": reason,
                                  "publications": self.publications, "gates": len(self.gates),
                                  "checks": len(self.checks), "last_event_hash": self.last_hash})
            atomic(self.output / "metadata.json", self.metadata)

    def public_state(self, role):
        with self.lock:
            result = {"status": self.state, "mode": self.mode, "role": role, "elapsed": self.elapsed(),
                      "models": self.source, "protocol": self.protocol, "publications": self.publications,
                      "gates": len(self.gates), "checks": len(self.checks), "fields": __import__("model").FIELDS,
                      "next_gate": self.protocol["warmup_seconds"] + len(self.gates) * self.protocol["period_seconds"]
                                   if len(self.gates) < self.protocol["windows"] else None}
            if role == "coordinator":
                result["last_checks"] = self.checks[-1]["tasks"] if self.checks else []
            return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8867, type=int)
    parser.add_argument("--mode", choices=["PRACTICE", "FORMAL", "FIXTURE"], default="PRACTICE")
    parser.add_argument("--output", default="sessions/" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()
    study = Study(Path(args.output).resolve(), args.mode)

    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status, obj):
            data = canonical(obj)
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)

        def role(self):
            query = parse_qs(urlparse(self.path).query)
            token = query.get("token", [""])[0]
            return next((role for role, expected in study.tokens.items() if secrets.compare_digest(token, expected)), None)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                data = (HERE / "web/index.html").read_bytes()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            elif path == "/health":
                self.send_json(200, {"status": study.state, "mode": study.mode})
            elif path == "/api/state" and self.role():
                self.send_json(200, study.public_state(self.role()))
            else:
                self.send_json(403, {"error": "Use a role link printed in the host terminal"})

        def do_POST(self):
            try:
                role = self.role()
                if role is None:
                    raise ValueError("Use an authorized role link")
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16384:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                path = urlparse(self.path).path
                if path == "/api/publish":
                    row = study.publish(role, data["file_id"], data["expected_version"], data["payload"])
                    self.send_json(200, {"version": row["version"], "seq": row["seq"]})
                elif role == "coordinator" and path == "/api/start":
                    study.start(data["participant_count"], data["confirmed"])
                    self.send_json(200, {"status": study.state})
                elif role == "coordinator" and path == "/api/card":
                    if study.state != "RUNNING" or data["card"] not in (1, 2, 3):
                        raise ValueError("Card release requires a running session and card 1,2,3")
                    with study.lock:
                        study.emit("request_card", card=data["card"])
                    self.send_json(200, {"recorded": data["card"]})
                elif role == "coordinator" and path == "/api/stop":
                    study.finish("ABORTED", "coordinator stopped early")
                    self.send_json(200, {"status": study.state})
                else:
                    raise ValueError("Operation not allowed for role")
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})

        def log_message(self, *args):
            # Role tokens in URL query strings must not enter access logs.
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)

    def timer():
        while study.alive:
            try:
                study.tick()
            except Exception as error:
                study.finish("ABORTED", "recorder error: " + type(error).__name__)
                print("RECORDER ERROR", repr(error), flush=True)
                return
            time.sleep(.2)

    links = []
    for role, token in study.tokens.items():
        links.append(role + ": http://127.0.0.1:" + str(args.port) + "/?token=" + token)
    (study.output / "access_links.txt").write_text("\n".join(links) + "\n")
    print("\n".join(links), flush=True)
    print("Mode:", args.mode, "Output:", study.output, flush=True)
    if args.host == "0.0.0.0":
        print("For other devices on the same trusted LAN, replace 127.0.0.1 with this Mac's LAN IP. No cloud service is used.", flush=True)
    threading.Thread(target=timer, daemon=True).start()
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        study.alive = False
        if study.state in ("READY", "RUNNING"):
            study.finish("ABORTED", "host process stopped before completion")
        server.server_close()


if __name__ == "__main__":
    main()
