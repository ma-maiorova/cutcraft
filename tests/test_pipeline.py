import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from contracts import ContractError, validate_catalog, validate_plan, validate_review
from planner import build_plan
from main import run, ROOT

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "data/catalog.json").read_text())
        self.plan = build_plan("test", self.catalog, demo=True)

    def test_demo_repairs_and_renders(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "run"
            self.assertEqual(run("<test>", ROOT / "data/catalog.json", out, True), "demo_accepted")
            history = json.loads((out / "history.json").read_text())
            self.assertEqual(len(history), 2)
            self.assertNotEqual(history[0]["plan"]["scenes"][1]["caption"], history[1]["plan"]["scenes"][1]["caption"])
            self.assertEqual(history[0]["plan"]["scenes"][0], history[1]["plan"]["scenes"][0])
            self.assertIn("&lt;test&gt;", (out / "report.html").read_text())

    def test_bad_bounds_and_unknown_segment(self):
        for key, value in (("source_end", 999), ("segment_id", "missing")):
            p = deepcopy(self.plan)
            p["scenes"][0][key] = value
            with self.assertRaises(ContractError):
                validate_plan(p, self.catalog)

    def test_incomplete_review_rejected(self):
        with self.assertRaises(ContractError):
            validate_review({"schema_version": "1.0", "items": []}, self.plan)

    def test_retry_limit(self):
        def reject(task, catalog, plan, frames, **kwargs):
            return {"schema_version": "1.0", "items": [{"scene_id": s["scene_id"], "decision": "revise_caption", "issue": "test", "evidence": "test", "requested_change": "test"} for s in plan["scenes"]]}
        with tempfile.TemporaryDirectory() as d, patch("main.review_plan", side_effect=reject) as mock:
            self.assertEqual(run("test", ROOT / "data/catalog.json", Path(d)/"run", True), "needs_human_review")
            self.assertEqual(mock.call_count, 2)

    def test_live_not_silently_demo(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)/"run"
            with self.assertRaises(NotImplementedError):
                run("test", ROOT / "data/catalog.json", out, False)
            self.assertEqual(json.loads((out/"status.json").read_text())["status"], "failed")

    def test_quote_and_duration(self):
        p = deepcopy(self.plan)
        p["scenes"][0]["source_quote"] = "выдуманная цитата"
        with self.assertRaises(ContractError):
            validate_plan(p, self.catalog)
        p = deepcopy(self.plan)
        for scene in p["scenes"]:
            scene["source_end"] = scene["source_start"] + 1
        with self.assertRaises(ContractError):
            validate_plan(p, self.catalog)

if __name__ == "__main__":
    unittest.main()
