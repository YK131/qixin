from __future__ import annotations

import math
import random
import sys
import time
import tkinter as tk
from datetime import datetime
from typing import Any, Callable

from .theme import (
    COLORS,
    ScaledCanvas,
    VisualKit,
    font,
    get_font_scale,
    mix_color,
)


# 每个餐段的菜池都一次性铺在同一张转盘上，所以数量控制在 16：再多扇形就会
# 窄到放不下四个字的菜名。名字尽量保持 4-6 个汉字，且全局不重复。
MEAL_OPTIONS: dict[str, list[str]] = {
    "早餐": [
        "煎饼果子",
        "鸡蛋灌饼",
        "豆浆油条",
        "小笼汤包",
        "鲜肉馄饨",
        "咸豆腐脑",
        "皮蛋瘦肉粥",
        "小米南瓜粥",
        "火腿三明治",
        "广式肠粉",
        "腊汁肉夹馍",
        "葱油手抓饼",
        "鲜肉生煎",
        "海苔饭团",
        "香辣鸡腿堡",
        "白粥咸菜",
    ],
    "午餐": [
        "麻辣香锅",
        "黄焖鸡米饭",
        "兰州拉面",
        "潮汕砂锅粥",
        "柳州螺蛳粉",
        "石锅拌饭",
        "老坛酸菜鱼",
        "南昌瓦罐汤",
        "韩式烤肉饭",
        "重庆鸡公煲",
        "日式咖喱饭",
        "手工水饺",
        "成都冒菜",
        "番茄盖浇饭",
        "黑椒铁板饭",
        "家常小碗菜",
    ],
    "晚餐": [
        "香辣烤鱼",
        "重庆麻辣烫",
        "台式卤肉饭",
        "扬州蛋炒饭",
        "过桥米线",
        "隆江猪脚饭",
        "干锅花菜",
        "番茄牛腩",
        "日式关东煮",
        "铁锅炖鸡",
        "蒜蓉粉丝扇贝",
        "青椒肉丝",
        "香菇滑鸡",
        "酸辣土豆丝",
        "梅菜扣肉",
        "麻婆豆腐",
    ],
    "夜宵": [
        "炭火烧烤",
        "麻辣小龙虾",
        "街边炒面",
        "韩式炸鸡",
        "东北烤冷面",
        "长沙臭豆腐",
        "川味酸辣粉",
        "铁板鱿鱼",
        "啤酒炸串",
        "便利店关东煮",
        "砂锅米线",
        "红油抄手",
        "芝士热狗",
        "生滚鱼片粥",
        "卤味拼盘",
        "爆浆鸡排",
    ],
}

WHEEL_COLORS = [
    "#C6E4F5",
    "#CDEBD9",
    "#F8E9B8",
    "#D3E8F1",
    "#E3DDF2",
    "#DCF0C9",
    "#F7DFCF",
    "#C6E7E5",
]

MAX_LABEL_CHARS = 6
IDLE_RESULT = "今天想吃得轻松一点"
MIN_TK_ANGLE_VERSION = (8, 6)


