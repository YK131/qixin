"""Render the food spinner after one completed spin."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.db import Store  # noqa: E402
from qixin.ui import QixinApp  # noqa: E402


def main() -> None:
    temporary = tempfile.TemporaryDirectory(prefix="qixin-food-shot-")
    store = Store(Path(temporary.name) / "demo.db")
    app = QixinApp(store)
    app.root.attributes("-topmost", True)
    app._open_food_wheel()
    dialog = app._food_wheel
    if dialog is None:
        raise RuntimeError("food wheel failed to open")
    dialog.window.attributes("-topmost", True)
    dialog.window.lift()

    def spin() -> None:
        dialog.spin()

    def capture() -> None:
        app.root.update_idletasks()
        image = ImageGrab.grab(window=dialog.window.winfo_id())
        target = ROOT / "screenshots" / "09-food-wheel.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f"saved {target}: {image.size}")
        dialog.close()
        app._on_close()
        temporary.cleanup()

    app.root.after(450, spin)
    app.root.after(3750, capture)
    app.root.mainloop()


if __name__ == "__main__":
    main()
