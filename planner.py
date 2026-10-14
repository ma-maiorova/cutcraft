"""Блок Марины. Общие интерфейсы сохраняем; сюда подключаем модель."""
from copy import deepcopy
import json
from pathlib import Path
from contracts import validate_catalog, validate_plan, validate_review, validate_revision, validate_task, ContractError
from model_client import chat_json

ROOT = Path(__file__).resolve().parent

def model_plan(task, catalog, plan=None, review=None):
    validate_task(task)
    validate_catalog(catalog)
    prompt = (ROOT / "prompts/planner.txt").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "schemas/plan.schema.json").read_text(encoding="utf-8"))
    prompt += "\nВерни ЭКЗЕМПЛЯР данных, а не саму схему. schema_version должна быть строкой \"1.0\". Поля type/properties/$schema в ответ не включать.\nJSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
    payload = {"task": task, "catalog": catalog}
    if plan is not None:
        validate_plan(plan, catalog)
        validate_review(review, plan)
        payload.update({"plan": plan, "review": review})
    result = validate_plan(chat_json(prompt, payload, schema=schema), catalog)
    if plan is not None:
        validate_revision(plan, result, review, catalog)
    return result



def build_plan(task, catalog, *, demo=False):
    validate_task(task)
    validate_catalog(catalog)
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
    validate_task(task)
    validate_plan(plan, catalog)
    validate_review(review, plan)
    if any(item["decision"] == "needs_human_review" for item in review["items"]):
        raise ContractError("Нужна ручная проверка, а не автоматическая доработка")
    if all(item["decision"] == "accept" for item in review["items"]):
        return deepcopy(plan)  # Не тратить запрос, если всё принято.
    if not demo:
        return model_plan(task, catalog, plan, review)
    updated = deepcopy(plan)
    # Только демонстрация передачи замечаний и обновления артефакта.
    by_id = {s["scene_id"]: s for s in updated["scenes"]}
    for item in review["items"]:
        if item["decision"] == "revise_caption":
            by_id[item["scene_id"]]["caption"] = by_id[item["scene_id"]]["source_quote"]
    return validate_revision(plan, updated, review, catalog)
