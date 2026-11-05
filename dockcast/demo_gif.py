"""Assemble the README demo GIF from timestamped frames (``make demo-gif``, PRD 17 M18).

``web/scripts/demo-frames.mjs`` saves ``<index>_<elapsed ms>.png`` while it drives the live site;
each GIF frame lasts until the next frame's timestamp, so the GIF plays at real speed.
"""

import argparse
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from PIL import Image

MAX_COLOURS = 128


def frame_durations(stamps: Sequence[int], last_ms: int = 1500) -> list[int]:
    """Display time of each frame in ms: the gap to the next timestamp (``last_ms`` for the last).

    Args:
        stamps: Elapsed milliseconds of each frame, in order.
        last_ms: How long the final frame stays on screen.

    Returns:
        One duration per frame, at least 20 ms (GIF players clamp shorter delays).
    """
    gaps = [b - a for a, b in pairwise(stamps)]
    return [max(20, gap) for gap in gaps] + [last_ms] if stamps else []


def build_gif(frames_dir: Path, out: Path, width: int = 720) -> int:
    """Write ``out`` from the PNG frames in ``frames_dir``, scaled to ``width`` pixels.

    Returns:
        The number of frames written.
    """
    paths = sorted(frames_dir.glob("*_*.png"))
    if not paths:
        raise FileNotFoundError(f"no frames in {frames_dir}")
    stamps = [int(p.stem.split("_")[1]) for p in paths]
    images = []
    for path in paths:
        with Image.open(path) as image:
            height = round(image.height * width / image.width)
            small = image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
            images.append(small.quantize(MAX_COLOURS, method=Image.Quantize.MEDIANCUT))
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=frame_durations(stamps),
        loop=0,
        optimize=True,
    )
    return len(images)


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m dockcast.demo_gif <frames-dir> <out.gif>``."""
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--width", type=int, default=720)
    args = parser.parse_args(argv)
    count = build_gif(args.frames, args.out, args.width)
    print(f"{count} frames -> {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
