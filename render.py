"""Статический отчёт запуска без веб-сервера: история шагов, решения критика, было → стало, раскадровка.

Строится только из сохранённых файлов папки запуска, моделей не вызывает. Старый запуск можно перерисовать:
    python3 render.py output/<запуск> [--out report.html]
"""
import argparse
import base64
import html
import json
import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTORS = {"code": "Код оркестратора", "planner": "Монтажёр (LLM)", "reviewer": "Проверяющий (LLM с кадрами)"}
DEMO_ACTORS = {**ACTORS, "planner": "Монтажёр (демо: фиксированный ответ, без LLM)",
               "reviewer": "Проверяющий (демо: фиксированный ответ, без LLM)"}
STATES = {"done": "выполнено", "skipped": "пропущено", "error": "ошибка", None: "нет данных"}
STATUSES = {"accepted": "план принят проверяющим", "demo_accepted": "план принят (демо)",
            "needs_human_review": "нужна проверка человеком", "failed": "запуск завершился ошибкой"}
# Канонический порядок шагов: (stage, iteration, название).
STEPS = [("input", None, "Вход и каталог"), ("plan", 0, "Монтажёр составляет план"),
         ("plan_check", 0, "Проверка плана кодом"), ("review", 0, "Проверяющий оценивает план"),
         ("revise", 1, "Монтажёр исправляет замечания"), ("revision_check", 1, "Проверка исправления кодом"),
         ("review", 1, "Повторная проверка"), ("finish", None, "Результат")]
STEP_ACTORS = {"input": "code", "plan": "planner", "plan_check": "code", "review": "reviewer",
               "revise": "planner", "revision_check": "code", "finish": "code"}
# Где лежали каталоги до появления catalog_path; последний — снимок, на котором записаны прогоны docs/evidence/real_video.
CATALOG_GUESSES = ("data/catalog.json", "examples/catalog.json", "docs/evidence/real_video/catalog_1a8be59/catalog.json")
STEP_OUTPUTS = {("input", None): ["input.json"], ("plan_check", 0): ["plan_0.json"], ("review", 0): ["review_0.json"],
                ("revision_check", 1): ["plan_1.json"], ("review", 1): ["review_1.json"]}
esc = lambda v: html.escape(str(v))


def load(run_dir, name):
    path = run_dir / name
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def find_frames(data, catalog):
    """Кадры при перестройке отчёта. Каталог ищем по catalog_path из input.json, у старых запусков — среди
    CATALOG_GUESSES. Кадр берём, только если его сегмент в найденном каталоге совпадает с сохранённым в input.json:
    у разных каталогов совпадают имена файлов (frames/s1.jpg), и без сверки отчёт показал бы кадр другого сегмента."""
    sources = []
    for name in [data["catalog_path"]] if (data or {}).get("catalog_path") else CATALOG_GUESSES:
        path = ROOT / name
        try:
            segments = {s["segment_id"]: s for s in json.loads(path.read_text(encoding="utf-8"))["segments"]}
        except (OSError, ValueError, KeyError, TypeError):
            continue
        sources.append((path.parent.resolve(), segments))
    found = {}
    for segment in catalog["segments"] if catalog else ():
        base = next((b for b, segments in sources if segments.get(segment["segment_id"]) == segment), None)
        for name in segment["frame_paths"]:
            path = (base / name).resolve() if base else None
            found[name] = path if path and path.is_relative_to(base) and path.is_file() else None
    return found


def reconstruct(files):
    """Без events.json: этапы восстанавливаются по артефактам. Проверки кодом не выдумываем — «нет данных»."""
    events = []
    def add(stage, iteration, state, message=""):
        events.append({"stage": stage, "iteration": iteration, "state": state, "message": message,
                       "outputs": STEP_OUTPUTS.get((stage, iteration), [])})
    if files["input"]:
        add("input", None, "done")
    if files["plan_0"]:
        add("plan", 0, "done")
        events[-1]["outputs"] = ["plan_0.json"]  # Проверка кодом не записана, план показываем у монтажёра.
    if files["review_0"]:
        add("review", 0, "done")
        decisions = {i["decision"] for i in files["review_0"]["items"]}
        if not files["plan_1"] and (decisions == {"accept"} or "needs_human_review" in decisions):
            reason = "Все сцены приняты с первой проверки" if decisions == {"accept"} else "Проверяющий передал план человеку"
            for stage, iteration in (("revise", 1), ("revision_check", 1), ("review", 1)):
                add(stage, iteration, "skipped", reason)
    if files["plan_1"]:
        add("revise", 1, "done")
        events[-1]["outputs"] = ["plan_1.json"]
    if files["review_1"]:
        add("review", 1, "done")
    if files["status"]:
        add("finish", None, "error" if files["status"].get("status") == "failed" else "done")
    return events


