import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from contracts import ContractError, validate_catalog, validate_plan, validate_review, validate_revision
from planner import build_plan, revise_plan

ROOT = Path(__file__).resolve().parents[1]
class ContractsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT/"examples/catalog.json").read_text())
        self.plan = json.loads((ROOT/"examples/plan.json").read_text())
        self.review = json.loads((ROOT/"examples/review.json").read_text())

    def test_examples_and_schema_keys_match(self):
        validate_plan(self.plan, self.catalog)
        validate_review(self.review, self.plan)
        for name, sample in (("catalog",self.catalog),("plan",self.plan),("review",self.review)):
            schema=json.loads((ROOT/f"schemas/{name}.schema.json").read_text())
            self.assertEqual(set(schema["required"]),set(sample))

    def test_boolean_and_nan_time(self):
        for bad in (True, float("nan"), float("inf")):
            c=deepcopy(self.catalog);c["segments"][0]["start"]=bad
            with self.assertRaises(ContractError):validate_catalog(c)

    def test_duplicate_and_unhashable_ids(self):
        for bad in ([], self.plan["scenes"][1]["segment_id"]):
            p=deepcopy(self.plan);p["scenes"][0]["segment_id"]=bad
            with self.assertRaises(ContractError):validate_plan(p,self.catalog)
        review=deepcopy(self.review);review["items"][0]["scene_id"]=[]
        with self.assertRaises(ContractError):validate_review(review,self.plan)

    def test_reject_unknown_fields(self):
        p=deepcopy(self.plan);p["secret"]=1
        with self.assertRaises(ContractError):validate_plan(p,self.catalog)

    def test_duplicate_missing_review(self):
        for items in (self.review["items"][:-1], [self.review["items"][0]]*3):
            with self.assertRaises(ContractError):validate_review({"schema_version":"1.0","items":items}, self.plan)

    def test_accepted_scene_preserved(self):
        p=deepcopy(self.plan);p["scenes"][0]["caption"]="Изменено"
        with self.assertRaises(ContractError):validate_revision(self.plan,p,self.review,self.catalog)

    def test_changed_scene_id_rejected(self):
        p=deepcopy(self.plan);p["scenes"][1]["scene_id"]="new"
        with self.assertRaises(ContractError):validate_revision(self.plan,p,self.review,self.catalog)

    def test_no_api_call_for_accept_or_escalation(self):
        accepted=deepcopy(self.review)
        for item in accepted["items"]:item.update(decision="accept",issue="",evidence="",requested_change="")
        with patch("planner.chat_json") as api:
            self.assertEqual(revise_plan("task",self.catalog,self.plan,accepted),self.plan)
            api.assert_not_called()
        manual=deepcopy(self.review);manual["items"][1]["decision"]="needs_human_review"
        with patch("planner.chat_json") as api:
            with self.assertRaises(ContractError):revise_plan("task",self.catalog,self.plan,manual)
            api.assert_not_called()

    def test_empty_task_before_api(self):
        with patch("planner.chat_json") as api:
            with self.assertRaises(ContractError):build_plan(" ",self.catalog)
            api.assert_not_called()
