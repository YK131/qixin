"""Rounded popup surfaces used by the desktop pet."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from dataclasses import dataclass
from typing import Callable

from .layout import TextMeter, fit_text
from .motion import Tween
from .theme import AURORA, COLORS, ScaledCanvas, VisualKit, active_font_family, get_font_scale, mix_color, widget_font


@dataclass(frozen=True)
class PetAction:
    label: str
    run: Callable[[], None] | None
    detail: str = ""


class GlassPanel:
    CORNER_KEY = "#FF01FE"

    def __init__(self, parent: tk.Misc, scale: float, *, interactive: bool = False):
        self.scale = scale
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.configure(bg=self.CORNER_KEY)
        self.window.attributes("-topmost", True)
        try:
            self.window.attributes("-transparentcolor", self.CORNER_KEY)
        except tk.TclError:
            self.window.configure(bg=COLORS["paper"])
        self.backing = self.window.cget("bg")
        self.canvas = ScaledCanvas(
            self.window, ui_scale=scale, bg=self.backing, highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.kit = VisualKit(self.window, scale)
        self.meter = TextMeter(self.window, scale)
        self.size = (0, 0)
        if interactive:
            self.window.bind("<Escape>", lambda _event: self.close())
            self.window.bind("<FocusOut>", lambda _event: self.window.after_idle(self._check_focus))
            self.window.bind("<ButtonPress-1>", self._outside_click, add="+")
        try:
            self.window.attributes("-alpha", 0.96)
        except tk.TclError:
            pass

    def paint(self, width: int, height: int) -> None:
        self.size = round(width * self.scale), round(height * self.scale)
        self.canvas.clear_scene()
        self.canvas.configure(width=self.size[0], height=self.size[1])
        self.photo = self.kit.panel_image(
            *self.size, self.kit.px(22),
            mix_color(COLORS["card"], COLORS["sage_soft"], 0.30), COLORS["sage_soft"],
            glows=((AURORA[0], 0.96, 0.08, self.size[0] * 0.52, 60),
                   (AURORA[2], 0.14, 0.95, self.size[0] * 0.33, 52)),
            border_alpha=210,
        )
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")

    def show(self, x: int, y: int, *, focus: bool = False, enter_from: int = 0) -> tuple[int, int]:
        width, height = self.size
        screen_x = self.window.winfo_vrootx()
        screen_y = self.window.winfo_vrooty()
        right = screen_x + self.window.winfo_vrootwidth()
        bottom = screen_y + self.window.winfo_vrootheight()
        if y + height > bottom:
            y -= height + 10
        x = max(screen_x, min(x, right - width))
        y = max(screen_y, min(y, bottom - height))
        self.window.geometry(f"{width}x{height}+{x}+{min(y + enter_from, bottom - height)}")
        self.window.deiconify()
        self.window.lift()
        if focus:
            self.window.focus_force()
        return x, y

    def _check_focus(self) -> None:
        if self.window.winfo_exists():
            focused = self.window.focus_get()
            if focused is None or focused.winfo_toplevel() is not self.window:
                self.close()

    def _outside_click(self, event: tk.Event) -> None:
        x = event.x_root - self.window.winfo_rootx()
        y = event.y_root - self.window.winfo_rooty()
        if not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
            self.close()

    def close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()


class PetMenu(GlassPanel):
    def __init__(self, parent: tk.Misc, scale: float, x: int, y: int):
        super().__init__(parent, scale, interactive=True)
        available = {family.casefold(): family for family in tkfont.families(self.window)}
        candidates = (
            "汇文明朝体", "匯文明朝體", "Huiwen-mincho", "Huiwen Mincho",
            "汇文明朝体GBK", "匯文明朝體GBK", "Huiwen-MinchoGBK",
        )
        self.menu_family = next(
            (available[name.casefold()] for name in candidates if name.casefold() in available),
            active_font_family(serif=True),
        )
        self.meter = TextMeter(self.window, scale, family=self.menu_family)
        self.x, self.y = x, y
        self.actions: list[PetAction] = []
        self.title = ""
        self.hover = 0
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._click)
        self.window.bind("<Up>", lambda _event: self._step(-1))
        self.window.bind("<Down>", lambda _event: self._step(1))
        self.window.bind("<Return>", lambda _event: self._activate(self.hover))

    def _menu_font(self, size: int) -> tuple[str, int, str]:
        return self.menu_family, widget_font(size, 1)[1], "normal"

    def display(self, title: str, actions: list[PetAction]) -> None:
        self.title = title
        self.actions = actions
        self.hover = next((i for i, action in enumerate(actions) if action.run), 0)
        scale = get_font_scale()
        self.row_h = max(32, round(29 * scale))
        self.top = max(52, round(42 * scale))
        width = max(282, round(248 * scale))
        self.paint(width, self.top + len(actions) * self.row_h + 12)
        self.canvas.create_text(19, self.top / 2, text=title, anchor="w",
                                font=self._menu_font(15), fill=COLORS["ink"])
        self.canvas.create_line(12, self.top - 3, width - 12, self.top - 3, fill=COLORS["line"])
        for i, action in enumerate(actions):
            y = self.top + i * self.row_h
            tag = f"menu_row_{i}"
            self.kit.draw_pill(
                self.canvas, 9, y + 2, width - 9, y + self.row_h - 2,
                12, COLORS["sage_soft"], tags=(tag,),
            )
            detail_width = self.meter.measure(action.detail, 8) + 12 if action.detail else 0
            self.canvas.create_text(
                19, y + self.row_h / 2, anchor="w",
                font=self._menu_font(10), fill=COLORS["ink"] if action.run else COLORS["muted"],
                text=fit_text(self.meter, action.label, width - 38 - detail_width, 10),
            )
            if action.detail:
                self.canvas.create_text(
                    width - 19, y + self.row_h / 2, anchor="e",
                    font=self._menu_font(8), fill=COLORS["sage"], text=action.detail,
                )
            self.canvas.itemconfigure(tag, state="normal" if i == self.hover else "hidden")
        self.show(self.x, self.y, focus=True)
        if self.window.grab_current() is None:
            self.window.grab_set()

    def _row(self, event: tk.Event) -> int:
        return int((event.y / self.scale - self.top) // self.row_h)

    def _motion(self, event: tk.Event) -> None:
        self._highlight(self._row(event))

    def _step(self, direction: int) -> None:
        for offset in range(1, len(self.actions) + 1):
            index = (self.hover + direction * offset) % len(self.actions)
            if self.actions[index].run:
                self._highlight(index)
                break

    def _highlight(self, index: int) -> None:
        if index != self.hover and 0 <= index < len(self.actions) and self.actions[index].run:
            self.canvas.itemconfigure(f"menu_row_{self.hover}", state="hidden")
            self.hover = index
            self.canvas.itemconfigure(f"menu_row_{index}", state="normal")

    def _click(self, event: tk.Event) -> None:
        if 0 <= event.x < self.size[0]:
            self._activate(self._row(event))

    def _activate(self, index: int) -> None:
        if 0 <= index < len(self.actions):
            action = self.actions[index].run
            if action is not None:
                action()


class PetNotice(GlassPanel):
    def __init__(
        self, parent, scale, title: str, detail: str, x: int, y: int,
        *, action: PetAction | None = None,
    ):
        super().__init__(parent, scale)
        width, height = 280, max(68, round(get_font_scale() * 49))
        if action is not None:
            width, height = 360, height + 37
        self.paint(width, height)
        for y_fraction, text, size, color in (
            (0.34, title, 11, COLORS["ink"]), (0.70, detail, 9, COLORS["sage"]),
        ):
            self.canvas.create_text(
                17, (height - 37 if action is not None else height) * y_fraction, anchor="w",
                font=widget_font(size, 1), fill=color,
                text=fit_text(self.meter, text, width - 34, size),
            )
        if action is not None:
            def open_link(_event: tk.Event) -> None:
                self.close()
                if action.run:
                    action.run()

            top = height - 39
            self.kit.draw_pill(self.canvas, 17, top, 140, height - 9, 12, COLORS["pine"], tags=("notice_action",))
            self.canvas.create_text(
                79, top + 15, text=action.label, fill=COLORS["white"],
                font=widget_font(9, 1), tags=("notice_action",),
            )
            self.canvas.tag_bind("notice_action", "<ButtonRelease-1>", open_link)
            self.canvas.tag_bind("notice_action", "<Enter>", lambda _event: self.canvas.configure(cursor="hand2"))
            self.canvas.tag_bind("notice_action", "<Leave>", lambda _event: self.canvas.configure(cursor=""))
        self._entrance: Tween | None = None
        if action is None:
            self.show(x, y)
        else:
            try:
                self.window.attributes("-alpha", 0.35)
                fade = True
            except tk.TclError:
                fade = False
            shift = round(8 * self.scale)
            x, y = self.show(x, y, enter_from=shift)
            width_px, height_px = self.size
            room = self.window.winfo_vrooty() + self.window.winfo_vrootheight() - height_px - y
            shift = min(shift, max(0, room))

            def enter(progress: float) -> None:
                top = y + round(shift * (1 - progress))
                self.window.geometry(f"{width_px}x{height_px}+{x}+{top}")
                if fade:
                    self.window.attributes("-alpha", 0.35 + 0.61 * progress)

            self._entrance = Tween(self.window, 165, enter)
        self._close_job = self.window.after(30_000 if action is not None else 5500, self.close)

    def close(self) -> None:
        if self.window.winfo_exists():
            if self._entrance is not None:
                self._entrance.cancel()
            self.window.after_cancel(self._close_job)
            super().close()
