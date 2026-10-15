import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from main import run, ROOT
from model_client import ModelError
from render import render_report

CATALOG = ROOT / "data/catalog.json"


def accept_all(task, catalog, plan, frames, **kwargs):
    return {"schema_version": "1.0", "items": [{"scene_id": s["scene_id"], "decision": "accept", "issue": "", "evidence": "", "requested_change": ""}
                                               for s in plan["scenes"]]}


def events(out):
    return [(e["stage"], e["iteration"], e["state"]) for e in json.loads((out / "events.json").read_text())["events"]]


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "run"

    def tearDown(self):
        self.tmp.cleanup()

    def html(self, out=None):
        return ((out or self.out) / "report.html").read_text(encoding="utf-8")

    def test_demo_revision_shows_both_versions(self):
        run("Объясни", CATALOG, self.out, True)
        self.assertEqual(events(self.out), [("input", None, "done"), ("plan", 0, "done"), ("plan_check", 0, "done"), ("review", 0, "done"),
                                            ("revise", 1, "done"), ("revision_check", 1, "done"), ("review", 1, "done"), ("finish", None, "done")])
        page = self.html()
        for text in ("review_0.json", "review_1.json", "plan_1.json", "Было → стало", "Утеряна оговорка о симуляции",
                     "Метод доказал эффективность", "без изменений", "ДЕМО"):
            self.assertIn(text, page)
        self.assertNotIn("(LLM", page)  # в демо модели не вызываются, шаги не подписаны как LLM

    def test_accepted_first_time_skips_revision(self):
        with patch("main.review_plan", side_effect=accept_all):
            self.assertEqual(run("Объясни", CATALOG, self.out, True), "demo_accepted")
        self.assertFalse((self.out / "plan_1.json").exists())
        self.assertEqual([e for e in events(self.out) if e[1] == 1], [("revise", 1, "skipped"), ("revision_check", 1, "skipped"), ("review", 1, "skipped")])
        page = self.html()
        self.assertIn("пропущено", page)
        self.assertNotIn("Было → стало", page)

    def test_diff_matches_scene_id_not_position(self):
        run("Объясни", CATALOG, self.out, True)
        plan = json.loads((self.out / "plan_1.json").read_text())
        plan["scenes"].reverse()
        (self.out / "plan_1.json").write_text(json.dumps(plan, ensure_ascii=False))
        render_report(self.out)
        page = self.html()
        self.assertEqual(page.count("без изменений</i>"), 11)  # 12 полей, изменён только заголовок scene_2

    def test_failure_on_revision_keeps_partial_history(self):
        with patch("main.revise_plan", side_effect=ModelError("429 upstream")):
            with self.assertRaises(ModelError):
                run("Объясни", CATALOG, self.out, True)
        self.assertEqual(json.loads((self.out / "status.json").read_text())["status"], "failed")
        self.assertIn(("revise", 1, "error"), events(self.out))
        self.assertTrue((self.out / "plan_0.json").exists() and (self.out / "review_0.json").exists())
        page = self.html()
        self.assertIn("Место сбоя: <b>Монтажёр исправляет замечания</b>", page)
        self.assertIn("429 upstream", page)
        self.assertIn("review_0.json", page)

    def test_live_failure_before_first_answer(self):
        with patch("main.build_plan", side_effect=ModelError("Заполни OPENROUTER_API_KEY")):
            with self.assertRaises(ModelError):
                run("Объясни", CATALOG, self.out, False)
        page = self.html()
        self.assertIn("Место сбоя: <b>Монтажёр составляет план</b>", page)
        self.assertNotIn("ответы получены", page)

    def test_old_run_without_journal(self):
        old = Path(self.tmp.name) / "old"
        shutil.copytree(ROOT / "docs/evidence/real_video/revision", old)
        (old / "report.html").unlink()
        render_report(old)
        page = self.html(old)
        self.assertIn("Подробный журнал (events.json) отсутствует", page)
        self.assertIn("нет данных", page)
        self.assertIn("Было → стало", page)

    def test_user_text_is_escaped(self):
        run("<script>alert(1)</script>", CATALOG, self.out, True)
        page = self.html()
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)


if __name__ == "__main__":
    unittest.main()
