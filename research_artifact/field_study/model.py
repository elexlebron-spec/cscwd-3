"""Small numerical coordination model. Not BIM/CAD software or a code check."""
import hashlib
import json

ZONES = ("A", "B", "C", "D")
ROLES = ("architecture", "structure", "mep")
FIELDS = {"architecture": {"opening_center": (-2, 2), "opening_width": (.2, 3), "ceiling": (2, 5)},
          "structure": {"beam_bottom": (1.8, 5)},
          "mep": {"duct_center": (-2, 2), "duct_width": (.1, 2), "duct_top": (1.5, 4.8)}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def initial_models():
    result = {}
    for zone in ZONES:
        result[zone + "_architecture"] = {"opening_center": 0., "opening_width": 1.2, "ceiling": 3.3}
        result[zone + "_structure"] = {"beam_bottom": 3.1}
        result[zone + "_mep"] = {"duct_center": 0., "duct_width": .8, "duct_top": 2.9}
    return result


def validate(file_id, payload):
    if file_id not in initial_models():
        raise ValueError("unknown model")
    role = file_id.split("_", 1)[1]
    if not isinstance(payload, dict) or set(payload) != set(FIELDS[role]):
        raise ValueError("unexpected model fields")
    for key, value in payload.items():
        lo, hi = FIELDS[role][key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ValueError("invalid value for " + key)


def task_definitions():
    tasks = [{"id": "clearance_" + zone, "kind": "clearance", "zones": [zone],
              "inputs": [zone + "_" + role for role in ROLES]} for zone in ZONES]
    for a, b in zip(ZONES, ZONES[1:]):
        tasks.append({"id": "connection_" + a + b, "kind": "connection", "zones": [a, b],
                      "inputs": [a + "_mep", b + "_mep", a + "_architecture", b + "_architecture"]})
    return tasks


def check(task, models):
    """Explicit metre-based predicates; current versions are not semantic truth."""
    issues = []
    if task["kind"] == "clearance":
        z = task["zones"][0]
        a, s, m = (models[z + "_" + role] for role in ROLES)
        if abs(m["duct_center"] - a["opening_center"]) + m["duct_width"] / 2 > a["opening_width"] / 2 + 1e-9:
            issues.append("outside_opening")
        if m["duct_top"] > a["ceiling"] + 1e-9:
            issues.append("above_ceiling")
        if m["duct_top"] > s["beam_bottom"] + 1e-9:
            issues.append("beam_clearance")
    else:
        a, b = task["zones"]
        ma, mb = models[a + "_mep"], models[b + "_mep"]
        if abs(ma["duct_center"] - mb["duct_center"]) > .15 + 1e-9:
            issues.append("connection_offset")
        for z in (a, b):
            arch, mep = models[z + "_architecture"], models[z + "_mep"]
            if abs(mep["duct_center"] - arch["opening_center"]) + mep["duct_width"] / 2 > arch["opening_width"] / 2 + 1e-9:
                issues.append("opening_" + z)
    return {"pass": not issues, "issues": issues}
