"""Seal the human-data protocol and prepare a standalone, data-empty field kit."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "field_study"
files = [path for path in sorted(HERE.rglob("*")) if path.is_file()
         and "__pycache__" not in path.parts and "sessions" not in path.relative_to(HERE).parts
         and path.suffix != ".pyc" and path.name not in {"LOCK.json", ".DS_Store"}]
hashes = {path.relative_to(HERE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
seal_path = HERE / "LOCK.json"
if seal_path.exists():
    seal = json.loads(seal_path.read_text())
    assert seal["sha256"] == hashes, "Do not silently reseal changed source after collection; version the protocol explicitly"
else:
    seal = {"version": "controlled_collaboration_v1", "sealed_utc": datetime.now(timezone.utc).isoformat(),
            "status": "SEALED_BEFORE_ANY_PARTICIPANT_OBSERVATIONS", "sha256": hashes,
            "data": "No participant sessions included; software tests are FIXTURE only"}
    seal_path.write_text(json.dumps(seal, indent=2) + "\n")
files.append(seal_path)
archive = ROOT / "output/CSCWD2027_field_study_kit.zip"
archive.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for path in files:
        z.write(path, "cscwd_field_study/" + path.relative_to(HERE).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for path in files:
        assert z.read("cscwd_field_study/" + path.relative_to(HERE).as_posix()) == path.read_bytes()
print(json.dumps({"status": "SEALED_DATA_EMPTY_KIT_READY", "files": len(files), "zip": str(archive),
                  "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))