def summary(stage, iteration, files):
    """Краткое описание входа и результата шага — только из сохранённых данных."""
    data, catalog = files["input"], (files["input"] or {}).get("catalog")
    plan, review = files.get(f"plan_{iteration}"), files.get(f"review_{iteration}")
    if stage == "input":
        if not catalog:
            return "Задание и путь к каталогу", "нет данных"
        return "Задание и каталог видео", f"{len(catalog['segments'])} фрагментов, источник {catalog['source_duration']} с"
    if stage == "plan":
        return "Задание и весь каталог: таймкоды и транскрипт, без кадров", scenes_line(plan)
    if stage == "plan_check":
        return "Черновик плана монтажёра", "сегменты существуют, границы, 20–30 с, дословные цитаты"
    if stage == "review":
        return ("Сцены с транскриптом своих фрагментов, неиспользованные фрагменты и кадры; обоснование монтажёра скрыто",
                decisions_line(iteration, review))
    if stage == "revise":
        return "Свой план и замечания проверяющего (plan_0.json, review_0.json)", changed_line(files)
    if stage == "revision_check":
        return "Исправленный план", "формат, границы и неизменность принятых сцен"
    status = (files["status"] or {}).get("status")
    return "Последняя проверка", STATUSES.get(status, "нет данных")


def scenes_line(plan):
    if not plan:
        return "нет данных"
    total = sum(s["source_end"] - s["source_start"] for s in plan["scenes"])
    return f"{len(plan['scenes'])} сцены, {total:.1f} с"


def review_groups(n, review):
    """Сцены проверки n по тому, что с ними сделал оркестратор: принятые и непустые группы остальных.
    На доработку уходят только замечания первой проверки и только если ни одну сцену не передали человеку:
    на needs_human_review main.py останавливается, а после повторной проверки доработок больше нет."""
    items = review["items"]
    accepted = [i["scene_id"] for i in items if i["decision"] == "accept"]
    human = [i["scene_id"] for i in items if i["decision"] == "needs_human_review"]
    fix = [i["scene_id"] for i in items if i["decision"] not in ("accept", "needs_human_review")]
    fix_label = ("замечания остались после доработки" if n == 1 else
                 "замечания без доработки, план передан человеку" if human else "отправлены на доработку")
    return accepted, [(label, ids) for label, ids in ((fix_label, fix), ("переданы человеку", human)) if ids]


def decisions_line(n, review):
    if not review:
        return "нет данных"
    accepted, others = review_groups(n, review)
    return "; ".join([f"принято {len(accepted)} из {len(review['items'])}"] + [f"{label}: {', '.join(ids)}" for label, ids in others])


def changed_line(files):
    before, after = files["plan_0"], files["plan_1"]
    if not before or not after:
        return "нет данных"
    old = {s["scene_id"]: s for s in before["scenes"]}
    changed = [s["scene_id"] for s in after["scenes"] if old.get(s["scene_id"]) != s]
    return "изменены: " + ", ".join(changed) if changed else "изменений нет"


