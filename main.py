"""Оркестратор: один раунд исправления, явные статусы, версии, журнал событий и HTML."""
import argparse
import copy
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from contracts import validate_catalog, validate_plan, validate_review, validate_revision
from model_client import load_environment
from planner import build_plan, revise_plan
from reviewer import review_plan
from render import render_report

ROOT = Path(__file__).resolve().parent


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return obj


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


def safe_message(exc):
    # Сообщения model_client не содержат ключа и заголовков; длину всё равно ограничиваем.
    return f"{type(exc).__name__}: {exc}"[:500]


class Journal:
    """events.json: порядок шагов, исполнитель, состояние, артефакты. Переписывается после каждого события,
    чтобы сбой не стирал уже полученное. Формат описан в docs/RUN_HISTORY_UI.md."""

    def __init__(self, out):
        self.path, self.events, self.failed = out / "events.json", [], False

    def log(self, stage, actor, state, *, iteration=None, inputs=(), outputs=(), message=""):
        self.events.append({"seq": len(self.events) + 1, "stage": stage, "actor": actor, "iteration": iteration,
                            "state": state, "inputs": list(inputs), "outputs": list(outputs), "message": message})
        save(self.path, {"schema_version": "1.0", "events": self.events})

    def step(self, stage, actor, fn, **meta):
        try:
            result = fn()
        except Exception as exc:
            self.failed = True
            self.log(stage, actor, "error", message=safe_message(exc), **meta)
            raise
        self.log(stage, actor, "done", **meta)
        return result

    def skip(self, iteration, reason):
        for stage, actor in (("revise", "planner"), ("revision_check", "code"), ("review", "reviewer")):
            self.log(stage, actor, "skipped", iteration=iteration, message=reason)


def models(demo):
    # Только имена моделей из .env/окружения, без ключа.
    if demo:
        return None
    load_environment()
    return {"planner": os.environ.get("TEXT_MODEL_NAME", ""), "reviewer": os.environ.get("VISION_MODEL_NAME", "")}


def run(task, catalog_path, out, demo=False, *, controlled_defect=False):
    if controlled_defect and demo:
        raise ValueError("Контрольный дефект доступен только для реальных API-вызовов")
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    mode = "demo" if demo else "live"
    history, journal, frames = [], Journal(out), None
    try:
        def load_input():
            catalog = validate_catalog(json.loads(catalog_path.read_text(encoding="utf-8")))
            try:
                where = str(catalog_path.relative_to(ROOT))
            except ValueError:
                where = str(catalog_path)
            save(out / "input.json", {"task": task, "catalog": catalog, "mode": mode, "catalog_path": where, "models": models(demo), "controlled_defect": controlled_defect})
            return catalog, resolve_frames(catalog, catalog_path.parent)
        catalog, frames = journal.step("input", "code", load_input, outputs=["input.json"])
        draft = journal.step("plan", "planner", lambda: build_plan(task, catalog, demo=demo), iteration=0, inputs=["input.json"])
        plan = journal.step("plan_check", "code", lambda: save(out / "plan_0.json", validate_plan(draft, catalog)),
                            iteration=0, outputs=["plan_0.json"])
        if controlled_defect:
            save(out / "plan_generated.json", copy.deepcopy(plan))
            def inject():
                damaged = copy.deepcopy(plan)
                scene = damaged["scenes"][0]
                original = scene["caption"]
                scene["caption"] = "Большой взрыв произошёл вчера в Москве"
                save(out / "controlled_defect.json", {
                    "scene_id": scene["scene_id"], "field": "caption", "before": original,
                    "after": scene["caption"], "origin": "injected_by_code_for_demo"})
                return save(out / "plan_0.json", validate_plan(damaged, catalog))
            plan = journal.step("controlled_defect", "code", inject, iteration=0,
                                inputs=["plan_generated.json"], outputs=["controlled_defect.json", "plan_0.json"])
        status = "needs_human_review"
        previous = None  # Прошлый раунд: принятые и не изменённые сцены критик не перепроверяет.
        for iteration in range(2):  # первоначальная проверка + одна доработка
            review = journal.step("review", "reviewer",
                                  lambda: save(out / f"review_{iteration}.json", validate_review(review_plan(task, catalog, plan, frames, demo=demo, previous=previous), plan)),
                                  iteration=iteration, inputs=[f"plan_{iteration}.json"], outputs=[f"review_{iteration}.json"])
            previous = {"plan": plan, "review": review}
            history.append({"plan": plan, "review": review})
            save(out / "history.json", history)
            decisions = {i["decision"] for i in review["items"]}
            if decisions == {"accept"}:
                status = "demo_accepted" if demo else "accepted"
                if iteration == 0:
                    journal.skip(1, "Все сцены приняты с первой проверки")
                break
            if "needs_human_review" in decisions:
                if iteration == 0:
                    journal.skip(1, "Проверяющий передал план человеку")
                break
            if iteration == 1:
                break
            before = plan
            draft = journal.step("revise", "planner", lambda: revise_plan(task, catalog, before, review, demo=demo),
                                 iteration=1, inputs=["plan_0.json", "review_0.json"])
            plan = journal.step("revision_check", "code",
                                lambda: save(out / "plan_1.json", validate_revision(before, validate_plan(draft, catalog), review, catalog)),
                                iteration=1, outputs=["plan_1.json"])
        save(out / "history.json", history)
        save(out / "status.json", {"status": status, "mode": mode, "seconds": round(time.monotonic()-started, 2), "revisions": len(history)-1})
        journal.log("finish", "code", "done", outputs=["history.json", "status.json", "report.html"], message=status)
        render_report(out, frames)
        return status
    except Exception as exc:
        save(out / "history.json", history)
        save(out / "status.json", {"status": "failed", "mode": mode, "error_type": type(exc).__name__, "message": str(exc), "seconds": round(time.monotonic()-started, 2)})
        if not journal.failed:
            journal.log("finish", "code", "error", message=safe_message(exc))
        try:
            render_report(out, frames)  # Частичный отчёт: показать то, что успели сохранить.
        except Exception as render_exc:
            print(f"Частичный отчёт не построен: {safe_message(render_exc)}", file=sys.stderr)
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
