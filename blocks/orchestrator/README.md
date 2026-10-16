# Кирилл — оркестрация, инфраструктура и результат

Ответственный: [KirillRatner](https://github.com/KirillRatner).

## Что менять

`main.py`, `render.py`, `contracts.py` (согласованно), общий клиент `model_client.py`, `scripts/demo.py`, `Dockerfile`, `compose*.yaml`, `.env.example` и инструкции запуска.

## Что уже работает

Часть задач этого блока сделали другие участники, пока шла интеграция:

- общий клиент OpenRouter с загрузкой `.env`, проверкой бесплатности модели, лимитом времени и передачей изображений (Марина и Галим);
- цепочка `build_plan → проверки кодом → review_plan → revise_plan → validate_revision → review_plan` с одним раундом доработки и статусами `accepted`, `needs_human_review`, `failed`;
- модели в `.env.example`: `nvidia/nemotron-3.5-super-vl:free` для обеих ролей;
- полный цикл на реальном видео и `report.html` с настоящими кадрами (15 октября, [результаты](../../docs/evidence/real_video/README.md)).

## Задачи

- [x] Страница истории запуска: этапы, входы и выходы, решения критика, сравнение до и после ([описание и приёмка](../../docs/RUN_HISTORY_UI.md)).
- [x] Журнал запуска `events.json`: каждый шаг цикла записывается по ходу работы.
- [x] Показывать в `report.html` поле `evidence` из замечаний критика.
- [x] Запуск в одном Docker-контейнере и через Compose ([ADR-0005](../../docs/adr/0005-single-container.md)).
- [x] Скрипт показа `scripts/demo.py` с живым запуском и режимом контрольной ошибки.

## Запуск

Основной способ — Docker:

```bash
docker compose build
docker compose -f compose.yaml -f compose.live.yaml run --rm app
```

Результат — план (`report.html`) и видео (`short.mp4`) в `output/<timestamp>/`. Если модель недоступна, статус `failed`.

Без Docker:

```bash
python3 main.py --demo                     # фиксированные ответы, без ключа
python3 -m unittest discover -s tests -v
python3 scripts/demo.py --live             # живой запуск и видео
```

Всё работает локально, модели вызываются по API. VM, база данных, GPU и запуск Claude Code или Codex внутри приложения не нужны.

## Для защиты

Почему оркестратор — код, а не LLM. Как цикл останавливается. Что сохраняется в папке запуска. Чем демо отличается от живого запуска. Почему один контейнер, а не сервис на каждую роль.
