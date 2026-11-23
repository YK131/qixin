from __future__ import annotations

import math
import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox
from typing import TYPE_CHECKING, Any, Callable

from PIL import Image, ImageOps, ImageTk

from .db import Store, app_data_dir
from .matting import fallback, load_image, matte, normalize
from .pet_panel import PetAction, PetMenu, PetNotice
from .theme import COLORS, widget_font


if TYPE_CHECKING:
    from .desktop_tools import DesktopTools, FocusSession


DEFAULT_PET_IMAGE = Path(__file__).resolve().parent / "assets" / "pet_default.png"
CUSTOM_PET_IMAGE = app_data_dir() / "pet" / "custom.png"

PET_SIZES = {
    "small": 150,
    "medium": 220,
    "large": 290,
}

PET_SIZE_LABELS = {
    "small": "小",
    "medium": "中",
    "large": "大",
}


def pendulum_angle(progress: float) -> float:
    """One full single-pendulum cycle, from centre to ±45° and back."""

    return 45.0 * math.sin(2 * math.pi * progress)


def prepare_pet_image(source: str | Path, destination: str | Path) -> Path:
    """Turn any Pillow-readable picture into a 512px transparent pet PNG.

    The background is removed automatically (see :mod:`qixin.matting`); if the
    cut-out looks implausible the original picture is kept inside a soft
    vignette with a shadow, so a failed upload still gives the user a visible
    pet instead of an empty window.
    """

    source = Path(source)
    destination = Path(destination)
    image = load_image(source)

    try:
        subject = matte(image)
    except Exception:  # noqa: BLE001 - a broken cut-out must never break upload
        subject = image

    canvas = normalize(subject)
    if canvas.getchannel("A").getextrema()[1] == 0:
        # Nothing survived: fall back to the original with its vignette.
        canvas = normalize(fallback(image))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.tmp.png")
    canvas.save(temporary, "PNG", optimize=True)
    os.replace(temporary, destination)
    return destination


def _fallback_pet() -> Image.Image:
    from PIL import ImageDraw

    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((88, 42, 424, 470), fill="#F2D58A")
    draw.ellipse((172, 148, 224, 200), fill="#E7EFE0", outline="#7B9D65", width=12)
    draw.ellipse((288, 148, 340, 200), fill="#E7EFE0", outline="#7B9D65", width=12)
    draw.ellipse((190, 166, 210, 186), fill="#26342E")
    draw.ellipse((306, 166, 326, 186), fill="#26342E")
    draw.arc((210, 184, 302, 256), start=10, end=170, fill="#9D7647", width=7)
    return image


