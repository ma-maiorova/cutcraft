# Общие контракты 1.0

## Каталог (`examples/catalog.json`)
- `schema_version`: "1.0"
- `source_duration`: положительное число секунд
- `assets_are_real`: boolean; false для условных карточек
- `segments`: объекты с уникальным `segment_id`, числовыми start/end, transcript, непустым frame_paths.
- Пути кадров относительны файлу каталога, не могут выходить из его папки.

## План (`examples/plan.json`)
- `schema_version`: "1.0"
- `scenes`: ровно три объекта; уникальные scene_id и segment_id.
- Поля сцены: scene_id, segment_id, source_start, source_end, caption, source_quote, selection_reason.
- Длительность вычисляет код; сумма 20–30 секунд. Кадры берём из каталога по segment_id.

## Проверка (`examples/review.json`)
- `schema_version`: "1.0"
- `items`: ровно одно решение для каждой сцены.
- Поля: scene_id, decision, issue, evidence, requested_change.
- decision: accept / revise_caption / replace_segment / adjust_bounds / needs_human_review.
- Для замечаний текстовые поля непустые; для accept допускается пустая строка.

## Интерфейсы Python

```python
build_plan(task, catalog, *, demo=False) -> dict
revise_plan(task, catalog, plan, review, *, demo=False) -> dict
review_plan(task, catalog, plan, frames, *, demo=False) -> dict
```

`frames` — словарь `путь из каталога -> pathlib.Path`. Реальный адаптер reviewer сам читает картинки для API. Передача локального пути в prompt не передаёт картинку модели.
Агенты возвращают данные, не записывают output. Состоянием и выводом управляет main.py.

Пример review содержит намеренное замечание к подписи первого плана. После исправления проверяющий должен принять исправленную сцену или привести новую конкретную причину отказа.

## Машиночитаемые контракты

- `schemas/catalog.schema.json`
- `schemas/plan.schema.json`
- `schemas/review.schema.json`

JSON Schema Draft 2020-12 описывает форму и обязательные поля. В версии 1.0 неизвестные поля запрещены; расширения согласуются командой.
`contracts.py` дополнительно проверяет связи между файлами: существование сегментов, уникальность ID, границы, суммарные 20–30 секунд, точную цитату, полноту review и сохранение принятых сцен. Эти межфайловые условия нельзя полностью выразить отдельной JSON Schema.

`validate_revision(before, after, review, catalog)` — единая проверка доработки. `validate_task` проверяет непустое задание до вызова API. Если все сцены приняты, модель не вызывается; needs_human_review завершает автоматическую доработку.
Не меняйте файлы `examples/` под свой контент: они служат неизменными контрольными примерами. Реальный каталог Артёма хранится в `data/`.

Приёмка модуля Марины: build_plan и revise_plan возвращают словари по контракту; неизвестные ID/нарушенные границы/изменение принятой сцены отклоняются; состояние ошибки не маскируется результатом демо. Техническая валидность не доказывает смысловую точность.
