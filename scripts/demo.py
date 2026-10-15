"""Presentation launcher: saved evidence by default, API only with --live."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts import validate_catalog, validate_task
from main import resolve_frames, run
from model_client import settings
from render import render_report

TASK = "Объясни за 30 секунд, почему учёные уверены, что был Большой взрыв"


def prepare_saved(destination):
    """Re-render recorded live runs without modifying evidence or calling models."""
    destination.mkdir(parents=True, exist_ok=True)
    reports = []
    for case in ("final", "revision"):
        source = ROOT / "docs/evidence/real_video" / case
        if not (source / "input.json").is_file() or not (source / "status.json").is_file():
            raise ValueError(f"Нет сохранённого прогона: {case}")
        target = destination / f"saved-{case}.html"
        render_report(source, path=target)
        # Explicit provenance stays visible even though the underlying run was live.
        text = target.read_text(encoding="utf-8")
        marker = ('<aside><strong>СОХРАНЁННЫЙ РЕАЛЬНЫЙ ПРОГОН, НЕ ТЕКУЩИЙ ЗАПУСК.</strong> '
                  'Ответы получены ранее; сейчас API не вызывается.</aside>')
        target.write_text(text.replace('<h1>', marker + '<h1>', 1), encoding="utf-8")
        reports.append(target)
    return reports


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
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/catalog.json")
    parser.add_argument("--task", default=TASK)
    args = parser.parse_args(argv)
    out = ROOT / "output" / ("presentation-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    try:
        saved = prepare_saved(out)
    except (OSError, ValueError) as exc:
        print(f"Не удалось подготовить сохранённые отчёты: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("СОХРАНЁННЫЕ реальные прогоны; сейчас модели не вызывались:", flush=True)
    for path in saved:
        print(path.resolve().as_uri(), flush=True)
    if not args.live and not args.demo:
        print("Для нового запуска: --live (API) или --demo (фиксированные ответы).")
        return 0
    current = out / "current"
    try:
        validate_task(args.task)
        count, frames = preflight(args.catalog.resolve(), live=args.live)
        print(f"Вход проверен: {count} фрагментов, {frames} кадров.", flush=True)
        print("LIVE: до 4 основных запросов, без повторов." if args.live else
              "ДЕМО: фиксированные ответы, не проверка моделей.", flush=True)
        status = run(args.task, args.catalog.resolve(), current, demo=args.demo)
    except Exception as exc:
        # Do not echo arbitrary exception text or credentials in a presentation console.
        print(f"НОВЫЙ запуск не завершён ({type(exc).__name__}). Используйте сохранённые отчёты выше.", file=sys.stderr)
        report = current / "report.html"
        if report.is_file():
            print("Частичный отчёт: " + report.resolve().as_uri())
        return 1
    print(f"НОВЫЙ запуск: {status}")
    print((current / "report.html").resolve().as_uri())
    return 0 if status in ("accepted", "demo_accepted") else 2


if __name__ == "__main__":
    sys.exit(main())
