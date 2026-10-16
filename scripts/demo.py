"""Запуск CutCraft для показа. Результат — одна папка output/<timestamp>: план (report.html) и видео (short.mp4)."""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts import validate_catalog, validate_task
from main import resolve_frames, run
from model_client import settings
sys.path.insert(0, str(ROOT / "scripts"))
from render_short import RenderError, render as render_short

TASK = "Объясни за 30 секунд, почему учёные уверены, что был Большой взрыв"


def default_video():
    """Исходное видео: CUTCRAFT_VIDEO, если задан, иначе единственный (первый по имени) .mp4 в папке media/."""
    if os.environ.get("CUTCRAFT_VIDEO"):
        return Path(os.environ["CUTCRAFT_VIDEO"])
    videos = sorted((ROOT / "media").glob("*.mp4"))
    return videos[0] if videos else ROOT / "media"


DEFAULT_VIDEO = default_video()


def make_short(run_dir, video, out=None):
    """Собрать shorts по итоговому плану. Сбой сборки видео не влияет на результат агентного цикла."""
    if video is None or not video.is_file():
        print(f"Видео не подключено ({video}): shorts не собираем, отчёт готов.", flush=True)
        return None
    print("Собираем shorts по итоговому плану (модели не вызываются)...", flush=True)
    try:
        path = render_short(run_dir, video, out=out, log=lambda m: print("  " + m, flush=True))
    except (RenderError, OSError, ValueError, KeyError) as exc:
        print(f"Shorts не собран: {exc}", file=sys.stderr, flush=True)
        return None
    print("Видео: " + path.resolve().as_uri(), flush=True)
    return path


def preflight(catalog_path, live=False):
    catalog = validate_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
    frames = resolve_frames(catalog, catalog_path.parent)
    if live:
        settings("TEXT_MODEL_NAME")
        settings("VISION_MODEL_NAME")
    return len(catalog["segments"]), len(frames)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true", help="Реальный запуск: 2–4 API-запроса")
    modes.add_argument("--demo", action="store_true", help="Фиксированные ответы, без API")
    parser.add_argument("--controlled-defect", action="store_true", help="С --live: испортить одну подпись кодом, явно пометив тест")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/catalog.json")
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO, help="Исходное видео для сборки shorts")
    parser.add_argument("--no-short", action="store_true", help="Не собирать shorts")
    args = parser.parse_args(argv)
    if args.controlled_defect and not args.live:
        parser.error("--controlled-defect требует --live")
    video = None if args.no_short else args.video
    if not args.live and not args.demo:
        print("Укажите режим: --live (реальные модели, 2–4 запроса) или --demo (фиксированные ответы, без API).")
        return 0
    # Результат запуска — одна папка: план (report.html) и, после живого запуска, видео (short.mp4).
    current = ROOT / "output" / datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        validate_task(args.task)
        count, frames = preflight(args.catalog.resolve(), live=args.live)
        print(f"Вход проверен: {count} фрагментов, {frames} кадров.", flush=True)
        print("LIVE: до 4 основных запросов, без повторов." if args.live else
              "ДЕМО: фиксированные ответы, не проверка моделей.", flush=True)
        if args.controlled_defect:
            print("КОНТРОЛЬНЫЙ ДЕФЕКТ: код испортит первую подпись после ответа модели; реальные API-вызовы.", flush=True)
            status = run(args.task, args.catalog.resolve(), current, controlled_defect=True)
        else:
            status = run(args.task, args.catalog.resolve(), current, demo=args.demo)
    except Exception as exc:
        # Do not echo arbitrary exception text or credentials in a presentation console.
        print(f"Запуск не завершён ({type(exc).__name__}).", file=sys.stderr)
        report = current / "report.html"
        if report.is_file():
            print("Частичный отчёт: " + report.resolve().as_uri())
        return 1
    print(f"Запуск: {status}")
    print("План: " + (current / "report.html").resolve().as_uri())
    if args.live and video is not None:
        make_short(current, video)
    if args.controlled_defect:
        defect = json.loads((current / "controlled_defect.json").read_text())
        review = json.loads((current / "review_0.json").read_text())
        detected = any(i["scene_id"] == defect["scene_id"] and i["decision"] != "accept" for i in review["items"])
        print("Контрольный дефект: " + ("ОБНАРУЖЕН" if detected else "ПРОПУЩЕН критиком; тест обнаружения не пройден"))
        if not detected:
            return 3
    return 0 if status in ("accepted", "demo_accepted") else 2


if __name__ == "__main__":
    sys.exit(main())
