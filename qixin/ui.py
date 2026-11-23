from __future__ import annotations

from .files import write_text_atomic

import calendar
import math
import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from tkinter import filedialog, messagebox, simpledialog
from tkinter import font as tkfont
from typing import Any, Callable

from PIL import Image, ImageOps, ImageTk

from .audio import AmbientPlayer
from .appearance import prepare_background, prepare_icon
from .content import (
    ACTIVITIES,
    MOOD_ORDER,
    MOODS,
    QUOTES,
    TRACK_BY_ID,
    care_note,
    quote_at,
    quote_for_day,
    quote_index,
    recommend_tracks,
    task_wisdom,
    time_bucket,
    track_reason,
)
from .db import Store, quote_by_id
from .desktop_tools import DesktopTools
from .floating import FloatingWisdom, show_quote_detail
from .food_wheel import FoodWheelDialog
from .layout import Block, TextMeter, fit_text
from .mood_editor import CustomMoodDialog
from .motion import MotionEngine
from .news import (
    SIGNUP_TIMEZONE, SOURCE_SAMPLE, NewsFeed, NewsItem, NewsService,
    reminder_items, signup_cutoff, signup_link, signup_opening,
)
from .notes import Note, NoteEditorDialog, list_notes
from .pages_calendar import draw_calendar
from .pages_music import draw_music
from .pages_settings import CONFIGURABLE_SECTIONS, draw_settings
from .pet import DesktopPet
from . import playlists
from .schedule_editor import DaySchedulesDialog, ScheduleDialog
from .services import (
    AIService,
    WeatherService,
    WeatherSnapshot,
    ai_context_preview,
    external_music_url,
    local_weekly_report,
)
from .theme import (
    COLORS,
    RADII,
    ScaledCanvas,
    VisualKit,
    detect_ui_scale,
    enable_high_dpi,
    font,
    get_font_scale,
    mix_color,
    set_font_scale,
    widget_font,
)
from .typography import FontLibrary


ROOT_WIDTH = 1600
ROOT_HEIGHT = 1000
SIDEBAR_WIDTH = 226
HEADER_HEIGHT = 94
PAGE_WIDTH = ROOT_WIDTH - SIDEBAR_WIDTH
PAGE_HEIGHT = ROOT_HEIGHT - HEADER_HEIGHT
SCROLL_FRAME_INTERVAL = 1 / 60
SCROLL_DURATION = 0.18


PAGE_HEADERS = {
    "today": ("把今天，过成一封慢慢读的信。", "今日栖居"),
    "music": ("不只推荐一首歌，而是理解你此刻的处境。", "情境歌单"),
    "calendar": ("情绪不是成绩单，是心留下的天气。", "情绪日历"),
    "essay": ("写下来，是把自己接住的一种方式。", "随笔记录"),
    "news": ("与你有关的事，先替你看着。", "今日新闻"),
    "settings": ("你的数据、接口与边界，都由你决定。", "数据与设置"),
}


# Stroke paths are drawn on the canvas so icons appear with any system font.
ICON_PATHS = {
    "today": (((-7, -1), (0, -7), (7, -1)), ((-5, -2), (-5, 6), (5, 6), (5, -2))),
    "calendar": (
        ((-6, -5), (6, -5), (6, 6), (-6, 6), (-6, -5)),
        ((-6, -1), (6, -1)), ((-3, -7), (-3, -3)), ((3, -7), (3, -3)),
    ),
    "music": (
        ((-3, 4), (-3, -5), (6, -7), (6, 2)),
        ((-3, 4), (-6, 5), (-6, 7), (-3, 6), (-3, 4)),
        ((6, 2), (3, 3), (3, 5), (6, 4), (6, 2)),
    ),
    "essay": (((-6, -5), (6, -5)), ((-6, 0), (6, 0)), ((-6, 5), (2, 5))),
    "news": (
        ((-6, -6), (6, -6), (6, 6), (-6, 6), (-6, -6)),
        ((-3, -2), (3, -2)), ((-3, 2), (3, 2)),
    ),
    "settings": (
        ((-6, -4), (6, -4)), ((-6, 4), (6, 4)),
        ((-2, -7), (-2, -1)), ((2, 1), (2, 7)),
    ),
    "pet_toggle": (
        ((-6, -2), (-5, -7), (-2, -5), (2, -5), (5, -7), (6, -2),
         (6, 4), (3, 6), (-3, 6), (-6, 4), (-6, -2)),
        ((-2, 0), (-2, 1)), ((2, 0), (2, 1)),
    ),
    "food_wheel_shortcut": (
        ((-7, 1), (-4, 6), (4, 6), (7, 1), (-7, 1)),
        ((-3, -1), (-3, -6)), ((2, -1), (2, -7)),
    ),
    "floating_toggle": (
        ((-6, -5), (6, -5), (6, 4), (-1, 4), (-4, 7), (-4, 4), (-6, 4), (-6, -5)),
        ((-3, -1), (3, -1)),
    ),
    "expand": (
        ((-6, -2), (-6, -6), (-2, -6)), ((2, -6), (6, -6), (6, -2)),
        ((-6, 2), (-6, 6), (-2, 6)), ((2, 6), (6, 6), (6, 2)),
    ),
    "collapse": (
        ((-6, -2), (-2, -2), (-2, -6)), ((2, -6), (2, -2), (6, -2)),
        ((-6, 2), (-2, 2), (-2, 6)), ((2, 6), (2, 2), (6, 2)),
    ),
}


