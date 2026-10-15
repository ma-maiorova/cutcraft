"""Показывает актуальные бесплатные (:free) модели OpenRouter с image input. Ключ не нужен, квоту не тратит."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_client import API, ModelError, check_free_model


def main():
    try:
        with urllib.request.urlopen(API + "/models", timeout=30) as response:
            models = json.load(response).get("data", [])
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            print("Python не доверяет сертификату HTTPS. На macOS с Python с python.org выполните один раз:\n"
                  f'  "/Applications/Python {sys.version_info.major}.{sys.version_info.minor}/Install Certificates.command"', file=sys.stderr)
        else:
            print(f"Не удалось получить каталог OpenRouter: {exc.reason}", file=sys.stderr)
        return 1
    rows = []
    for m in models:
        if not m.get("id", "").endswith(":free"):
            continue
        try:
            check_free_model(models, m["id"], vision=True)
        except ModelError:
            continue
        params = m.get("supported_parameters", [])
        rows.append((m["id"], m.get("context_length"), "structured_outputs" in params, "response_format" in params))
    if not rows:
        print("Бесплатных моделей с image input сейчас не найдено.")
        return 1
    print("id | context | structured_outputs | response_format")
    for row in sorted(rows, key=lambda r: (not r[2], not r[3], r[0])):
        print(" | ".join(str(x) for x in row))
    print("\nВпиши выбранный id в VISION_MODEL_NAME локального .env. Модели выше в списке поддерживают строгий JSON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
