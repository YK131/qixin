"""Create a five-pose contact sheet for the pendulum animation."""

from __future__ import annotations

import math
import sys
import tempfile
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.db import Store  # noqa: E402
from qixin.pet import DesktopPet, pendulum_angle  # noqa: E402
from qixin.theme import detect_ui_scale, enable_high_dpi  # noqa: E402


def main() -> None:
    enable_high_dpi()
    temporary = tempfile.TemporaryDirectory(prefix="qixin-sway-shot-")
    store = Store(Path(temporary.name) / "sway.db")
    root = tk.Tk()
    root.withdraw()
    pet = DesktopPet(root, store, detect_ui_scale(root))
    poses = [0, 9, 18, 27, 36]
    labels = ["中心", "左摆 45°", "回到中心", "右摆 45°", "回到中心"]
    tile = 286
    sheet = Image.new("RGBA", (tile * len(poses), 370), "#F7F3EB")
    draw = ImageDraw.Draw(sheet)
    try:
        caption_font = ImageFont.truetype("C:/Windows/Fonts/NotoSansSC-VF.ttf", 20)
    except OSError:
        caption_font = ImageFont.load_default()
    for index, (pose, label) in enumerate(zip(poses, labels)):
        progress = pose / 36
        wave = math.cos(2 * math.pi * 2.25 * progress) * math.exp(-3.8 * progress)
        frame = pet._compose_frame(
            1 + 0.115 * wave,
            1 - 0.19 * wave,
            5.2 * wave,
            pendulum_angle(progress),
        )
        bbox = frame.getchannel("A").getbbox()
        if bbox:
            frame = frame.crop(bbox)
        frame.thumbnail((240, 280), Image.Resampling.LANCZOS)
        x = index * tile + (tile - frame.width) // 2
        sheet.alpha_composite(frame, (x, 300 - frame.height))
        draw.text(
            (index * tile + tile // 2, 330),
            label,
            font=caption_font,
            fill="#284B3E",
            anchor="mm",
        )
    target = ROOT / "screenshots" / "11-pet-sway.png"
    sheet.convert("RGB").save(target)
    print(f"saved {target}: {sheet.size}")
    pet.close()
    store.close()
    root.destroy()
    temporary.cleanup()


if __name__ == "__main__":
    main()
