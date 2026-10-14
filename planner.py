"""Блок Марины. Общие интерфейсы сохраняем; сюда подключаем модель."""
from copy import deepcopy
import json
from pathlib import Path
from contracts import validate_catalog, validate_plan, validate_review, ContractError
from model_client import chat_json

ROOT = Path(__file__).resolve().parent

def model_plan(task, catalog, plan=None, review=None):
    validate_catalog(catalog)
    prompt = (ROOT / "prompts/planner.txt").read_text(encoding="utf-8")
    example = json.loads((ROOT / "examples/plan.json").read_text(encoding="utf-8"))
    prompt += "\nФорма JSON-ответа показана ниже. Значения выбирай из входного каталога, не копируй пример:\n" + json.dumps(example, ensure_ascii=False)
    payload = {"task": task, "catalog": catalog}
    if plan is not None:
        validate_plan(plan, catalog)
        validate_review(review, plan)
        payload.update({"plan": plan, "review": review})
    result = validate_plan(chat_json(prompt, payload), catalog)
    if plan is not None:
        unchanged = {x["scene_id"] for x in review["items"] if x["decision"] == "accept"}
        before = {s["scene_id"]: s for s in plan["scenes"]}
        after = {s["scene_id"]: s for s in result["scenes"]}
        if set(before) != set(after):
            raise ContractError("При исправлении изменены идентификаторы сцен")
        if any(before[i] != after[i] for i in unchanged):
            raise ContractError("Модель изменила принятую сцену; результат не принят")
    return result



def build_plan(task, catalog, *, demo=False):
    if not demo:
        return model_plan(task, catalog)
    # Демонстрационная заглушка: фиксированный выбор, НЕ вызов LLM.
    return {"schema_version": "1.0", "scenes": [
        {"scene_id": f"scene_{i}", "segment_id": s["segment_id"],
         "source_start": s["start"], "source_end": s["end"],
         "caption": ("Метод доказал эффективность" if i == 2 else s["transcript"]),
         "source_quote": s["transcript"], "selection_reason": "Фиксированная демонстрационная сцена"}
        for i, s in enumerate(catalog["segments"][:3], 1)]}


def revise_plan(task, catalog, plan, review, *, demo=False):
    if not demo:
        return model_plan(task, catalog, plan, review)
    updated = deepcopy(plan)
    # Только демонстрация передачи замечаний и обновления артефакта.
    by_id = {s["scene_id"]: s for s in updated["scenes"]}
    for item in review["items"]:
        if item["decision"] == "revise_caption":
            by_id[item["scene_id"]]["caption"] = by_id[item["scene_id"]]["source_quote"]
    return updated
