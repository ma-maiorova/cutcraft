"""Общий минимальный клиент OpenRouter. Только бесплатные ID; без платного fallback."""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = "https://openrouter.ai/api/v1"

class ModelError(RuntimeError):
    """partial — обрезанный текст ответа (если был), usage — счётчики токенов OpenRouter; ключей не содержат."""
    def __init__(self, message, *, partial=None, usage=None):
        super().__init__(message)
        self.partial = partial
        self.usage = usage


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


def read_until(response, deadline):
    """Общий лимит времени на ответ. Socket timeout его не даёт: OpenRouter шлёт пробелы-keepalive,
    пока модель думает, и чтение может длиться бесконечно."""
    chunks = []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError()
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:  # Одно ожидание порции не дольше остатка общего лимита.
            sock.settimeout(max(0.5, deadline - time.monotonic()))
        chunk = response.read(8192)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def provider_reason(exc):
    """Короткая причина из тела ошибки OpenRouter (например, дневной лимит или перегрузка модели). Ключ там не содержится."""
    try:
        error = json.loads(exc.read(4096).decode("utf-8", "replace")).get("error", {})
        parts = [str(error.get("message", ""))]
        raw = (error.get("metadata") or {}).get("raw")
        if raw:
            parts.append(str(raw))
        text = " | ".join(p for p in parts if p).replace("\n", " ")[:300]
        return f". Причина от OpenRouter: {text}" if text else ""
    except Exception:
        return ""


def request_json(path, key, timeout, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(API + path, data=data, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    started = time.monotonic()
    try:
        deadline = started + timeout
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            return json.loads(read_until(response, deadline))
    except urllib.error.HTTPError as exc:
        hint = {401: "проверь ключ", 402: "модель недоступна без оплаты; платного повтора не будет", 429: "исчерпана квота или провайдер занят; повтори позже"}.get(exc.code, "проверь доступность бесплатной модели")
        raise ModelError(f"OpenRouter HTTP {exc.code}: {hint}{provider_reason(exc)}") from None
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise ModelError("Python не доверяет сертификату HTTPS; на macOS запусти Install Certificates.command из папки Python") from None
        raise ModelError(f"Не удалось получить ответ OpenRouter за {time.monotonic() - started:.0f} с: сеть или timeout") from None
    except (TimeoutError, OSError):
        stage = "каталог моделей" if path == "/models" else "ответ модели"
        raise ModelError(f"Этап «{stage}»: нет ответа за {time.monotonic() - started:.0f} с (лимит {timeout:g} с); квота могла быть списана") from None
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


def user_content(payload, images=None):
    """Текст задания; при наличии кадров — части image_url с base64 data URL (схема OpenRouter)."""
    text = json.dumps(payload, ensure_ascii=False)
    if not images:
        return text
    parts = [{"type": "text", "text": text}]
    for image in images:
        parts.append({"type": "text", "text": image["label"]})
        encoded = base64.b64encode(image["data"]).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{image['mime']};base64,{encoded}"}})
    return parts


def chat_json(system, payload, *, model_env="TEXT_MODEL_NAME", vision=False, schema=None, schema_name="cutcraft_plan", images=None,
              max_tokens=2200, reasoning=None):
    if images and not vision:
        raise ModelError("Изображения можно отправлять только модели, проверенной на image input")
    key, model, timeout = settings(model_env)
    metadata = request_json("/models", key, timeout)
    found = check_free_model(metadata.get("data", []), model, vision=vision)
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content(payload, images)}], "max_tokens": max_tokens, "temperature": 0.2}
    if reasoning:
        # Настройки рассуждений OpenRouter, например {"max_tokens": 3000} — бюджет, чтобы на ответ остались токены.
        # Для моделей без рассуждений OpenRouter параметр пропускает. Текст рассуждений в ответ не включаем.
        body["reasoning"] = {**reasoning, "exclude": True}
    if schema is not None and "structured_outputs" in found.get("supported_parameters", []):
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
    elif "response_format" in found.get("supported_parameters", []):
        body["response_format"] = {"type": "json_object"}
    response = request_json("/chat/completions", key, timeout, body)
    if response.get("error"):
        raise ModelError("OpenRouter сообщил об ошибке модели")
    try:
        choice = response["choices"][0]
        if choice.get("finish_reason") == "length":
            usage = response.get("usage") or {}
            reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            partial = (choice.get("message") or {}).get("content") or ""
            raise ModelError(f"Ответ модели обрезан лимитом max_tokens={max_tokens} (рассуждения: {reasoning_tokens if reasoning_tokens is not None else 'нет данных'} токенов, "
                             f"текст ответа: {len(partial)} символов); результат не принят", partial=partial, usage=usage)
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
