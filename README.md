# CutCraft

CutCraft делает короткий ролик из длинного видео. Вы пишете, о чём должен быть ролик. Монтажёр (LLM) выбирает три фрагмента и пишет к ним заголовки, проверяющий (LLM с изображениями) сверяет их с транскриптом и кадрами. Если он находит ошибку, монтажёр исправляет только эту сцену. На выходе — план ролика (`report.html`) и готовое вертикальное видео (`short.mp4`).

## Документация

- [Project proposal](docs/PROJECT_PROPOSAL.md): проблема, MVP, архитектура, что проверено.
- [Порядок показа демо](docs/DEMO_GUIDE.md).
- [Контракты 1.0](docs/CONTRACTS.md), [JSON Schema](schemas/), [архитектурные решения](docs/adr/README.md).
- [Источник данных](data/SOURCE.md) и [контрольные примеры](examples/).
- Результаты проверок: [монтажёр](docs/evidence/planner/README.md), [проверяющий](docs/evidence/reviewer/README.md), [полный цикл на реальном видео](docs/evidence/real_video/README.md).
- [Инструкции по модулям](blocks/) и [страница истории запуска](docs/RUN_HISTORY_UI.md).

## Установка

```bash
git clone https://github.com/cemouse/cutcraft.git
cd cutcraft
cp .env.example .env
```

Впишите ключ OpenRouter в `OPENROUTER_API_KEY` в `.env` и положите нужное видео в папку `media/`.

## Запуск через Docker

```bash
docker compose build
docker compose -f compose.yaml -f compose.live.yaml run --rm app
```

То же без Compose:

```bash
docker build -t cutcraft:local .
docker run --rm --env-file .env --user "$(id -u):$(id -g)" -v "$PWD/output:/app/output" -v "$PWD/media:/app/media:ro" cutcraft:local python scripts/demo.py --live
```

Ключ передаётся только при запуске. Другие папки для результатов и видео задаются через `CUTCRAFT_OUTPUT` и `CUTCRAFT_MEDIA`.

Запуск с контрольной ошибкой: код подменяет первый заголовок на заведомо ложный, проверяющий должен это поймать. Все решения моделей остаются реальными.

```bash
docker compose -f compose.yaml -f compose.live.yaml run --rm app python scripts/demo.py --live --controlled-defect
```

## Что на выходе

Каждый запуск создаёт папку `output/<timestamp>/`:

| Файл | Что это |
|---|---|
| `report.html` | план ролика: задание и статус, шаги цикла, решения проверяющего, «было → стало» и итоговая раскадровка |
| `short.mp4` | видео 9:16 по итоговому плану: заголовок сцены сверху, дословные субтитры снизу |
| `*.json` | служебные данные запуска, из которых собраны отчёт и видео |

Статусы: `accepted` — план принят; `needs_human_review` — замечания остались после исправления, решение за человеком; `failed` — ошибка модели или формата.

## Зачем LLM, две роли и OpenRouter

LLM выбирает фрагменты по смыслу задания и формулирует короткие заголовки; мультимодальный проверяющий сопоставляет текст с транскриптом и кадрами. В отличие от арифметики таймкодов, эта задача требует смысловой интерпретации. Один вызов модели остаётся возможным baseline: преимущество цикла с критиком ещё предстоит измерить сравнительным экспериментом.

В шаблоне обе роли используют `nvidia/nemotron-3.5-super-vl:free` через OpenRouter: эта модель принимает изображения, доступна через выбранный бесплатный маршрут и дала сохранённые успешные прогоны на нашем видео.

## Без Docker

Нужны Python 3.10+, ffmpeg и Pillow. Остальной код использует только стандартную библиотеку.

```bash
python3 scripts/demo.py --live
```

Задание по умолчанию — «Объясни за 30 секунд, почему учёные уверены, что был Большой взрыв», другое задаётся через `--task`.

## Настройки `.env`

