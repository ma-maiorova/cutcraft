# Галим — проверяющий и редактор-критик

Ответственный: [GGalim-AG](https://github.com/GGalim-AG).

## Что менять

`reviewer.py`, `prompts/reviewer.txt`; контрольные примеры и тесты критика. Модуль остаётся в корне.

## Задачи

- [ ] Согласовать с Кириллом общий клиент API и модель с поддержкой изображений.
- [ ] Реализовать `review_plan(task, catalog, plan, frames, *, demo=False)`.
- [ ] Передавать модели текст и реальные байты PNG/JPEG по схеме провайдера. Словарь frames содержит pathlib.Path; простое перечисление путей картинку не передаёт.
- [ ] Вернуть JSON по `examples/review.json`, одно решение для каждой scene_id.
- [ ] Для отклонения указать issue, evidence, requested_change; отделить искажение источника от редакторского совета.
- [ ] Проверить корректный пример, подпись с потерянной оговоркой и неподходящий кадр. Записать пропуски и ложные отказы.
- [ ] Не заявлять анализ звука/движения, если модели переданы только кадры.

## Проверка отдельно

После подключения модели и настройки окружения, из корня:

```python
import json
from pathlib import Path
from main import resolve_frames
from contracts import validate_review
from reviewer import review_plan
p = Path("data/catalog.json").resolve()
catalog = json.loads(p.read_text())
plan = json.load(open("examples/plan.json"))  # заменить подходящим планом для нового каталога
frames = resolve_frames(catalog, p.parent)
review = validate_review(review_plan("Объясни результат и ограничения", catalog, plan, frames), plan)
```

## Передать

Функцию, prompt, конфигурацию, контрольные примеры и результаты. Реальную визуальную проверку нельзя заменять демонстрационным сравнением строки из текущей заглушки.