class DesktopPet:
    """A transparent, draggable, always-on-top desktop companion."""

    TRANSPARENT_KEY = "#F8F3E9"

    def __init__(
        self,
        root: tk.Tk,
        store: Store,
        ui_scale: float,
        *,
        tools: DesktopTools | None = None,
        on_open_app: Callable[[], None] | None = None,
        on_toggle_wisdom: Callable[[], None] | None = None,
        on_food_wheel: Callable[[], None] | None = None,
        on_hide: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_image_changed: Callable[[], None] | None = None,
    ):
        self.root = root
        self.store = store
        self.tools = tools
        self.menu: PetMenu | None = None
        self.notice: PetNotice | None = None
        self._notice_is_hover = False
        self._hover_job: str | None = None
        self._fullscreen_quiet = False
        self._badge_state: tuple[str, int, int] | None = None
        self.scale = max(1.0, float(ui_scale))
        self.on_open_app = on_open_app
        self.on_toggle_wisdom = on_toggle_wisdom
        self.on_food_wheel = on_food_wheel
        self.on_hide = on_hide
        self.on_quit = on_quit
        self.on_image_changed = on_image_changed

        self.size_key = store.get_setting("pet_size", "medium")
        if self.size_key not in PET_SIZES:
            self.size_key = "medium"
        self.click_sway = store.get_setting("pet_click_sway", "1") == "1"
        self.click_bounce = store.get_setting("pet_click_bounce", "1") == "1"
        self._phase_job: str | None = None
        self._frame_cache: list[ImageTk.PhotoImage] = []
        self._drag_start: tuple[int, int, int, int] | None = None
        self._dragged = False
        self._closed = False
        self._photo: ImageTk.PhotoImage | None = None
        self._master = self._load_master()

        self.window = tk.Toplevel(root)
        self.window.title("栖心桌宠")
        self.window.overrideredirect(True)
        self.window.configure(bg=self.TRANSPARENT_KEY)
        try:
            self.window.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
            self.window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass

        self._base_px = round(PET_SIZES[self.size_key] * self.scale)
        self._side_px = self._window_side()
        self.canvas = tk.Canvas(
            self.window,
            width=self._side_px,
            height=self._side_px,
            bg=self.TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self._place_window()
        self._render_frame(1.0, 1.0, 0)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Control-Button-1>", self._show_menu)
        self.canvas.bind("<Enter>", self._hover_enter)
        self.canvas.bind("<Leave>", self._hover_leave)
        self.window.bind("<Escape>", lambda _event: self._request_hide())
        self._precompute_job = self.window.after(140, self._precompute_animation)

    @property
    def custom_active(self) -> bool:
        return (
            self.store.get_setting("pet_image", "default") == "custom"
            and CUSTOM_PET_IMAGE.exists()
        )

    def _image_path(self) -> Path:
        return CUSTOM_PET_IMAGE if self.custom_active else DEFAULT_PET_IMAGE

    def _load_master(self) -> Image.Image:
        try:
            with Image.open(self._image_path()) as opened:
                image = opened.convert("RGBA")
                image.load()
            if image.size != (512, 512):
                image = ImageOps.contain(
                    image,
                    (512, 512),
                    Image.Resampling.LANCZOS,
                )
            return image
        except (OSError, ValueError):
            return _fallback_pet()

    def _window_side(self) -> int:
        pet_size = PET_SIZES[self.size_key]
        # 45° swing needs a larger transparent canvas than the resting pose.
        return round((pet_size * 1.62 + 30) * self.scale)

    def _screen_limits(self) -> tuple[int, int, int, int]:
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        margin = round(18 * self.scale)
        return (
            margin,
            margin,
            max(margin, screen_w - self._side_px - margin),
            max(margin, screen_h - self._side_px - round(58 * self.scale)),
        )

    def _place_window(self) -> None:
        min_x, min_y, max_x, max_y = self._screen_limits()
        saved_x = self.store.get_setting("pet_x")
        saved_y = self.store.get_setting("pet_y")
        try:
            x = int(saved_x) if saved_x else max_x
            y = int(saved_y) if saved_y else max_y
        except ValueError:
            x, y = max_x, max_y
        x = min(max(x, min_x), max_x)
        y = min(max(y, min_y), max_y)
        self.window.geometry(f"{self._side_px}x{self._side_px}+{x}+{y}")

    def refresh_font(self) -> None:
        self.close_menu()

    def menu_is_open(self) -> bool:
        return self.menu is not None and bool(self.menu.window.winfo_exists())

    def close_menu(self) -> None:
        if self.menu is not None:
            self.menu.close()
            self.menu = None

    def _run_menu_action(self, command: Callable[[], None]) -> None:
        self.close_menu()
        command()

    def _action(self, label: str, command: Callable[[], None], detail: str = "") -> PetAction:
        return PetAction(label, lambda: self._run_menu_action(command), detail)

    def _show_menu(self, event: tk.Event[Any]) -> str:
        self._cancel_hover()
        self.hide_notice()
        self.close_menu()
        self.menu = PetMenu(self.window, self.scale, event.x_root, event.y_root)
        self._main_menu()
        return "break"

    def _main_actions(self) -> list[PetAction]:
        actions = []
        if self.tools is not None:
            actions.extend((
                PetAction("专注计时", self._focus_menu, "25 分钟  ›"),
                self._action("随手记一下", self.tools.open_capture, "Ctrl+Alt+N"),
                self._action("下一件事", lambda: self._show_next_schedule(manual=True)),
                self._action(
                    "恢复提醒" if self.tools.muted_until > time.time() else "暂停提醒一小时",
                    self.tools.toggle_quiet,
                ),
            ))
        actions.extend((
            self._action("今天吃什么？", self._open_food_wheel),
            PetAction("桌宠外观与动画", self._appearance_menu, "›"),
            self._action("打开栖心", self._open_app),
            PetAction("更多操作", self._more_menu, "›"),
        ))
        return actions

    def _main_menu(self) -> None:
        if self.menu is not None:
            self.menu.display("栖心桌宠", self._main_actions())

    def _more_menu(self) -> None:
        if self.menu is not None:
            self.menu.display("更多操作", [
                PetAction("返回", self._main_menu, "‹"),
                self._action("显示或隐藏轻语窗", self._toggle_wisdom),
                self._action("隐藏桌宠", self._request_hide),
                self._action("退出栖心", self._quit_app),
            ])

    def _appearance_menu(self) -> None:
        if self.menu is not None:
            self.menu.display("桌宠外观与动画", [
                PetAction("返回", self._main_menu, "‹"),
                self._action("更换桌宠形象", self.choose_image),
                self._action("恢复默认外观", self.reset_image)
                if self.custom_active else PetAction("已使用默认外观", None),
                PetAction("桌宠大小", self._size_menu, PET_SIZE_LABELS[self.size_key] + "  ›"),
                PetAction("点击动画选项", self._animation_menu, "›"),
                self._action("播放点击动画", self.bounce),
            ])

    def _size_menu(self) -> None:
        if self.menu is not None:
            self.menu.display("桌宠大小", [PetAction("返回", self._appearance_menu, "‹")] + [
                self._action(f"{label}号", lambda target=key: self.set_size(target),
                             "当前" if key == self.size_key else "")
                for key, label in PET_SIZE_LABELS.items()
            ])

    def _animation_menu(self) -> None:
        if self.menu is not None:
            self.menu.display("点击动画选项", [
                PetAction("返回", self._appearance_menu, "‹"),
                self._action("左右摇摆", lambda: self._set_animation_option("sway", not self.click_sway),
                             "开启" if self.click_sway else "关闭"),
                self._action("Q 弹回弹", lambda: self._set_animation_option("bounce", not self.click_bounce),
                             "开启" if self.click_bounce else "关闭"),
            ])

    def refresh_focus_menu(self) -> None:
        if self.menu_is_open() and self.menu.title == "专注计时":
            self._focus_menu()

    def _focus_menu(self, page: int = 0) -> None:
        tools, menu = self.tools, self.menu
        if tools is None or menu is None:
            return
        actions = [PetAction("返回", self._main_menu, "‹")]
        session = tools.session
        if session is None:
            pending = [row for row in self.store.tasks_for_day() if not row["done"]]
            page_size = 4
            for row in pending[page * page_size : (page + 1) * page_size]:
                actions.append(self._action(
                    row["title"], lambda item=row: tools.start(item["id"], item["title"]),
                ))
            if page > 0:
                actions.append(PetAction("上一页", lambda: self._focus_menu(page - 1), "‹"))
            if (page + 1) * page_size < len(pending):
                actions.append(PetAction("更多待办", lambda: self._focus_menu(page + 1), "›"))
            actions.append(self._action("直接开始专注", lambda: tools.start(None, "自由专注"), "25 分钟"))
            menu.display("选择一条待办", actions)
            return

        actions.append(PetAction(session.title, None))
        if session.phase in ("focus", "break"):
            actions.append(self._action("结束计时", tools.finish))
        else:
            actions.append(self._action("再专注 25 分钟", tools.continue_focus))
            if session.phase == "ready":
                actions.append(self._action("休息 5 分钟", tools.rest))
            if session.task_id is not None:
                actions.append(self._action("标记待办完成", lambda: tools.finish(complete_task=True)))
            actions.append(self._action("结束本次专注", tools.finish))
        menu.display("专注计时", actions)

    def _hover_enter(self, _event: tk.Event[Any]) -> None:
        self.canvas.configure(cursor="hand2")
        if self.tools is not None:
            self._hover_job = self.window.after(650, self._show_next_schedule)

    def _hover_leave(self, _event: tk.Event[Any]) -> None:
        self.canvas.configure(cursor="")
        self._cancel_hover()
        if self._notice_is_hover:
            self.hide_notice()

    def _cancel_hover(self) -> None:
        if self._hover_job is not None:
            self.window.after_cancel(self._hover_job)
            self._hover_job = None

    def _show_next_schedule(self, *, manual: bool = False) -> None:
        self._hover_job = None
        if self.tools is not None and not self.menu_is_open() and not self.tools.signup_notice_open() and (
            manual or not self.tools.is_quiet(time.time())
        ):
            self.notify(*self.tools.next_schedule(), hover=not manual)

    def notify(self, title: str, detail: str, *, hover: bool = False) -> None:
        self.hide_notice()
        x = self.window.winfo_rootx()
        y = self.window.winfo_rooty()
        self._notice_is_hover = hover
        self.notice = PetNotice(self.window, self.scale, title, detail, x, y - round(82 * self.scale))

    def hide_notice(self) -> None:
        if self.notice is not None:
            self.notice.close()
            self.notice = None

    def set_fullscreen_quiet(self, enabled: bool) -> None:
        if self._fullscreen_quiet == enabled:
            return
        self._fullscreen_quiet = enabled
        if enabled:
            self._cancel_hover()
            self.hide_notice()
            self.close_menu()
            self.window.withdraw()
        else:
            self.window.deiconify()
            self.window.lift()

    def show_focus(self, session: FocusSession | None) -> None:
        remaining = session.remaining(time.time()) if session is not None else 0
        state = None if session is None else (session.phase, remaining, self._side_px)
        if state == self._badge_state:
            return
        self._badge_state = state
        self.canvas.delete("focus")
        if session is None:
            return
        inset = round(13 * self.scale)
        ring = (inset, inset, self._side_px - inset, self._side_px - inset)
        self.canvas.create_oval(*ring, outline=COLORS["sage_soft"], width=max(6, round(8*self.scale)), tags=("focus",))
        if remaining:
            self.canvas.create_arc(
                *ring, start=90, extent=-359.9 * remaining / session.duration,
                style="arc", outline=COLORS["sage"], width=max(6, round(8*self.scale)), tags=("focus",),
            )
            radius = (ring[2] - ring[0]) / 2
            center = self._side_px / 2
            cap = max(6, round(8*self.scale)) / 2
            for angle in (0, math.radians(359.9 * remaining / session.duration)):
                x = center + radius * math.sin(angle)
                y = center - radius * math.cos(angle)
                self.canvas.create_oval(x-cap, y-cap, x+cap, y+cap, fill=COLORS["sage"], outline="", tags=("focus",))
        labels = {"focus": "专注", "break": "休息", "ready": "专注结束", "rested": "休息结束"}
        label = labels[session.phase]
        if remaining:
            label += f"  {remaining // 60:02d}:{remaining % 60:02d}"
        x, y = self._side_px / 2, self._side_px / 2
        font = widget_font(10, self.scale, "bold")
        width = tkfont.Font(root=self.window, font=font).measure(label) + 20
        self.canvas.create_oval(
            x - width / 2, y - 13, x + width / 2, y + 13,
            fill=COLORS["card"], outline=COLORS["line"], tags=("focus",),
        )
        self.canvas.create_text(x, y, text=label, font=font, fill=COLORS["pine"], tags=("focus",))

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.window,
            title="选择桌宠形象（任意格式图片，自动去背景）",
            filetypes=[
                (
                    "所有支持的图片",
                    "*.png *.jpg *.jpeg *.jpe *.jfif *.webp *.bmp *.gif *.tif "
                    "*.tiff *.ico *.ppm *.pgm *.tga *.dds *.pcx *.psd",
                ),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            prepare_pet_image(path, CUSTOM_PET_IMAGE)
        except ValueError as exc:
            messagebox.showerror(
                "无法更换形象",
                f"{exc}\n\n任意格式图片都可以，会自动去背景。",
                parent=self.window,
            )
            return
        self.store.set_setting("pet_image", "custom")
        self._master = self._load_master()
        self._frame_cache = []
        self._render_frame(1.0, 1.0, 0)
        self._schedule_precompute(80)
        if self.on_image_changed:
            self.on_image_changed()

    def reset_image(self) -> None:
        self.store.set_setting("pet_image", "default")
        self._master = self._load_master()
        self._frame_cache = []
        self._render_frame(1.0, 1.0, 0)
        self._schedule_precompute(80)
        if self.on_image_changed:
            self.on_image_changed()

    def set_size(self, size_key: str) -> None:
        if size_key not in PET_SIZES:
            return
        old_x = self.window.winfo_x()
        old_y = self.window.winfo_y()
        old_side = self._side_px
        self.size_key = size_key
        self.store.set_setting("pet_size", size_key)
        self._base_px = round(PET_SIZES[self.size_key] * self.scale)
        self._side_px = self._window_side()
        new_x = old_x + (old_side - self._side_px) // 2
        new_y = old_y + old_side - self._side_px
        min_x, min_y, max_x, max_y = self._screen_limits()
        new_x = min(max(new_x, min_x), max_x)
        new_y = min(max(new_y, min_y), max_y)
        self.canvas.configure(width=self._side_px, height=self._side_px)
        self.window.geometry(f"{self._side_px}x{self._side_px}+{new_x}+{new_y}")
        self.store.set_setting("pet_x", str(new_x))
        self.store.set_setting("pet_y", str(new_y))
        self._frame_cache = []
        self._render_frame(1.0, 1.0, 0)
        self._schedule_precompute(80)

    def _set_animation_option(self, name: str, enabled: bool) -> None:
        if name == "sway":
            self.click_sway = enabled
            self.store.set_setting("pet_click_sway", "1" if enabled else "0")
        elif name == "bounce":
            self.click_bounce = enabled
            self.store.set_setting("pet_click_bounce", "1" if enabled else "0")
        if self._phase_job:
            try:
                self.window.after_cancel(self._phase_job)
            except tk.TclError:
                pass
            self._phase_job = None
        self._frame_cache = []
        self._render_frame(1.0, 1.0, 0)
        self._schedule_precompute(60)

    def _compose_frame(
        self,
        scale_x: float,
        scale_y: float,
        offset_y: float,
        rotation: float = 0.0,
    ) -> Image.Image:
        side = self._side_px
        target_w = max(1, round(self._base_px * scale_x))
        target_h = max(1, round(self._base_px * scale_y))
        scaled = self._master.resize(
            (target_w, target_h),
            Image.Resampling.LANCZOS,
        )
        if abs(rotation) > 0.01:
            scaled = scaled.rotate(
                rotation,
                resample=Image.Resampling.BICUBIC,
                expand=True,
            )
        frame = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        x = (side - scaled.width) // 2
        bottom_margin = round(12 * self.scale)
        y = side - scaled.height - bottom_margin + round(offset_y * self.scale)
        frame.alpha_composite(scaled, (x, y))
        return frame

    def _render_frame(self, scale_x: float, scale_y: float, offset_y: float) -> None:
        if self._closed:
            return
        frame = self._compose_frame(scale_x, scale_y, offset_y)
        self._photo = ImageTk.PhotoImage(frame, master=self.window)
        self.canvas.delete("pet")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags=("pet",))
        self.canvas.tag_raise("focus")

    def _build_animation_frames(self) -> None:
        self._frame_cache = []
        if not self.click_sway and not self.click_bounce:
            return
        total_frames = 36
        for index in range(total_frames + 1):
            progress = index / total_frames
            squash_wave = math.cos(2 * math.pi * 2.25 * progress) * math.exp(
                -3.8 * progress
            )
            # One clean pendulum period: fast through the centre and slow at ±45°.
            sway = math.sin(2 * math.pi * progress)
            if self.click_bounce:
                scale_x = 1.0 + 0.115 * squash_wave
                scale_y = 1.0 - 0.19 * squash_wave
                offset_y = 5.2 * squash_wave
            else:
                scale_x = scale_y = 1.0
                offset_y = 0.0
            rotation = pendulum_angle(progress) if self.click_sway else 0.0
            frame = self._compose_frame(
                scale_x,
                scale_y,
                offset_y,
                rotation,
            )
            self._frame_cache.append(ImageTk.PhotoImage(frame, master=self.window))
        normal = self._compose_frame(1.0, 1.0, 0.0)
        self._frame_cache[-1] = ImageTk.PhotoImage(normal, master=self.window)

    def _schedule_precompute(self, delay: int) -> None:
        if self._precompute_job is not None:
            self.window.after_cancel(self._precompute_job)
        self._precompute_job = self.window.after(delay, self._precompute_animation)

    def _precompute_animation(self) -> None:
        self._precompute_job = None
        if (
            self._closed
            or self._frame_cache
            or (not self.click_sway and not self.click_bounce)
        ):
            return
        self._build_animation_frames()

    def bounce(self) -> None:
        if self._closed or (not self.click_sway and not self.click_bounce):
            return
        if self._phase_job:
            try:
                self.window.after_cancel(self._phase_job)
            except tk.TclError:
                pass
            self._phase_job = None
        if not self._frame_cache:
            self._build_animation_frames()
        frames = list(self._frame_cache)
        if not frames:
            return
        started = time.perf_counter()
        frame_interval = 1 / 60

        def play(index: int = 0) -> None:
            self._phase_job = None
            if self._closed or index >= len(frames):
                return
            self._photo = frames[index]
            self.canvas.delete("pet")
            self.canvas.create_image(
                0,
                0,
                anchor="nw",
                image=self._photo,
                tags=("pet",),
            )
            self.canvas.tag_raise("focus")
            if index == len(frames) - 1:
                return
            target = started + (index + 1) * frame_interval
            delay_ms = max(1, round((target - time.perf_counter()) * 1000))
            self._phase_job = self.window.after(delay_ms, lambda: play(index + 1))

        play()

    def _press(self, event: tk.Event[Any]) -> None:
        self._cancel_hover()
        if self._notice_is_hover:
            self.hide_notice()
        self._drag_start = (
            event.x_root,
            event.y_root,
            self.window.winfo_x(),
            self.window.winfo_y(),
        )
        self._dragged = False

    def _drag(self, event: tk.Event[Any]) -> None:
        if not self._drag_start:
            return
        start_x, start_y, window_x, window_y = self._drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if abs(dx) + abs(dy) > 4:
            self._dragged = True
        min_x, min_y, max_x, max_y = self._screen_limits()
        x = min(max(window_x + dx, min_x), max_x)
        y = min(max(window_y + dy, min_y), max_y)
        self.window.geometry(f"+{x}+{y}")

    def _release(self, _event: tk.Event[Any]) -> None:
        if self._dragged:
            self.store.set_setting("pet_x", str(self.window.winfo_x()))
            self.store.set_setting("pet_y", str(self.window.winfo_y()))
        else:
            self.bounce()
        self._drag_start = None
        self._dragged = False

    def _open_app(self) -> None:
        if self.on_open_app:
            self.on_open_app()

    def _toggle_wisdom(self) -> None:
        if self.on_toggle_wisdom:
            self.on_toggle_wisdom()

    def _open_food_wheel(self) -> None:
        if self.on_food_wheel:
            self.on_food_wheel()

    def _request_hide(self) -> None:
        if self.on_hide:
            self.on_hide()

    def _quit_app(self) -> None:
        if self.on_quit:
            self.on_quit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._precompute_job is not None:
            self.window.after_cancel(self._precompute_job)
            self._precompute_job = None
        if self._phase_job:
            try:
                self.window.after_cancel(self._phase_job)
            except tk.TclError:
                pass
        self._cancel_hover()
        self.close_menu()
        self.hide_notice()
        self._frame_cache.clear()
        try:
            self.window.destroy()
        except tk.TclError:
            pass
