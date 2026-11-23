from __future__ import annotations

import tkinter as tk
from typing import Callable

from .theme import COLORS, ScaledCanvas, VisualKit, font, mix_color, widget_font


MOOD_COLOR_CHOICES = [
    "#D49B36",
    "#D6855E",
    "#6E9270",
    "#4E7F85",
    "#8A7A66",
    "#C36D50",
    "#B8554B",
    "#66778F",
]


class CustomMoodDialog:
    WIDTH = 500
    HEIGHT = 430

    def __init__(
        self,
        root: tk.Tk,
        scale: float,
        kit: VisualKit,
        on_save: Callable[[str, str], str | None],
        on_close: Callable[[], None] | None = None,
    ):
        self.root = root
        self.scale = scale
        self.kit = kit
        self.on_save = on_save
        self.on_close = on_close
        self.selected_color = MOOD_COLOR_CHOICES[0]
        self.error = ""

        self.window = tk.Toplevel(root)
        self.window.title("自定义心情")
        self.window.configure(bg=COLORS["paper"])
        self.window.resizable(False, False)
        self.window.transient(root)
        width = round(self.WIDTH * scale)
        height = round(self.HEIGHT * scale)
        self.window.geometry(f"{width}x{height}")
        self._center(width, height)
        try:
            self.window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = ScaledCanvas(
            self.window,
            ui_scale=scale,
            width=width,
            height=height,
            bg=COLORS["paper"],
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self._draw()
        self.entry = tk.Entry(
            self.canvas,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=COLORS["card_alt"],
            fg=COLORS["ink"],
            insertbackground=COLORS["pine"],
            font=widget_font(12, scale),
        )
        self.entry.place(
            x=round(44 * scale),
            y=round(109 * scale),
            width=round(412 * scale),
            height=round(38 * scale),
        )
        self.entry.focus_force()
        self.entry.bind("<Return>", lambda _event: self.save())
        self.window.bind("<Escape>", lambda _event: self.close())

    def _center(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2
        self.window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def _draw(self) -> None:
        self.canvas.delete("all")
        self.kit.draw_round(
            self.canvas,
            16,
            14,
            self.WIDTH - 16,
            self.HEIGHT - 14,
            24,
            COLORS["card"],
            COLORS["line"],
            1,
        )
        self.canvas.create_text(
            42,
            32,
            anchor="nw",
            text="自定义一种心情",
            fill=COLORS["ink"],
            font=font(23, serif=True),
        )
        self.canvas.create_text(
            43,
            67,
            anchor="nw",
            text="不必符合标准词汇。给此刻的感受一个你认得的名字。",
            fill=COLORS["muted"],
            font=font(9),
        )
        self.kit.draw_round(
            self.canvas,
            44,
            103,
            456,
            153,
            14,
            COLORS["card_alt"],
            COLORS["line"],
            1,
        )
        self.canvas.create_text(
            43,
            170,
            anchor="nw",
            text="选择一种颜色",
            fill=COLORS["sage"],
            font=font(9, "bold"),
        )
        for index, color in enumerate(MOOD_COLOR_CHOICES):
            x = 69 + index * 52
            tag = f"mood_color_{index}"
            selected = color == self.selected_color
            self.canvas.create_oval(
                x - 17,
                196,
                x + 17,
                230,
                fill=color,
                outline=COLORS["ink"] if selected else COLORS["card"],
                width=3 if selected else 1,
                tags=(tag,),
            )
            self.canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda _event, value=color: self._choose_color(value),
            )
            self.canvas.tag_bind(
                tag,
                "<Enter>",
                lambda _event: self.canvas.configure(cursor="hand2"),
            )
            self.canvas.tag_bind(
                tag,
                "<Leave>",
                lambda _event: self.canvas.configure(cursor=""),
            )
        self.kit.draw_round(
            self.canvas,
            44,
            249,
            456,
            304,
            16,
            mix_color(self.selected_color, COLORS["white"], 0.84),
            None,
            0,
        )
        self.canvas.create_text(
            62,
            264,
            anchor="nw",
            text="预览",
            fill=self.selected_color,
            font=font(8, "bold"),
        )
        self.canvas.create_text(
            62,
            282,
            anchor="nw",
            text="新心情会出现在今日打卡和情绪统计里。",
            fill=COLORS["ink_soft"],
            font=font(9),
        )
        if self.error:
            self.canvas.create_text(
                44,
                317,
                anchor="nw",
                text=self.error,
                fill=COLORS["clay"],
                font=font(8, "bold"),
            )
        self._button("mood_cancel", 244, 351, 340, 391, "取消", self.close, False)
        self._button("mood_save", 350, 351, 456, 391, "添加心情", self.save, True)

    def _button(
        self,
        tag: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        text: str,
        command: Callable[[], None],
        primary: bool,
    ) -> None:
        self.kit.draw_pill(
            self.canvas,
            x1,
            y1,
            x2,
            y2,
            (y2 - y1) / 2,
            "#1B2438" if primary else "#FFFFFF",
            "#2A3652" if primary else "#F4F7FD",
            "#35456B" if primary else "#E4E9F4",
            1,
            (tag,),
            highlight=0.8 if primary else 0.3,
        )
        self.canvas.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text=text,
            fill="#F7F9FF" if primary else COLORS["ink_soft"],
            font=font(10, "bold"),
            anchor="center",
            tags=(tag,),
        )
        self.canvas.tag_bind(tag, "<Button-1>", lambda _event: command())
        self.canvas.tag_bind(
            tag,
            "<Enter>",
            lambda _event: self.canvas.configure(cursor="hand2"),
        )
        self.canvas.tag_bind(tag, "<Leave>", lambda _event: self.canvas.configure(cursor=""))

    def _choose_color(self, color: str) -> None:
        self.selected_color = color
        self.error = ""
        self._draw()

    def save(self) -> None:
        name = self.entry.get().strip()
        if not name:
            self.error = "先给这种心情起一个名字。"
            self._draw()
            return
        if len(name) > 8:
            self.error = "名字请控制在 8 个汉字以内。"
            self._draw()
            return
        error = self.on_save(name, self.selected_color)
        if error:
            self.error = error
            self._draw()
            return
        self.close()

    def close(self) -> None:
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()
