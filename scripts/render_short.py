"""Превью шортса по итоговому плану запуска: 9:16, заголовок сцены сверху, дословные субтитры снизу.

Не входит в агентный цикл и не вызывает модели: собирает видео по уже готовому плану.
Нужны ffmpeg, Pillow (`pip install pillow`) и исходное видео (ссылка в data/SOURCE.md).

    python3 scripts/render_short.py --video ~/Downloads/shtern_big_bang.mp4
    python3 scripts/render_short.py --run output/20261015-213955-154054 --video ... --out short.mp4
"""
import argparse
import difflib
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Нужен Pillow: pip install pillow")

ROOT = Path(__file__).resolve().parents[1]
W, H = 1080, 1920
FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf"]


def font(size):
    for path in FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    sys.exit("Не найден шрифт с кириллицей: добавьте путь в FONTS")


def text_png(path, text, size, width_chars, box_alpha):
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


def render(run_dir, video, transcript, out):
    status = json.loads((run_dir / "status.json").read_text()).get("status")
    if status not in ("accepted", "needs_human_review"):
        sys.exit(f"Запуск {run_dir.name} завершился статусом {status}: собирать нечего")
    if status != "accepted":
        print("Внимание: план не принят проверяющим полностью (needs_human_review)")
    segments = {s["segment_id"]: s for s in json.loads((run_dir / "input.json").read_text())["catalog"]["segments"]}
    plan_file = sorted(run_dir.glob("plan_*.json"))[-1]
    plan = json.loads(plan_file.read_text())
    words = [w for s in json.loads(transcript.read_text())["segments"] for w in s["words"]]
    tmp = Path(tempfile.mkdtemp())
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
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(video), *inputs,
                        "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a", "-c:v", "libx264", "-preset", "fast",
                        "-crf", "20", "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(clip)], check=True)
        clips.append(clip)
        print(f"Сцена {n}: {scene['segment_id']} {start}–{end} с — «{scene['caption']}»")
    (tmp / "list.txt").write_text("".join(f"file '{c}'\n" for c in clips))
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c", "copy",
                    "-movflags", "+faststart", str(out)], check=True)
    print(f"План {plan_file.relative_to(ROOT) if plan_file.is_relative_to(ROOT) else plan_file} → {out}")


def main():
    runs = sorted((ROOT / "output").glob("*/status.json"))
    parser = argparse.ArgumentParser(description="Превью шортса 9:16 по итоговому плану запуска")
    parser.add_argument("--run", type=Path, default=runs[-1].parent if runs else None, help="папка запуска в output/ (по умолчанию последняя)")
    parser.add_argument("--video", type=Path, required=True, help="исходное видео (в Git не хранится)")
    parser.add_argument("--transcript", type=Path, default=ROOT / "data/transcript.json", help="транскрипт Whisper с пословными таймкодами")
    parser.add_argument("--out", type=Path, help="куда сохранить MP4 (по умолчанию <run>/short.mp4)")
    args = parser.parse_args()
    if args.run is None:
        sys.exit("Нет запусков в output/: сначала python3 main.py ...")
    render(args.run.resolve(), args.video.expanduser(), args.transcript, args.out or args.run / "short.mp4")


if __name__ == "__main__":
    main()
