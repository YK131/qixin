"""Render the weekly reflection dialog for visual QA."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.db import Store  # noqa: E402
from qixin.services import local_weekly_report  # noqa: E402
from qixin.theme import enable_high_dpi  # noqa: E402
from qixin.ui import QixinApp, WeeklyReportDialog  # noqa: E402


def main() -> None:
    enable_high_dpi()
    temp_dir = Path(tempfile.mkdtemp(prefix="qixin-report-"))
    store = Store(temp_dir / "report.db", demo=True)
    app = QixinApp(store, demo=True)
    app.root.geometry("+20+20")
    stats = store.weekly_stats()
    dialog = WeeklyReportDialog(app, stats, local_weekly_report(stats))
    dialog.window.attributes("-topmost", True)
    dialog.show()

    def capture() -> None:
        app.root.update_idletasks()
        dialog.window.update_idletasks()
        x = dialog.window.winfo_rootx()
        y = dialog.window.winfo_rooty()
        w = dialog.window.winfo_width()
        h = dialog.window.winfo_height()
        image = ImageGrab.grab(bbox=(x, y - 32, x + w, y + h))
        target = ROOT / "screenshots" / "06-weekly-report.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f"saved {target}: {image.size}")
        app._on_close()

    app.root.after(650, capture)
    app.root.mainloop()


if __name__ == "__main__":
    main()
