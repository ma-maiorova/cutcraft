"""Ветка доработки на двух реальных моделях: критик → монтажёр → критик (3 запроса).
Стартовый план — контрольный дефект lost_caveat (потерянная оговорка), чтобы доработка гарантированно понадобилась.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts import validate_catalog, validate_plan, validate_review, validate_revision
from main import resolve_frames
from model_client import load_environment
from planner import revise_plan
from reviewer import review_plan

CASES = ROOT / "docs/evidence/reviewer/cases"


def main():
    load_environment()
    out = ROOT / "output" / ("revision-live-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    out.mkdir(parents=True)
    save = lambda name, value: (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task = json.loads((CASES / "cases.json").read_text(encoding="utf-8"))["task"]
    catalog = validate_catalog(json.loads((CASES / "catalog.json").read_text(encoding="utf-8")))
    frames = resolve_frames(catalog, CASES)
    plan = validate_plan(json.loads((CASES / "plan_lost_caveat.json").read_text(encoding="utf-8")), catalog)
    started, steps = time.monotonic(), []
    def step(name, fn):
        print(f"… {name}", flush=True)
        t = time.monotonic()
        value = fn()
        steps.append({"step": name, "seconds": round(time.monotonic() - t, 2)})
        return value
    try:
        save("plan_0.json", plan)
        review0 = step("критик проверяет план с дефектом", lambda: validate_review(review_plan(task, catalog, plan, frames), plan))
        save("review_0.json", review0)
        if all(i["decision"] == "accept" for i in review0["items"]):
            raise RuntimeError("Критик пропустил контрольный дефект — доработка не запускается")
        plan1 = step("монтажёр исправляет по замечаниям", lambda: validate_revision(plan, revise_plan(task, catalog, plan, review0), review0, catalog))
        save("plan_1.json", plan1)
        review1 = step("критик проверяет исправленный план", lambda: validate_review(review_plan(task, catalog, plan1, frames, previous={"plan": plan, "review": review0}), plan1))
        save("review_1.json", review1)
        accepted = all(i["decision"] == "accept" for i in review1["items"])
        result = {"status": "accepted" if accepted else "needs_human_review"}
    except Exception as exc:
        result = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)}
    result.update({"text_model": os.getenv("TEXT_MODEL_NAME"), "vision_model": os.getenv("VISION_MODEL_NAME"),
                   "utc": datetime.now(timezone.utc).isoformat(), "seconds": round(time.monotonic() - started, 2),
                   "model_calls": len(steps), "steps": steps,
                   "start_plan": "docs/evidence/reviewer/cases/plan_lost_caveat.json (controlled defect)"})
    save("result.json", result)
    print(f"{result['status']}: {out}")
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