def render_steps(events, files, demo=False):
    # Действует последнее событие этапа: finish записан как done до построения отчёта,
    # и если отчёт не построился, следом идёт finish/error.
    by_key = {(event["stage"], event.get("iteration")): event for event in events}
    rows = []
    for stage, iteration, title in STEPS:
        event = by_key.get((stage, iteration))
        state = event["state"] if event else None
        given, result = summary(stage, iteration, files)
        if state in ("error", "skipped") and event.get("message"):
            result = event["message"]
        elif state is None:
            result = "нет данных"
        artifacts = [n for n in (event or {}).get("outputs", []) if n.endswith(".json") and files.get(n[:-5]) is not None]
        dumps = "".join(f'<details><summary>{esc(n)}</summary><pre>{esc(json.dumps(files[n[:-5]], ensure_ascii=False, indent=2))}</pre></details>'
                        for n in artifacts)
        rows.append(f'<li class="step {esc(state or "none")}"><div class="head"><b>{esc(title)}</b>'
                    f'<span class="badge {esc(state or "none")}">{esc(STATES[state])}</span></div>'
                    f'<div class="who">{esc((DEMO_ACTORS if demo else ACTORS)[STEP_ACTORS[stage]])}</div>'
                    f'<p><span class="k">Вход:</span> {esc(given)}</p><p><span class="k">Результат:</span> {esc(result)}</p>{dumps}</li>')
    return f'<ol class="steps">{"".join(rows)}</ol>'


def render_reviews(files):
    blocks = []
    for n, title in ((0, "Первая проверка"), (1, "Повторная проверка")):
        review = files.get(f"review_{n}")
        if not review:
            continue
        rows = "".join(f'<tr><td>{esc(i["scene_id"])}</td><td><span class="badge {"done" if i["decision"] == "accept" else "error"}">{esc(i["decision"])}</span></td>'
                       f'<td>{esc(i["issue"]) or "—"}</td><td>{esc(i["evidence"]) or "—"}</td><td>{esc(i["requested_change"]) or "—"}</td></tr>'
                       for i in review["items"])
        accepted, others = review_groups(n, review)
        groups = "".join(f" {label[0].upper()}{label[1:]}: {esc(', '.join(ids))}." for label, ids in others)
        blocks.append(f'<h3>{title} · review_{n}.json</h3><p>Приняты: {esc(", ".join(accepted) or "—")}.{groups}</p>'
                      f'<div class="scroll"><table><tr><th>Сцена</th><th>Решение</th><th>Проблема</th><th>Свидетельство</th><th>Что изменить</th></tr>{rows}</table></div>')
    return "".join(blocks) or "<p>Нет данных: проверка не сохранена.</p>"


def render_diff(files):
    before, after = files["plan_0"], files["plan_1"]
    if not before or not after:
        return ""
    fields = (("Заголовок", lambda s: s["caption"]), ("Сегмент", lambda s: s["segment_id"]),
              ("Таймкоды", lambda s: f'{s["source_start"]}–{s["source_end"]} с'), ("Цитата", lambda s: s["source_quote"]))
    new = {s["scene_id"]: s for s in after["scenes"]}
    rows = []
    for scene in before["scenes"]:  # Сопоставление по scene_id, а не по позиции в списке.
        other = new.get(scene["scene_id"])
        for label, get in fields:
            old_value = get(scene)
            new_value = get(other) if other else "сцены нет в plan_1"
            cell = (f'<td colspan="2" class="same">{esc(old_value)} <i>без изменений</i></td>' if old_value == new_value
                    else f'<td class="old">{esc(old_value)}</td><td class="new">{esc(new_value)}</td>')
            rows.append(f'<tr><td>{esc(scene["scene_id"])}</td><td>{label}</td>{cell}</tr>')
    return (f'<h2>Было → стало</h2><p>plan_0.json → plan_1.json, по scene_id.</p><div class="scroll"><table>'
            f'<tr><th>Сцена</th><th>Поле</th><th>Было</th><th>Стало</th></tr>{"".join(rows)}</table></div>')


