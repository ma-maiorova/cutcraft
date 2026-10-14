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