def _abbreviate(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    """Keep at most ``limit`` characters, marking the cut with an ellipsis."""

    text = str(text).strip()
    limit = max(1, int(limit))
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _split_two_lines(text: str) -> str:
    """Balance a short Chinese dish name into at most two centred lines."""

    text = text.strip()
    if len(text) <= 2:
        return text
    if len(text) <= 4:
        cut = (len(text) + 1) // 2
    else:
        cut = min(3, max(2, len(text) - 2))
    return f"{text[:cut]}\n{text[cut:]}"


def _supports_text_angle(widget: tk.Misc) -> bool:
    """Tk 8.6 added the ``-angle`` option on text items; older Tk lacks it."""

    try:
        version = str(widget.tk.call("info", "patchlevel"))
    except tk.TclError:
        return False
    parts = version.split(".")
    try:
        return (int(parts[0]), int(parts[1])) >= MIN_TK_ANGLE_VERSION
    except (IndexError, ValueError):
        return False


def _window_decoration() -> tuple[int, int]:
    """Return ``(side border, caption + border)`` in screen pixels.

    ``wm geometry`` positions the decorated window while Tk measures the
    client area, so the difference has to be budgeted or the dialog can hang a
    caption-bar off the bottom of the screen.
    """

    if sys.platform == "win32":
        try:
            import ctypes

            metrics = ctypes.windll.user32.GetSystemMetrics
            caption = int(metrics(4))  # SM_CYCAPTION
            frame_x = int(metrics(32))  # SM_CXSIZEFRAME
            frame_y = int(metrics(33))  # SM_CYSIZEFRAME
            padded = int(metrics(92))  # SM_CXPADDEDBORDER
            border = max(0, frame_x + padded)
            return border, max(0, caption + frame_y + padded)
        except (AttributeError, OSError, ValueError):
            pass
    return 0, 0


def _work_area(root: tk.Misc) -> tuple[int, int, int, int]:
    """Return the screen work area (taskbar excluded) in screen pixels."""

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030
            ok = ctypes.windll.user32.SystemParametersInfoW(
                0x0030,
                0,
                ctypes.byref(rect),
                0,
            )
            width = int(rect.right) - int(rect.left)
            height = int(rect.bottom) - int(rect.top)
            if ok and width > 320 and height > 320:
                return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
        except (AttributeError, OSError, ValueError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class FoodWheelDialog:
    """One big wheel with every dish of the current meal on it.

    Layout is computed in screen pixels so the wheel can fill the available
    work area, then converted to the logical coordinates that
    :class:`~qixin.theme.ScaledCanvas` expects.  Text is scaled by the global
    font coefficient and clamped to the space a sector actually offers, so a
    larger font never overlaps a neighbour or spills out of the wheel.
    """

    # Geometry budget (in pixels at font scale 1.0); all of it is multiplied
    # by the active font scale unless noted otherwise.
    OUTER_MARGIN = 11.0
    TITLE_SIZE = 26.0
    SUBTITLE_SIZE = 11.0
    BADGE_SIZE = 9.0
    RESULT_SIZE = 13.5
    BUTTON_TEXT_SIZE = 15.0
    BUTTON_HEIGHT = 52.0
    WHEEL_SHARE = 0.56
    HUB_SHARE = 0.145
    LABEL_ANCHOR_SHARE = 0.27
    LABEL_OUTER_SHARE = 0.965
    LABEL_RADIUS_SHARE = 0.58

    def __init__(
        self,
        root: tk.Tk,
        ui_scale: float,
        kit: VisualKit,
        on_close: Callable[[], None] | None = None,
    ):
        # ui.py calls ``FoodWheelDialog(root, ui_scale, kit, on_close=...)``.
        # Accept ``(root, kit, ui_scale)`` as well, in case a caller uses the
        # kit-first spelling.
        if isinstance(ui_scale, VisualKit) and isinstance(kit, (int, float)):
            ui_scale, kit = kit, ui_scale
        self.root = root
        try:
            self.scale = max(0.5, float(ui_scale or 1.0))
        except (TypeError, ValueError):
            self.scale = 1.0
        self.kit = kit
        self.on_close = on_close
        self.font_scale = get_font_scale()
        self.rotation = 0.0
        self.spinning = False
        self._animation_job: str | None = None
        self._meal = self._current_meal()
        self.options = list(MEAL_OPTIONS[self._meal])
        random.shuffle(self.options)
        self.result = ""
        self.winner: int | None = None
        self._result_popup: tk.Toplevel | None = None
        self._labels: list[tuple[str, float]] = []
        self._labels_radial = False
        self._labels_key: tuple[Any, ...] | None = None
        self._frame_x, self._frame_y = _window_decoration()

        self.window = tk.Toplevel(root)
        self.window.title("今天吃什么")
        self.window.configure(bg=COLORS["paper"])
        self.window.resizable(False, False)
        self.window.transient(root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._compute_layout()
        self.window.geometry(
            f"{self.width_px}x{self.height_px}+{self._left}+{self._top}"
        )
        try:
            self.window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = ScaledCanvas(
            self.window,
            ui_scale=self.scale,
            width=self.width_px,
            height=self.height_px,
            bg=COLORS["paper"],
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self._text_angle = _supports_text_angle(self.window)
        self._refresh_labels()
        self._draw()
        self._focus_job = self.window.after(80, self.window.focus_force)
        self.window.bind("<Escape>", lambda _event: self.close())

    def show(self) -> None:
        """Bring an existing dialog back to the front (ui.py keeps one)."""

        try:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _compute_layout(self) -> None:
        fs = self.font_scale
        work_left, work_top, work_right, work_bottom = _work_area(self.root)
        # Tk reports its own screen rectangle; if the process is not DPI aware
        # the two sources can disagree, so intersect them.  The window must
        # never be placed outside what Tk believes the screen is.
        screen_w = max(320, self.root.winfo_screenwidth())
        screen_h = max(320, self.root.winfo_screenheight())
        left = max(0, min(work_left, screen_w))
        top = max(0, min(work_top, screen_h))
        right = min(screen_w, max(left + 320, work_right))
        bottom = min(screen_h, max(top + 320, work_bottom))
        area_w = max(360, right - left)
        area_h = max(360, bottom - top)
        deco_w = 2 * self._frame_x
        deco_h = self._frame_y + self._frame_x
        avail_w = max(320, area_w - deco_w)
        avail_h = max(320, area_h - deco_h)
        short = min(avail_w, avail_h)

        margin = self.OUTER_MARGIN * fs
        title_px = self.TITLE_SIZE * fs
        subtitle_px = self.SUBTITLE_SIZE * fs
        badge_px = self.BADGE_SIZE * fs
        result_px = self.RESULT_SIZE * fs
        button_px = self.BUTTON_TEXT_SIZE * fs
        button_h = max(self.BUTTON_HEIGHT * fs, button_px * 2.3)

        inset = 10.0 * fs
        title_y = inset + 12.0 * fs
        subtitle_y = title_y + title_px * 1.2 + 4.0 * fs
        header_h = subtitle_y + subtitle_px * 1.6 + 9.0 * fs
        footer_h = 7.0 * fs + result_px * 1.5 + 8.0 * fs + button_h + margin * 0.8

        # The wheel gets everything the header/footer do not need.  A very
        # small breathing strip keeps the dialog from sitting flush against
        # the screen edge.
        edge_pad = 4.0
        diameter = min(
            avail_w - 2.0 * margin - 8.0,
            avail_h - header_h - footer_h - edge_pad,
            short * self.WHEEL_SHARE,
        )
        diameter = max(diameter, 220.0)
        height_px = diameter + header_h + footer_h
        if height_px > avail_h:
            diameter = max(180.0, avail_h - header_h - footer_h - edge_pad)
            height_px = diameter + header_h + footer_h
        width_px = diameter + 2.0 * margin + 14.0 * fs

        self.width_px = int(round(min(width_px, avail_w)))
        self.height_px = int(round(min(height_px, avail_h)))
        self.margin_px = margin
        self.inset_px = inset
        self.title_px = title_px
        self.subtitle_px = subtitle_px
        self.badge_px = badge_px
        self.result_px = result_px
        self.button_px = button_px
        self.button_h_px = button_h
        self.header_px = header_h
        self.radius_px = diameter / 2.0
        self.cx_px = self.width_px / 2.0
        self.cy_px = header_h + diameter / 2.0
        self.title_y_px = title_y
        self.subtitle_y_px = subtitle_y

        content_w = max(200.0, self.width_px - 2.0 * margin)
        gap = 12.0 * fs
        close_w = max(96.0 * fs, content_w * 0.32)
        close_w = min(close_w, content_w - gap - 120.0 * fs)
        close_w = max(72.0 * fs, close_w)
        spin_w = max(120.0 * fs, content_w - gap - close_w)
        button_top = self.height_px - margin - button_h
        self.spin_rect = (
            margin,
            button_top,
            margin + spin_w,
            button_top + button_h,
        )
        self.close_rect = (
            margin + spin_w + gap,
            button_top,
            self.width_px - margin,
            button_top + button_h,
        )
        self.result_y_px = (header_h + diameter + button_top) / 2.0

        # ``wm geometry`` is the decorated window's origin, so centre the
        # whole frame (client + caption + border) inside the work area.
        outer_w = self.width_px + deco_w
        outer_h = self.height_px + deco_h
        x = int(round(left + (area_w - outer_w) / 2.0))
        y = int(round(top + (area_h - outer_h) / 2.0))
        self._left = max(left, min(x, right - outer_w))
        self._top = max(top, min(y, bottom - outer_h))

    def _lp(self, pixels: float) -> float:
        """Convert screen pixels to the canvas' logical coordinates."""

        return pixels / self.scale

    def _fnt(
        self,
        pixels: float,
        weight: str = "normal",
        serif: bool = False,
    ) -> tuple[str, int, str]:
        """Ask :func:`font` for a face that renders at ``pixels`` high.

        ``font`` already multiplies by the global font coefficient and
        ``ScaledCanvas`` multiplies again by the UI scale, so both are divided
        back out here.  The result honours the user's font size while still
        landing on the exact pixel size the layout budgeted for.
        """

        logical = pixels / max(0.01, self.font_scale * self.scale)
        return font(max(6, int(round(logical))), weight, serif)

    @property
    def cx(self) -> float:
        return self._lp(self.cx_px)

    @property
    def cy(self) -> float:
        return self._lp(self.cy_px)

    @property
    def radius(self) -> float:
        return self._lp(self.radius_px)

    def _current_meal(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 10:
            return "早餐"
        if 10 <= hour < 15:
            return "午餐"
        if 15 <= hour < 21:
            return "晚餐"
        return "夜宵"

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def _draw(self) -> None:
        self.canvas.delete("all")
        self._draw_card()
        self._draw_header()
        self._draw_wheel()
        self._draw_actions()

    def _draw_card(self) -> None:
        inset = self._lp(self.inset_px)
        self.kit.draw_round(
            self.canvas,
            inset,
            inset * 0.8,
            self._lp(self.width_px) - inset,
            self._lp(self.height_px) - inset * 0.8,
            26,
            COLORS["card"],
            COLORS["line"],
            1,
        )

    def _draw_header(self) -> None:
        margin = self._lp(self.margin_px)
        self.canvas.create_text(
            margin + self._lp(24.0 * self.font_scale),
            self._lp(self.title_y_px),
            anchor="nw",
            text="今天吃什么？",
            fill=COLORS["ink"],
            font=self._fnt(self.title_px, serif=True),
        )
        self.canvas.create_text(
            margin + self._lp(25.0 * self.font_scale),
            self._lp(self.subtitle_y_px),
            anchor="nw",
            text=f"{self._meal}选项 · 全部铺在转盘上，把选择交给它。",
            fill=COLORS["ink_soft"],
            font=self._fnt(self.subtitle_px),
        )
        self.canvas.create_text(
            self._lp(self.width_px) - margin - self._lp(22.0 * self.font_scale),
            self._lp(self.subtitle_y_px - 6.0 * self.font_scale),
            anchor="ne",
            text=f"今天 · {self._meal}",
            fill=COLORS["sage"],
            font=self._fnt(self.badge_px, "bold"),
        )

    def _sector_color(self, index: int) -> str:
        palette = WHEEL_COLORS
        base = palette[index % len(palette)]
        cycle = index // len(palette)
        if cycle:
            return mix_color(base, COLORS["paper"], min(0.34, 0.17 * cycle))
        return base

    def _draw_wheel(self) -> None:
        self.canvas.delete("wheel")
        count = len(self.options)
        if count == 0:
            return
        extent = 360.0 / count
        cx, cy, radius = self.cx, self.cy, self.radius
        left, top = cx - radius, cy - radius
        right, bottom = cx + radius, cy + radius
        highlight = self.winner is not None and 0 <= self.winner < count
        for index in range(count):
            start = 90.0 - extent / 2.0 + index * extent + self.rotation
            base = self._sector_color(index)
            if highlight and index == self.winner:
                fill = mix_color(base, COLORS["white"], 0.10)
                outline = COLORS["pine"]
                edge = 4
            elif highlight:
                # 未中选的扇区压暗，视线自然落到结果上。
                fill = mix_color(base, "#E7EAE4", 0.52)
                outline = COLORS["card"]
                edge = 2
            else:
                fill = base
                outline = COLORS["card"]
                edge = 2
            self.canvas.create_arc(
                left,
                top,
                right,
                bottom,
                start=start,
                extent=extent,
                fill=fill,
                outline=outline,
                width=edge,
                style="pieslice",
                tags=("wheel",),
            )
        for index in range(count):
            mid = 90.0 + index * extent + self.rotation
            self._draw_label(index, mid)
        self._draw_pointer()
        self._draw_hub()
        self._draw_result()

    def _refresh_labels(self) -> None:
        """Pick one font size and one label per sector, once.

        Radial labels are split into at most two short lines: a single long
        string rotated along the radius is what made neighbouring sectors
        collide at 12+ options. Two balanced lines keep the tangential
        thickness small (so neighbours never touch) while still reading as one
        dish name.
        """

        count = len(self.options)
        key = (
            count,
            round(self.radius_px, 1),
            self.font_scale,
            self._text_angle,
            tuple(self.options),
        )
        if key == self._labels_key:
            return
        self._labels_key = key
        self._labels = []
        if count == 0:
            return
        radial = count > 8 and self._text_angle
        self._labels_radial = radial
        radius_px = self.radius_px
        if radial:
            anchor_radius = radius_px * self.LABEL_RADIUS_SHARE
            radial_room = radius_px * 0.52
            chord = 2.0 * radius_px * self.LABEL_ANCHOR_SHARE * math.sin(
                math.pi / count
            )
            # The chord at the *inner* anchor is the tightest place on the
            # sector, so the two stacked lines are sized against it.
            size = min(20.0 * self.font_scale, chord * 0.68)
        else:
            anchor_radius = radius_px * 0.62
            radial_room = radius_px * 0.56
            chord = 2.0 * anchor_radius * math.sin(math.pi / count)
            size = min(13.0 * self.font_scale, chord * 0.66)

        for option in self.options:
            text = _abbreviate(option)
            if radial:
                text = _split_two_lines(text)
            longest = max(len(line) for line in text.split("\n"))
            local = size
            # Shrink before truncating: the radial direction has room for the
            # whole name in most cases.
            if longest and longest * local > radial_room:
                local = max(7.5, radial_room / longest)
            self._labels.append((text, local))

    def _draw_label(self, index: int, mid_deg: float) -> None:
        if index >= len(self._labels):
            return
        text, size_px = self._labels[index]
        text_font = self._fnt(size_px, "bold")
        # 中选之外的标签一起变暗，和扇区保持一致的强弱关系。
        ink = "#6E685E" if self.winner is not None and index != self.winner else COLORS["ink"]
        cx, cy, radius = self.cx, self.cy, self.radius
        rad = math.radians(mid_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        if self._labels_radial:
            label_radius = radius * self.LABEL_RADIUS_SHARE
            angle = mid_deg if cos_a >= 0.0 else mid_deg + 180.0
            self.canvas.create_text(
                cx + cos_a * label_radius,
                cy - sin_a * label_radius,
                text=text,
                fill=ink,
                font=text_font,
                angle=angle,
                anchor="center",
                justify="center",
                tags=("wheel", "wheel_label"),
            )
            return
        label_radius = radius * 0.62
        self.canvas.create_text(
            cx + cos_a * label_radius,
            cy - sin_a * label_radius,
            text=text,
            fill=ink,
            font=text_font,
            anchor="center",
            justify="center",
            tags=("wheel", "wheel_label"),
        )

    def _draw_pointer(self) -> None:
        unit = self._lp(1.0) * self.font_scale
        cx = self.cx
        tip_y = self.cy - self.radius - 8.0 * unit
        top_y = tip_y - 26.0 * unit
        half = 14.0 * unit
        self.canvas.create_polygon(
            cx - half,
            top_y,
            cx + half,
            top_y,
            cx,
            tip_y,
            fill=COLORS["clay"],
            outline=COLORS["paper"],
            width=2,
            tags=("wheel",),
        )

    def _draw_hub(self) -> None:
        hub = self.radius * self.HUB_SHARE
        cx, cy = self.cx, self.cy
        self.canvas.create_oval(
            cx - hub,
            cy - hub,
            cx + hub,
            cy + hub,
            fill=COLORS["paper"],
            outline=COLORS["line"],
            width=2,
            tags=("wheel",),
        )
        self.canvas.create_text(
            cx,
            cy,
            text="吃",
            fill=COLORS["pine"],
            font=self._fnt(self.radius_px * 0.11, serif=True),
            anchor="center",
            tags=("wheel",),
        )

    def _draw_result(self) -> None:
        if self.spinning:
            text = "转盘正在替你纠结…"
            color = COLORS["muted"]
        elif self.result and self.result != IDLE_RESULT:
            text = f"结果 · {self.result}"
            color = COLORS["clay"]
        else:
            text = IDLE_RESULT
            color = COLORS["muted"]
        self.canvas.create_text(
            self.cx,
            self._lp(self.result_y_px),
            text=text,
            fill=color,
            font=self._fnt(self.result_px, "bold"),
            anchor="center",
            width=self._lp(self.width_px - 2.0 * self.margin_px),
            tags=("wheel", "wheel_result"),
        )

    def _draw_actions(self) -> None:
        self._draw_action_button(
            "food_spin",
            *self.spin_rect,
            "转一下，替我决定",
            self.spin,
            COLORS["pine"],
            COLORS["paper"],
        )
        self._draw_action_button(
            "food_close",
            *self.close_rect,
            "先不决定",
            self.close,
            COLORS["card_alt"],
            COLORS["ink_soft"],
        )

    def _draw_action_button(
        self,
        tag: str,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        text: str,
        command: Callable[[], Any],
        fill: str,
        ink: str,
    ) -> None:
        logical_h = self._lp(y2) - self._lp(y1)
        self.kit.draw_pill(
            self.canvas,
            self._lp(x1),
            self._lp(y1),
            self._lp(x2),
            self._lp(y2),
            max(10.0, logical_h / 2.0),
            fill,
            None,
            COLORS["line"] if fill != COLORS["pine"] else None,
            1,
            (tag,),
            highlight=0.7 if fill == COLORS["pine"] else 0.2,
        )
        self.canvas.create_text(
            self._lp((x1 + x2) / 2.0),
            self._lp((y1 + y2) / 2.0),
            text=text,
            fill=ink,
            font=self._fnt(self.button_px, "bold"),
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

    # ------------------------------------------------------------------
    # behaviour
    # ------------------------------------------------------------------
    def spin(self) -> None:
        if self.spinning or not self.options:
            return
        count = len(self.options)
        extent = 360.0 / count
        winner = random.randrange(count)
        self.spinning = True
        self.result = ""
        self.winner = None
        if self._result_popup is not None:
            try:
                self._result_popup.destroy()
            except tk.TclError:
                pass
            self._result_popup = None

        start = self.rotation % 360.0
        # Sector mid angles are ``90 + index * extent + rotation``; put the
        # winner's middle under the pointer at 90 degrees.
        final = (-winner * extent) % 360.0
        turns = 6
        target = start + turns * 360.0 + ((final - start) % 360.0)
        started = time.monotonic()
        duration = 2.65

        def animate() -> None:
            elapsed = min(1.0, (time.monotonic() - started) / duration)
            eased = 1.0 - (1.0 - elapsed) ** 3
            self.rotation = start + (target - start) * eased
            self._draw_wheel()
            if elapsed < 1.0:
                self._animation_job = self.canvas.after(16, animate)
                return
            self.rotation = final
            self.spinning = False
            self.result = self.options[winner]
            self.winner = winner
            self._animation_job = None
            self._draw_wheel()
            self._show_result_popup(self.result)

        animate()

    def _show_result_popup(self, dish: str) -> None:
        """A small card that announces the result: 「今天该吃……」."""

        if self._result_popup is not None:
            try:
                self._result_popup.destroy()
            except tk.TclError:
                pass
            self._result_popup = None
        popup = tk.Toplevel(self.window)
        popup.title("今天该吃……")
        popup.transient(self.window)
        try:
            popup.attributes("-topmost", True)
        except tk.TclError:
            pass
        popup.configure(bg=COLORS["paper"])
        scale = max(0.8, self.scale * self.font_scale)
        width = int(360 * scale)
        height = int(210 * scale)
        x = self.window.winfo_x() + max(0, (self.window.winfo_width() - width) // 2)
        y = self.window.winfo_y() + max(0, (self.window.winfo_height() - height) // 2)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.resizable(False, False)

        tk.Label(
            popup,
            text="今天该吃……",
            bg=COLORS["paper"],
            fg=COLORS["sage"],
            font=font(13, "bold"),
        ).pack(pady=(int(18 * scale), 0))
        tk.Label(
            popup,
            text=dish,
            bg=COLORS["paper"],
            fg=COLORS["ink"],
            font=font(30, "bold", serif=True),
            wraplength=width - int(30 * scale),
        ).pack(pady=(int(6 * scale), int(2 * scale)))
        tk.Label(
            popup,
            text=f"{self._meal} · 来自今天这一盘",
            bg=COLORS["paper"],
            fg=COLORS["muted"],
            font=font(10),
        ).pack()

        actions = tk.Frame(popup, bg=COLORS["paper"])
        actions.pack(side="bottom", pady=int(16 * scale))
        for label, command, primary in (
            ("就吃这个", self.close, True),
            ("再转一次", self._spin_again, False),
        ):
            tk.Button(
                actions,
                text=label,
                command=command,
                relief="flat",
                bd=0,
                padx=int(16 * scale),
                pady=int(7 * scale),
                bg=COLORS["pine"] if primary else COLORS["card_alt"],
                fg=COLORS["paper"] if primary else COLORS["ink"],
                activebackground=mix_color(
                    COLORS["pine"] if primary else COLORS["card_alt"],
                    COLORS["white"],
                    0.12,
                ),
                activeforeground=COLORS["paper"] if primary else COLORS["ink"],
                cursor="hand2",
                font=font(11, "bold"),
            ).pack(side="left", padx=int(6 * scale))
        popup.bind("<Escape>", lambda _event: popup.destroy())
        self._result_popup = popup

    def _spin_again(self) -> None:
        if self._result_popup is not None:
            try:
                self._result_popup.destroy()
            except tk.TclError:
                pass
            self._result_popup = None
        self.winner = None
        self._draw_wheel()
        self.spin()

    def close(self) -> None:
        if self._focus_job is not None:
            try:
                self.window.after_cancel(self._focus_job)
            except tk.TclError:
                pass
            self._focus_job = None
        if self._result_popup is not None:
            try:
                self._result_popup.destroy()
            except tk.TclError:
                pass
            self._result_popup = None
        if self._animation_job:
            try:
                self.window.after_cancel(self._animation_job)
            except tk.TclError:
                pass
            self._animation_job = None
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()
