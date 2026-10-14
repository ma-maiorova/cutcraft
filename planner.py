"""Блок Марины. Общие интерфейсы сохраняем; сюда подключаем модель."""
from copy import deepcopy


def build_plan(task, catalog, *, demo=False):
    if not demo:
        raise NotImplementedError("Марина: подключить модель в planner.build_plan; см. prompts/planner.txt")
    # Демонстрационная заглушка: фиксированный выбор, НЕ вызов LLM.
    return {"schema_version": "1.0", "scenes": [
        {"scene_id": f"scene_{i}", "segment_id": s["segment_id"],
         "source_start": s["start"], "source_end": s["end"],
         "caption": ("Метод доказал эффективность" if i == 2 else s["transcript"]),
         "source_quote": s["transcript"], "selection_reason": "Фиксированная демонстрационная сцена"}
        for i, s in enumerate(catalog["segments"][:3], 1)]}


def revise_plan(task, catalog, plan, review, *, demo=False):
    if not demo:
        raise NotImplementedError("Марина: подключить модель в planner.revise_plan")
    updated = deepcopy(plan)
    # Только демонстрация передачи замечаний и обновления артефакта.
    by_id = {s["scene_id"]: s for s in updated["scenes"]}
    for item in review["items"]:
        if item["decision"] == "revise_caption":
            by_id[item["scene_id"]]["caption"] = by_id[item["scene_id"]]["source_quote"]
    return updated
