"""Software fixtures, never participant data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyze import analyze, audit
from model import check, initial_models, task_definitions
from server import Study


class StudyTest(unittest.TestCase):
    def fixture(self, parent):
        clock = [1000.]
        with patch("server.time.monotonic", side_effect=lambda: clock[0]):
            c = json.loads((Path(__file__).parent / "protocol.json").read_text())
            c.update({"warmup_seconds": 0, "windows": 2})
            study = Study(Path(parent) / "FIXTURE", "FIXTURE", c)
            study.start(3, True); study.tick()
            clock[0] = 1010
            payload = study.source["A_architecture"]["payload"].copy(); payload["opening_width"] = 1.3
            study.publish("architecture", "A_architecture", 1, payload)
            clock[0] = 1045.1; study.tick()
            clock[0] = 1090; study.tick()
            clock[0] = 1100
            payload = study.source["A_mep"]["payload"].copy(); payload["duct_width"] = 1.8
            study.publish("mep", "A_mep", 1, payload)
            clock[0] = 1135.1; study.tick()
            clock[0] = 1180; study.tick()
        return study

    def test_real_copy_numeric_check_and_offline_replay_match(self):
        with tempfile.TemporaryDirectory() as d:
            study = self.fixture(d)
            result = analyze(study.output)
            self.assertEqual(study.state, "COMPLETE")
            self.assertFalse(result["eligible_as_completed_controlled_case"])
            first = study.checks[0]["tasks"][0]
            self.assertFalse(first["fresh"])
            self.assertTrue(first["predicate_verdict_agrees"])
            second = study.checks[1]["tasks"][0]
            self.assertTrue(second["cached_check"]["pass"])
            self.assertFalse(second["current_check"]["pass"])
            self.assertEqual(result["publications"], 2)
            metadata = json.loads((study.output / "metadata.json").read_text())
            self.assertEqual(metadata["initial_models"]["A_architecture"]["version"], 1)

    def test_hash_chain_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            study = self.fixture(d)
            path = study.output / "events.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[2]["payload"]["opening_width"] = 2.0
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with self.assertRaises(AssertionError):
                audit(study.output)

    def test_role_conflict_unchanged_and_no_midwindow_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            study = Study(Path(d) / "FIXTURE", "FIXTURE")
            study.start(2, True)
            old = copy.deepcopy(study.cache)
            value = study.source["A_mep"]["payload"].copy(); value["duct_width"] = 1.1
            with self.assertRaises(ValueError):
                study.publish("architecture", "A_mep", 1, value)
            study.publish("mep", "A_mep", 1, value)
            with self.assertRaises(ValueError):
                study.publish("mep", "A_mep", 1, value)
            with self.assertRaises(ValueError):
                study.publish("mep", "A_mep", 2, value)
            self.assertEqual(study.cache, old)
            study.finish("ABORTED", "fixture cleanup")

    def test_actual_cross_file_numerical_constraints(self):
        models = initial_models(); task = task_definitions()[0]
        self.assertTrue(check(task, models)["pass"])
        models["A_structure"]["beam_bottom"] = 2.7
        self.assertIn("beam_clearance", check(task, models)["issues"])
        models["A_mep"]["duct_center"] = .5
        self.assertIn("outside_opening", check(task, models)["issues"])


if __name__ == "__main__":
    unittest.main()
