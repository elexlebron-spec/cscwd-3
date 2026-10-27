"""Package actual sessions for return, excluding transient role-access tokens."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from analyze import analyze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sessions", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("CSCWD_field_return.zip"))
    args = parser.parse_args()
    entries, summaries = [], []
    for index, folder in enumerate(args.sessions, 1):
        result = analyze(folder)
        summaries.append({"session": index, "mode": result["mode"], "status": result["session_status"],
                          "eligible": result["eligible_as_completed_controlled_case"], "publications": result["publications"]})
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.name == "access_links.txt" or path.suffix in {".pyc", ".zip"} or "__pycache__" in path.parts:
                continue
            if path.name in {"metadata.json", "events.jsonl", "analysis.json", "session_notes.json"} or path.relative_to(folder).parts[0] in {"versions", "source_snapshot"}:
                entries.append((path, "session_" + str(index) + "/" + path.relative_to(folder).as_posix()))
    manifest = {name: hashlib.sha256(path.read_bytes()).hexdigest() for path, name in entries}
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in entries:
            archive.write(path, name)
        archive.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
        archive.writestr("SESSION_INDEX.json", json.dumps(summaries, indent=2))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
    print(json.dumps({"package": str(args.output.resolve()), "sessions": summaries,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "notice": "A private handoff for review; do not publish participant observations automatically"}, indent=2))


if __name__ == "__main__":
    main()
