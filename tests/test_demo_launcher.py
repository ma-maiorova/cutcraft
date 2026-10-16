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
    def test_failure_hides_exception_text(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(launcher, "ROOT", root), patch.object(launcher, "preflight", return_value=(15, 18)), patch.object(launcher, "run", side_effect=RuntimeError("SECRET")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                code = launcher.main(["--live"])
            self.assertEqual(code, 1)
            self.assertNotIn("SECRET", output.getvalue())

    def test_output_is_one_run_folder_without_extra_reports(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "ROOT", Path(directory)), patch.object(launcher, "preflight", return_value=(15, 18)), patch.object(launcher, "run", return_value="accepted") as run, patch.object(launcher, "make_short") as make_short, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(["--live"]), 0)
            run_dir = run.call_args.args[2]
            self.assertEqual(run_dir.parent, Path(directory) / "output")
            make_short.assert_called_once_with(run_dir, launcher.DEFAULT_VIDEO)
            self.assertFalse(list((Path(directory) / "output").glob("saved*")))

    def test_without_mode_nothing_runs(self):
        with patch.object(launcher, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main([]), 0)
            run.assert_not_called()

    def test_human_review_is_not_reported_as_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "ROOT", Path(directory)), patch.object(launcher, "preflight", return_value=(15, 18)), patch.object(launcher, "run", return_value="needs_human_review"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(["--demo"]), 2)
