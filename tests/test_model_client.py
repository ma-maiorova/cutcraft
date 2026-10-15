import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from model_client import ModelError, check_free_model, load_environment, settings, chat_json
from planner import build_plan, revise_plan
import json

class ModelClientTests(unittest.TestCase):
    def test_paid_or_unknown_model_rejected(self):
        paid = {"id": "test:free", "pricing": {"prompt": "1", "completion": "0"}}
        with self.assertRaises(ModelError):
            check_free_model([paid], "test:free")
        with self.assertRaises(ModelError):
            check_free_model([], "test:free")

    def test_vision_required(self):
        model = {"id": "test:free", "pricing": {"prompt": "0", "completion": "0"}}
        with self.assertRaises(ModelError):
            check_free_model([model], "test:free", vision=True)

    def test_dotenv_does_not_override_shell(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"TEXT_MODEL_NAME": "shell:free"}, clear=True):
            p = Path(d)/".env"
            p.write_text("TEXT_MODEL_NAME=file:free\nOPENROUTER_API_KEY=example\n")
            load_environment(p)
            self.assertEqual(os.environ["TEXT_MODEL_NAME"], "shell:free")
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "example")

    def test_non_official_endpoint_rejected_before_network(self):
        with patch("model_client.load_environment"), patch.dict(os.environ, {"OPENROUTER_BASE_URL":"https://example.com"}, clear=True):
            with self.assertRaises(ModelError):
                settings("TEXT_MODEL_NAME")

    def test_live_planner_validates_model_result(self):
        root = Path(__file__).resolve().parents[1]
        c = json.loads((root/"data/catalog.json").read_text())
        result = build_plan("test", c, demo=True)
        result["scenes"][0]["segment_id"] = "not-real"
        with patch("planner.chat_json", return_value=result):
            with self.assertRaises(ValueError):
                build_plan("test", c)

    def test_strict_schema_sent_when_supported(self):
        model = {"id":"test:free","pricing":{"prompt":"0","completion":"0"},"supported_parameters":["structured_outputs"]}
        with patch("model_client.settings", return_value=("example","test:free",10)), patch("model_client.request_json", side_effect=[{"data":[model]}, {"choices":[{"finish_reason":"stop","message":{"content":'{"schema_version":"1.0"}'}}]}]) as request:
            schema={"type":"object","properties":{},"additionalProperties":False}
            self.assertEqual(chat_json("system", {}, schema=schema)["schema_version"], "1.0")
            body=request.call_args.args[3]
            self.assertEqual(body["response_format"]["type"],"json_schema")
            self.assertTrue(body["response_format"]["json_schema"]["strict"])
            self.assertNotIn("models",body)  # Нет списка fallback-моделей.

    def test_no_completion_for_nonfree_metadata(self):
        with patch("model_client.settings", return_value=("example", "test:free", 10)), patch("model_client.request_json", return_value={"data":[]}) as request:
            with self.assertRaises(ModelError):
                chat_json("system", {})
            self.assertEqual(request.call_count, 1)
