"""Render the demo pages to PNG for visual QA and presentation screenshots."""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qixin.db import Store  # noqa: E402
from qixin.news import NewsService  # noqa: E402
from qixin.notes import note_from_text  # noqa: E402
from qixin.ui import QixinApp  # noqa: E402


def fetch_news_with_timeout(seconds: float = 50.0):
    """Fetch news off the UI thread so a slow network cannot freeze capture."""

    box: dict[str, object] = {}

    def worker() -> None:
        try:
            box["feed"] = NewsService().fetch(force=True)
        except Exception as exc:  # pragma: no cover - screenshots must not fail
            box["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(seconds)
    return box.get("feed")


def _work_dir() -> Path:
    """A writable scratch directory (some sandboxes reject 0700 temp dirs)."""

    try:
        candidate = Path(tempfile.mkdtemp(prefix="qixin-shot-"))
        probe = candidate / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        fallback = ROOT / ".shots"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def screenshot(app: QixinApp, target: Path, lift_root: bool = True) -> None:
    app.root.attributes("-topmost", True)
    if lift_root:
        app.root.lift()
    app.root.update_idletasks()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        window_image = ImageGrab.grab(window=app.root.winfo_id())
        sample = window_image.convert("RGB").resize((1, 1)).getpixel((0, 0))
        if window_image.width >= 500 and window_image.height >= 400 and max(sample) > 20:
            window_image.save(target)
            print(f"saved {target.name}: window capture {window_image.size}")
            return
    except (OSError, ValueError):
        pass
    x = app.root.winfo_rootx()
    y = app.root.winfo_rooty()
    w = app.root.winfo_width()
    h = app.root.winfo_height()
    screen = ImageGrab.grab()
    # Fallback for systems where direct window capture is unavailable.
    scale = screen.width / app.root.winfo_screenwidth()
    left = max(0, round((x - 11) * scale))
    top = max(0, round((y - 32) * scale))
    bbox = (
        left,
        top,
        min(screen.width, round((x + w) * scale) + 4),
        min(screen.height, round((y + h + 4) * scale)),
    )
    screen.crop(bbox).save(target)
    print(f"saved {target.name}: {bbox}")


def main() -> None:
    temp_dir = _work_dir()
    store = Store(temp_dir / "demo.db", demo=True)
    if not store.get_setting("demo_note_seeded"):
        note_from_text(
            store,
            "今天在九龙湖的窗边读完了两章书，风把纸吹得沙沙响。\n"
            "临走在便签上写了一句：把难的事拆成今天迈得动的一小步。",
            title="窗边的下午",
        )
        note_from_text(
            store,
            "晚课之后绕操场走了三圈，耳机里没有放歌，只是听脚步声。",
            title="操场三圈",
        )
        store.set_setting("demo_note_seeded", "1")

    app = QixinApp(store, demo=True)
    app.root.attributes("-topmost", True)
    output = ROOT / "screenshots"

    print("fetching news before capture…", flush=True)
    feed = fetch_news_with_timeout()
    if feed is not None:
        app.news_feed = feed
        print(
            f"news ready: live={feed.live} items={len(feed.items)}",
            flush=True,
        )
    else:
        print("news unavailable, capturing whatever the app shows", flush=True)

    app.root.after(
        260,
        lambda: app._floating.window.withdraw()
        if app._floating is not None
        else None,
    )

    def hide_pet_for_page_shot() -> None:
        if app._pet is not None:
            app._pet.close()
            app._pet = None
            app._draw_sidebar()

    def prepare_news() -> None:
        # Already fetched before the mainloop started; nothing blocking here.
        return None

    steps = [
        ("01-home.png", "today"),
        ("02-music.png", "music"),
        ("03-calendar.png", "calendar"),
        ("03b-calendar-agenda.png", "calendar@agenda"),
        ("04-settings.png", "settings"),
        ("07-essay.png", "essay"),
        ("08-news.png", "news"),
    ]

    def capture_step(index: int) -> None:
        if index >= len(steps):
            app._on_close()
            return
        name, page = steps[index]
        if page == "calendar@agenda":
            app._set_calendar_view("agenda")
        else:
            if app.calendar_view != "month":
                app._set_calendar_view("month")
            app.show_page(page)
        app.root.after(
            160,
            lambda: (
                screenshot(app, output / name),
                app.root.after(80, lambda: capture_step(index + 1)),
            ),
        )

    app.root.after(620, hide_pet_for_page_shot)
    app.root.after(700, prepare_news)
    app.root.after(900, lambda: capture_step(0))
    app.root.mainloop()


if __name__ == "__main__":
    main()