| Переменная | Значение |
|---|---|
| `OPENROUTER_API_KEY` | ключ OpenRouter |
| `TEXT_MODEL_NAME` | модель монтажёра |
| `VISION_MODEL_NAME` | модель проверяющего, должна принимать изображения; кандидаты: `python3 scripts/list_free_vision_models.py` |
| `OPENROUTER_FREE_ONLY` | `true`: клиент пускает только ID с `:free` и нулевой ценой |
| `MODEL_TIMEOUT_SECONDS` | лимит на один запрос, 1–120 с |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` |

Переменные окружения важнее `.env`. Платного запасного варианта и автоматических повторов нет: при ошибке 429 запуск останавливается и пишет причину. Полный прогон тратит 2–4 запроса из дневной квоты.

## Как устроено

```text
scripts/demo.py
  → main.run
      → build_plan(task, catalog)                  монтажёр
      → validate_plan                              код
      → review_plan(task, catalog, plan, frames)   проверяющий, видит кадры
      → revise_plan(...) при замечаниях            монтажёр
      → validate_revision, повторная проверка      код и проверяющий
      → events.json, history.json, status.json, report.html
  → render_short.render                            видео по итоговому плану
```

| Модуль | Что делает |
|---|---|
| `planner.py` | создаёт план и исправляет его по замечаниям |
| `reviewer.py` | проверяет сцены по транскрипту и кадрам; аргументов монтажёра не видит |
| `model_client.py` | ходит в OpenRouter: настройки, бесплатные модели, картинки, лимит времени, разбор JSON |
| `contracts.py`, `schemas/` | проверяют форму, ссылки, таймкоды, цитаты и правила доработки |
| `main.py` | порядок шагов, один раунд исправления, статусы, журнал |
| `render.py` | HTML-отчёт |
| `scripts/demo.py` | запуск: цикл, затем сборка видео |
| `scripts/render_short.py` | видео по итоговому плану, моделей не вызывает |

Оркестратор — обычный код: порядок шагов и лимиты известны заранее. Всё работает в одном процессе и одном контейнере, модели вызываются по API ([ADR-0005](docs/adr/0005-single-container.md), [ADR-0006](docs/adr/0006-shorts-in-container.md)).

Каталог описывает фрагменты одного видео: `segment_id`, `start`, `end`, `transcript`, `frame_paths`. Сейчас это 15 фрагментов интервью Бориса Штерна с настоящими кадрами. План — ровно три сцены на 20–30 секунд, у каждой заголовок и дословная цитата. Проверка — одно решение на сцену. Подробности в [контрактах](docs/CONTRACTS.md).

## Проверка

```bash
python3 -m unittest discover -s tests -v
python3 main.py --demo
```

67 тестов. Демо проходит цикл на фиксированных ответах без ключа и показывает механику, а не работу моделей. Живые проверки отдельных ролей: `scripts/check_planner_live.py` и `scripts/check_reviewer_live.py`, [результаты монтажёра](docs/evidence/planner/README.md) и [проверяющего](docs/evidence/reviewer/README.md). Перед PR — [skill проверки](.agents/skills/cutcraft-pr-preflight/SKILL.md).

## Команда

| Участник | GitHub | Модуль |
|---|---|---|
| Марина | [cemouse](https://github.com/cemouse) | [монтажёр](blocks/planner/README.md) |
| Артём | [Anelessar](https://github.com/Anelessar) | [данные и видео](blocks/data/README.md) |
| Галим | [GGalim-AG](https://github.com/GGalim-AG) | [проверяющий](blocks/reviewer/README.md) |
| Кирилл | [KirillRatner](https://github.com/KirillRatner) | [оркестрация](blocks/orchestrator/README.md) |

## Ограничения

Транскрипт и нарезка готовятся заранее. Проверяющий видит стоп-кадры и не слышит звук. Обе роли работают на одной модели, поэтому проверка не полностью независима. Ответы моделей меняются от запуска к запуску; сохранённые прогоны — примеры, а не оценка надёжности. Верность источнику не означает проверку фактов.