class QixinApp:
    def __init__(self, store: Store, demo: bool = False):
        self.store = store
        self.demo = demo
        enable_high_dpi()
        self.root = tk.Tk()
        self.ui_scale = detect_ui_scale(self.root)
        self.font_library = FontLibrary(self.root, self.store)
        self.font_library.restore()
        self.font_scale = set_font_scale(
            self.store.get_setting("font_scale", "1.2")
        )
        self.root.title("栖心 · 东大人的数字解压阀")
        self.root.configure(bg=COLORS["paper"])
        self.root.resizable(True, True)
        self.root.option_add("*Font", widget_font(14, self.ui_scale))
        self.root.tk.call("tk", "scaling", 1.0)

        # Shell metrics are dynamic: the window can be resized or go fullscreen,
        # and every page lays itself out from these instead of module constants.
        self.sidebar_w = float(SIDEBAR_WIDTH)
        self.header_h = float(HEADER_HEIGHT)
        self.win_w = float(ROOT_WIDTH)
        self.win_h = float(ROOT_HEIGHT)
        self.page_w = float(PAGE_WIDTH)
        self.page_h = float(PAGE_HEIGHT)
        self._fullscreen = False
        self._resize_job: str | None = None
        self._set_window_metrics(*self._center_window())

        self.kit = VisualKit(self.root, self.ui_scale)
        self.motion = MotionEngine(self.root, self.kit, self.ui_scale)
        self.meter = TextMeter(self.root, self.ui_scale)
        self._scroll_job: str | None = None
        self._scroll_position = 0.0
        self._scroll_target = 0.0
        self._scroll_start = 0.0
        self._scroll_started = 0.0
        self._scroll_next_frame = 0.0
        self._scroll_limit = 0
        self._page_height_px = 1
        self._page_content_height = 0.0
        self._rendered_page: str | None = None
        self._sidebar_state: tuple[Any, ...] | None = None
        self._header_state: tuple[Any, ...] | None = None
        self._scroll_hint: tk.Label | None = None
        self._custom_icon_photo: ImageTk.PhotoImage | None = None
        self._custom_taskbar_icon: ImageTk.PhotoImage | None = None
        self._custom_background_source: Image.Image | None = None
        self._backdrop_layers: dict[tk.Canvas, ImageTk.PhotoImage] = {}
        self._bottom_glass: dict[tk.Canvas, ImageTk.PhotoImage] = {}
        self._load_appearance_assets()
        self.icon_photo = self._custom_taskbar_icon or self.kit.app_icon()
        self.root.iconphoto(True, self.icon_photo)

        self.current_page = "today"
        self._hidden_sections = CONFIGURABLE_SECTIONS.intersection(
            self.store.get_setting("hidden_sections").split(",")
        )
        self._task_entry: tk.Entry | None = None
        self._task_entry_placeholder = "写下一件今天愿意完成的小事…"
        self._task_buffer = ""
        self._toast_items: list[int] = []
        self._floating: FloatingWisdom | None = None
        self._pet: DesktopPet | None = None
        self._food_wheel: FoodWheelDialog | None = None
        self._mood_editor: CustomMoodDialog | None = None
        self._schedule_dialog: ScheduleDialog | None = None
        self._day_dialog: DaySchedulesDialog | None = None
        self._closing = False
        self._ui_jobs: set[str] = set()
        self._background_results: SimpleQueue = SimpleQueue()
        self._weather_request = 0
        self._audio_request = 0
        self._audio_loading_id: str | None = None

        today_quote = quote_for_day()
        self.quote_i = quote_index(today_quote)
        self.moods = dict(MOODS)
        self.mood_order = list(MOOD_ORDER)
        self._load_custom_moods()
        self.mood = "已老实"
        self.activity = "写论文"
        latest = self.store.latest_mood_for_day()
        if latest:
            self.mood = str(latest["mood"])
            self.activity = str(latest["activity"] or "写论文")

        self.player = AmbientPlayer()
        self.weather_service = WeatherService()
        self.ai = AIService()
        self.news_service = NewsService()
        self.news_feed = NewsFeed(
            items=[],
            fetched_at="",
            live=False,
            source_note="尚未同步",
            error="",
        )
        self._news_loading = False
        self._news_reminder_keys: tuple[str, ...] = ()
        self._signup_panel_keys: tuple[str, ...] = ()
        self._note_editor: NoteEditorDialog | None = None
        now = datetime.now()
        self.weather = WeatherSnapshot(
            self.weather_service.city,
            None,
            "多云",
            6 <= now.hour < 18,
            False,
            now,
        )

        self.music_mood = self.mood
        self.music_activity = self.activity
        self.weather_mode = "自动"
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.ai_music_busy = False

        self.calendar_anchor = date.today().replace(day=1)
        self.selected_day = date.today()
        self.calendar_view = self.store.get_setting("calendar_view", "month")
        if self.calendar_view not in {"month", "agenda"}:
            self.calendar_view = "month"

        # Start the canvases at the restored window size.
        self.sidebar_canvas = ScaledCanvas(
            self.root,
            ui_scale=self.ui_scale,
            width=round(self.sidebar_w * self.ui_scale),
            height=round(self.win_h * self.ui_scale),
            bg=COLORS["paper"],
            highlightthickness=0,
            bd=0,
        )
        self.sidebar_canvas.place(x=0, y=0)
        self.header_canvas = ScaledCanvas(
            self.root,
            ui_scale=self.ui_scale,
            width=round(self.page_w * self.ui_scale),
            height=round(self.header_h * self.ui_scale),
            bg=COLORS["paper"],
            highlightthickness=0,
            bd=0,
        )
        self.header_canvas.place(x=round(self.sidebar_w * self.ui_scale), y=0)
        self.page_canvas = ScaledCanvas(
            self.root,
            ui_scale=self.ui_scale,
            width=round(self.page_w * self.ui_scale),
            height=round(self.page_h * self.ui_scale),
            bg=COLORS["paper"],
            highlightthickness=0,
            bd=0,
        )
        self.page_canvas.place(
            x=round(self.sidebar_w * self.ui_scale),
            y=round(self.header_h * self.ui_scale),
        )
        for canvas in (self.sidebar_canvas, self.header_canvas, self.page_canvas):
            self.motion.attach(canvas)
        self.page_canvas.bind(
            "<Double-Button-1>",
            self._on_calendar_double_click,
            add="+",
        )
        self.page_canvas.bind("<ButtonPress-1>", self._stop_scroll, add="+")
        # On Windows Tk can deliver wheel events to the focused widget. Route
        # them by the pointer position and leave other windows' wheels alone.
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(sequence, self._on_page_wheel, add="+")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.resizable(True, True)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.minsize(
            min(round((SIDEBAR_WIDTH + 640) * self.ui_scale), screen_w),
            min(round(620 * self.ui_scale), int(screen_h * 0.72)),
        )
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.bind("<F11>", lambda _event: self._toggle_fullscreen())
        self.root.bind("<Escape>", lambda _event: self._exit_fullscreen())
        self.desktop_tools = DesktopTools(self)
        self.render()
        self._schedule_ui(300, self._show_floating)
        self._schedule_ui(520, self._show_pet_if_enabled)
        self._schedule_ui(150, self._refresh_weather)
        self._schedule_ui(900, self._refresh_news)
        self._schedule_ui(40, self._drain_background_results)
        self._schedule_ui(60_000, self._expire_news_reminders)
        self.root.bind_all("<Control-Alt-n>", self._capture_hotkey, add="+")
        self.root.bind_all("<Control-q>", lambda _event: self._on_close())

    # ------------------------------------------------------------ window shell

    def _schedule_ui(self, delay: int | None, callback: Callable[[], Any]) -> str:
        def run() -> None:
            self._ui_jobs.discard(job)
            if not self._closing:
                callback()

        job = self.root.after_idle(run) if delay is None else self.root.after(delay, run)
        self._ui_jobs.add(job)
        return job

    def _cancel_ui(self, job: str) -> None:
        self._ui_jobs.discard(job)
        self.root.after_cancel(job)

    def _drain_background_results(self) -> None:
        try:
            for _ in range(20):
                try:
                    callback = self._background_results.get_nowait()
                except Empty:
                    break
                try:
                    callback()
                except Exception:
                    self.root.report_callback_exception(*sys.exc_info())
                if self._closing:
                    break
        finally:
            if not self._closing:
                self._schedule_ui(40, self._drain_background_results)

    def _run_background(self, work, ready, failed) -> None:
        def worker() -> None:
            try:
                result = work()
            except Exception as exc:
                message = str(exc)
                self._background_results.put(lambda: failed(message))
            else:
                self._background_results.put(lambda: ready(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_window_configure(self, event: tk.Event[Any]) -> None:
        if event.widget is not self.root or self._closing:
            return
        if self._resize_job is not None:
            try:
                self._cancel_ui(self._resize_job)
            except tk.TclError:
                pass
        # Debounce: dragging a window edge fires dozens of events.
        self._resize_job = self._schedule_ui(90, self._after_window_resize)

    def _after_window_resize(self) -> None:
        self._resize_job = None
        if self._closing:
            return
        if self._sync_shell_geometry():
            self.meter.invalidate()
            self.render()

    def _sync_shell_geometry(self) -> bool:
        """Re-fit the three canvases to the current window size."""

        device_w = self.root.winfo_width()
        device_h = self.root.winfo_height()
        if device_w <= 1 or device_h <= 1:
            return False
        if (device_w, device_h) == (
            round(self.win_w * self.ui_scale), round(self.win_h * self.ui_scale),
        ):
            return False
        self._set_window_metrics(device_w, device_h)

        side_px = round(self.sidebar_w * self.ui_scale)
        head_px = round(self.header_h * self.ui_scale)
        self.sidebar_canvas.configure(
            width=side_px,
            height=round(self.win_h * self.ui_scale),
        )
        self.sidebar_canvas.place(x=0, y=0)
        self.header_canvas.configure(
            width=round(self.page_w * self.ui_scale),
            height=head_px,
        )
        self.header_canvas.place(x=side_px, y=0)
        self.page_canvas.configure(
            width=round(self.page_w * self.ui_scale),
            height=round(self.page_h * self.ui_scale),
        )
        self.page_canvas.place(x=side_px, y=head_px)
        # Both fixed canvases sample the whole window, even on a width-only resize.
        self._backdrop_layers.clear()
        self._sidebar_state = self._header_state = None
        return True

    def _set_window_metrics(self, width: int, height: int) -> None:
        scale = self.ui_scale
        self.win_w, self.win_h = width / scale, height / scale
        self.page_w = max(640.0, (width - round(self.sidebar_w * scale)) / scale)
        self.page_h = max(420.0, (height - round(self.header_h * scale)) / scale)

    def _toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        try:
            self.root.attributes("-fullscreen", self._fullscreen)
        except tk.TclError:
            self._fullscreen = False
            return
        if not self._fullscreen:
            self._center_window()
        if self._resize_job is not None:
            self._cancel_ui(self._resize_job)
        self._resize_job = self._schedule_ui(140, self._after_window_resize)

    def _exit_fullscreen(self) -> None:
        if self._fullscreen:
            self._toggle_fullscreen()

    def _center_window(self) -> tuple[int, int]:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        window_width = round(ROOT_WIDTH * self.ui_scale)
        window_height = round(ROOT_HEIGHT * self.ui_scale)
        # Remember the size the user dragged to last time.
        saved = self.store.get_setting("window_size", "")
        if "x" in saved:
            try:
                saved_w, saved_h = (int(part) for part in saved.split("x", 1))
            except ValueError:
                saved_w = saved_h = 0
            if saved_w >= int(760 * self.ui_scale) and saved_h >= int(540 * self.ui_scale):
                window_width = min(saved_w, sw)
                window_height = min(saved_h, sh)
        x = max(0, (sw - window_width) // 2)
        y = max(0, (sh - window_height) // 2)
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        return window_width, window_height

    def _draw_backdrop(self, canvas: tk.Canvas, y: float = 0) -> int:
        """Paint the canvas's pixel-aligned crop of the shared window surface."""
        if not self._backdrop_layers:
            scale = self.ui_scale
            width, height = round(self.win_w * scale), round(self.win_h * scale)
            side, head = round(self.sidebar_w * scale), round(self.header_h * scale)
            backdrop = self.kit.window_backdrop(width, height, self._custom_background_source)
            for pane, bounds in (
                (self.sidebar_canvas, (0, 0, side, height)),
                (self.header_canvas, (side, 0, width, head)),
                (self.page_canvas, (side, head, width, height)),
            ):
                self._backdrop_layers[pane] = ImageTk.PhotoImage(
                    backdrop.crop(bounds), master=self.root,
                )
            # Fade scrolling cards and sidebar shadows into one continuous bottom edge.
            fade_height = min(height - head, self.kit.px(34))
            transition = max(1, fade_height - self.kit.px(10))
            fade_alpha = Image.new("L", (1, fade_height))
            stops = []
            for row in range(fade_height):
                progress = min(1, row / transition)
                stops.append(round(255 * progress * progress * (3 - 2 * progress)))
            fade_alpha.putdata(stops)
            fade = backdrop.crop((0, height - fade_height, width, height)).convert("RGBA")
            fade.putalpha(fade_alpha.resize(fade.size, Image.Resampling.NEAREST))
            for pane, left, right in (
                (self.sidebar_canvas, 0, side),
                (self.page_canvas, side, width),
            ):
                self._bottom_glass[pane] = ImageTk.PhotoImage(
                    fade.crop((left, 0, right, fade_height)), master=self.root,
                )
        # A pane may still show its previous crop during a deferred redraw.
        canvas._backdrop_photo = self._backdrop_layers[canvas]
        return tk.Canvas.create_image(
            canvas, 0, y, image=canvas._backdrop_photo, anchor="nw",
            tags=("window_backdrop", "fixed_glass"),
        )

    def _draw_page_background(self) -> None:
        c = self.page_canvas
        origin = c.canvasy(0)
        c.tag_lower(self._draw_backdrop(c, origin))
        self._draw_bottom_glass(c, origin)
        x = self.page_w / 2
        y = self.page_h - 13 + origin / self.ui_scale
        c.create_line(x-5, y-2, x, y+2, x+5, y-2, width=2, fill=COLORS["sage"],
                      capstyle="round", joinstyle="round", tags=("fixed_glass", "scroll_arrow"))
        self._update_scroll_hint(self._scroll_limit > 0 and self._scroll_position == 0)

    def _draw_bottom_glass(self, canvas: tk.Canvas, origin: float = 0) -> None:
        fade = self._bottom_glass[canvas]
        y = origin + self._backdrop_layers[canvas].height() - fade.height()
        tk.Canvas.create_image(
            canvas, 0, y, image=fade, anchor="nw", state="disabled",
            tags=("window_bottom_glass", "fixed_glass"),
        )

    def _load_appearance_assets(self) -> None:
        self._custom_icon_photo = None
        self._custom_taskbar_icon = None
        self._custom_background_source = None
        self._backdrop_layers.clear()
        self._sidebar_state = self._header_state = None

        background_value = self.store.get_setting("custom_background_path")
        background_path = Path(background_value) if background_value else None
        if background_path and background_path.exists():
            try:
                with Image.open(background_path) as opened:
                    self._custom_background_source = opened.convert("RGB")
            except (OSError, ValueError):
                self.store.set_setting("custom_background_path", "")

        icon_value = self.store.get_setting("custom_icon_path")
        icon_path = Path(icon_value) if icon_value else None
        if icon_path and icon_path.exists():
            try:
                with Image.open(icon_path) as opened:
                    icon = opened.convert("RGBA")
                    icon.load()
                icon_size = round(40 * self.ui_scale)
                sidebar_icon = ImageOps.fit(
                    icon,
                    (icon_size, icon_size),
                    method=Image.Resampling.LANCZOS,
                )
                self._custom_icon_photo = ImageTk.PhotoImage(
                    self.kit.round_image(sidebar_icon, round(14 * self.ui_scale)),
                    master=self.root,
                )
                taskbar_icon = ImageOps.fit(
                    icon,
                    (128, 128),
                    method=Image.Resampling.LANCZOS,
                )
                self._custom_taskbar_icon = ImageTk.PhotoImage(
                    taskbar_icon,
                    master=self.root,
                )
            except (OSError, ValueError):
                self.store.set_setting("custom_icon_path", "")

    # ---------------------------------------------------------------- general UI

    def _text(
        self,
        canvas: tk.Canvas,
        x: float,
        y: float,
        text: str,
        size: int = 14,
        fill: str | None = None,
        *,
        anchor: str = "nw",
        weight: str = "normal",
        serif: bool = False,
        width: int | None = None,
        spacing1: int = 0,
        spacing2: int = 0,
        justify: str = "left",
        tags: tuple[str, ...] | str | None = None,
    ) -> int:
        options: dict[str, Any] = {
            "text": text,
            "anchor": anchor,
            "fill": fill or COLORS["ink"],
            "font": font(size, weight, serif),
            "justify": justify,
        }
        if width:
            options["width"] = width
        return canvas.create_text(x, y, tags=tags, **options)

    def _card(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        fill: str = COLORS["card"],
        radius: float = RADII["card"],
        outline: str | None = COLORS["line"],
        tags: tuple[str, ...] | str | None = None,
    ) -> int:
        if canvas is self.page_canvas:
            if self.current_page == "calendar":
                if len(fill) == 7:
                    fill += "CD"
                if outline == COLORS["line"]:
                    outline += "A8"
            else:
                radius = min(radius, RADII["content_card"])
                if len(fill) == 7:
                    fill = mix_color(fill, COLORS["card"], 0.48)
        item = self.kit.draw_card(
            canvas,
            x1,
            y1,
            x2,
            y2,
            radius,
            fill,
            outline,
            1,
            tags,
        )
        # Hovering lifts the shadow instead of moving the card, so nothing
        # inside it ever shifts by a pixel.
        self.motion.add_card(
            canvas,
            item,
            (x1, y1, x2, y2),
            radius,
            fill,
            outline,
            1,
        )
        return item

    def _defer(self, command: Callable[[], Any]) -> None:
        """Run a control command after Tk finishes dispatching its click."""

        def run() -> None:
            if self._closing:
                return
            try:
                command()
            except tk.TclError:
                pass

        try:
            self._schedule_ui(None, run)
        except tk.TclError:
            pass

    def _button(
        self,
        canvas: tk.Canvas,
        tag: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        text: str,
        command: Callable[[], Any],
        style: str = "secondary",
        size: int = 13,
        radius: int = 16,
        prefix: str = "",
    ) -> None:
        styles = {
            "primary": (COLORS["pine"], COLORS["pine_light"], None, COLORS["white"]),
            "secondary": (COLORS["white"], COLORS["card_alt"], COLORS["line"], COLORS["ink"]),
            "accent": (COLORS["clay_soft"], None, None, COLORS["clay"]),
            "ghost": (COLORS["sunken"], None, None, COLORS["ink_soft"]),
            "sage": (COLORS["sage_soft"], None, None, COLORS["pine"]),
            "dark_ghost": (COLORS["pine_light"], None, None, COLORS["white"]),
        }
        fill, fill2, outline, ink = styles.get(style, styles["secondary"])
        pill_radius = min(self._sz(radius), (y2 - y1) / 2)
        highlight = 0.18 if style == "primary" else 0.0
        sheen = COLORS["white"] if style in ("primary", "dark_ghost") else COLORS["sage"]
        item = self.kit.draw_pill(
            canvas,
            x1,
            y1,
            x2,
            y2,
            pill_radius,
            fill,
            fill2,
            outline,
            1,
            tags=(tag,),
            highlight=highlight,
        )
        if text or prefix:
            self._text(
                canvas,
                (x1 + x2) / 2,
                (y1 + y2) / 2,
                (prefix + " " if prefix else "") + text,
                size,
                ink,
                anchor="center",
                weight="bold",
                tags=(tag,),
            )
        surface = self.motion.add_surface(
            canvas,
            item,
            (x1, y1, x2, y2),
            pill_radius,
            fill,
            fill2,
            outline,
            1,
            hover_outline=(
                mix_color(COLORS["iris"], COLORS["white"], 0.68)
                if outline is None
                else mix_color(outline, COLORS["iris"], 0.4)
            ),
            sheen_color=sheen,
            sheen_strength=0.24,
            highlight=highlight,
            press_scale=0.032,
        )

        def pressed(_event: tk.Event[Any]) -> str:
            surface.press_now()
            return "break"

        def released(_event: tk.Event[Any]) -> None:
            surface.release_now()
            self._defer(command)
            return None

        def enter(_event: tk.Event[Any]) -> None:
            canvas.configure(cursor="hand2")

        def leave(_event: tk.Event[Any]) -> None:
            canvas.configure(cursor="")

        canvas.tag_bind(tag, "<ButtonPress-1>", pressed)
        canvas.tag_bind(tag, "<ButtonRelease-1>", released)
        canvas.tag_bind(tag, "<Enter>", enter)
        canvas.tag_bind(tag, "<Leave>", leave)

    def _chip(
        self,
        canvas: tk.Canvas,
        tag: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        text: str,
        selected: bool,
        command: Callable[[], Any],
        color: str | None = None,
        size: int = 12,
    ) -> None:
        color = color or COLORS["pine"]
        if selected:
            fill = mix_color(color, COLORS["white"], 0.86)
            fill2 = mix_color(color, COLORS["white"], 0.93)
            outline = mix_color(color, COLORS["white"], 0.58)
            ink = mix_color(color, COLORS["ink"], 0.32)
            highlight = 0.2
        else:
            fill = COLORS["sunken"]
            fill2 = mix_color(COLORS["sunken"], COLORS["white"], 0.6)
            outline = COLORS["hairline"]
            ink = COLORS["ink_soft"]
            highlight = 0.0
        pill_radius = max(1.0, (y2 - y1) / 2)
        item = self.kit.draw_pill(
            canvas,
            x1,
            y1,
            x2,
            y2,
            pill_radius,
            fill,
            fill2,
            outline,
            1,
            tags=(tag,),
            highlight=highlight,
        )
        self._text(
            canvas,
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text,
            size,
            ink,
            anchor="center",
            weight="bold" if selected else "normal",
            tags=(tag,),
        )
        surface = self.motion.add_surface(
            canvas,
            item,
            (x1, y1, x2, y2),
            pill_radius,
            fill,
            fill2,
            outline,
            1,
            hover_outline=(
                mix_color(color, COLORS["white"], 0.45)
                if selected
                else mix_color(COLORS["iris"], COLORS["white"], 0.7)
            ),
            sheen_color=color if selected else COLORS["iris"],
            sheen_strength=0.24,
            highlight=highlight,
            press_scale=0.035,
        )

        def pressed(_event: tk.Event[Any]) -> str:
            surface.press_now()
            return "break"

        def released(_event: tk.Event[Any]) -> None:
            surface.release_now()
            self._defer(command)
            return None

        canvas.tag_bind(tag, "<ButtonPress-1>", pressed)
        canvas.tag_bind(tag, "<ButtonRelease-1>", released)
        canvas.tag_bind(
            tag,
            "<Enter>",
            lambda _event: canvas.configure(cursor="hand2"),
        )
        canvas.tag_bind(tag, "<Leave>", lambda _event: canvas.configure(cursor=""))

    def _small_dot(self, canvas: tk.Canvas, x: float, y: float, color: str) -> None:
        canvas.create_oval(
            x - 4,
            y - 4,
            x + 4,
            y + 4,
            fill=color,
            outline="",
        )

    def _draw_leaf_motif(
        self,
        canvas: tk.Canvas,
        x: float,
        y: float,
        scale: float = 1.0,
        color: str = COLORS["sage"],
    ) -> None:
        canvas.create_line(
            x,
            y + 28 * scale,
            x,
            y - 36 * scale,
            fill=mix_color(color, COLORS["ink"], 0.25),
            width=max(1, round(2 * scale)),
            smooth=True,
        )
        canvas.create_oval(
            x - 20 * scale,
            y - 22 * scale,
            x + 2 * scale,
            y - 2 * scale,
            fill=mix_color(color, COLORS["white"], 0.15),
            outline="",
        )
        canvas.create_oval(
            x + 1 * scale,
            y - 8 * scale,
            x + 23 * scale,
            y + 13 * scale,
            fill=mix_color(color, COLORS["white"], 0.32),
            outline="",
        )
        canvas.create_oval(
            x - 26 * scale,
            y + 26 * scale,
            x + 26 * scale,
            y + 40 * scale,
            fill=COLORS["clay_soft"],
            outline="",
        )

    def _capture_entry(self) -> None:
        if self._task_entry is not None:
            value = self._task_entry.get()
            if value and value != self._task_entry_placeholder:
                self._task_buffer = value

    def _destroy_transient_widgets(self) -> None:
        self._capture_entry()
        if self._task_entry is not None:
            try:
                self._task_entry.destroy()
            except tk.TclError:
                pass
            self._task_entry = None

    def render(self) -> None:
        self._stop_scroll()
        # Keep the user's place when data updates within the same page.
        offset = self._scroll_position if self._rendered_page == self.current_page else 0
        self.motion.begin(self.page_canvas)
        self._destroy_transient_widgets()
        self._home_cards = {}
        self.page_canvas.clear_scene()
        self._draw_sidebar()
        self._draw_header()
        bottom = 0.0
        if self.current_page == "today":
            bottom = self._draw_today() or 0.0
        elif self.current_page == "music":
            bottom = self._draw_music() or 0.0
        elif self.current_page == "calendar":
            bottom = self._draw_calendar() or 0.0
        elif self.current_page == "settings":
            bottom = self._draw_settings() or 0.0
        elif self.current_page == "essay":
            bottom = self._draw_essay_page() or 0.0
        elif self.current_page == "news":
            bottom = self._draw_news() or 0.0
        self._finish_page(bottom, offset)
        self._draw_page_background()
        self._rendered_page = self.current_page

    # ------------------------------------------------------------ adaptive layout

    @staticmethod
    def _sz(value: float) -> float:
        """Scale a logical dimension by the user's font scale."""

        return value * get_font_scale()

    def _page_metrics(self) -> tuple[float, float, float]:
        """Return (margin, gap, usable width) for the current font scale."""

        margin = self._sz(24)
        gap = self._sz(16)
        return margin, gap, self.page_w - margin * 2

    def _use_two_columns(self) -> bool:
        """Wide layouts collapse when the font grows or the window gets narrow."""

        usable = self.page_w - self._sz(48)
        return get_font_scale() <= 1.24 and usable >= self._sz(980)

    def _flow_card(
        self,
        x: float,
        y: float,
        width: float,
        body: Callable[["Block"], Any],
        *,
        fill: str = COLORS["card"],
        outline: str = COLORS["line"],
        radius: float = RADII["card"],
        pad_x: float = 22,
        pad_y: float = 16,
        tags: tuple[str, ...] | str | None = None,
    ) -> float:
        """Draw a card whose height is derived from ``body`` content."""

        scale = get_font_scale()
        inner_x = x + pad_x * scale
        inner_y = y + pad_y * scale
        inner_width = width - 2 * pad_x * scale
        probe = Block(self, self.page_canvas, inner_x, inner_y, inner_width, draw=False)
        body(probe)
        height = probe.used + 2 * pad_y * scale
        self._card(
            self.page_canvas,
            x,
            y,
            x + width,
            y + height,
            fill,
            radius,
            outline,
            tags,
        )
        painter = Block(self, self.page_canvas, inner_x, inner_y, inner_width, draw=True)
        body(painter)
        return height

    def _finish_page(self, content_bottom: float, offset: float) -> None:
        """Set the new scroll bounds and clamp the previous viewport position."""

        self._page_content_height = max(content_bottom, self.page_h)
        device_width = round(self.page_w * self.ui_scale)
        self._page_height_px = round(self._page_content_height * self.ui_scale)
        viewport_height = round(self.page_h * self.ui_scale)
        self._scroll_limit = max(0, self._page_height_px - viewport_height)
        self.page_canvas.configure(
            scrollregion=(0, 0, device_width, self._page_height_px),
        )
        self._scroll_position = min(self._scroll_limit, max(0, round(offset)))
        self._scroll_target = self._scroll_position
        self._move_page_view(self._scroll_position)
        self._update_scroll_hint(self._scroll_limit > 0)

    def _move_page_view(self, position: int) -> None:
        c = self.page_canvas
        previous_origin = c.canvasy(0)
        c.yview_moveto(position / self._page_height_px)
        # Only the content scrolls. Keep both glass layers at viewport coordinates.
        c.move("fixed_glass", 0, c.canvasy(0) - previous_origin)
        if self._scroll_limit:
            fraction = min(1, position / max(1, min(self._scroll_limit, 48 * self.ui_scale)))
            c.itemconfigure("scroll_arrow", fill=mix_color(COLORS["sage"], COLORS["glass_edge"][:7], fraction))
            self._update_scroll_hint(fraction < 1)

    def _update_scroll_hint(self, visible: bool) -> None:
        """Show a quiet hint so users know more content sits below the fold."""

        self.page_canvas.itemconfigure("scroll_arrow", state="disabled" if visible else "hidden")

    def _on_page_wheel(self, event: tk.Event[Any]) -> str | None:
        if self._closing or not self._scroll_limit:
            return None
        if event.widget.winfo_toplevel() is not self.root:
            return None
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is None or widget not in (
            self.page_canvas, self._task_entry, self._scroll_hint,
        ):
            return None

        if event.num in (4, 5):  # X11 delivers wheel notches as buttons.
            notches = -1 if event.num == 4 else 1
        else:
            notches = -event.delta / 120
        distance = notches * self._sz(56) * self.ui_scale
        if not distance:
            return None

        # Accumulate fractional wheel input in device pixels. On a deliberate
        # reversal, discard the untravelled distance in the old direction.
        remaining = self._scroll_target - self._scroll_position
        base = self._scroll_position if remaining * distance < 0 else self._scroll_target
        target = min(self._scroll_limit, max(0.0, base + distance))
        if target == self._scroll_target:
            return "break"
        self._scroll_start = self._scroll_position
        self._scroll_target = target
        self._scroll_started = time.perf_counter()
        if self._scroll_job is None:
            self.motion.set_scrolling(self.page_canvas, True)
            self._scroll_next_frame = self._scroll_started + SCROLL_FRAME_INTERVAL
            self._schedule_scroll_frame()
        return "break"

    def _schedule_scroll_frame(self) -> None:
        delay_ms = math.ceil((self._scroll_next_frame - time.perf_counter()) * 1000)
        self._scroll_job = self._schedule_ui(max(1, delay_ms), self._apply_scroll)

    def _apply_scroll(self) -> None:
        self._scroll_job = None
        now = time.perf_counter()
        progress = min(1.0, (now - self._scroll_started) / SCROLL_DURATION)
        eased = 1 - (1 - progress) ** 3
        old_pixel = round(self._scroll_position)
        self._scroll_position = self._scroll_start + (
            self._scroll_target - self._scroll_start
        ) * eased
        new_pixel = round(self._scroll_position)
        if new_pixel != old_pixel:
            self._move_page_view(new_pixel)
        if progress == 1.0:
            self.motion.set_scrolling(self.page_canvas, False)
            return

        # Keep absolute 60 Hz deadlines. Skip missed frames if Tk is busy
        # instead of extending the animation or replaying obsolete positions.
        elapsed_frames = int((now - self._scroll_next_frame) / SCROLL_FRAME_INTERVAL)
        self._scroll_next_frame += (max(0, elapsed_frames) + 1) * SCROLL_FRAME_INTERVAL
        self._schedule_scroll_frame()

    def _stop_scroll(self, _event: tk.Event[Any] | None = None) -> None:
        if self._scroll_job is not None:
            self._cancel_ui(self._scroll_job)
            self._scroll_job = None
            self.motion.set_scrolling(self.page_canvas, False)
        self._scroll_position = round(self._scroll_position)
        self._scroll_target = self._scroll_position

    def show_page(self, page: str) -> None:
        if page not in PAGE_HEADERS or not self.feature_visible(page):
            return
        self.current_page = page
        self.render()

    def feature_visible(self, key: str) -> bool:
        return key not in self._hidden_sections

    def _toggle_feature_visibility(self, key: str) -> None:
        if key in CONFIGURABLE_SECTIONS:
            self._save_feature_visibility(self._hidden_sections ^ {key})

    def _restore_feature_visibility(self) -> None:
        self._save_feature_visibility(frozenset())

    def _save_feature_visibility(self, hidden: frozenset[str]) -> None:
        if hidden == self._hidden_sections:
            return
        self.store.set_setting("hidden_sections", ",".join(sorted(hidden)))
        self._hidden_sections = hidden
        if not self.feature_visible(self.current_page):
            self.current_page = "today"
        self.render()

    def _draw_no_visible_sections(self) -> float:
        margin, _, usable = self._page_metrics()

        def body(block: Block) -> None:
            block.text("当前页面的区块已隐藏", 17, COLORS["ink"], serif=True)
            block.gap(12)
            block.button(
                "page_display_settings", "调整页面显示",
                lambda: self.show_page("settings"), style="secondary", size=11,
            )

        return margin * 2 + self._flow_card(margin, margin, usable, body)

    def _draw_sidebar(self) -> None:
        pet_enabled = self.store.get_setting("pet_visible", "1") == "1"
        has_news_alerts = self._news_reminders_visible() and bool(reminder_items(self.news_feed))
        state = (
            self.current_page, self.win_h, get_font_scale(),
            self._custom_background_source, self._custom_icon_photo,
            bool(self._floating), pet_enabled, has_news_alerts, self._hidden_sections,
        )
        if state == self._sidebar_state:
            return

        c = self.sidebar_canvas
        start = c.coords("nav_selection") if (
            self._sidebar_state and self._sidebar_state[0] != self.current_page
        ) else []
        self.motion.begin(c)
        c.clear_scene()
        self._draw_backdrop(c)
        left, right = 16, self.sidebar_w - 16
        self.kit.draw_card(
            c, left, 16, right, self.win_h - 16,
            RADII["panel"], COLORS["glass"], COLORS["glass_edge"],
        )

        x1, x2 = left + 12, right - 12
        brand_x, brand_y = x1 + 6, 29
        badge = 42
        self.kit.draw_round(
            c, brand_x, brand_y, brand_x + badge, brand_y + badge,
            15, COLORS["pine"],
        )
        if self._custom_icon_photo is not None:
            c.create_image(
                brand_x + badge / 2, brand_y + badge / 2,
                image=self._custom_icon_photo, anchor="center",
            )
        else:
            self._text(
                c, brand_x + badge / 2, brand_y + badge / 2,
                "栖", 19, COLORS["white"], anchor="center", serif=True,
            )
        self._text(
            c, brand_x + badge + 12, brand_y + badge / 2,
            "栖心", 22, COLORS["ink"], anchor="w", serif=True,
        )

        pages = (
            ("today", "今日栖居"),
            ("calendar", "情绪日历"),
            ("music", "情境歌单"),
            ("essay", "随笔记录"),
            ("news", "学院新闻"),
            ("settings", "数据与设置"),
        )
        tools = (
            ("pet_toggle", "隐藏桌宠" if pet_enabled else "显示桌宠", self._toggle_pet),
            ("food_wheel_shortcut", "今天吃什么", self._open_food_wheel),
            ("floating_toggle", "隐藏轻语窗" if self._floating else "打开轻语窗",
             self._toggle_floating),
        )
        row_h = min(self._sz(33), max(self._sz(19), (self.win_h - 154) / 10))
        gap = 5
        y = brand_y + badge + 22
        active_y = y
        for page, label in pages:
            if not self.feature_visible(page):
                continue
            if page == self.current_page:
                active_y = y
            self._sidebar_row(
                "nav_" + page, x1, x2, y, row_h, page, label,
                lambda target=page: self.show_page(target),
                active=page == self.current_page, alert=page == "news" and has_news_alerts,
            )
            y += row_h + gap
        if self.feature_visible(self.current_page):
            plate = self.kit.draw_round(
                c, x1, active_y, x2, active_y + row_h, 12,
                COLORS["sage_soft"], COLORS["glass_edge"], tags=("nav_selection",),
            )
            c.itemconfigure(plate, state="disabled")
            c.tag_raise("nav_caption")
            self.motion.slide_item(c, "nav_selection", start, 160)

        tools_top = max(y + 14, self.win_h - 32 - len(tools) * (row_h + gap))
        c.create_line(x1 + 8, tools_top - 10, x2 - 8, tools_top - 10, fill=COLORS["line"])
        for tag, label, command in tools:
            self._sidebar_row(tag, x1, x2, tools_top, row_h, tag, label, command)
            tools_top += row_h + gap
        self._draw_bottom_glass(c)
        self._sidebar_state = state

    def _sidebar_row(
        self, tag: str, x1: float, x2: float, y: float, height: float,
        icon: str, label: str, command: Callable[[], Any], *,
        active: bool = False, alert: bool = False,
    ) -> None:
        c = self.sidebar_canvas
        fill = f"{COLORS['card_alt']}02"
        ink = COLORS["pine"] if active else COLORS["ink_soft"]
        bounds = (x1, y, x2, y + height)
        item = self.kit.draw_pill(c, *bounds, 12, fill, tags=(tag,))
        surface = self.motion.add_surface(
            c, item, bounds, 12, fill,
            hover_fill=f"{COLORS['sage_soft']}A8",
            sheen_strength=0.0, press_scale=0.025,
        )
        middle = y + height / 2
        captions = (tag, "nav_caption") if tag.startswith("nav_") else (tag,)
        self._line_icon(c, icon, x1 + 19, middle, captions)
        self._text(c, x1 + 37, middle, label, 11, ink,
                   anchor="w", weight="bold" if active else "normal", tags=captions)
        if alert:
            c.create_oval(x2 - 16, middle - 3, x2 - 10, middle + 3,
                          fill=COLORS["clay"], outline="", tags=captions)
        c.tag_bind(tag, "<ButtonPress-1>", lambda _event: surface.press_now())

        def release(_event: tk.Event[Any]) -> None:
            surface.release_now()
            self._defer(command)

        c.tag_bind(tag, "<ButtonRelease-1>", release)
        c.tag_bind(tag, "<Enter>", lambda _event: c.configure(cursor="hand2"))
        c.tag_bind(tag, "<Leave>", lambda _event: c.configure(cursor=""))

    def _line_icon(
        self, canvas: tk.Canvas, name: str, x: float, y: float, tags: str | tuple[str, ...],
    ) -> None:
        for path in ICON_PATHS[name]:
            coords = [coord for dx, dy in path for coord in (x + dx, y + dy)]
            canvas.create_line(
                *coords, fill=COLORS["sage"], width=1.5,
                capstyle="round", joinstyle="round", tags=tags,
            )

    def _draw_header(self) -> None:
        today = date.today()
        weather_label = self.weather.summary
        if self.weather.temperature is None:
            weather_label = f"{self.weather.city} · 天气待更新"
        state = (
            self.current_page, self.page_w, get_font_scale(), self._fullscreen,
            self._custom_background_source, weather_label, self.ai.configured, today,
        )
        if state == self._header_state:
            return
        page_changed = self._header_state and self._header_state[0] != self.current_page
        c = self.header_canvas
        self.motion.begin(c)
        c.clear_scene()
        self._draw_backdrop(c)
        left, _, _ = self._page_metrics()
        top, right, bottom = 13, self.page_w - left, self.header_h - 15
        self.kit.draw_card(
            c, left, top, right, bottom,
            RADII["hero"], COLORS["glass"], COLORS["glass_edge"],
        )

        subtitle, title = PAGE_HEADERS[self.current_page]
        x = left + 22
        fs_right = right - 13
        control_size = min(self._sz(28), bottom - top - 12)
        control_y = (top + bottom - control_size) / 2
        fs_left = fs_right - control_size
        self._button(
            c, "header_fullscreen", fs_left, control_y, fs_right,
            control_y + control_size, "",
            self._toggle_fullscreen, "ghost", radius=10,
        )
        self._line_icon(
            c, "collapse" if self._fullscreen else "expand",
            (fs_left + fs_right) / 2, control_y + control_size / 2, "header_fullscreen",
        )

        weather_width = min(self._sz(200), (right - left) * 0.34)
        status_right = fs_left - 12
        status_height = self.meter.line_height(10, "bold") + self.meter.line_height(10) + 3
        date_y = (top + bottom - status_height) / 2
        date_label = f"{today.month}月{today.day}日  周{'一二三四五六日'[today.weekday()]}"
        if self.ai.configured:
            date_label += " · AI 已连接"
        self._text(c, status_right, date_y,
                   fit_text(self.meter, date_label, weather_width, 10, "bold"),
                   10, COLORS["ink_soft"], anchor="ne", weight="bold")
        weather_y = date_y + self.meter.line_height(10, "bold") + 3
        self._text(
            c, status_right, weather_y,
            fit_text(self.meter, weather_label, weather_width, 10),
            10, COLORS["muted"], anchor="ne",
        )
        title_room = status_right - weather_width - x - 12
        title_height = self.meter.line_height(20, "bold")
        subtitle_height = self.meter.line_height(9) + 3
        show_subtitle = title_height + subtitle_height <= bottom - top - 10
        content_height = title_height + (subtitle_height if show_subtitle else 0)
        title_y = (top + bottom - content_height) / 2
        self._text(c, x, title_y, fit_text(self.meter, title, title_room, 20, "bold"),
                   20, COLORS["ink"], weight="bold", tags=("page_heading_text",))
        if show_subtitle:
            self._text(c, x, title_y + title_height + 3,
                       fit_text(self.meter, subtitle, title_room, 9),
                       9, COLORS["ink_soft"], tags=("page_heading_text",))
        self._header_state = state
        if page_changed:
            self.motion.fade_text(c, "page_heading_text", 150, COLORS["card"])

    # ---------------------------------------------------------------- daily page

    def _draw_today(self) -> float:
        margin, gap, usable = self._page_metrics()
        inbox = self.store.inbox_tasks() if self.feature_visible("home_inbox") else []
        following = self.desktop_tools.next_schedule_row(datetime.now()) if self.feature_visible("home_next") else None
        planning = [
            ("home_next", lambda block: self._today_next_body(block, following),
             dict(fill=COLORS["sage_soft"], pad_y=14)),
            ("home_focus", self._home_focus, dict(pad_y=16)),
            ("home_tasks", self._today_tasks_body, dict(pad_y=19)),
            ("home_inbox", lambda block: self._inbox_body(block, inbox),
             dict(fill=COLORS["card_alt"], pad_y=19)),
        ]
        reading = [
            ("home_quote", self._today_quote_body, dict(pad_x=28, pad_y=25)),
            ("home_mood", self._today_mood_body, dict(fill=COLORS["card_alt"], pad_y=19)),
            ("home_care", self._today_care_body,
             dict(fill=COLORS["peach_soft"], outline=COLORS["gold_soft"])),
        ]
        planning = [item for item in planning if self.feature_visible(item[0])
                    and (item[0] != "home_inbox" or inbox)]
        reading = [item for item in reading if self.feature_visible(item[0])]
        font_visible = self.feature_visible("home_font")
        if not (planning or reading or font_visible):
            return self._draw_no_visible_sections()

        def draw_stack(cards, x: float, width: float) -> float:
            y = margin
            for key, body, options in cards:
                canvas = self.page_canvas
                before = set(canvas.find_all())
                height = self._flow_card(x, y, width, body, tags=(key,), **options)
                self._home_cards[key] = (x, y, width, body, options, height, set(canvas.find_all()) - before)
                y += height + gap
            return y

        if planning and reading and usable >= self._sz(720):
            left_width = round((usable - gap) * 0.57)
            top = max(draw_stack(planning, margin, left_width),
                      draw_stack(reading, margin + left_width + gap, usable - left_width - gap))
        else:
            top = draw_stack(planning + reading, margin, usable)
        if font_visible:
            top += self._flow_card(
                margin, top, usable, self._today_font_body,
                fill=COLORS["card_alt"], tags=("home_font",),
            ) + gap
        return top - gap + margin

    def _refresh_home_card(self, key):
        card = self._home_cards.get(key)
        if self.current_page != "today" or not card:
            self.render()
            return
        x, y, width, body, options, height, items = card
        canvas = self.page_canvas
        if key == "home_tasks":
            self._destroy_transient_widgets()
        self.motion.forget_items(canvas, items)
        for item in items:
            canvas.delete(item)
        before = set(canvas.find_all())
        new_height = self._flow_card(x, y, width, body, tags=(key,), **options)
        if new_height != height:
            self.render()
            return
        self._home_cards[key] = (*card[:6], set(canvas.find_all()) - before)
        canvas.tag_raise("window_bottom_glass")
        canvas.tag_raise("scroll_arrow")

    def _home_focus(self, block):
        tools = self.desktop_tools
        session = tools.session
        phase = session.phase if session else "idle"
        label = {"idle":"准备专注", "focus":"专注中", "break":"休息中", "ready":"专注结束", "rested":"休息结束"}[phase]
        block.label("专注计时", 12, COLORS["pine"])
        compact = phase == "idle" and block.width >= block.sz(230)
        radius = block.sz(34 if compact else 46)
        x, y = block.x + block.width / 2, block.y + radius + block.sz(6)
        if compact:
            x = block.x + radius + block.sz(4)
        if block.draw:
            box = (x-radius, y-radius, x+radius, y+radius)
            block.canvas.create_oval(*box, outline=COLORS["line"], width=block.sz(8))
            block.canvas.create_arc(*box, start=90, extent=-359.9, style="arc", outline=COLORS["sage"],
                                    width=block.sz(8), tags=("focus_arc",))
            self._text(block.canvas, x, y-block.sz(10), label, 10, COLORS["sage"], anchor="center")
            self._text(block.canvas, x, y+block.sz(10), "25:00", 16, COLORS["pine"], anchor="center",
                       weight="bold", tags=("focus_time",))
            self._update_home_focus()
        block.y = y + radius + block.sz(14)
        if compact:
            left = x + radius + block.sz(20)
            block.button_at("home_start", "开始专注 25 分钟", lambda: tools.start(None, "自由专注"),
                            left, y-block.sz(18), min(block.sz(180), block.x+block.width-left),
                            block.sz(36), style="primary")
            return
        if phase == "ready":
            block.button("home_rest", "休息 5 分钟", tools.rest)
            block.gap(4)
        if phase in ("idle", "ready", "rested"):
            block.button("home_start", "开始专注 25 分钟", lambda: tools.start(None, "自由专注"))
        if session:
            block.button("home_end", "结束计时", tools.finish)

    def _update_home_focus(self):
        import time
        session = self.desktop_tools.session
        remaining = session.remaining(time.time()) if session else 1500
        self.page_canvas.itemconfigure("focus_time", text=f"{remaining//60:02d}:{remaining%60:02d}")
        canvas = self.page_canvas
        angle = 359.9 * remaining / (session.duration if session else 1500)
        canvas.itemconfigure("focus_arc", extent=-angle)
        canvas.delete("focus_cap")
        box = canvas.coords("focus_arc")
        if remaining and box:
            x, y = (box[0] + box[2])/2, (box[1] + box[3])/2
            radius = (box[2] - box[0])/2
            cap = float(canvas.itemcget("focus_arc", "width"))/2
            for radians in (0, math.radians(angle)):
                cx, cy = x + radius*math.sin(radians), y - radius*math.cos(radians)
                tk.Canvas.create_oval(canvas, cx-cap, cy-cap, cx+cap, cy+cap, outline="",
                                      fill=COLORS["sage"], tags=("focus_cap",))

    def _today_next_body(self, block: Block, schedule: Any) -> None:
        top = block.y
        if schedule is None:
            block.text("下一件事 · 近期没有日程", 11, COLORS["ink_soft"])
            return
        block.label("下一件事", 10, COLORS["pine"], spacing=6)
        day = date.fromisoformat(schedule["local_date"])
        if self.feature_visible("calendar"):
            block.button_right(
                "home_next_open", "查看日程", lambda: self._show_home_schedule(day),
                size=9, height=27, style="ghost", y=top,
            )
            block.y = max(block.y, top + block.sz(27)) + block.sz(2)
        caption = "今天" if day == date.today() else f"{day.month}月{day.day}日"
        block.text(f"{caption}  ·  {schedule['start_time'] or '全天'}", 10, COLORS["sage"], weight="bold")
        block.gap(4)
        block.text(schedule["title"], 15, COLORS["ink"], weight="bold", spacing=4)

    def _show_home_schedule(self, day: date) -> None:
        self.calendar_anchor = day.replace(day=1)
        self.selected_day = day
        self.show_page("calendar")

    def _inbox_body(self, block: Block, rows: list[Any]) -> None:
        block.text("待办收件箱", 16, COLORS["ink"], serif=True, weight="bold")
        block.gap(8)
        for row in rows:
            item_id = row["id"]
            top = block.y
            remove_width = block.button_right(
                f"inbox_remove_{item_id}", "删除",
                lambda target=item_id: self._remove_inbox_task(target),
                size=9, height=28, style="ghost",
            )
            move_width = block.meter.measure("加入今日", 9, "bold") + block.sz(24)
            block.button_at(
                f"inbox_move_{item_id}", "加入今日",
                lambda target=item_id: self._move_inbox_task(target),
                block.x + block.width - remove_width - move_width - block.sz(6),
                top, move_width, block.sz(28), size=9, style="sage",
            )
            block.text(
                row["title"], 11,
                width=block.width - remove_width - move_width - block.sz(20),
            )
            block.y = max(block.y, top + block.sz(28))
            block.gap(7)

    def _capture_hotkey(self, _event: tk.Event[Any]) -> str:
        self.desktop_tools.open_capture()
        return "break"

    def _desktop_data_changed(self) -> None:
        if self.current_page in ("today", "calendar", "settings"):
            self.render()

    def _remove_inbox_task(self, item_id: int) -> None:
        self.store.remove_from_inbox(item_id)
        self._desktop_data_changed()

    def _move_inbox_task(self, item_id: int) -> None:
        if self.store.move_inbox_task_to_today(item_id, self.mood):
            self._desktop_data_changed()

    # -- today: quote ------------------------------------------------------
    def _today_quote_body(self, block: Block) -> None:
        quote = quote_at(self.quote_i)
        row_top = block.y
        button_width = block.button_right(
            "today_quote_next",
            "换一句",
            self._next_quote,
            size=10,
            height=28,
            style="ghost",
        )
        label_width = block.width - button_width - block.sz(12)
        block.text(
            "今日一句",
            10,
            COLORS["sage"],
            weight="bold",
            width=label_width,
        )
        block.y = max(block.y, row_top + block.sz(28)) + block.sz(10)

        def paragraph(text: str, size: int, color: str, *, serif: bool = False, spacing: float = 0) -> None:
            # Measure and draw the same lines so Tk's wrapping cannot move a
            # mixed-language paragraph into the one that follows.
            lines = block.meter.wrap(text, size, block.width, serif=serif)
            for index, line in enumerate(lines):
                block.label(
                    line, size, color, weight="normal", serif=serif,
                    spacing=spacing if index + 1 < len(lines) else 0,
                    tags=("quote_click",),
                )

        paragraph(quote["text"], 27, COLORS["ink"], serif=True, spacing=7)
        block.gap(15)
        paragraph(f"— {quote['source']}", 11, COLORS["ink_soft"])
        block.gap(14)
        block.divider()
        block.gap(12)
        block.label(fit_text(block.meter, quote["explanation"], block.width, 11), 11, COLORS["ink_soft"])
        block.button_right("quote_read", "读解", lambda: show_quote_detail(self.root, quote),
            size=10, height=28, style="ghost")
        block.y += block.sz(28)
        if block.draw:
            canvas = block.canvas
            canvas.tag_bind("quote_click", "<Button-1>", lambda _e: self._next_quote())
            canvas.tag_bind(
                "quote_click",
                "<Enter>",
                lambda _e: canvas.configure(cursor="hand2"),
            )
            canvas.tag_bind("quote_click", "<Leave>", lambda _e: canvas.configure(cursor=""))

    # -- today: font size control (moved from settings) --------------------
    def _today_font_body(self, block: Block) -> None:
        current = round(get_font_scale() * 100)
        label = f"阅读字号 · {current}%"
        row_top = block.y
        button_height = block.sz(34)
        gap = block.sz(8)
        compact = min(block.sz(76), (block.width - gap * 2) * 0.30)
        rest = min(block.sz(125), block.width - compact * 2 - gap * 2)
        left = block.x
        if block.width >= block.sz(480):
            label_top = row_top + (button_height - block.meter.line_height(10, "bold")) / 2
            if block.draw:
                self._text(block.canvas, left, label_top, label, 10, COLORS["sage"], weight="bold")
            left += block.width - compact * 2 - rest - gap * 2
        else:
            block.label(label, 10, COLORS["sage"], spacing=8)
        top = block.y
        block.button_at(
            "today_font_minus",
            "A−",
            lambda: self._change_font_size(-0.05),
            left,
            top,
            compact,
            button_height,
            style="secondary",
            size=10,
        )
        block.button_at(
            "today_font_plus",
            "A＋",
            lambda: self._change_font_size(0.05),
            left + compact + gap,
            top,
            compact,
            button_height,
            style="primary",
            size=10,
        )
        block.button_at(
            "today_font_more",
            "更换字体…",
            lambda: self.show_page("settings"),
            left + compact * 2 + gap * 2,
            top,
            rest,
            button_height,
            style="ghost",
            size=9,
        )
        block.y = top + button_height

    # -- today: mood -------------------------------------------------------
    def _today_mood_body(self, block: Block) -> None:
        row_top = block.y
        button_width = block.button_right(
            "add_custom_mood",
            "＋ 自定义",
            self._open_custom_mood_editor,
            size=9,
            height=28,
            style="ghost",
        )
        block.text(
            "今天属于哪一款？",
            16,
            COLORS["ink"],
            weight="bold",
            serif=True,
            width=block.width - button_width - block.sz(12),
        )
        block.y = max(block.y, row_top + block.sz(28)) + block.sz(4)
        block.text(
            self.moods[self.mood]["description"],
            10,
            COLORS["muted"],
        )
        block.gap(12)

        mood_entries: list[tuple[str, str, bool, object, str]] = []
        for index, mood in enumerate(self.mood_order):
            config = self.moods[mood]
            mood_entries.append(
                (
                    f"mood_pick_{index}",
                    mood,
                    mood == self.mood,
                    lambda value=mood: self._select_mood(value),
                    str(config["color"]),
                )
            )
        block.chip_rows(mood_entries, size=10, gap=8, row_gap=8)

        block.gap(14)
        block.label("接下来要做什么", 9, COLORS["sage"], spacing=6)
        activity_entries = [
            (
                f"activity_pick_{index}",
                activity,
                activity == self.activity,
                lambda value=activity: self._select_activity(value),
                COLORS["sage"],
            )
            for index, activity in enumerate(ACTIVITIES)
        ]
        block.chip_rows(activity_entries, size=10, gap=8, row_gap=8)
        block.gap(14)
        block.button(
            "save_mood",
            "记下此刻",
            self._save_mood,
            style="primary",
            size=11,
            height=40,
            prefix="✓",
        )

    # -- today: gentle care card ------------------------------------------
    def _today_care_body(self, block: Block) -> None:
        block.text("给今天留一点余量", 17, COLORS["ink"], weight="bold", serif=True)
        block.gap(10)
        block.text(
            care_note(self.mood, self.activity),
            11,
            COLORS["ink_soft"],
            spacing=4,
        )
        block.gap(14)
        block.divider(color=COLORS["hairline"])
        block.gap(12)
        block.label("今天的三个小动作", 9, COLORS["sage"], spacing=8)
        rituals = [
            ("一", "关掉一个不必要的通知"),
            ("二", "离开屏幕，走到窗边"),
            ("三", "听 18 秒风，不追求效率"),
        ]
        for number, ritual in rituals:
            row_top = block.y
            dot = block.sz(24)
            if block.draw:
                block.canvas.create_oval(
                    block.x,
                    row_top + block.sz(2),
                    block.x + dot,
                    row_top + block.sz(2) + dot,
                    fill=COLORS["gold_soft"],
                    outline="",
                )
                self._text(
                    block.canvas,
                    block.x + dot / 2,
                    row_top + block.sz(2) + dot / 2,
                    number,
                    9,
                    COLORS["gold"],
                    anchor="center",
                    weight="bold",
                )
            text_height = block.meter.height(
                ritual,
                11,
                block.width - dot - block.sz(12),
            )
            if block.draw:
                self._text(
                    block.canvas,
                    block.x + dot + block.sz(12),
                    row_top + block.sz(3),
                    ritual,
                    11,
                    COLORS["ink_soft"],
                    width=block.width - dot - block.sz(12),
                )
            block.y = row_top + max(text_height, dot) + block.sz(9)

        block.gap(2)
        block.text(
            f"此刻 · {self.mood} / {self.activity} / {time_bucket()}",
            9,
            COLORS["muted"],
        )
        if self.feature_visible("music"):
            block.gap(14)
            block.button(
                "today_to_music",
                "去听一段属于此刻的声音",
                self._open_music_for_mood,
                style="primary",
                size=11,
                height=40,
                prefix="→",
            )

    # -- today: task list --------------------------------------------------
    def _today_tasks_body(self, block: Block) -> None:
        total, done = self.store.task_counts_for_day()
        ring_radius = self._sz(22)
        heading_width = block.width - ring_radius * 2 - self._sz(16)
        row_top = block.y
        block.text(
            "今日待办",
            17,
            COLORS["ink"],
            weight="bold",
            width=heading_width,
        )
        block.gap(4)
        block.text(
            f"{total - done} 项待完成" if total else "今天暂无待办",
            10,
            COLORS["muted"],
            width=heading_width,
        )
        if block.draw:
            canvas = block.canvas
            cx = block.x + block.width - ring_radius
            cy = row_top + ring_radius
            stroke = max(2, round(self._sz(4)))
            canvas.create_oval(
                cx - ring_radius,
                cy - ring_radius,
                cx + ring_radius,
                cy + ring_radius,
                outline=COLORS["line"],
                width=stroke,
            )
            if total:
                canvas.create_arc(
                    cx - ring_radius,
                    cy - ring_radius,
                    cx + ring_radius,
                    cy + ring_radius,
                    start=90,
                    extent=-359 * (done / total),
                    outline=COLORS["sage"],
                    width=stroke,
                    style="arc",
                    tags=("task_progress_arc",),
                )
            self._text(
                canvas,
                cx,
                cy,
                f"{done}/{total}",
                10,
                COLORS["pine"],
                anchor="center",
                weight="bold",
            )
        block.y = max(block.y, row_top + ring_radius * 2) + self._sz(6)
        block.divider()
        block.gap(12)

        tasks = self.store.tasks_for_day()
        if tasks:
            for task in tasks:
                self._today_task_row(block, task)
                block.gap(10)
        else:
            self._today_empty_tasks(block)

        # Inline composer: the Entry is a real widget, so it is positioned
        # after the layout knows where its slot ended up.
        block.gap(6)
        composer_height = block.sz(44)
        top = block.y
        button_width = block.sz(64)
        field_width = block.width - button_width - block.sz(10)
        if block.draw:
            canvas = block.canvas
            self.kit.draw_round(
                canvas,
                block.x,
                top,
                block.x + field_width,
                top + composer_height,
                round(self._sz(15)),
                COLORS["card_alt"],
                COLORS["line"],
                1,
            )
            entry = tk.Entry(
                canvas,
                relief="flat",
                bd=0,
                highlightthickness=0,
                bg=COLORS["card_alt"],
                fg=COLORS["ink"],
                insertbackground=COLORS["pine"],
                font=widget_font(11, self.ui_scale),
            )
            # Tk scrolls the embedded widget along with the painted controls.
            canvas.create_window(
                round((block.x + self._sz(14)) * self.ui_scale),
                round((top + self._sz(11)) * self.ui_scale),
                anchor="nw",
                window=entry,
                width=round((field_width - self._sz(26)) * self.ui_scale),
                height=round(self._sz(22) * self.ui_scale),
            )
            self._install_placeholder(entry)
            if self._task_buffer:
                entry.delete(0, "end")
                entry.insert(0, self._task_buffer)
                entry.configure(fg=COLORS["ink"])
            entry.bind("<Return>", lambda _event: self._add_task())
            entry.bind("<ButtonPress-1>", self._stop_scroll, add="+")
            self._task_entry = entry
            block.button_at(
                "add_task",
                "加入",
                self._add_task,
                block.x + field_width + self._sz(10),
                top,
                button_width,
                composer_height,
                style="primary",
                size=11,
            )
        block.y = top + composer_height

    def _today_task_row(self, block: Block, task: Any) -> None:
        task_id = int(task["id"])
        done = bool(task["done"])
        row_tag = f"task_row_{task_id}"
        toggle_tag = f"task_toggle_{task_id}"
        delete_tag = f"task_delete_{task_id}"
        quote = quote_by_id(str(task["quote_id"]))
        title = str(task["title"])
        quote_line = f"{quote['text']}  ·  {quote['concept']}"

        pad = self._sz(14)
        circle = self._sz(22)
        text_x = pad + circle + self._sz(14)
        text_width = block.width - text_x - self._sz(34)
        title_height = block.meter.height(title, 12, text_width, "bold")
        quote_height = block.meter.height(quote_line, 9, text_width)
        row_height = pad * 2 + title_height + self._sz(4) + quote_height

        top = block.y
        if block.draw:
            canvas = block.canvas
            row_fill = COLORS["sage_soft"] if done else COLORS["sunken"]
            row_item = self.kit.draw_round(
                canvas,
                block.x,
                top,
                block.x + block.width,
                top + row_height,
                round(self._sz(15)),
                row_fill,
                None,
                0,
                (row_tag,),
            )
            self.motion.add_surface(
                canvas,
                row_item,
                (block.x, top, block.x + block.width, top + row_height),
                self._sz(15),
                row_fill,
                None,
                None,
                1,
                sheen_color=COLORS["iris"],
                sheen_strength=0.28,
                press_scale=0.0,
            )
            canvas.create_oval(
                block.x + pad,
                top + pad,
                block.x + pad + circle,
                top + pad + circle,
                fill=COLORS["sage"] if done else COLORS["card"],
                outline=COLORS["sage"] if done else "#D3DCE9",
                width=max(1, round(self._sz(2))),
                tags=(toggle_tag,),
            )
            if done:
                canvas.create_line(
                    block.x + pad + circle * 0.28,
                    top + pad + circle * 0.52,
                    block.x + pad + circle * 0.45,
                    top + pad + circle * 0.70,
                    block.x + pad + circle * 0.75,
                    top + pad + circle * 0.32,
                    fill=COLORS["paper"],
                    width=max(1, round(self._sz(2))),
                    smooth=True,
                    tags=(toggle_tag, f"task_check_{task_id}"),
                )
            self._text(
                canvas,
                block.x + text_x,
                top + pad,
                title,
                12,
                COLORS["muted"] if done else COLORS["ink"],
                weight="normal" if done else "bold",
                width=text_width,
                tags=(row_tag, f"task_title_{task_id}"),
            )
            self._text(
                canvas,
                block.x + text_x,
                top + pad + title_height + self._sz(4),
                quote_line,
                9,
                COLORS["muted"],
                width=text_width,
                tags=(row_tag,),
            )
            self._text(
                canvas,
                block.x + block.width - pad,
                top + pad,
                "×",
                15,
                "#B2ADA3",
                anchor="ne",
                tags=(delete_tag,),
            )
            canvas.tag_bind(
                row_tag,
                "<Button-1>",
                lambda _e, value=task_id: self._toggle_task(value),
            )
            canvas.tag_bind(
                toggle_tag,
                "<Button-1>",
                lambda _e, value=task_id: self._toggle_task(value),
            )
            canvas.tag_bind(
                delete_tag,
                "<Button-1>",
                lambda _e, value=task_id: self._delete_task(value),
            )
            for tag in (row_tag, toggle_tag, delete_tag):
                canvas.tag_bind(tag, "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
                canvas.tag_bind(tag, "<Leave>", lambda _e: canvas.configure(cursor=""))
        block.y = top + row_height

    def _today_empty_tasks(self, block: Block) -> None:
        row_top = block.y
        icon = self._sz(52)
        if block.draw:
            block.canvas.create_oval(
                block.x,
                row_top,
                block.x + icon,
                row_top + icon,
                fill=COLORS["sage_soft"],
                outline="",
            )
            self._draw_leaf_motif(
                block.canvas,
                block.x + icon / 2,
                row_top + icon * 0.72,
                self._sz(0.52),
                COLORS["sage"],
            )
        text_x = block.x + icon + self._sz(20)
        text_width = block.width - icon - self._sz(20)
        if block.draw:
            self._text(
                block.canvas,
                text_x,
                row_top + self._sz(2),
                "清单还是空的。",
                15,
                COLORS["ink"],
                weight="bold",
            )
        title_h = block.meter.height("清单还是空的。", 15, text_width, "bold")
        body = "不必写得很完整。先放下一件最想被记住的小事。"
        body_h = block.meter.height(body, 10, text_width)
        if block.draw:
            self._text(
                block.canvas,
                text_x,
                row_top + self._sz(6) + title_h,
                body,
                10,
                COLORS["muted"],
                width=text_width,
            )
        hint = "比如：把引言的第一段写完。"
        hint_h = block.meter.height(hint, 11, text_width, serif=True)
        if block.draw:
            self._text(
                block.canvas,
                text_x,
                row_top + self._sz(10) + title_h + body_h,
                hint,
                11,
                COLORS["sage"],
                width=text_width,
                serif=True,
            )
        block.y = row_top + max(icon, title_h + body_h + hint_h + self._sz(16))
    def _install_placeholder(self, entry: tk.Entry) -> None:
        entry.insert(0, self._task_entry_placeholder)
        entry.configure(fg=COLORS["muted"])

        def focus_in(_event: tk.Event[Any]) -> None:
            if entry.get() == self._task_entry_placeholder:
                entry.delete(0, "end")
                entry.configure(fg=COLORS["ink"])

        def focus_out(_event: tk.Event[Any]) -> None:
            if not entry.get():
                entry.insert(0, self._task_entry_placeholder)
                entry.configure(fg=COLORS["muted"])

        entry.bind("<FocusIn>", focus_in)
        entry.bind("<FocusOut>", focus_out)

    # ---------------------------------------------------------------- interactions

    def _next_quote(self) -> None:
        self.quote_i = (self.quote_i + 1) % len(QUOTES)
        if self._floating:
            self._floating.set_quote(self.quote_i)
        if self.current_page == "today":
            self._refresh_home_card("home_quote")

    def _select_mood(self, mood: str) -> None:
        self._capture_entry()
        self.mood = mood
        self._refresh_home_card("home_mood")

    def _select_activity(self, activity: str) -> None:
        self._capture_entry()
        self.activity = activity
        self._refresh_home_card("home_mood")

    def _save_mood(self) -> None:
        self.store.add_mood(
            self.mood,
            self.activity,
            self.weather.condition,
            self.weather.temperature,
        )
        self.render()
        canvas = self.page_canvas
        index = self.mood_order.index(self.mood)
        bounds = canvas.bbox(f"mood_pick_{index}")
        labels = [item for item in canvas.find_withtag("save_mood") if canvas.type(item) == "text"]
        if bounds is None or not labels:
            self._toast(f"已记下：{self.mood} · {self.activity}")
            return
        label = labels[0]
        original = canvas.itemcget(label, "text")
        canvas.itemconfigure(label, text="✓ 已记下")
        x1, y1, x2, y2 = bounds
        color = self.moods[self.mood]["color"]
        glow = canvas.create_image(0, 0, anchor="nw", state="disabled")
        canvas.tag_lower(glow, "window_bottom_glass")

        def shimmer(progress: float) -> None:
            spread = round(self.ui_scale * (1 + 6 * progress))
            width, height = x2 - x1 + spread * 2, y2 - y1 + spread * 2
            strength = round(130 * (1 - progress))
            photo = self.kit.rounded(width, height, height // 2, "#00000000", f"{color[:7]}{strength:02X}", 2)
            tk.Canvas.coords(canvas, glow, x1 - spread, y1 - spread)
            canvas.itemconfigure(glow, image=photo)
            canvas._mood_glow_photo = photo

        self.motion.animate(canvas, "mood_glow", 230, shimmer, lambda: canvas.delete(glow))
        self.motion.animate(
            canvas, "mood_saved", 1050, lambda _progress: None,
            lambda: canvas.itemconfigure(label, text=original),
        )

    def _load_custom_moods(self) -> None:
        for row in self.store.custom_moods():
            name = str(row["name"]).strip()
            color = str(row["color"]).strip()
            if not name or name in self.moods or not color.startswith("#"):
                continue
            self.moods[name] = {
                "color": color,
                "soft": mix_color(color, COLORS["white"], 0.84),
                "short": "✦",
                "description": "你为自己定义的心情",
                "score": 3,
            }
            self.mood_order.append(name)

    def _open_custom_mood_editor(self) -> None:
        if len(self.mood_order) - len(MOOD_ORDER) >= 3:
            self._toast("最多保存 3 种自定义心情")
            return
        if self._mood_editor is not None:
            try:
                self._mood_editor.window.lift()
                self._mood_editor.window.focus_force()
                return
            except tk.TclError:
                self._mood_editor = None
        self._mood_editor = CustomMoodDialog(
            self.root,
            self.ui_scale,
            self.kit,
            on_save=self._save_custom_mood,
            on_close=self._custom_mood_closed,
        )

    def _save_custom_mood(self, name: str, color: str) -> str | None:
        name = name.strip()
        if not name:
            return "请输入心情名称。"
        if name in self.moods:
            return "这种心情已经存在了。"
        if len(self.mood_order) - len(MOOD_ORDER) >= 3:
            return "最多保存 3 种自定义心情。"
        try:
            self.store.add_custom_mood(name, color)
        except Exception:
            return "保存失败，请稍后再试。"
        self.moods[name] = {
            "color": color,
            "soft": mix_color(color, COLORS["white"], 0.84),
            "short": "✦",
            "description": "你为自己定义的心情",
            "score": 3,
        }
        self.mood_order.append(name)
        self.mood = name
        self.music_mood = name
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.render()
        self._toast(f"已添加心情：{name}")
        return None

    def _custom_mood_closed(self) -> None:
        self._mood_editor = None

    def _add_task(self) -> None:
        if not self._task_entry:
            return
        title = self._task_entry.get().strip()
        if not title or title == self._task_entry_placeholder:
            self._toast("先写下一件具体的小事")
            return
        quote = task_wisdom(title, self.mood)
        self.store.add_task(title, quote["id"])
        self._task_buffer = ""
        self._toast(f"配上一句「{quote['concept']}」")
        self.render()

    def _toggle_task(self, task_id: int) -> None:
        canvas = self.page_canvas
        title = f"task_title_{task_id}"
        arc = "task_progress_arc"
        previous_color = canvas.itemcget(title, "fill") if canvas.find_withtag(title) else ""
        previous_extent = canvas.itemcget(arc, "extent") if canvas.find_withtag(arc) else ""
        self.store.toggle_task(task_id)
        self._refresh_home_card("home_tasks")
        if not previous_color or not canvas.find_withtag(title):
            return
        color = canvas.itemcget(title, "fill")
        extent = float(canvas.itemcget(arc, "extent"))
        start = float(previous_extent or extent)
        check = f"task_check_{task_id}"
        points = canvas.coords(check)
        if points:
            ax, ay, bx, by, cx, cy = points
            first = math.hypot(bx - ax, by - ay)
            second = math.hypot(cx - bx, cy - by)

        def complete(progress: float) -> None:
            canvas.itemconfigure(title, fill=mix_color(previous_color, color, progress))
            canvas.itemconfigure(arc, extent=start + (extent - start) * progress)
            if not points:
                return
            distance = (first + second) * progress
            if distance <= first:
                ratio = distance / first
                coords = (ax, ay, ax + (bx - ax) * ratio, ay + (by - ay) * ratio)
            else:
                ratio = (distance - first) / second
                coords = (ax, ay, bx, by, bx + (cx - bx) * ratio, by + (cy - by) * ratio)
            tk.Canvas.coords(canvas, check, *coords)

        self.motion.animate(canvas, "task_completion", 155, complete)

    def _delete_task(self, task_id: int) -> None:
        self.store.delete_task(task_id)
        self._toast("已从清单里轻轻移除")
        self.render()

    def _open_music_for_mood(self) -> None:
        self.music_mood = self.mood
        self.music_activity = self.activity
        self.weather_mode = "自动"
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.show_page("music")

    def _toast(self, text: str, duration: int = 2400) -> None:
        for item in self._toast_items:
            try:
                self.page_canvas.delete(item)
            except tk.TclError:
                pass
        self._toast_items = []
        tag = f"toast_{time.time_ns()}"
        canvas = self.page_canvas
        width = max(190.0, min(self.page_w - 56, self.meter.measure(text, 10, "bold") + 52))
        top = canvas.canvasy(0) / self.ui_scale + self.page_h - self._sz(58)
        x1 = (self.page_w - width) / 2
        x2 = x1 + width
        y1 = top
        y2 = top + self._sz(38)
        self.kit.draw_soft_shadow(
            canvas,
            x1,
            y1,
            x2,
            y2,
            (y2 - y1) / 2,
            alpha=46,
            blur=16,
            dy=6,
        )
        self.kit.draw_pill(
            canvas,
            x1,
            y1,
            x2,
            y2,
            (y2 - y1) / 2,
            "#1B2438",
            "#25304B",
            "#3B4A6E",
            1,
            tags=(tag,),
            highlight=0.55,
        )
        self._toast_items.append(
            self._text(
                canvas,
                (x1 + x2) / 2,
                (y1 + y2) / 2,
                text,
                10,
                COLORS["white"],
                anchor="center",
                weight="bold",
                tags=(tag,),
            )
        )
        image_items = canvas.find_withtag(tag)
        self._toast_items.extend(image_items)
        self._schedule_ui(
            duration,
            lambda current_tag=tag: [
                canvas.delete(item)
                for item in canvas.find_withtag(current_tag)
            ],
        )

    def _refresh_weather(self) -> None:
        self._request_weather(manual=False)
        self._schedule_ui(30 * 60 * 1000, self._refresh_weather)

    def _request_weather(self, *, manual: bool) -> None:
        self._weather_request += 1
        request = self._weather_request

        def ready(snapshot):
            if request != self._weather_request:
                return
            if manual:
                self._weather_manual_ready(snapshot)
            else:
                self._weather_ready(snapshot)

        def failed(message):
            if manual and request == self._weather_request:
                self._toast(f"天气同步失败：{message[:48]}")

        self._run_background(lambda: self.weather_service.current(force=True), ready, failed)

    def _weather_ready(self, snapshot: WeatherSnapshot) -> None:
        self.weather = snapshot
        self._draw_header()
        if self.current_page == "music" and self.weather_mode == "自动":
            self.music_results = self._build_recommendations()

    def _show_floating(self) -> None:
        if self._floating is not None or self._closing:
            return
        self._floating = FloatingWisdom(
            self.root,
            self.kit,
            self.quote_i,
            on_quote_change=self._floating_quote_changed,
            on_close=self._floating_closed,
        )
        self._draw_sidebar()

    def _show_pet_if_enabled(self) -> None:
        if self.store.get_setting("pet_visible", "1") == "1":
            self._show_pet()

    def _show_pet(self) -> None:
        if self._pet is not None or self._closing:
            return
        self._pet = DesktopPet(
            self.root,
            self.store,
            self.ui_scale,
            tools=self.desktop_tools,
            on_open_app=self._activate_main_window,
            on_toggle_wisdom=self._toggle_floating,
            on_food_wheel=self._open_food_wheel,
            on_hide=self._hide_pet,
            on_quit=self._on_close,
            on_image_changed=self._draw_sidebar,
        )
        self._pet.show_focus(self.desktop_tools.session)
        self._pet.set_fullscreen_quiet(self.desktop_tools.fullscreen)
        self.store.set_setting("pet_visible", "1")
        self._draw_sidebar()

    def _hide_pet(self) -> None:
        if self._pet is not None:
            self._pet.close()
            self._pet = None
        self.store.set_setting("pet_visible", "0")
        self._draw_sidebar()

    def _toggle_pet(self) -> None:
        if self._pet is not None:
            self._hide_pet()
            return
        self.store.set_setting("pet_visible", "1")
        self._show_pet()

    def _activate_main_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _open_food_wheel(self) -> None:
        if self._food_wheel is not None:
            try:
                self._food_wheel.window.deiconify()
                self._food_wheel.window.lift()
                self._food_wheel.window.focus_force()
                return
            except tk.TclError:
                self._food_wheel = None
        self._food_wheel = FoodWheelDialog(
            self.root,
            self.ui_scale,
            self.kit,
            on_close=self._food_wheel_closed,
        )

    def _food_wheel_closed(self) -> None:
        self._food_wheel = None

    def _refresh_news(self, force: bool = False) -> None:
        if self._news_loading:
            return
        self._news_loading = True

        def failed(message):
            self._news_ready(NewsFeed(
                items=list(self.news_feed.items),
                fetched_at=self.news_feed.fetched_at,
                live=False,
                source_note=self.news_feed.source_note,
                error=message[:120],
            ))

        self._run_background(lambda: self.news_service.fetch(force=force), self._news_ready, failed)

    def _news_ready(self, feed: NewsFeed) -> None:
        self._news_loading = False
        was_loaded = bool(self.news_feed.items)
        self.news_feed = feed
        reminders = reminder_items(feed)
        self._news_reminder_keys = tuple(item.key for item in reminders)
        if self.current_page == "news":
            self.render()
        else:
            self._draw_sidebar()
        if reminders and not was_loaded and self._news_reminders_visible():
            self._toast(f"有 {len(reminders)} 条导师交流 / 人文讲座，记得抢选", 3600)

    def _news_reminders_visible(self) -> bool:
        return self.feature_visible("news") and self.feature_visible("news_reminders")

    def _expire_news_reminders(self) -> None:
        if self._closing:
            return
        self._schedule_ui(60_000, self._expire_news_reminders)
        keys = tuple(item.key for item in reminder_items(self.news_feed))
        if self.current_page == "news" and self._signup_panel_keys != tuple(
            row["news_key"] for row in self.store.signup_reminders(time.time())
        ):
            self._news_reminder_keys = keys
            self.render()
            return
        if keys == self._news_reminder_keys:
            return
        self._news_reminder_keys = keys
        if self._news_reminders_visible():
            if self.current_page == "news":
                self.render()
            else:
                self._draw_sidebar()

    def _open_note_editor(self, note_id: int | None = None) -> None:
        self._capture_entry()
        self._note_editor = NoteEditorDialog(
            self,
            self.store,
            note_id,
            on_saved=self._note_saved,
        )
        self._note_editor.show()

    def _note_saved(self, note_id: int) -> None:
        self._toast("随笔已保存")
        if self.current_page in {"essay", "calendar"}:
            self.render()

    def _floating_quote_changed(self, index: int) -> None:
        self.quote_i = index
        if self.current_page == "today":
            self.render()

    def _floating_closed(self) -> None:
        self._floating = None
        self._draw_sidebar()

    def _toggle_floating(self) -> None:
        if self._floating:
            self._floating._close()
        else:
            self._show_floating()

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_scroll()
        for job in tuple(self._ui_jobs):
            self._cancel_ui(job)
        self.motion.shutdown()
        self.desktop_tools.close()
        self.player.stop()
        if self._floating:
            try:
                self._floating.window.destroy()
            except tk.TclError:
                pass
            self._floating = None
        if self._pet:
            self._pet.close()
            self._pet = None
        if self._food_wheel:
            self._food_wheel.close()
            self._food_wheel = None
        if self._mood_editor:
            self._mood_editor.close()
            self._mood_editor = None
        if self._schedule_dialog:
            self._schedule_dialog.close()
            self._schedule_dialog = None
        if self._day_dialog:
            self._day_dialog.close()
            self._day_dialog = None
        try:
            if not self._fullscreen:
                width = self.root.winfo_width()
                height = self.root.winfo_height()
                if width > 200 and height > 200:
                    self.store.set_setting("window_size", f"{width}x{height}")
        except tk.TclError:
            pass
        self.store.close()
        self.root.destroy()

    # ---------------------------------------------------------------- music page

    def _effective_weather(self) -> str:
        return self.weather.condition if self.weather_mode == "自动" else self.weather_mode

    def _build_recommendations(self) -> list[dict[str, Any]]:
        return recommend_tracks(
            self.music_mood,
            self.music_activity,
            self._effective_weather(),
            time_bucket(),
        )

    def _draw_music(self) -> float:
        """情境歌单：布局与自适应逻辑见 :mod:`qixin.pages_music`。"""

        return draw_music(self)
    def _set_music_mood(self, mood: str) -> None:
        self.music_mood = mood
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.render()

    def _set_music_activity(self, activity: str) -> None:
        self.music_activity = activity
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.render()

    def _set_weather_mode(self, mode: str) -> None:
        self.weather_mode = mode
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.render()

    def _generate_playlist(self) -> None:
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.render()
        if self.current_page == "music":
            canvas = self.page_canvas
            background = mix_color(COLORS["iris_soft"], COLORS["card"], 0.48)
            self.motion.fade_text(canvas, "recommendation_title", 180, background)
            artwork = {
                (item, option): color
                for item in canvas.find_withtag("recommendation_artwork")
                for option in ("fill", "outline")
                if (color := canvas.itemcget(item, option))
            }

            def reveal_artwork(progress):
                for (item, option), color in artwork.items():
                    canvas.itemconfigure(item, **{option: mix_color(background, color, progress)})

            if artwork:
                self.motion.animate(canvas, "recommendation_artwork", 180, reveal_artwork)
        label = (
            f"{self.weather_mode if self.weather_mode != '自动' else self.weather.condition}"
            f" · {self.music_mood} · {self.music_activity}"
        )
        self._toast(f"已为「{label}」重新编排")
        if self.ai.configured:
            self._run_playlist_ai()

    def _run_playlist_ai(self) -> None:
        if self.ai_music_busy or not self.ai.configured:
            return
        self.ai_music_busy = True
        candidates = [dict(item) for item in self.music_results[:4]]
        mood = self.music_mood
        activity = self.music_activity
        weather = self._effective_weather()
        moment = time_bucket()
        self.render()

        def ready(result):
            current = self.music_mood, self.music_activity, self._effective_weather()
            if current != (mood, activity, weather) or self.music_results[:4] != candidates:
                self.ai_music_busy = False
                if self.current_page == "music":
                    self.render()
                return
            self._playlist_ai_ready(result)

        self._run_background(
            lambda: self.ai.refine_playlist(mood, activity, weather, moment, candidates),
            ready,
            self._playlist_ai_failed,
        )

    def _playlist_ai_ready(self, result: dict[str, Any]) -> None:
        self.ai_music_busy = False
        track_id = str(result.get("track_id", ""))
        for i, item in enumerate(self.music_results):
            if item["id"] == track_id:
                self.music_index = i
                break
        self.ai_music_reason = str(result.get("reason", "")).strip()
        self.ai_music_note = str(result.get("care_note", "")).strip()
        if self.current_page == "music":
            self.render()
            self._toast("AI 已从人工曲库中选出更贴近的一段")

    def _playlist_ai_failed(self, message: str) -> None:
        self.ai_music_busy = False
        if self.current_page == "music":
            self.render()
            short = message[:58]
            self._toast(f"已保留本地策展结果 · {short}")

    def _next_recommendation(self) -> None:
        self.music_index = (self.music_index + 1) % len(self.music_results)
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.render()

    def _choose_music(self, index: int) -> None:
        index = min(max(index, 0), len(self.music_results) - 1)
        self.music_index = index
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.render()

    def _toggle_play(self, track: dict[str, Any]) -> None:
        track_id = str(track["id"])
        if track.get("platform_only"):
            # Real pop / rock / classical recordings are not redistributed by
            # this demo; the card hands the listener to the official platform.
            link = playlists.first_link(track)
            if link is None:
                self._toast("这条曲目还没有可用的平台链接")
                return
            if playlists.open_url(link["url"]):
                self._record_playlist(track)
                artist = str(track.get("artist") or "").strip()
                name = f"{artist}《{track['title']}》" if artist else f"《{track['title']}》"
                self._toast(f"已打开平台试听：{name}")
            else:
                self._toast("浏览器没有响应，可以去平台手动搜索")
            return
        self._audio_request += 1
        request = self._audio_request
        if self._audio_loading_id == track_id or (
            self.player.playing and self.player.current_track_id == track_id
        ):
            self.player.stop()
            self._audio_loading_id = None
            self.render()
            return
        external = external_music_url(track_id)
        if external:
            webbrowser.open(external)
            self._record_playlist(track)
            self._toast("已交给你的音乐服务打开")
            return
        self._audio_loading_id = track_id
        self.render()

        def ready(_ready_id: str) -> None:
            self._background_results.put(lambda: self._audio_ready(track) if request == self._audio_request else None)

        def failed(message: str) -> None:
            self._background_results.put(lambda: self._audio_error(message) if request == self._audio_request else None)

        self.player.play_async(track, ready, failed)

    def _audio_ready(self, track: dict[str, Any]) -> None:
        self._audio_loading_id = None
        self._record_playlist(track)
        if self.current_page == "music":
            self.render()
        self._toast(f"正在播放 · {track['title']}", 2000)

    def _audio_error(self, message: str) -> None:
        self._audio_loading_id = None
        if self.current_page == "music":
            self.render()
        self._toast(f"音频播放失败：{message[:48]}")

    def _record_playlist(self, track: dict[str, Any]) -> None:
        self.store.record_playlist(
            self.music_mood,
            self.music_activity,
            self._effective_weather(),
            time_bucket(),
            str(track["id"]),
            str(track["title"]),
        )

    # --------------------------------------------------------------- calendar page

    def _draw_calendar(self) -> float:
        """情绪日历：布局与自适应逻辑见 :mod:`qixin.pages_calendar`。"""

        return draw_calendar(self)
    def _set_calendar_view(self, view: str) -> None:
        if view not in {"month", "agenda"}:
            return
        self.calendar_view = view
        self.store.set_setting("calendar_view", view)
        self.render()

    def _clear_mood_history(self) -> None:
        count = int(self.store.recap_counts()["mood_count"])
        if count == 0:
            self._toast("还没有可清空的情绪记录")
            return
        confirmed = messagebox.askyesno(
            "清空情绪记录",
            f"将删除全部 {count} 条情绪打卡记录。\n\n"
            "待办、歌单记录和本地设置会保留，但情绪记录清空后无法恢复。",
            parent=self.root,
        )
        if not confirmed:
            return
        removed = self.store.clear_moods()
        self.mood = "已老实"
        self.music_mood = "已老实"
        self.render()
        self._toast(f"已清空 {removed} 条情绪记录")

    def _shift_month(self, delta: int) -> None:
        year = self.calendar_anchor.year
        month = self.calendar_anchor.month + delta
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        self.calendar_anchor = date(year, month, 1)
        self.selected_day = date(year, month, 1)
        self.render()

    def _calendar_today(self) -> None:
        today = date.today()
        self.calendar_anchor = today.replace(day=1)
        self.selected_day = today
        self.render()

    def _on_calendar_double_click(self, event: tk.Event[Any]) -> None:
        """Double-clicking a month cell opens that day's schedule editor."""

        if self.current_page != "calendar":
            return
        canvas = self.page_canvas
        try:
            items = canvas.find_withtag("current")
            tags = [tag for item in items for tag in canvas.gettags(item)]
        except tk.TclError:
            return
        for tag in tags:
            if tag.startswith("agenda_day_"):
                try:
                    day = date.fromisoformat(tag[len("agenda_day_") :])
                except ValueError:
                    continue
                self._open_day_schedules(day)
                return
            if not tag.startswith("calendar_day_"):
                continue
            try:
                day_number = int(tag.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            anchor = self.calendar_anchor
            try:
                day = date(anchor.year, anchor.month, day_number)
            except ValueError:
                return
            self._open_day_schedules(day)
            return

    def _select_calendar_day(self, day: date) -> None:
        if day == self.selected_day:
            return
        start = self.page_canvas.coords("calendar_selection")
        self.selected_day = day
        self.render()
        self.motion.slide_item(self.page_canvas, "calendar_selection", start, 150)
        self.motion.fade_text(self.page_canvas, "calendar_detail_text", 155, COLORS["card"])

    def _open_weekly_report(self) -> None:
        stats = self.store.weekly_stats()
        report = local_weekly_report(stats)
        dialog = WeeklyReportDialog(self, stats, report)
        dialog.show()

    def _open_schedule_dialog(
        self,
        day: date | None = None,
        schedule: dict[str, Any] | None = None,
    ) -> None:
        if self._schedule_dialog is not None:
            try:
                self._schedule_dialog.close()
            except tk.TclError:
                pass
            self._schedule_dialog = None
        target_day = day or self.selected_day
        self._schedule_dialog = ScheduleDialog(
            self.root,
            self.ui_scale,
            self.kit,
            target_day,
            on_save=self._save_schedule,
            data_dir=self.store.path.parent,
            on_close=self._schedule_closed,
            schedule=schedule,
        )

    def _save_schedule(
        self,
        day: date,
        start_time: str,
        title: str,
        note: str,
        schedule_id: int | None = None,
        alarm_sound: str | None = None,
    ) -> str | None:
        if not title.strip():
            return "请填写日程名称。"
        if schedule_id is not None:
            self.store.update_schedule(schedule_id, title, day, start_time, note, alarm_sound)
            message = f"已更新日程：{title}"
        else:
            self.store.add_schedule(title, day, start_time, note, alarm_sound)
            message = f"已添加日程：{title}"
        self.desktop_tools.alarm_dirty = True
        self.calendar_anchor = day.replace(day=1)
        self.selected_day = day
        self._refresh_day_dialog()
        self.render()
        self._toast(message)
        return None

    def _check_alarms(self, minute, start=None):
        from .alarms import AlarmQueue
        start = start or minute
        db = self.store.conn
        with db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id, title, alarm_sound, local_date || ' ' || start_time AS due "
                "FROM schedule_events WHERE local_date BETWEEN ? AND ? "
                "AND alarm_sound IS NOT NULL AND due BETWEEN ? AND ? "
                "AND COALESCE(alarm_fired, '') != due ORDER BY due, id",
                (start[:10], minute[:10], start, minute)
            ).fetchall()
            if rows:
                if not hasattr(self, "_alarm_queue"):
                    self._alarm_queue = AlarmQueue(self.root)
                self._alarm_queue.add(rows)
                db.executemany("UPDATE schedule_events SET alarm_fired=? WHERE id=?",
                               [(r["due"], r["id"]) for r in rows])

    def _schedule_closed(self) -> None:
        self._schedule_dialog = None

    # ---------------------------------------------------- day schedule editor

    def _open_day_schedules(self, day: date) -> None:
        """双击日历格：列出当天全部日程并逐条编辑。"""

        if self._day_dialog is not None:
            try:
                self._day_dialog.close()
            except tk.TclError:
                pass
            self._day_dialog = None
        self._day_dialog = DaySchedulesDialog(
            self.root,
            self.ui_scale,
            self.kit,
            day,
            self.store.schedules_for_day(day),
            on_add=lambda: self._open_schedule_dialog(day=day),
            on_edit=self._edit_schedule_row,
            on_delete=self._delete_schedule_row,
            on_close=self._day_dialog_closed,
        )

    def _edit_schedule_row(self, row: dict[str, Any]) -> None:
        try:
            day = date.fromisoformat(str(row.get("local_date", "")))
        except ValueError:
            day = self.selected_day
        self._open_schedule_dialog(day=day, schedule=dict(row))

    def _delete_schedule_row(self, row: dict[str, Any]) -> None:
        parent = self._day_dialog.window if self._day_dialog is not None else self.root
        title = str(row.get("title") or "这条日程")
        if not messagebox.askyesno("删除日程", f"删除「{title}」？", parent=parent):
            return
        try:
            self.store.delete_schedule(int(row.get("id")))
        except (TypeError, ValueError):
            return
        self._refresh_day_dialog()
        self.render()
        self._toast("已删除日程")

    def _refresh_day_dialog(self) -> None:
        if self._day_dialog is None:
            return
        try:
            self._day_dialog.refresh(self.store.schedules_for_day(self._day_dialog.day))
        except tk.TclError:
            self._day_dialog = None

    def _day_dialog_closed(self) -> None:
        self._day_dialog = None
        if not self._closing:
            self.render()

    # --------------------------------------------------------------- settings page

    def _draw_essay_page(self) -> float:
        """随笔记录：整页浏览所有随笔（编辑器由 notes.NoteEditorDialog 提供）。"""

        margin, gap, usable = self._page_metrics()
        y = margin
        notes = list_notes(self.store, limit=40)
        if not notes:
            return y + self._flow_card(margin, y, usable, self._essay_empty_body, pad_y=28) + margin
        self._button(self.page_canvas, "essay_new", margin, y, margin + self._sz(144),
                     y + self._sz(36), "＋ 写一篇随笔", self._open_note_editor, "primary", 11)
        y += self._sz(36) + gap
        month = None
        for note in notes:
            note_month = note.updated_at[:7]
            if note_month != month:
                month = note_month
                self._text(self.page_canvas, margin, y, month.replace("-", " 年 ") + " 月",
                           12, COLORS["sage"], weight="bold")
                y += self.meter.line_height(12, "bold") + gap / 2
            key = f"essay_open_{note.id}"
            before = set(self.page_canvas.find_all())
            y += self._flow_card(margin, y, usable, self._essay_card_body(note)) + gap
            for item in set(self.page_canvas.find_all()) - before:
                self.page_canvas.addtag_withtag(key, item)
            self.page_canvas.tag_bind(key, "<Button-1>", lambda _event, target=note.id: self._open_note_editor(target))
        return y + margin

    def _essay_empty_body(self, block: Block) -> None:
        block.label(date.today().strftime("%Y.%m.%d"), 12, COLORS["sage"])
        block.gap(18)
        block.button("essay_empty_new", "今天想记下什么？", self._open_note_editor,
                     style="ghost", size=18, height=64)

    def _essay_card_body(self, note: "Note") -> Callable[[Block], None]:
        def body(block: Block) -> None:
            block.text(note.title or "未命名随笔", 15, COLORS["ink"], weight="bold", serif=True)
            block.label(note.updated_at[:16].replace("T", " "), 10, COLORS["muted"])
            block.gap(6)
            lines = block.meter.wrap(note.plain_text.strip(), 11, block.width, serif=True)
            for line in lines[:2]:
                block.label(line, 11, COLORS["ink_soft"], serif=True)
        return body

    def _draw_news(self) -> float:
        """今日新闻：导师交流与人文讲座，带抢选提醒。"""

        margin, gap, usable = self._page_metrics()
        y = margin
        y += self._flow_card(margin, y, usable, self._news_intro_body)
        y += gap
        saved = self.store.signup_reminders(time.time())
        self._signup_panel_keys = tuple(row["news_key"] for row in saved)
        if saved:
            y += self._flow_card(
                margin, y, usable, lambda block: self._saved_signup_body(block, saved),
                fill=COLORS["sage_soft"],
            ) + gap
        feed = self.news_feed
        if not feed.items:
            y += self._flow_card(margin, y, usable, self._news_empty_body)
            return y + margin
        reminders = reminder_items(feed) if self.feature_visible("news_reminders") else []
        if reminders:
            y += self._flow_card(
                margin,
                y,
                usable,
                lambda block: self._news_reminder_body(block, reminders),
                fill=COLORS["peach_soft"],
                outline="#F8DFD2",
            )
            y += gap
        for index, item in enumerate(feed.items):
            y += self._flow_card(margin, y, usable, self._news_item_body(item, index))
            y += gap
        return y + margin

    def _news_reminder_body(self, block: Block, reminders: list["NewsItem"]) -> None:
        block.text("记得抢选", 18, COLORS["clay"], weight="bold", serif=True)
        block.gap(6)
        block.text(
            f"共 {len(reminders)} 场活动已开放或即将开放报名，名额有限，建议提前两分钟守在报名页。",
            11,
            COLORS["ink_soft"],
            spacing=5,
        )
        block.gap(16)
        now = datetime.now(SIGNUP_TIMEZONE)
        for index, item in enumerate(reminders):
            detail = item.signup_text or item.when_text
            label = f"· {item.kind}｜{item.title}"
            block.text(label, 12, COLORS["ink"], weight="bold", spacing=7)
            block.gap(4)
            block.text(detail, 11, COLORS["clay"], spacing=7)
            url = signup_link(item.signup_url) or signup_link(item.url)
            if item.key in self._signup_panel_keys:
                block.text("已设置提醒", 10, COLORS["pine"])
            elif item.source != SOURCE_SAMPLE and url:
                opening = signup_opening(item, self.news_feed.fetched_at)
                if opening is not None and opening <= now:
                    label = "打开报名页" if signup_link(item.signup_url) else "打开原文"
                    block.button(
                        f"signup_open_{index}", label, lambda link=url: webbrowser.open(link),
                        size=10, height=30, width=self._sz(110),
                    )
                else:
                    block.button(
                        f"signup_set_{index}", "报名时提醒我",
                        lambda news=item: self._confirm_signup_reminder(news),
                        size=10, height=30, width=self._sz(126), style="primary",
                    )
            if index < len(reminders) - 1:
                block.gap(10)

    def _saved_signup_body(self, block: Block, rows: list[Any]) -> None:
        block.text("我的抢选提醒", 16, COLORS["pine"], weight="bold", serif=True)
        block.gap(10)
        for index, row in enumerate(rows):
            opening = datetime.fromtimestamp(row["opens_at"], SIGNUP_TIMEZONE)
            status = "已提醒" if row["notified"] else "待提醒"
            block.text(row["title"], 11, COLORS["ink"], weight="bold", spacing=4)
            block.text(f"{opening:%m月%d日 %H:%M} 北京时间 · {status}", 10, COLORS["muted"])
            block.gap(7)
            y, _ = block.row(30)
            url = signup_link(row["url"])
            if url:
                label = "打开报名页" if row["direct_link"] else "打开原文"
                block.button_at(
                    f"signup_saved_open_{index}", label, lambda link=url: webbrowser.open(link),
                    block.x, y, block.sz(100), block.sz(30), size=10,
                )
            block.button_at(
                f"signup_cancel_{index}", "移除" if row["notified"] else "取消提醒",
                lambda key=row["news_key"]: self._cancel_signup_reminder(key),
                block.x + block.sz(110), y, block.sz(90), block.sz(30), size=10, style="ghost",
            )
            if index + 1 < len(rows):
                block.gap(12)

    def _confirm_signup_reminder(self, item: NewsItem) -> None:
        direct = signup_link(item.signup_url)
        url = direct or signup_link(item.url)
        if not url or item.source == SOURCE_SAMPLE:
            return
        opening = signup_opening(item, self.news_feed.fetched_at)
        initial = opening.strftime("%Y-%m-%d %H:%M") if opening is not None else ""
        prompt = "请确认报名开放时间（北京时间）\n请输入 YYYY-MM-DD HH:MM"
        if opening is None:
            prompt = "请根据公告填写报名开放时间（北京时间）\n请输入 YYYY-MM-DD HH:MM"
        while True:
            value = simpledialog.askstring("设置抢选提醒", prompt, initialvalue=initial, parent=self.root)
            if value is None:
                return
            initial = value.strip()
            try:
                opens_at = datetime.strptime(initial, "%Y-%m-%d %H:%M").replace(tzinfo=SIGNUP_TIMEZONE)
            except ValueError:
                prompt = "请输入有效的北京时间\n格式为 YYYY-MM-DD HH:MM"
                continue
            now = datetime.now(SIGNUP_TIMEZONE)
            cutoff = signup_cutoff(item, self.news_feed.fetched_at, now)
            if opens_at <= now or (cutoff is not None and opens_at >= cutoff):
                prompt = "请选择尚未到达、且早于报名截止或活动开始的时间（北京时间）\n格式为 YYYY-MM-DD HH:MM"
                continue
            expires = opens_at + timedelta(minutes=30)
            if cutoff is not None:
                expires = min(expires, cutoff)
            self.store.save_signup_reminder(
                item.key, item.title, url, bool(direct), int(opens_at.timestamp()), int(expires.timestamp()),
            )
            self.render()
            self._toast(f"已设置 {opens_at:%m月%d日 %H:%M} 的抢选提醒")
            return

    def _cancel_signup_reminder(self, key: str) -> None:
        self.store.cancel_signup_reminder(key)
        self.render()

    def _news_intro_body(self, block: Block) -> None:
        row_top = block.y
        block.text(
            "今日新闻",
            17,
            COLORS["ink"],
            weight="bold",
            serif=True,
            width=block.width - self._sz(180),
        )
        block.button_right(
            "news_refresh",
            "↻ 立即同步",
            lambda: self._refresh_news(force=True),
            size=9,
            height=30,
            style="secondary",
            y=row_top,
        )
        block.y = max(block.y, row_top + self._sz(30)) + self._sz(8)
        feed = self.news_feed
        state = "实时同步" if feed.live else "离线缓存"
        stamp = feed.fetched_at[:16].replace("T", " ") if feed.fetched_at else "尚未同步"
        block.text(
            f"{feed.source_note or '尚未同步'} · {state} · {stamp}",
            9,
            COLORS["muted"],
        )
        if feed.error:
            block.gap(6)
            block.text(f"提示：{feed.error}", 9, COLORS["clay"])

    def _news_empty_body(self, block: Block) -> None:
        block.text("正在同步学院公众号…", 13, COLORS["ink"], weight="bold")
        block.gap(6)
        block.text(
            "首次同步需要联网；若暂时失败，会先显示缓存或示例内容，稍后点“立即同步”重试。",
            10,
            COLORS["muted"],
        )

    def _news_item_body(self, item: "NewsItem", index: int) -> Callable[[Block], None]:
        palette = {
            "导师交流": (COLORS["clay_soft"], COLORS["clay"]),
            "人文讲座": (COLORS["sage_soft"], COLORS["pine"]),
            "通知": (COLORS["card_alt"], COLORS["ink_soft"]),
        }
        badge_fill, badge_ink = palette.get(item.kind, palette["通知"])

        def body(block: Block) -> None:
            row_top = block.y
            badge_width = block.meter.measure(item.kind, 9, "bold") + block.sz(22)
            if block.draw:
                self.kit.draw_round(
                    block.canvas,
                    block.x,
                    row_top,
                    block.x + badge_width,
                    row_top + block.sz(24),
                    round(block.sz(11)),
                    badge_fill,
                    None,
                    0,
                    (f"news_badge_{index}",),
                )
                self._text(
                    block.canvas,
                    block.x + badge_width / 2,
                    row_top + block.sz(12),
                    item.kind,
                    9,
                    badge_ink,
                    anchor="center",
                    weight="bold",
                    tags=(f"news_badge_{index}",),
                )
            title_x = block.x + badge_width + block.sz(12)
            title_width = block.width - badge_width - block.sz(12)
            title_height = block.meter.height(item.title, 13, title_width, "bold")
            if block.draw:
                self._text(
                    block.canvas,
                    title_x,
                    row_top,
                    item.title,
                    13,
                    COLORS["ink"],
                    weight="bold",
                    width=title_width,
                )
            block.y = row_top + max(block.sz(24), title_height) + block.sz(8)

            meta_parts: list[str] = []
            if item.when_text:
                meta_parts.append(f"时间 {item.when_text}")
            if item.place:
                meta_parts.append(f"地点 {item.place}")
            if meta_parts:
                block.text("  ·  ".join(meta_parts), 10, COLORS["ink_soft"], spacing=3)
                block.gap(6)
            if item.speakers:
                names = "、".join(item.speakers[:8])
                if len(item.speakers) > 8:
                    names += f" 等 {len(item.speakers)} 位"
                block.text(f"导师 / 演讲人：{names}", 10, COLORS["pine"], spacing=3)
                block.gap(6)
            if item.signup_text:
                block.text(f"抢选：{item.signup_text}", 10, COLORS["clay"], spacing=3)
                block.gap(6)
            if item.seats:
                block.text(f"名额：{item.seats}", 9, COLORS["muted"])
                block.gap(6)
            if item.summary:
                block.text(item.summary, 10, COLORS["muted"], spacing=3)
                block.gap(8)
            if block.draw and item.url:
                block.button_at(
                    f"news_open_{index}",
                    "打开原文",
                    lambda: webbrowser.open(item.url),
                    block.x,
                    block.y,
                    min(block.sz(120), block.width),
                    block.sz(30),
                    style="ghost",
                    size=9,
                )
            block.y += block.sz(30)

        return body


    def _draw_settings(self) -> float:
        """数据与设置：布局与自适应逻辑见 :mod:`qixin.pages_settings`。"""

        return draw_settings(self)
    def _show_ai_help(self) -> None:
        message = (
            "栖心使用兼容 Chat Completions 的模型接口。\n\n"
            "启动前设置以下环境变量：\n"
            "QIXIN_AI_API_KEY=你的密钥\n"
            "QIXIN_AI_BASE_URL=https://api.openai.com/v1\n"
            "QIXIN_AI_MODEL=gpt-4.1-mini\n\n"
            "也可以使用 OPENAI_API_KEY / OPENAI_BASE_URL / "
            "OPENAI_MODEL。\n\n"
            "未配置时，四维歌单、任务寄语和周报仍由本地规则完整生成。"
        )
        messagebox.showinfo("AI 接入方式", message, parent=self.root)

    def _choose_custom_font(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择界面字体",
            filetypes=[
                ("字体文件", "*.ttf *.otf *.ttc"),
                ("TrueType", "*.ttf"),
                ("OpenType", "*.otf"),
                ("字体集合", "*.ttc"),
            ],
        )
        if not path:
            return
        try:
            family = self.font_library.upload(path)
        except ValueError as exc:
            messagebox.showerror("无法更换字体", str(exc), parent=self.root)
            return
        self._refresh_after_font_change()
        self._toast(f"字体已切换为：{family}")

    def _choose_background(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择应用背景图",
            filetypes=[
                ("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            saved = prepare_background(path)
        except ValueError as exc:
            messagebox.showerror("无法更换背景", str(exc), parent=self.root)
            return
        self.store.set_setting("custom_background_path", str(saved))
        self._reload_appearance()
        self._toast("背景图已更新")

    def _reset_background(self) -> None:
        self.store.set_setting("custom_background_path", "")
        self._reload_appearance()
        self._toast("已恢复默认毛玻璃背景")

    def _choose_app_icon(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择左上角图标",
            filetypes=[
                ("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            saved = prepare_icon(path)
        except ValueError as exc:
            messagebox.showerror("无法更换图标", str(exc), parent=self.root)
            return
        self.store.set_setting("custom_icon_path", str(saved))
        self._reload_appearance()
        self._toast("左上角图标已更新")

    def _reset_app_icon(self) -> None:
        self.store.set_setting("custom_icon_path", "")
        self._reload_appearance()
        self._toast("已恢复默认图标")

    def _reload_appearance(self) -> None:
        self._load_appearance_assets()
        self.icon_photo = self._custom_taskbar_icon or self.kit.app_icon()
        self.root.iconphoto(True, self.icon_photo)
        self.render()
        if self._floating:
            self._floating.window.lift()

    def _reset_custom_font(self) -> None:
        self.font_library.reset()
        self._refresh_after_font_change()
        self._toast("已恢复默认字体")

    def _change_font_size(self, delta: float) -> None:
        self.font_scale = set_font_scale(get_font_scale() + delta)
        self.store.set_setting("font_scale", str(self.font_scale))
        self._refresh_after_font_change()
        self._toast(f"字号已调整为 {round(self.font_scale * 100)}%")

    def _refresh_after_font_change(self) -> None:
        self._sidebar_state = self._header_state = None
        self.root.option_add("*Font", widget_font(14, self.ui_scale))
        self.meter.invalidate()
        self.render()
        if self._floating:
            self._floating.set_scale()
        if self._pet:
            self._pet.refresh_font()

    def _fetch_weather_now(self) -> None:
        self._toast("正在同步天气…", 1200)

        self._request_weather(manual=True)

    def _weather_manual_ready(self, snapshot: WeatherSnapshot) -> None:
        self.weather = snapshot
        self.render()
        self._toast("天气已更新" if snapshot.live else "暂时离线，保留示例天气")

    def _export_json(self) -> None:
        default_name = f"栖心数据_{date.today().isoformat()}.json"
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出栖心本地数据",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON 数据", "*.json")],
        )
        if not target:
            return
        try:
            self.store.export_json(target)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self._toast("数据已导出到本地")

    def _export_report(self) -> None:
        report = local_weekly_report(self.store.weekly_stats())
        default_name = f"情绪与哲思周报_{date.today().isoformat()}.md"
        target = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出情绪与哲思周报",
            initialfile=default_name,
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("文本", "*.txt")],
        )
        if not target:
            return
        try:
            write_text_atomic(target, report)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self._toast("周报已保存")

    def _open_data_folder(self) -> None:
        folder = self.store.path.parent
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            webbrowser.open(folder.as_uri())

    def _launch_scenario(self, weather: str, mood: str, activity: str) -> None:
        self.music_mood = mood
        self.music_activity = activity
        self.weather_mode = weather
        self.ai_music_note = ""
        self.ai_music_reason = ""
        self.music_results = self._build_recommendations()
        self.music_index = 0
        self.show_page("music")
        self._toast(f"已生成：{weather} · {mood} · {activity}")
        if self.ai.configured:
            self._run_playlist_ai()

    def _choose_pet_image(self) -> None:
        if self._pet is None:
            self.store.set_setting("pet_visible", "1")
            self._show_pet()
        if self._pet is not None:
            self._pet.choose_image()


class WeeklyReportDialog:
    def __init__(self, app: QixinApp, stats: dict[str, Any], report: str):
        self.app = app
        self.scale = app.ui_scale
        self.stats = stats
        self.report = report
        self._ai_busy = False
        self.window = tk.Toplevel(app.root)
        self.window.title("情绪与哲思周报")
        self.window.configure(bg=COLORS["paper"])
        self.window.geometry(
            f"{self._px(820)}x{self._px(720)}"
        )
        self.window.resizable(False, False)
        self.window.transient(app.root)
        self._center()
        self.status_var = tk.StringVar(
            value="由本地数据叙事生成 · 你的记录没有离开设备"
            if not app.ai.configured
            else "本地周报已生成 · 可交给已配置的 AI 深度整理"
        )
        self._build()

    def _px(self, value: int | float) -> int:
        return max(1, round(value * self.scale))

    def _center(self) -> None:
        self.window.update_idletasks()
        width = self._px(820)
        height = self._px(720)
        root_w = max(1, self.app.root.winfo_width())
        root_h = max(1, self.app.root.winfo_height())
        x = self.app.root.winfo_rootx() + (root_w - width) // 2
        y = self.app.root.winfo_rooty() + (root_h - height) // 2
        x = max(0, min(x, self.app.root.winfo_screenwidth() - width))
        y = max(0, min(y, self.app.root.winfo_screenheight() - height))
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _build(self) -> None:
        header = tk.Frame(
            self.window,
            bg=COLORS["paper"],
            padx=self._px(42),
            pady=self._px(30),
        )
        header.pack(fill="x")
        tk.Label(
            header,
            text="情绪与哲思周报",
            bg=COLORS["paper"],
            fg=COLORS["ink"],
            font=widget_font(25, self.scale, serif=True),
            anchor="w",
        ).pack(fill="x")
        start = self.stats["start"]
        end = self.stats["end"]
        tk.Label(
            header,
            text=f"{start.strftime('%Y.%m.%d')} — {end.strftime('%Y.%m.%d')}",
            bg=COLORS["paper"],
            fg=COLORS["sage"],
            font=widget_font(10, self.scale, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(self._px(6), 0))

        text_shell = tk.Frame(
            self.window,
            bg=COLORS["card"],
            highlightbackground=COLORS["line"],
            highlightthickness=self._px(1),
        )
        self.text = tk.Text(
            text_shell,
            wrap="word",
            relief="flat",
            bd=0,
            padx=self._px(26),
            pady=self._px(22),
            bg=COLORS["card"],
            fg=COLORS["ink_soft"],
            insertbackground=COLORS["pine"],
            font=widget_font(12, self.scale),
            spacing1=self._px(3),
            spacing2=self._px(6),
            spacing3=self._px(8),
            selectbackground=COLORS["sage_soft"],
        )
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", self.report)
        self.text.configure(state="disabled")

        actions = tk.Frame(
            self.window,
            bg=COLORS["paper"],
            padx=self._px(42),
            pady=0,
        )
        actions.pack(side="bottom", fill="x", pady=(0, self._px(26)))
        status = tk.Label(
            self.window,
            textvariable=self.status_var,
            bg=COLORS["paper"],
            fg=COLORS["muted"],
            font=widget_font(9, self.scale),
            anchor="w",
        )
        status.pack(
            side="bottom",
            fill="x",
            padx=self._px(44),
            pady=(self._px(10), self._px(6)),
        )
        text_shell.pack(fill="both", expand=True, padx=self._px(42))
        self._action_button(
            actions,
            "复制全文",
            self._copy,
            COLORS["card_alt"],
            COLORS["ink"],
        ).pack(side="left")
        self._action_button(
            actions,
            "保存 Markdown",
            self._save,
            COLORS["card_alt"],
            COLORS["ink"],
        ).pack(side="left", padx=self._px(8))
        self._action_button(
            actions,
            "AI 深度整理",
            self._ai_refine,
            COLORS["pine"],
            COLORS["paper"],
        ).pack(side="right")
        self.window.bind("<Escape>", lambda _event: self.window.destroy())

    def _action_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], Any],
        bg: str,
        fg: str,
    ) -> tk.Button:
        """A canvas-quality pill rendered as a real Tk button."""

        label_font = widget_font(10, self.scale, "bold")
        measured = tkfont.Font(
            root=self.window,
            family=label_font[0],
            size=label_font[1],
            weight=label_font[2],
        )
        width = self._px(40) + measured.measure(text)
        height = self._px(40)
        primary = bg == COLORS["pine"]
        kit = self.app.kit
        if primary:
            face = kit.pill_face(
                width, height, height // 2,
                "#1B2438", "#2A3652", "#35456B", 1, highlight=0.8,
            )
            hover = kit.pill_face(
                width, height, height // 2,
                "#26324E", "#34425F", "#46577F", 1, highlight=0.9,
            )
        else:
            face = kit.pill_face(
                width, height, height // 2,
                "#FFFFFF", "#F4F7FD", "#E4E9F4", 1, highlight=0.3,
            )
            hover = kit.pill_face(
                width, height, height // 2,
                "#F1F4FB", "#EAEFFA", "#DDE4F2", 1, highlight=0.3,
            )
        button = tk.Button(
            parent,
            text=text,
            image=face,
            compound="center",
            command=command,
            relief="flat",
            bd=0,
            padx=0,
            pady=0,
            highlightthickness=0,
            bg=COLORS["paper"],
            activebackground=COLORS["paper"],
            fg=fg,
            activeforeground=fg,
            cursor="hand2",
            font=label_font,
        )
        button.image = face  # type: ignore[attr-defined]
        button.bind("<Enter>", lambda _event: button.configure(image=hover))
        button.bind("<Leave>", lambda _event: button.configure(image=face))
        return button

    def show(self) -> None:
        self.window.lift()
        self.window.focus_force()

    def _copy(self) -> None:
        self.window.clipboard_clear()
        self.window.clipboard_append(self.report)
        self.status_var.set("已复制到剪贴板")

    def _save(self) -> None:
        target = filedialog.asksaveasfilename(
            parent=self.window,
            title="保存周报",
            initialfile=f"情绪与哲思周报_{date.today().isoformat()}.md",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("文本", "*.txt")],
        )
        if target:
            try:
                write_text_atomic(target, self.report)
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc))
                return
            self.status_var.set("周报已保存")

    def _ai_refine(self) -> None:
        if not self.app.ai.configured:
            messagebox.showinfo(
                "AI 尚未配置",
                "当前展示的是本地生成的周报。\n\n"
                "设置 QIXIN_AI_API_KEY 后重启栖心，即可让 AI "
                "基于同一份匿名化统计进一步整理。",
                parent=self.window,
            )
            return
        if self._ai_busy:
            return
        self._ai_busy = True
        self.status_var.set("正在整理这一周的情绪地形…")
        self.app._run_background(
            lambda: self.app.ai.weekly_report(self.stats),
            self._ai_ready,
            self._ai_failed,
        )

    def _ai_ready(self, content: str) -> None:
        self._ai_busy = False
        if not self.window.winfo_exists():
            return
        self.report = content
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.configure(state="disabled")
        self.app.store.save_report(self.stats["start"], content)
        self.status_var.set("AI 已基于匿名化统计完成整理")

    def _ai_failed(self, message: str) -> None:
        self._ai_busy = False
        if not self.window.winfo_exists():
            return
        self.status_var.set(f"AI 整理失败，本地周报已保留 · {message[:80]}")