def render_storyboard(files, frames):
    catalog = (files["input"] or {}).get("catalog")
    n = 1 if files["plan_1"] else 0
    plan, review = files.get(f"plan_{n}"), files.get(f"review_{n}")
    if not plan or not catalog:
        return "<h2>Итоговая раскадровка</h2><p>Нет данных: план не сохранён.</p>"
    lookup = {s["segment_id"]: s for s in catalog["segments"]}
    remarks = {x["scene_id"]: x for x in (review or {}).get("items", [])}
    cards, missing = [], False
    for scene in plan["scenes"]:
        imgs = []
        for name in lookup[scene["segment_id"]]["frame_paths"]:
            f = frames.get(name)
            if f is None:
                missing = True
                imgs.append(f'<div class="nofile">Кадр недоступен: {esc(name)}</div>')
                continue
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            imgs.append(f'<img src="data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}" alt="Кадр {esc(scene["scene_id"])}">')
        r = remarks.get(scene["scene_id"])
        verdict = (f'<b>{esc(r["decision"])}</b>' + "".join(f'<p><span class="k">{k}:</span> {esc(r[f])}</p>'
                   for k, f in (("Проблема", "issue"), ("Свидетельство", "evidence"), ("Что изменить", "requested_change")) if r[f])
                   if r else "<b>нет проверки</b>")
        cards.append(f'<article>{"".join(imgs)}<h3>{esc(scene["scene_id"])} · {esc(scene["segment_id"])} · {esc(scene["source_start"])}–{esc(scene["source_end"])} с</h3>'
                     f'<p class="caption">{esc(scene["caption"])}</p><blockquote>{esc(scene["source_quote"])}</blockquote>{verdict}</article>')
    note = ("<p>Часть кадров не показана: каталог этого запуска не найден или с тех пор изменился, "
            "а кадры другого каталога отчёт не подставляет.</p>" if missing else "")
    return f'<h2>Итоговая раскадровка · plan_{n}.json</h2>{note}<section class="cards">{"".join(cards)}</section>'


def render_outcome(files, events):
    status = files["status"] or {}
    state = status.get("status")
    if state in ("accepted", "demo_accepted"):
        return "<p>Все сцены приняты проверяющим.</p>"
    if state == "needs_human_review":
        last = files["review_1"] or files["review_0"]
        items = [i for i in (last or {}).get("items", []) if i["decision"] != "accept"]
        rows = "".join(f'<li><b>{esc(i["scene_id"])}</b> ({esc(i["decision"])}): {esc(i["issue"])}</li>' for i in items)
        why = ("После доработки замечания остались, а автоматический цикл ограничен одной доработкой. Решение за человеком."
               if files["review_1"] else "Проверяющий сразу передал план человеку, автоматическая доработка не запускалась.")
        return f"<p>{why} Оставшиеся замечания:</p><ul>{rows}</ul>"
    if state == "failed":
        # Восстановленное событие finish (без seq) лишь фиксирует ошибку, места сбоя оно не знает.
        failed = next((e for e in events if e["state"] == "error" and (e["stage"] != "finish" or "seq" in e)), None)
        where = next((t for s, i, t in STEPS if failed and (s, i) == (failed["stage"], failed.get("iteration"))), None)
        return (f'<p>Место сбоя: <b>{esc(where or "нет данных")}</b>.</p>'
                f'<p>Ошибка: {esc(status.get("error_type", ""))}: {esc(status.get("message", ""))}</p>'
                "<p>Ниже показано всё, что успели сохранить до сбоя.</p>")
    return "<p>Нет данных: status.json отсутствует.</p>"


def render_report(run_dir, frames=None, path=None):
    run_dir = Path(run_dir)
    names = ("input", "status", "events", "plan_0", "review_0", "plan_1", "review_1")
    files = {n: load(run_dir, f"{n}.json") for n in names}
    data = files["input"] or {}
    catalog = data.get("catalog")
    frames = frames if frames is not None else find_frames(data, catalog)
    journal = (files["events"] or {}).get("events")
    events = journal if journal is not None else reconstruct(files)
    status = (files["status"] or {}).get("status")
    demo = data.get("mode", (files["status"] or {}).get("mode")) == "demo"
    notes = []
    if demo:
        notes.append("ДЕМО: ответы монтажёра и проверяющего зашиты в код, ошибка в заголовке внесена специально. LLM не вызывались, это показ цикла, а не работы моделей.")
    elif data.get("mode") == "live":
        # Не утверждаем, что модели ответили: запуск мог упасть до первого ответа.
        used = data.get("models") or {}
        names = "; ".join(f"{role}: {used[key]}" for role, key in (("монтажёр", "planner"), ("проверяющий", "reviewer")) if used.get(key))
        notes.append("Живой запуск: роли выполняют модели OpenRouter" + (f" ({names})" if names else "") + ".")
    if catalog:
        notes.append("Кадры и транскрипт — из настоящего видео." if catalog["assets_are_real"]
                     else "Материалы условные; это не стоп-кадры из видео.")
    if journal is None:
        notes.append("Подробный журнал (events.json) отсутствует: шаги восстановлены по сохранённым plan/review, "
                     "проверки кодом помечены «нет данных».")
    body = (f'<h1>CutCraft — история запуска</h1><aside class="{"demo" if demo else "live"}">{"<br>".join(esc(n) for n in notes)}</aside>'
            f'<dl><dt>Задание</dt><dd>{esc(data.get("task", "нет данных"))}</dd>'
            f'<dt>Режим</dt><dd>{"демо" if demo else esc(data.get("mode", "нет данных"))}</dd>'
            f'<dt>Статус</dt><dd><b>{esc(status or "нет данных")}</b> — {esc(STATUSES.get(status, "нет данных"))}</dd>'
            f'<dt>Время</dt><dd>{esc((files["status"] or {}).get("seconds", "нет данных"))} с на весь запуск</dd></dl>'
            f'<h2>Шаги</h2>{render_steps(events, files, demo)}<h2>Решения проверяющего</h2>{render_reviews(files)}'
            f'{render_diff(files)}{render_storyboard(files, frames)}<h2>Итог</h2>{render_outcome(files, events)}')
    (Path(path) if path else run_dir / "report.html").write_text(f'<!doctype html><html lang="ru"><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>CutCraft</title><style>{CSS}</style><body>{body}</body></html>',
        encoding="utf-8")


