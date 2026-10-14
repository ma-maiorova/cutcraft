"""Отдельный запуск монтажёра без проверяющего. Выход — JSON, не одобренный критиком."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from planner import build_plan, revise_plan
from contracts import validate_plan

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description="Монтажёр: создание или исправление плана")
    parser.add_argument("--task", default="Объясни результат и ограничения метода")
    parser.add_argument("--catalog", type=Path, default=ROOT/"data/catalog.json")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT/"output"/("planner-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".json"))
    args = parser.parse_args()
    if bool(args.plan) != bool(args.review):
        parser.error("Для доработки нужны оба аргумента --plan и --review")
    try:
        catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
        if args.plan:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            review = json.loads(args.review.read_text(encoding="utf-8"))
            result = revise_plan(args.task, catalog, plan, review, demo=args.demo)
        else:
            result = build_plan(args.task, catalog, demo=args.demo)
        validate_plan(result, catalog)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"План не создан: {exc}", file=sys.stderr)
        return 1
    print(f"План сохранён, ещё не проверен критиком: {args.out.resolve()}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
