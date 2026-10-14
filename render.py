"""Простая статическая раскадровка без веб-сервера."""
import base64
import html
import mimetypes


def render_report(path, task, catalog, history, status, frames, demo):
    esc = lambda v: html.escape(str(v))
    blocks = []
    lookup = {s["segment_id"]: s for s in catalog["segments"]}
    for iteration, entry in enumerate(history):
        cards = []
        remarks = {x["scene_id"]: x for x in entry["review"]["items"]}
        for scene in entry["plan"]["scenes"]:
            imgs = []
            for name in lookup[scene["segment_id"]]["frame_paths"]:
                f = frames[name]
                mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                data = base64.b64encode(f.read_bytes()).decode()
                imgs.append(f'<img src="data:{mime};base64,{data}" alt="Кадр {esc(scene["scene_id"])}">')
            r = remarks[scene["scene_id"]]
            cards.append(f'<article>{"".join(imgs)}<h3>{esc(scene["scene_id"])} · {scene["source_start"]}–{scene["source_end"]} с</h3><p>{esc(scene["caption"])}</p><blockquote>{esc(scene["source_quote"])}</blockquote><b>{esc(r["decision"])}</b><p>{esc(r["issue"])}</p><p>{esc(r["requested_change"])}</p></article>')
        blocks.append(f'<h2>Версия {iteration + 1}</h2><section>{"".join(cards)}</section>')
    warning = "ДЕМО: фиксированные ответы, специально внесённая ошибка и условные SVG-карточки. LLM и визуальная проверка не подключены." if demo else "Рабочий режим; качество проверки зависит от подключённых моделей."
    assets = "Материалы помечены как настоящие" if catalog["assets_are_real"] else "Материалы условные; это не стоп-кадры из видео"
    path.write_text(f'<!doctype html><html lang="ru"><meta charset="utf-8"><title>CutCraft</title><style>body{{font:16px system-ui;max-width:1150px;margin:32px auto;padding:16px;background:#f4f5f7}}section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}article{{background:white;padding:16px;border-radius:12px}}img{{width:100%;max-height:220px;object-fit:contain}}aside{{background:#fff1bd;padding:16px}}blockquote{{margin:12px 0;border-left:3px solid #888;padding-left:12px}}</style><h1>CutCraft — раскадровка</h1><aside>{esc(warning)}<br>{esc(assets)}</aside><p>Задание: {esc(task)}</p><p>Статус: <b>{esc(status)}</b></p>{"".join(blocks)}</html>', encoding="utf-8")
