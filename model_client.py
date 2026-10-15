"""Общий минимальный клиент OpenRouter. Только бесплатные ID; без платного fallback."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://openrouter.ai/api/v1"

class ModelError(RuntimeError):
    pass


def load_environment(path=None):
    path = Path(path) if path is not None else ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in (chr(34), chr(39)):
            value = value[1:-1]
        if key in {"OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "TEXT_MODEL_NAME", "VISION_MODEL_NAME", "OPENROUTER_FREE_ONLY", "MODEL_TIMEOUT_SECONDS"}:
            os.environ.setdefault(key, value)


def settings(model_env):
    load_environment()
    if os.getenv("OPENROUTER_BASE_URL", API).rstrip("/") != API:
        raise ModelError("Разрешён только официальный API OpenRouter")
    if os.getenv("OPENROUTER_FREE_ONLY", "true").lower() != "true":
        raise ModelError("В этом MVP разрешён только бесплатный режим")
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ModelError("Заполни OPENROUTER_API_KEY в локальном .env")
    model = os.getenv(model_env, "").strip()
    if not model.endswith(":free"):
        raise ModelError(f"{model_env} должен содержать точный ID бесплатной модели :free")
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
        if not 1 <= timeout <= 120:
            raise ValueError()
    except ValueError:
        raise ModelError("MODEL_TIMEOUT_SECONDS должен быть от 1 до 120") from None
    return key, model, timeout


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Не передавать Authorization на другой адрес.


def request_json(path, key, timeout, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        hint = {401: "проверь ключ", 402: "модель недоступна без оплаты; платного повтора не будет", 429: "исчерпана квота или провайдер занят; повтори позже"}.get(exc.code, "проверь доступность бесплатной модели")
        raise ModelError(f"OpenRouter HTTP {exc.code}: {hint}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ModelError("Не удалось получить ответ OpenRouter: сеть или timeout") from None
    except (ValueError, TypeError):
        raise ModelError("OpenRouter вернул некорректный JSON") from None


def check_free_model(models, model, *, vision=False):
    found = next((m for m in models if m.get("id") == model), None)
    if not found or not model.endswith(":free"):
        raise ModelError("Выбранная бесплатная модель отсутствует в актуальном каталоге")
    pricing = found.get("pricing", {})
    try:
        if any(float(pricing.get(k, "1")) != 0 for k in ("prompt", "completion")):
            raise ValueError()
        if any(float(pricing.get(k, "0")) != 0 for k in ("request", "image", "web_search", "internal_reasoning")):
            raise ValueError()
    except (ValueError, TypeError):
        raise ModelError("Нулевая стоимость модели не подтверждена; запрос отменён") from None
    if vision and "image" not in found.get("architecture", {}).get("input_modalities", []):
        raise ModelError("Выбранная модель не принимает изображения")
    return found


def chat_json(system, payload, *, model_env="TEXT_MODEL_NAME", vision=False, schema=None):
    key, model, timeout = settings(model_env)
    metadata = request_json("/models", key, timeout)
    found = check_free_model(metadata.get("data", []), model, vision=vision)
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "max_tokens": 2200, "temperature": 0.2}
    if schema is not None and "structured_outputs" in found.get("supported_parameters", []):
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "cutcraft_plan", "strict": True, "schema": schema}}
    elif "response_format" in found.get("supported_parameters", []):
        body["response_format"] = {"type": "json_object"}
    response = request_json("/chat/completions", key, timeout, body)
    if response.get("error"):
        raise ModelError("OpenRouter сообщил об ошибке модели")
    try:
        choice = response["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ModelError("Ответ обрезан лимитом; план не принят")
        text = choice["message"]["content"]
        if not isinstance(text, str):
            raise ValueError()
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError()
        return obj
    except (KeyError, IndexError, TypeError, ValueError):
        raise ModelError("Модель не вернула JSON-объект нужного формата; автоматического повтора нет") from None