CSS = """
:root{--bg:#f4f5f7;--card:#fff;--text:#1d1f23;--muted:#5f6670;--line:#d9dce1;--warn:#fff1bd;--live:#e3f1ff;
--ok:#1f7a3f;--ok-bg:#e1f4e7;--err:#a32020;--err-bg:#fbe3e3;--skip:#6b6f76;--skip-bg:#eceef1;--old:#fdeaea;--new:#e6f6ea}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--card:#202329;--text:#e7e9ec;--muted:#a3a9b2;--line:#363a42;
--warn:#4a3f12;--live:#14324d;--ok:#7ad69a;--ok-bg:#183524;--err:#ff9a9a;--err-bg:#421c1c;--skip:#b0b4bb;--skip-bg:#2c3037;--old:#3d1f22;--new:#1b3624}}
body{font:16px/1.45 system-ui,sans-serif;max-width:1150px;margin:0 auto;padding:24px 16px;background:var(--bg);color:var(--text)}
aside{padding:12px 16px;border-radius:10px;background:var(--live)}aside.demo{background:var(--warn)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px}dt{color:var(--muted)}dd{margin:0}
.steps{list-style:none;padding:0;display:grid;gap:8px;counter-reset:s}
.step{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--skip);border-radius:8px;padding:10px 14px}
.step.done{border-left-color:var(--ok)}.step.error{border-left-color:var(--err)}.step p{margin:4px 0}
.head{display:flex;justify-content:space-between;gap:8px}.who,.k{color:var(--muted)}.who{font-size:14px}
.badge{font-size:13px;padding:1px 8px;border-radius:99px;background:var(--skip-bg);color:var(--skip);white-space:nowrap}
.badge.done{background:var(--ok-bg);color:var(--ok)}.badge.error{background:var(--err-bg);color:var(--err)}
details{margin-top:6px}summary{cursor:pointer;color:var(--muted)}pre{white-space:pre-wrap;word-break:break-word;font-size:13px;max-height:420px;overflow:auto;background:var(--bg);padding:8px;border-radius:6px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card)}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
td.old{background:var(--old)}td.new{background:var(--new)}td.same i{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
article{background:var(--card);padding:16px;border-radius:12px}article p{margin:6px 0}.caption{font-weight:600}
img{width:100%;max-height:220px;object-fit:contain}.nofile{padding:24px;text-align:center;border:1px dashed var(--line);color:var(--muted)}
blockquote{margin:12px 0;border-left:3px solid var(--muted);padding-left:12px}
"""


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Перерисовать отчёт по сохранённой папке запуска (без моделей)")
    p.add_argument("run", type=Path, help="папка запуска, например output/<время>")
    p.add_argument("--out", type=Path, help="куда записать HTML (по умолчанию <папка>/report.html)")
    a = p.parse_args()
    render_report(a.run, path=a.out)
    print(a.out or a.run / "report.html")
