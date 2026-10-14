"""Общие контракты команды. Меняем совместно; время — секунды."""
import math

class ContractError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise ContractError(message)

def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def validate_catalog(catalog):
    require(isinstance(catalog, dict), "Каталог должен быть объектом")
    require(catalog.get("schema_version") == "1.0", "Нужна schema_version 1.0")
    require(number(catalog.get("source_duration")) and catalog["source_duration"] > 0, "Неверная длина источника")
    require(isinstance(catalog.get("assets_are_real"), bool), "Укажите assets_are_real")
    segments = catalog.get("segments")
    require(isinstance(segments, list) and len(segments) >= 3, "Нужно минимум 3 сегмента")
    ids = set()
    for s in segments:
        require(isinstance(s, dict), "Сегмент должен быть объектом")
        ident = s.get("segment_id")
        require(isinstance(ident, str) and ident and ident not in ids, "Пустой или повторный segment_id")
        ids.add(ident)
        require(number(s.get("start")) and number(s.get("end")), "Таймкоды должны быть числами")
        require(0 <= s["start"] < s["end"] <= catalog["source_duration"], "Сегмент за границами источника")
        require(isinstance(s.get("transcript"), str) and s["transcript"].strip(), "Нужен transcript")
        require(isinstance(s.get("frame_paths"), list) and s["frame_paths"] and all(isinstance(p, str) and p for p in s["frame_paths"]), "Нужны frame_paths")
    return catalog

def validate_plan(plan, catalog):
    validate_catalog(catalog)
    require(isinstance(plan, dict) and plan.get("schema_version") == "1.0", "Неверная версия плана")
    scenes = plan.get("scenes")
    require(isinstance(scenes, list) and len(scenes) == 3, "В упрощённом MVP ровно 3 сцены")
    lookup = {s["segment_id"]: s for s in catalog["segments"]}
    ids, used, total = set(), set(), 0
    for s in scenes:
        require(isinstance(s, dict), "Сцена должна быть объектом")
        ident = s.get("scene_id")
        require(isinstance(ident, str) and ident and ident not in ids, "Повторный/пустой scene_id")
        ids.add(ident)
        require(s.get("segment_id") in lookup, "Выбран несуществующий segment_id")
        require(s["segment_id"] not in used, "Повтор одного сегмента")
        used.add(s["segment_id"])
        source = lookup[s["segment_id"]]
        require(number(s.get("source_start")) and number(s.get("source_end")), "Неверные таймкоды сцены")
        require(source["start"] <= s["source_start"] < s["source_end"] <= source["end"], "Границы сцены вне сегмента")
        for key in ("caption", "source_quote", "selection_reason"):
            require(isinstance(s.get(key), str) and s[key].strip(), f"Нужно поле {key}")
        require(s["source_quote"] in source["transcript"], "Цитата отсутствует в транскрипте сегмента")
        total += s["source_end"] - s["source_start"]
    require(20 <= total <= 30, "Общая длительность должна быть 20–30 секунд")
    return plan

def validate_review(review, plan):
    require(isinstance(review, dict) and review.get("schema_version") == "1.0", "Неверная версия review")
    items = review.get("items")
    require(isinstance(items, list), "Нужен список items")
    expected = {s["scene_id"] for s in plan["scenes"]}
    ids = set()
    for item in items:
        require(isinstance(item, dict), "Замечание должно быть объектом")
        require(item.get("scene_id") in expected and item["scene_id"] not in ids, "Неизвестная или повторная сцена review")
        ids.add(item["scene_id"])
        decision = item.get("decision")
        require(decision in ("accept", "revise_caption", "replace_segment", "adjust_bounds", "needs_human_review"), "Неизвестное решение")
        for key in ("issue", "evidence", "requested_change"):
            require(isinstance(item.get(key), str), f"Нужно строковое поле {key}")
            if decision != "accept":
                require(item[key].strip(), f"Для замечания нужно непустое {key}")
    require(ids == expected, "Проверяющий должен оценить каждую сцену")
    return review
