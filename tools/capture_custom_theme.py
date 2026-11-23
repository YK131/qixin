"""Render a custom background/icon example for visual QA."""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.db import Store  # noqa: E402
from qixin.ui import QixinApp  # noqa: E402


def main() -> None:
    temporary = tempfile.TemporaryDirectory(prefix="qixin-theme-shot-")
    folder = Path(temporary.name)
    background = Image.new("RGB", (1600, 1000), "#E7EADB")
    draw = ImageDraw.Draw(background)
    draw.ellipse((80, 520, 690, 1180), fill="#C7D5C0")
    draw.ellipse((760, -220, 1540, 620), fill="#E6D3A8")
    draw.polygon([(0, 630), (430, 260), (830, 690), (1260, 220), (1600, 600), (1600, 1000), (0, 1000)], fill="#A9C3AE")
    draw.ellipse((1230, 580, 1500, 850), fill="#E8C373")
    background_path = folder / "background.png"
    background.save(background_path)

    store = Store(folder / "demo.db", demo=True)
    store.add_custom_mood("被DDL追着跑", "#66778F")
    store.add_mood("被DDL追着跑", "写论文", "多云", 16)
    store.add_schedule("交课程大作业", date.today(), "23:30", "不要再改标题了")
    store.set_setting("custom_background_path", str(background_path))
    store.set_setting("custom_icon_path", str(ROOT / "qixin" / "assets" / "pet_default.png"))
    app = QixinApp(store, demo=True)
    app.root.attributes("-topmost", True)
    app.show_page("calendar")

    def prepare() -> None:
        if app._floating is not None:
            app._floating.window.withdraw()
        if app._pet is not None:
            app._pet.close()
            app._pet = None
        app._draw_sidebar()

    def capture() -> None:
        app.root.update_idletasks()
        image = ImageGrab.grab(window=app.root.winfo_id())
        target = ROOT / "screenshots" / "12-custom-theme.png"
        image.save(target)
        print(f"saved {target}: {image.size}")
        app._on_close()
        temporary.cleanup()

    app.root.after(700, prepare)
    app.root.after(850, capture)
    app.root.mainloop()


if __name__ == "__main__":
    main()
