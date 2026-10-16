"""Превью шортса по итоговому плану запуска: 9:16, заголовок сцены сверху, дословные субтитры снизу.

Не входит в агентный цикл и не вызывает модели: собирает видео по уже готовому плану.
Нужны ffmpeg, Pillow (`pip install pillow`) и исходное видео (ссылка в data/SOURCE.md).
В Docker всё это уже есть, а `scripts/demo.py` вызывает сборку сам, если видео подключено.

    python3 scripts/render_short.py --video ~/Downloads/shtern_big_bang.mp4
    python3 scripts/render_short.py --run output/20261015-213955-154054 --video ... --out short.mp4
"""
import argparse
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W, H = 1080, 1920
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf"]
RENDERABLE = ("accepted", "needs_human_review")


class RenderError(RuntimeError):
    """Видео не собрать: нет зависимостей, файлов или подходящего плана."""


def final_plan(run_dir):
    """Итоговый план — последний plan_N.json. plan_generated.json и прочие служебные копии не берём."""
    plans = [f for f in run_dir.glob("plan_*.json") if f.stem.split("_", 1)[1].isdigit()]
    if not plans:
        raise RenderError(f"В {run_dir} нет plan_N.json")
    return max(plans, key=lambda f: int(f.stem.split("_", 1)[1]))


def check_ready(run_dir, video, transcript):
    """Проверить всё до запуска ffmpeg, чтобы ошибка была понятной."""
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8")).get("status")
    if status not in RENDERABLE:
        raise RenderError(f"Запуск завершился статусом {status}: собирать нечего")
    if not Path(video).is_file():
        raise RenderError(f"Нет исходного видео: {video}")
    if not Path(transcript).is_file():
        raise RenderError(f"Нет транскрипта: {transcript}")
    if shutil.which("ffmpeg") is None:
        raise RenderError("Не найден ffmpeg")
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise RenderError("Нужен Pillow: pip install pillow") from None
    return status


def font(size):
    from PIL import ImageFont
    for path in FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RenderError("Не найден шрифт с кириллицей: добавьте путь в FONTS")


def text_png(path, text, size, width_chars, box_alpha):
    from PIL import Image, ImageDraw
    face = font(size)
    lines = textwrap.wrap(text, width_chars)
    line_h = int(size * 1.25)
    img = Image.new("RGBA", (W, line_h * len(lines) + 60), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([30, 0, W - 30, img.height], radius=28, fill=(0, 0, 0, box_alpha))
    for i, line in enumerate(lines):
        width = draw.textlength(line, font=face)
        draw.text(((W - width) / 2, 30 + i * line_h), line, font=face, fill="white", stroke_width=3, stroke_fill="black")
    img.save(path)


def subtitle_chunks(words, start, end, text, size=5):
    """Тайминги — пословные таймкоды Whisper, текст — исправленный транскрипт каталога. Субтитры не перекрываются."""
    seg = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    raw, fixed = "".join(w["word"] for w in seg).split(), text.split()
    fixes = {" ".join(raw[a1:a2]): " ".join(fixed[b1:b2])
             for op, a1, a2, b1, b2 in difflib.SequenceMatcher(a=raw, b=fixed).get_opcodes() if op == "replace"}
    parts = [seg[i:i + size] for i in range(0, len(seg), size)]
    for n, part in enumerate(parts):
        chunk = "".join(w["word"] for w in part).strip()
        for wrong, right in fixes.items():
            chunk = chunk.replace(wrong, right)
        shown_from = 0 if n == 0 else part[0]["start"] - start
        shown_to = parts[n + 1][0]["start"] - start - 0.04 if n + 1 < len(parts) else end - start
        yield chunk, shown_from, shown_to


def render(run_dir, video, transcript=ROOT / "data/transcript.json", out=None, log=print):
    """Собрать short.mp4 по итоговому плану запуска. Возвращает путь к видео; при проблеме — RenderError."""
    run_dir, video, transcript = Path(run_dir), Path(video), Path(transcript)
    out = Path(out) if out else run_dir / "short.mp4"
    status = check_ready(run_dir, video, transcript)
    if status != "accepted":
        log("Внимание: план не принят проверяющим полностью (needs_human_review)")
    segments = {s["segment_id"]: s for s in json.loads((run_dir / "input.json").read_text(encoding="utf-8"))["catalog"]["segments"]}
    plan_file = final_plan(run_dir)
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    words = [w for s in json.loads(transcript.read_text(encoding="utf-8"))["segments"] for w in s["words"]]
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        clips = []
        for n, scene in enumerate(plan["scenes"], 1):
            start, end = scene["source_start"], scene["source_end"]
            text_png(tmp / f"cap{n}.png", scene["caption"], 66, 24, 170)
            inputs = ["-i", str(tmp / f"cap{n}.png")]
            graph = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25[bg];"
                     "[b]scale=1080:-2[fg];[bg][fg]overlay=0:(H-h)/2[v0];[v0][1:v]overlay=0:230[v1]")
            last = "v1"
            chunks = subtitle_chunks(words, start, end, segments[scene["segment_id"]]["transcript"])
            for k, (text, shown_from, shown_to) in enumerate(chunks, 2):
                text_png(tmp / f"sub{n}_{k}.png", text, 54, 30, 120)
                inputs += ["-i", str(tmp / f"sub{n}_{k}.png")]
                graph += f";[{last}][{k}:v]overlay=0:1450:enable='between(t,{shown_from:.2f},{shown_to:.2f})'[v{k}]"
                last = f"v{k}"
            clip = tmp / f"clip{n}.mp4"
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(video), *inputs,
                                "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a", "-c:v", "libx264", "-preset", "fast",
                                "-crf", "20", "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(clip)], check=True)
            except subprocess.CalledProcessError:
                raise RenderError(f"ffmpeg не смог собрать сцену {n}") from None
            clips.append(clip)
            log(f"Сцена {n}: {scene['segment_id']} {start}–{end} с — «{scene['caption']}»")
        (tmp / "list.txt").write_text("".join(f"file '{c}'\n" for c in clips))
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c", "copy",
                            "-movflags", "+faststart", str(out)], check=True)
        except subprocess.CalledProcessError:
            raise RenderError("ffmpeg не смог склеить сцены") from None
    log(f"План {plan_file.name} → {out}")
    return out


def main():
    # Последний запуск по времени, включая output/presentation-*/current из scripts/demo.py.
    runs = sorted((ROOT / "output").glob("**/status.json"), key=lambda f: f.stat().st_mtime)
    parser = argparse.ArgumentParser(description="Превью шортса 9:16 по итоговому плану запуска")
    parser.add_argument("--run", type=Path, default=runs[-1].parent if runs else None,
                        help="папка запуска (по умолчанию последняя по времени, включая output/presentation-*/current)")
    parser.add_argument("--video", type=Path, required=True, help="исходное видео (в Git не хранится)")
    parser.add_argument("--transcript", type=Path, default=ROOT / "data/transcript.json", help="транскрипт Whisper с пословными таймкодами")
    parser.add_argument("--out", type=Path, help="куда сохранить MP4 (по умолчанию <run>/short.mp4)")
    args = parser.parse_args()
    if args.run is None:
        sys.exit("Нет запусков в output/: сначала python3 main.py ...")
    try:
        render(args.run.resolve(), args.video.expanduser(), args.transcript, args.out)
    except RenderError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
