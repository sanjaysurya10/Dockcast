"""Demo GIF assembly from timestamped frames."""

from pathlib import Path

import pytest
from PIL import Image

from dockcast.demo_gif import build_gif, frame_durations

pytestmark = pytest.mark.unit


def test_durations_follow_the_timestamps() -> None:
    assert frame_durations([0, 150, 160, 400], last_ms=1000) == [150, 20, 240, 1000]
    assert frame_durations([]) == []


def test_gif_keeps_every_frame_and_its_timing(tmp_path: Path) -> None:
    for index, (stamp, colour) in enumerate([(0, "red"), (200, "green"), (500, "blue")]):
        Image.new("RGB", (100, 60), colour).save(tmp_path / f"{index:04d}_{stamp}.png")
    out = tmp_path / "demo.gif"
    assert build_gif(tmp_path, out, width=50) == 3
    with Image.open(out) as gif:
        assert gif.size == (50, 30)
        assert gif.n_frames == 3
        assert gif.info["duration"] == 200
