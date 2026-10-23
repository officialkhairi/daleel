"""Turns the frames from e2e/scripts/record-demo.mjs into docs/demo/daleel.gif.

    uv run --no-project --with pillow python docs/demo/make-gif.py <frames-dir>

Identical consecutive frames are merged, long waits for the model are shortened, and the
palette is shared across frames to keep the file small.
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageChops

WIDTH = 960
MAX_STILL_MS = 1600  # a frame that doesn't change for longer than this is shortened
OUT = Path(__file__).with_name("daleel.gif")


def main(frames_dir: Path) -> None:
    timings = json.loads((frames_dir / "timings.json").read_text())
    frames: list[Image.Image] = []
    durations: list[int] = []
    previous = None
    for entry in timings:
        image = Image.open(frames_dir / entry["file"]).convert("RGB")
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
        if previous is not None and ImageChops.difference(image, previous).getbbox() is None:
            durations[-1] += entry["ms"]
            continue
        frames.append(image)
        durations.append(entry["ms"])
        previous = image
    durations = [min(d, MAX_STILL_MS) for d in durations]
    durations[-1] = 3000

    palette = frames[len(frames) // 2].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    quantized[0].save(
        OUT, save_all=True, append_images=quantized[1:], duration=durations, loop=0, optimize=True
    )
    total = sum(durations) / 1000
    size = OUT.stat().st_size / 1e6
    print(f"{OUT}: {len(frames)} frames, {total:.0f} s, {size:.1f} MB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
