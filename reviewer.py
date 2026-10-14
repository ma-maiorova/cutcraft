"""Блок проверяющего. Реальная модель должна получать байты изображений."""
def review_plan(task, catalog, plan, frames, *, demo=False):
    if not demo:
        raise NotImplementedError("Подключить мультимодальную модель в reviewer.review_plan; см. prompts/reviewer.txt")
    # НЕ визуальный анализ: детерминированная демонстрация одного известного дефекта.
    items = []
    for scene in plan["scenes"]:
        bad = scene["caption"] == "Метод доказал эффективность"
        items.append({"scene_id": scene["scene_id"],
                      "decision": "revise_caption" if bad else "accept",
                      "issue": "Утеряна оговорка о симуляции" if bad else "",
                      "evidence": scene["source_quote"] if bad else "",
                      "requested_change": "Сохранить ограничение исходного утверждения" if bad else ""})
    return {"schema_version": "1.0", "items": items}
