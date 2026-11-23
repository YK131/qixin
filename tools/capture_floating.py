"""Render the floating wisdom card on its own for presentation."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.floating import FloatingWisdom  # noqa: E402
from qixin.theme import VisualKit, detect_ui_scale, enable_high_dpi  # noqa: E402


def main() -> None:
    enable_high_dpi()
    root = tk.Tk()
    root.withdraw()
    scale = detect_ui_scale(root)
    background = tk.Toplevel(root)
    background.overrideredirect(True)
    background.geometry(
        f"{round(590 * scale)}x{round(450 * scale)}+20+20"
    )
    background.configure(bg="#F5F0E7")
    kit = VisualKit(root, scale)
    canvas = tk.Canvas(
        background,
        width=round(590 * scale),
        height=round(450 * scale),
        bg="#F5F0E7",
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(fill="both", expand=True)
    canvas.create_image(
        0,
        0,
        anchor="nw",
        image=kit.background(round(590 * scale), round(450 * scale)),
    )
    background.attributes("-topmost", True)
    floating = FloatingWisdom(root, kit, 8)
    floating.window.geometry(
        f"+{round(70 * scale)}+{round(82 * scale)}"
    )
    root.update()
    floating.window.attributes("-topmost", True)
    floating.window.lift()

    def capture() -> None:
        root.update()
        x = floating.window.winfo_rootx()
        y = floating.window.winfo_rooty()
        w = floating.window.winfo_width()
        h = floating.window.winfo_height()
        image = ImageGrab.grab(bbox=(x - 8, y - 8, x + w + 8, y + h + 8))
        target = ROOT / "screenshots" / "05-floating.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f"saved {target}: {image.size}")
        floating.window.destroy()
        background.destroy()
        root.destroy()

    root.after(650, capture)
    root.mainloop()


if __name__ == "__main__":
    main()
