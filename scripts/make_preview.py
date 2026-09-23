"""Build the README animation from the generated Lucas-Kanade track videos.

From the repository root::

    python -m pip install -r requirements-preview.txt
    python scripts/make_preview.py

Playback uses source timestamps at normal speed. The shorter video repeats while
the longer video finishes; use --shorter hold to freeze its final frame instead.
Both panes have the same size and preserve the videos' original aspect ratios.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = "#101827"
FOREGROUND = "#e7eef8"
MUTED = "#aab9ce"


class Video:
    """Read a source frame at a playback timestamp without changing its speed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not self.capture.isOpened() or self.fps <= 0 or self.count <= 0:
            self.capture.release()
            raise ValueError(f"Cannot read a valid video: {path}")
        self.duration = self.count / self.fps
        self.next_index = 0
        self.last_index = -1
        self.last_frame: Image.Image | None = None

    def frame_at(self, seconds: float, shorter: str) -> Image.Image:
        index = int(seconds * self.fps)
        index = index % self.count if shorter == "loop" else min(index, self.count - 1)
        if index == self.last_index and self.last_frame is not None:
            return self.last_frame
        if index < self.next_index:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            self.next_index = index
        while self.next_index <= index:
            ok, frame = self.capture.read()
            if not ok:
                raise ValueError(f"Could not decode frame {self.next_index}: {self.path}")
            self.next_index += 1
        self.last_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.last_index = index
        return self.last_frame

    def close(self) -> None:
        self.capture.release()


def render_frame(
    ants: Image.Image,
    shapes: Image.Image,
    width: int,
    footer: str,
) -> Image.Image:
    """Place equally sized, letterboxed panes under readable dataset labels."""
    margin = max(8, round(width / 80))
    gap = margin
    pane_width = (width - 2 * margin - gap) // 2
    pane_height = round(pane_width * 3 / 4)
    header_height = round(width * 0.071)
    footer_height = round(width * 0.043)
    canvas = Image.new("RGB", (width, header_height + pane_height + footer_height), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default(size=max(14, round(width * 0.022)))
    note_font = ImageFont.load_default(size=max(10, round(width * 0.015)))
    for index, (label, source) in enumerate((("ANTS", ants), ("SHAPES", shapes))):
        x = margin + index * (pane_width + gap)
        draw.text((x, round(width * 0.014)), label, fill=FOREGROUND, font=title_font)
        draw.text((x, round(width * 0.043)), "Lucas-Kanade tracks", fill=MUTED, font=note_font)
        fitted = ImageOps.contain(source, (pane_width, pane_height), Image.Resampling.LANCZOS)
        draw.rectangle((x, header_height, x + pane_width - 1, header_height + pane_height - 1), fill="black")
        canvas.paste(fitted, (x + (pane_width - fitted.width) // 2, header_height + (pane_height - fitted.height) // 2))
    draw.text((margin, header_height + pane_height + margin), footer, fill=MUTED, font=note_font)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ants", type=Path, default=ROOT / "out/videos/ants/lk_tracks.avi")
    parser.add_argument("--shapes", type=Path, default=ROOT / "out/videos/shapes/lk_tracks.avi")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/assets/lk-tracks.gif")
    parser.add_argument("--width", type=int, default=960, help="total animation width in pixels (default: 960)")
    parser.add_argument("--fps", type=int, choices=(5, 10, 20, 25, 50), default=10, help="GIF sampling rate; source playback speed is unchanged")
    parser.add_argument("--duration", type=float, help="seconds to show; defaults to the longer source's duration")
    parser.add_argument("--shorter", choices=("loop", "hold"), default="loop", help="repeat shorter source or hold its last frame (default: loop)")
    args = parser.parse_args()
    if args.width < 480:
        parser.error("--width must be at least 480 for legible labels")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("--duration must be positive and finite")

    videos: list[Video] = []
    try:
        videos = [Video(args.ants)]
        videos.append(Video(args.shapes))
        duration = args.duration or max(video.duration for video in videos)
        shortest_index = min(range(2), key=lambda index: videos[index].duration)
        shortest = videos[shortest_index]
        name = ("Ants", "Shapes")[shortest_index]
        action = "repeats" if args.shorter == "loop" else "holds its last frame"
        footer = f"Normal playback speed  |  {name} {action} after {shortest.duration:.2f}s"
        frames = [
            render_frame(*(video.frame_at(index / args.fps, args.shorter) for video in videos), args.width, footer)
            for index in range(math.ceil(duration * args.fps))
        ]
    finally:
        for video in videos:
            video.close()

    # One palette across all frames avoids color flicker. Include every frame in
    # a reduced contact sheet so track colors from either clip are represented.
    sample_width = 240
    sample_height = round(frames[0].height * sample_width / frames[0].width)
    samples = Image.new("RGB", (sample_width, sample_height * len(frames)))
    for index, frame in enumerate(frames):
        samples.paste(frame.resize((sample_width, sample_height)), (0, index * sample_height))
    palette = samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        args.output,
        save_all=True,
        append_images=quantized[1:],
        duration=1000 // args.fps,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"Saved {args.output}: {frames[0].width}x{frames[0].height}, {len(frames) / args.fps:.2f}s, {args.fps} fps, {args.output.stat().st_size / 1024 / 1024:.2f} MiB")
    print(footer)


if __name__ == "__main__":
    main()
