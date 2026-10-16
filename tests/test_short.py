import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


short = load("render_short_under_test", "scripts/render_short.py")
launcher = load("demo_launcher_short", "scripts/demo.py")


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class RenderShortTests(unittest.TestCase):
    def test_final_plan_ignores_generated_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            for name in ("plan_0.json", "plan_1.json", "plan_generated.json"):
                write(run / name, {})
            self.assertEqual(short.final_plan(run).name, "plan_1.json")

    def test_numeric_order_not_text_order(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            for name in ("plan_2.json", "plan_10.json"):
                write(run / name, {})
            self.assertEqual(short.final_plan(run).name, "plan_10.json")

    def test_failed_run_is_not_rendered(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write(run / "status.json", {"status": "failed"})
            with self.assertRaises(short.RenderError):
                short.check_ready(run, run / "video.mp4", run / "t.json")

    def test_missing_video_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            write(run / "status.json", {"status": "accepted"})
            with self.assertRaisesRegex(short.RenderError, "видео"):
                short.check_ready(run, run / "нет.mp4", ROOT / "data/transcript.json")


class LauncherShortTests(unittest.TestCase):
    def run_main(self, args, status="accepted"):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launcher, "ROOT", Path(directory)), \
                patch.object(launcher, "preflight", return_value=(15, 18)), \
                patch.object(launcher, "run", return_value=status), \
                patch.object(launcher, "make_short") as make_short, \
                contextlib.redirect_stdout(output):
            code = launcher.main(args)
        return code, make_short

    def test_live_run_builds_short(self):
        code, make_short = self.run_main(["--live", "--video", "clip.mp4"])
        self.assertEqual(code, 0)
        make_short.assert_called_once()
        self.assertEqual(make_short.call_args.args[1], Path("clip.mp4"))

    def test_no_short_flag_skips_video(self):
        _, make_short = self.run_main(["--live", "--no-short"])
        make_short.assert_not_called()

    def test_demo_answers_are_not_turned_into_video(self):
        _, make_short = self.run_main(["--demo"], status="demo_accepted")
        make_short.assert_not_called()

    def test_any_mp4_in_media_is_used(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "ROOT", Path(directory)), \
                patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("CUTCRAFT_VIDEO", None)
            media = Path(directory) / "media"
            media.mkdir()
            (media / "интервью.mp4").write_bytes(b"")
            self.assertEqual(launcher.default_video().name, "интервью.mp4")

    def test_missing_video_does_not_fail(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertIsNone(launcher.make_short(ROOT, Path("/нет/такого.mp4")))
        self.assertIn("Видео не подключено", output.getvalue())

    def test_render_error_does_not_change_result(self):
        output = io.StringIO()
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video, \
                patch.object(launcher, "render_short", side_effect=launcher.RenderError("нет ffmpeg")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertIsNone(launcher.make_short(ROOT, Path(video.name)))
        self.assertIn("Shorts не собран", output.getvalue())


if __name__ == "__main__":
    unittest.main()
