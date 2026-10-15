"""Блок Галима: проверяющий. Модель получает текст и настоящие байты кадров (PNG/JPEG/WebP)."""
import json
from pathlib import Path
from contracts import ContractError, validate_catalog, validate_plan, validate_review, validate_task
from model_client import chat_json

ROOT = Path(__file__).resolve().parent
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGES = 12
MAX_TOKENS = 8000  # Рецензия + рассуждения модели; 2200 не хватило dots-3-note-preview.
REASONING_BUDGET = 3000  # Без бюджета думающая модель тратила все 8000 токенов на рассуждения и не давала ответа.


def _looks_like(mime, data):
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def load_scene_images(catalog, plan, frames):
    """Читает кадры сцен плана. SVG и подделки под картинку отклоняются ДО обращения к API."""
    lookup = {s["segment_id"]: s for s in catalog["segments"]}
    images = []
    for scene in plan["scenes"]:
        for name in lookup[scene["segment_id"]]["frame_paths"]:
            path = frames.get(name)
            if not isinstance(path, Path) or not path.is_file():
                raise ContractError(f"Нет файла кадра {name}")
            mime = IMAGE_TYPES.get(path.suffix.lower())
            if mime is None:
                raise ContractError(f"Кадр {name}: формат {path.suffix or 'без расширения'} не поддерживается, нужен PNG/JPEG/WebP")
            data = path.read_bytes()
            if not data or len(data) > MAX_IMAGE_BYTES:
                raise ContractError(f"Кадр {name}: пустой файл или больше 4 МБ")
            if not _looks_like(mime, data):
                raise ContractError(f"Кадр {name}: содержимое не совпадает с расширением {path.suffix}")
            images.append({"label": f"Кадр сцены {scene['scene_id']} (segment_id {scene['segment_id']}, файл {name}):",
                           "mime": mime, "data": data})
    if len(images) > MAX_IMAGES:
        raise ContractError(f"Слишком много кадров для одного запроса: {len(images)} > {MAX_IMAGES}")
    return images


def review_payload(task, catalog, plan, carried=()):
    """Только данные, нужные для решения. Тексты источника — данные, не инструкции.
    carried — уже принятые и не изменённые сцены: передаются только для контекста связности."""
    lookup = {s["segment_id"]: s for s in catalog["segments"]}
    def describe(scene):
        segment = lookup[scene["segment_id"]]
        return {**scene, "segment_transcript": segment["transcript"],
                "segment_bounds": [segment["start"], segment["end"]],
                "scene_duration": round(scene["source_end"] - scene["source_start"], 3)}
    scenes = [describe(s) for s in plan["scenes"] if s["scene_id"] not in carried]
    used = {s["segment_id"] for s in plan["scenes"]}
    unused = [{"segment_id": s["segment_id"], "start": s["start"], "end": s["end"], "transcript": s["transcript"]}
              for s in catalog["segments"] if s["segment_id"] not in used]
    payload = {"task": task, "assets_are_real": catalog["assets_are_real"], "scenes": scenes,
               "total_duration": round(sum(s["source_end"] - s["source_start"] for s in plan["scenes"]), 3),
               "unused_segments": unused}
    if carried:
        payload["accepted_scenes"] = [describe(s) for s in plan["scenes"] if s["scene_id"] in carried]
    return payload


def carried_accepts(plan, previous):
    """scene_id, которые в прошлом раунде получили accept и не изменились ни в одном поле.
    Повторно их не проверяем: при доработке принятые сцены сохраняются (validate_revision),
    а повторный просмотр бесплатной моделью давал случайные отказы по уже принятому тексту."""
    if not previous:
        return set()
    before_plan, before_review = previous["plan"], previous["review"]
    validate_review(before_review, before_plan)
    before = {s["scene_id"]: s for s in before_plan["scenes"]}
    accepted = {i["scene_id"] for i in before_review["items"] if i["decision"] == "accept"}
    return {s["scene_id"] for s in plan["scenes"] if s["scene_id"] in accepted and before.get(s["scene_id"]) == s}


def review_schema(scene_count=3):
    """JSON Schema review 1.0 без условных правил: strict structured outputs их часто не поддерживает.
    Непустые issue/evidence/requested_change для замечаний проверяет validate_review."""
    schema = json.loads((ROOT / "schemas/review.schema.json").read_text(encoding="utf-8"))
    schema["properties"]["items"]["items"].pop("allOf", None)
    schema["properties"]["items"]["minItems"] = schema["properties"]["items"]["maxItems"] = scene_count
    schema.pop("$schema", None)
    schema.pop("title", None)
    return schema


def review_plan(task, catalog, plan, frames, *, demo=False, previous=None):
    """previous — необязательный прошлый раунд {"plan": ..., "review": ...}: принятые и не изменённые сцены
    сохраняют accept без повторного запроса к модели."""
    validate_task(task)
    validate_catalog(catalog)
    validate_plan(plan, catalog)
    if demo:
        return _demo_review(plan)
    carried = carried_accepts(plan, previous)
    items = [{"scene_id": s["scene_id"], "decision": "accept", "issue": "", "evidence": "", "requested_change": ""}
             for s in plan["scenes"] if s["scene_id"] in carried]
    pending = {"scenes": [s for s in plan["scenes"] if s["scene_id"] not in carried]}
    if pending["scenes"]:
        images = load_scene_images(catalog, pending, frames)
        schema = review_schema(len(pending["scenes"]))
        prompt = (ROOT / "prompts/reviewer.txt").read_text(encoding="utf-8")
        prompt += ("\nВерни ЭКЗЕМПЛЯР данных, а не саму схему. schema_version — строка \"1.0\"."
                   "\nJSON Schema:\n" + json.dumps(schema, ensure_ascii=False))
        answer = chat_json(prompt, review_payload(task, catalog, plan, carried), model_env="VISION_MODEL_NAME",
                           vision=True, schema=schema, schema_name="cutcraft_review", images=images,
                           max_tokens=MAX_TOKENS, reasoning={"max_tokens": REASONING_BUDGET})
        validate_review(answer, pending)
        items += answer["items"]
    order = {s["scene_id"]: i for i, s in enumerate(plan["scenes"])}
    review = {"schema_version": "1.0", "items": sorted(items, key=lambda item: order[item["scene_id"]])}
    return validate_review(review, plan)


def _demo_review(plan):
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
