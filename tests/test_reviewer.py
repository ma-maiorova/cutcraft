import base64
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from contracts import ContractError, validate_catalog, validate_plan
from main import resolve_frames
from model_client import ModelError
from reviewer import load_scene_images, review_payload, review_plan, review_schema
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_reviewer_live import score

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "docs/evidence/reviewer/cases"
VISION = {"id": "vision:free", "pricing": {"prompt": "0", "completion": "0"},
          "architecture": {"input_modalities": ["text", "image"]}, "supported_parameters": ["response_format"]}


def load(name):
    return json.loads((CASES / name).read_text(encoding="utf-8"))


def accept_all(plan):
    return {"schema_version": "1.0", "items": [
        {"scene_id": s["scene_id"], "decision": "accept", "issue": "", "evidence": "", "requested_change": ""}
        for s in reversed(plan["scenes"])]}


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.catalog = validate_catalog(load("catalog.json"))
        self.plan = validate_plan(load("plan_correct.json"), self.catalog)
        self.frames = resolve_frames(self.catalog, CASES)

    def fake_api(self, review):
        completion = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(review, ensure_ascii=False)}}]}
        return patch("model_client.request_json", side_effect=[{"data": [VISION]}, completion])

    def test_real_png_bytes_sent_to_vision_model(self):
        with patch("model_client.settings", return_value=("example", "vision:free", 10)), self.fake_api(accept_all(self.plan)) as api:
            review = review_plan("task", self.catalog, self.plan, self.frames)
        body = api.call_args.args[3]
        parts = body["messages"][1]["content"]
        urls = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
        self.assertEqual(len(urls), 3)
        first = self.frames[self.catalog["segments"][1]["frame_paths"][0]]  # scene_1 -> s2
        self.assertEqual(urls[0], "data:image/png;base64," + base64.b64encode(first.read_bytes()).decode())
        self.assertIn("scene_1", [p["text"] for p in parts if p["type"] == "text"][1])
        self.assertEqual([i["scene_id"] for i in review["items"]], ["scene_1", "scene_2", "scene_3"])
        self.assertGreaterEqual(body["max_tokens"], 8000)
        self.assertLess(body["reasoning"]["max_tokens"], body["max_tokens"])  # На сам ответ остаются токены.

    def test_svg_placeholders_rejected_before_api(self):
        catalog = json.loads((ROOT / "examples/catalog.json").read_text())
        plan = json.loads((ROOT / "examples/plan.json").read_text())
        with patch("reviewer.chat_json") as api:
            with self.assertRaises(ContractError):
                review_plan("task", catalog, plan, resolve_frames(catalog, ROOT / "examples"))
            api.assert_not_called()

    def test_fake_png_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "s2.png"
            fake.write_text("not an image")
            frames = dict(self.frames, **{"frames/s2.png": fake})
            with self.assertRaises(ContractError):
                load_scene_images(self.catalog, self.plan, frames)

    def test_text_only_model_rejected(self):
        text_only = deepcopy(VISION)
        text_only["architecture"]["input_modalities"] = ["text"]
        with patch("model_client.settings", return_value=("example", "vision:free", 10)), \
             patch("model_client.request_json", return_value={"data": [text_only]}) as api:
            with self.assertRaises(ModelError):
                review_plan("task", self.catalog, self.plan, self.frames)
            self.assertEqual(api.call_count, 1)  # До запроса completion не дошло.

    def test_incomplete_or_empty_remark_rejected(self):
        partial = accept_all(self.plan)
        partial["items"].pop()
        empty = accept_all(self.plan)
        empty["items"][0]["decision"] = "revise_caption"
        for bad in (partial, empty):
            with patch("model_client.settings", return_value=("example", "vision:free", 10)), self.fake_api(bad):
                with self.assertRaises(ContractError):
                    review_plan("task", self.catalog, self.plan, self.frames)

    def test_unchanged_accepted_scenes_not_reviewed_again(self):
        before = validate_plan(load("plan_lost_caveat.json"), self.catalog)
        first = accept_all(before)
        first["items"][2].update(decision="revise_caption", issue="i", evidence="e", requested_change="c")  # scene_1
        after = deepcopy(before)
        after["scenes"][0]["caption"] = after["scenes"][0]["source_quote"]
        answer = {"schema_version": "1.0", "items": [
            {"scene_id": "scene_1", "decision": "accept", "issue": "", "evidence": "", "requested_change": ""}]}
        with patch("model_client.settings", return_value=("example", "vision:free", 10)), self.fake_api(answer) as api:
            review = review_plan("task", self.catalog, after, self.frames, previous={"plan": before, "review": first})
        body = api.call_args.args[3]
        parts = body["messages"][1]["content"]
        self.assertEqual(sum(p["type"] == "image_url" for p in parts), 1)  # Кадр только изменённой сцены.
        payload = json.loads(parts[0]["text"])
        self.assertEqual([s["scene_id"] for s in payload["scenes"]], ["scene_1"])
        self.assertEqual([s["scene_id"] for s in payload["accepted_scenes"]], ["scene_2", "scene_3"])
        self.assertEqual([i["decision"] for i in review["items"]], ["accept"] * 3)

    def test_all_carried_means_no_api_call(self):
        with patch("reviewer.chat_json") as api:
            review = review_plan("task", self.catalog, self.plan, self.frames,
                                 previous={"plan": self.plan, "review": accept_all(self.plan)})
            api.assert_not_called()
        self.assertEqual(len(review["items"]), 3)

    def test_changed_scene_is_reviewed_even_if_accepted_before(self):
        changed = deepcopy(self.plan)
        changed["scenes"][1]["caption"] = "Другая подпись."
        answer = {"schema_version": "1.0", "items": [
            {"scene_id": "scene_2", "decision": "revise_caption", "issue": "i", "evidence": "e", "requested_change": "c"}]}
        with patch("model_client.settings", return_value=("example", "vision:free", 10)), self.fake_api(answer):
            review = review_plan("task", self.catalog, changed, self.frames,
                                 previous={"plan": self.plan, "review": accept_all(self.plan)})
        self.assertEqual([i["decision"] for i in review["items"]], ["accept", "revise_caption", "accept"])

    def test_main_passes_previous_round_to_reviewer(self):
        from main import run
        calls = []
        def fake(task, catalog, plan, frames, **kwargs):
            calls.append(kwargs.get("previous"))
            return review_plan(task, catalog, plan, frames, demo=True)
        with tempfile.TemporaryDirectory() as d, patch("main.review_plan", side_effect=fake):
            run("task", ROOT / "data/catalog.json", Path(d) / "run", True)
        self.assertIsNone(calls[0])
        self.assertEqual(set(calls[1]), {"plan", "review"})

    def test_planner_reasoning_hidden_from_reviewer(self):
        catalog, plan = load("catalog.json"), load("plan_correct.json")
        payload = review_payload("Объясни результат и ограничения", catalog, plan)
        self.assertTrue(all("selection_reason" not in scene for scene in payload["scenes"]))
        self.assertTrue(all("caption" in scene and "source_quote" in scene for scene in payload["scenes"]))
        carried = review_payload("Объясни результат и ограничения", catalog, plan, {plan["scenes"][0]["scene_id"]})
        self.assertTrue(all("selection_reason" not in scene for scene in carried["accepted_scenes"]))

    def test_schema_matches_contract_without_conditionals(self):
        schema = review_schema()
        self.assertNotIn("allOf", json.dumps(schema))
        self.assertEqual(schema["required"], ["schema_version", "items"])

    def test_demo_still_marks_known_defect(self):
        catalog = json.loads((ROOT / "examples/catalog.json").read_text())
        plan = json.loads((ROOT / "examples/plan.json").read_text())
        review = review_plan("task", catalog, plan, {}, demo=True)
        self.assertEqual([i["decision"] for i in review["items"]], ["accept", "revise_caption", "accept"])

    def test_control_cases_valid_and_scoring(self):
        spec = load("cases.json")
        for case in spec["cases"]:
            catalog = validate_catalog(load(case["catalog"]))
            validate_plan(load(case["plan"]), catalog)
            resolve_frames(catalog, CASES)
        lost = next(c for c in spec["cases"] if c["name"] == "lost_caveat")
        missed = score(accept_all(self.plan), lost["expected"])
        self.assertEqual(missed["misses"], ["scene_1"])
        self.assertFalse(missed["passed"])
        self.assertTrue(score(accept_all(self.plan), spec["cases"][0]["expected"])["passed"])


if __name__ == "__main__":
    unittest.main()
