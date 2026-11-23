"""Render the add-schedule dialog."""

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
    temporary = tempfile.TemporaryDirectory(prefix="qixin-schedule-shot-")
    store = Store(Path(temporary.name) / "demo.db", demo=True)
    app = QixinApp(store, demo=True)
    app.root.attributes("-topmost", True)
    app._open_schedule_dialog()
    dialog = app._schedule_dialog
    if dialog is None:
        raise RuntimeError("schedule dialog failed to open")
    dialog.window.attributes("-topmost", True)
    dialog.window.lift()

    def capture() -> None:
        app.root.update_idletasks()
        image = ImageGrab.grab(window=dialog.window.winfo_id())
        target = ROOT / "screenshots" / "13-add-schedule.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f"saved {target}: {image.size}")
        dialog.close()
        app._on_close()
        temporary.cleanup()

    app.root.after(500, capture)
    app.root.mainloop()


if __name__ == "__main__":
    main()
