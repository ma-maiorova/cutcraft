import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("demo_launcher", Path(__file__).resolve().parents[1] / "scripts/demo.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class DemoLauncherTests(unittest.TestCase):
    def test_saved_report_is_labeled_without_api(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "run") as run:
            reports = launcher.prepare_saved(Path(directory))
            self.assertEqual(len(reports), 2)
            for report in reports:
                text = report.read_text()
                self.assertIn("СОХРАНЁННЫЙ РЕАЛЬНЫЙ ПРОГОН", text)
                self.assertIn("data:image/", text)
            run.assert_not_called()

    def test_failure_keeps_saved_paths_and_hides_exception_text(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            with patch.object(launcher, "ROOT", root), patch.object(launcher, "prepare_saved", return_value=[root / "saved.html"]), patch.object(launcher, "preflight", return_value=(15, 18)), patch.object(launcher, "run", side_effect=RuntimeError("SECRET")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                code = launcher.main(["--live"])
            self.assertEqual(code, 1)
            self.assertIn("saved.html", output.getvalue())
            self.assertNotIn("SECRET", output.getvalue())

    def test_human_review_is_not_reported_as_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "ROOT", Path(directory)), patch.object(launcher, "prepare_saved", return_value=[]), patch.object(launcher, "preflight", return_value=(15, 18)), patch.object(launcher, "run", return_value="needs_human_review"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(["--demo"]), 2)
