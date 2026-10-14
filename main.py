"""Оркестратор: один раунд исправления, явные статусы, версии и HTML."""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from contracts import validate_catalog, validate_plan, validate_review
from planner import build_plan, revise_plan
from reviewer import review_plan
from render import render_report

ROOT = Path(__file__).resolve().parent


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_frames(catalog, base):
    result = {}
    for segment in catalog["segments"]:
        for name in segment["frame_paths"]:
            path = (base / name).resolve()
            if not path.is_relative_to(base.resolve()):
                raise ValueError("Картинки должны находиться внутри каталога данных")
            if not path.is_file():
                raise FileNotFoundError(f"Не найден кадр: {path}")
            result[name] = path
    return result


def run(task, catalog_path, out, demo=False):
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    history = []
    try:
        catalog = validate_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
        frames = resolve_frames(catalog, catalog_path.parent)
        save(out / "input.json", {"task": task, "catalog": catalog, "mode": "demo" if demo else "live"})
        plan = validate_plan(build_plan(task, catalog, demo=demo), catalog)
        status = "needs_human_review"
        for iteration in range(2):  # первоначальная проверка + одна доработка
            review = validate_review(review_plan(task, catalog, plan, frames, demo=demo), plan)
            entry = {"plan": plan, "review": review}
            history.append(entry)
            save(out / f"plan_{iteration}.json", plan)
            save(out / f"review_{iteration}.json", review)
            decisions = {i["decision"] for i in review["items"]}
            if decisions == {"accept"}:
                status = "demo_accepted" if demo else "accepted"
                break
            if "needs_human_review" in decisions or iteration == 1:
                break
            plan = validate_plan(revise_plan(task, catalog, plan, review, demo=demo), catalog)
        save(out / "history.json", history)
        render_report(out / "report.html", task, catalog, history, status, frames, demo)
        save(out / "status.json", {"status": status, "mode": "demo" if demo else "live", "seconds": round(time.monotonic()-started, 2), "revisions": len(history)-1})
        return status
    except Exception as exc:
        save(out / "status.json", {"status": "failed", "error_type": type(exc).__name__, "message": str(exc), "seconds": round(time.monotonic()-started, 2)})
        raise


def main():
    p = argparse.ArgumentParser(description="CutCraft: каркас подготовки эдита")
    p.add_argument("--task", default="Объясни результат и ограничения метода")
    p.add_argument("--catalog", type=Path, default=ROOT / "data/catalog.json")
    p.add_argument("--out", type=Path, default=ROOT / "output" / datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    p.add_argument("--demo", action="store_true", help="Фиксированные ответы, без LLM; не выдавать за реальных агентов")
    a = p.parse_args()
    try:
        status = run(a.task, a.catalog.resolve(), a.out.resolve(), a.demo)
    except Exception as exc:
        print(f"Запуск не завершён: {exc}. Статус: {a.out / 'status.json'}", file=sys.stderr)
        return 1
    print(f"{status}: {a.out.resolve() / 'report.html'}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
