from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from threading import Thread
from datetime import date
from .alarms import import_sound
from .db import app_data_dir
from tkinter import font as tkfont
from typing import Any, Callable

from .theme import (
    COLORS,
    ScaledCanvas,
    VisualKit,
    active_font_family,
    font,
    get_font_scale,
    widget_font,
)


class ScheduleDialog:
    WIDTH = 560
    HEIGHT = 520

    def __init__(
        self,
        root: tk.Tk,
        scale: float,
        kit: VisualKit,
        default_date: date,
        on_save: Callable[[date, str, str, str, int | None, str | None], str | None],
        on_close: Callable[[], None] | None = None,
        schedule: dict[str, Any] | None = None,
        data_dir: Path | None = None,
    ):
        self.data_dir = data_dir or app_data_dir()
        self.importing = False
        self.import_job = None
        self.root = root
        self.schedule = dict(schedule) if schedule else None
        self.schedule_id = (
            int(self.schedule["id"]) if self.schedule and "id" in self.schedule else None
        )
        self.editing = self.schedule is not None
        self.scale = scale
        self.kit = kit
        self.on_save = on_save
        self.on_close = on_close
        self.error = ""
        self.window = tk.Toplevel(root)
        self.window.title("编辑日程" if self.schedule else "添加日程")
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

        entry_style = {
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 0,
            "bg": COLORS["card_alt"],
            "fg": COLORS["ink"],
            "insertbackground": COLORS["pine"],
            "font": widget_font(11, scale),
        }
        self.title_entry = tk.Entry(self.canvas, **entry_style)
        self.title_entry.place(
            x=round(46 * scale),
            y=round(111 * scale),
            width=round(468 * scale),
            height=round(38 * scale),
        )
        self.date_entry = tk.Entry(self.canvas, **entry_style)
        self.date_entry.place(
            x=round(46 * scale),
            y=round(190 * scale),
            width=round(230 * scale),
            height=round(38 * scale),
        )
        self.date_entry.insert(0, default_date.isoformat())
        self.time_entry = tk.Entry(self.canvas, **entry_style)
        self.time_entry.place(
            x=round(300 * scale),
            y=round(190 * scale),
            width=round(214 * scale),
            height=round(38 * scale),
        )
        self.time_entry.insert(0, "09:00")
        if self.schedule:
            self.title_entry.delete(0, "end")
            self.title_entry.insert(0, str(self.schedule.get("title", "")))
            self.date_entry.delete(0, "end")
            self.date_entry.insert(0, str(self.schedule.get("local_date", "")))
            self.time_entry.delete(0, "end")
            self.time_entry.insert(0, str(self.schedule.get("start_time", "")))
        self.note_text = tk.Text(
            self.canvas,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=COLORS["card_alt"],
            fg=COLORS["ink"],
            insertbackground=COLORS["pine"],
            font=widget_font(10, scale),
            padx=round(10 * scale),
            pady=round(8 * scale),
            wrap="word",
        )
        self.note_text.place(
            x=round(46 * scale),
            y=round(274 * scale),
            width=round(468 * scale),
            height=round(100 * scale),
        )
        if self.schedule:
            self.note_text.insert("1.0", str(self.schedule.get("note", "")))
        from tkinter import filedialog
        from pathlib import Path
        sound = (self.schedule or {}).get("alarm_sound")
        self.alarm = tk.BooleanVar(self.window, value=sound is not None)
        self.sound = sound or ""
        bar = tk.Frame(self.canvas, bg=COLORS["card"])
        bar.place(x=round(45*scale), y=round(350*scale))
        self.note_text.place_configure(height=round(68*scale))
        tk.Checkbutton(bar, text="到点响铃", variable=self.alarm, bg=COLORS["card"]).pack(side="left")
        caption = tk.StringVar(bar, value=Path(self.sound).name or "卡农")
        def choose():
            value = filedialog.askopenfilename(parent=self.window, filetypes=[("MP3 音乐", "*.mp3")])
            if value:
                self.sound = value
                caption.set(Path(value).name)
                self.alarm.set(True)
        def reset():
            self.sound = ""
            caption.set("卡农")
        tk.Button(bar, textvariable=caption, width=14, command=choose).pack(side="left")
        tk.Button(bar, text="选 MP3", command=choose).pack(side="left")
        tk.Button(bar, text="用卡农", command=reset).pack(side="left")
        self.input_widgets = [self.title_entry, self.date_entry, self.time_entry, self.note_text, *bar.winfo_children()]
        self.title_entry.focus_force()
        self.title_entry.bind("<Return>", lambda _event: self.save())
        self.date_entry.bind("<Return>", lambda _event: self.save())
        self.time_entry.bind("<Return>", lambda _event: self.save())
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
            44,
            32,
            anchor="nw",
            text="修改这条日程" if self.editing else "在日历里放下一件事",
            fill=COLORS["ink"],
            font=font(23, serif=True),
        )
        self.canvas.create_text(
            46,
            67,
            anchor="nw",
            text=(
                "改动会立即同步到月历与周视图。"
                if self.editing
                else "日程会按日期显示在月历与周视图中。"
            ),
            fill=COLORS["muted"],
            font=font(9),
        )
        labels = [
            ("日程名称", 86),
            ("日期        格式 YYYY-MM-DD", 165),
            ("开始时间    24 小时制", 165),
            ("备注（可选）", 250),
        ]
        self.canvas.create_text(
            46, labels[0][1], anchor="nw", text=labels[0][0], fill=COLORS["sage"], font=font(8, "bold")
        )
        self.canvas.create_text(
            46, labels[1][1], anchor="nw", text="日期 · YYYY-MM-DD", fill=COLORS["sage"], font=font(8, "bold")
        )
        self.canvas.create_text(
            300, labels[2][1], anchor="nw", text=labels[2][0], fill=COLORS["sage"], font=font(8, "bold")
        )
        self.canvas.create_text(
            46, labels[3][1], anchor="nw", text=labels[3][0], fill=COLORS["sage"], font=font(8, "bold")
        )
        self.kit.draw_round(
            self.canvas,
            45,
            105,
            515,
            155,
            14,
            COLORS["card_alt"],
            COLORS["line"],
            1,
        )
        self.kit.draw_round(
            self.canvas,
            45,
            184,
            285,
            234,
            14,
            COLORS["card_alt"],
            COLORS["line"],
            1,
        )
        self.kit.draw_round(
            self.canvas,
            299,
            184,
            515,
            234,
            14,
            COLORS["card_alt"],
            COLORS["line"],
            1,
        )
        self.kit.draw_round(
            self.canvas,
            45,
            268,
            515,
            380,
            14,
            COLORS["card_alt"],
            COLORS["line"],
            1,
        )
        if self.error:
            self.canvas.create_text(
                46,
                397,
                anchor="nw",
                text=self.error,
                fill=COLORS["clay"],
                font=font(9, "bold"),
            )
        self._button("schedule_cancel", 290, 432, 390, 474, "取消", self.close, False)
        self._button(
            "schedule_save",
            402,
            432,
            515,
            474,
            "正在导入…" if self.importing else ("保存修改" if self.editing else "添加日程"),
            self.save,
            True,
        )

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

    def save(self) -> None:
        if self.importing:
            return
        title = self.title_entry.get().strip()
        if not title:
            self.error = "先写下要做什么。"
            self._draw()
            return
        try:
            day = date.fromisoformat(self.date_entry.get().strip())
        except ValueError:
            self.error = "日期格式应为 YYYY-MM-DD。"
            self._draw()
            return
        start_time = self.time_entry.get().strip()
        if start_time:
            try:
                hour_text, minute_text = start_time.split(":", 1)
                hour = int(hour_text)
                minute = int(minute_text)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
                start_time = f"{hour:02d}:{minute:02d}"
            except ValueError:
                self.error = "时间格式应为 HH:MM。"
                self._draw()
                return
        note = self.note_text.get("1.0", "end").strip()
        if self.alarm.get() and not start_time:
            self.error = "设置闹铃需要填写时间。"
            self._draw()
            return
        values = (day, start_time, title, note, self.schedule_id)
        sound = self.sound if self.alarm.get() else None
        if not sound:
            self._finish_save(values, sound)
            return
        self.importing = True
        for widget in self.input_widgets:
            widget.configure(state="disabled")
        self.error = ""
        self._draw()
        result = Future()
        def copy():
            try:
                result.set_result(str(import_sound(Path(sound), self.data_dir)))
            except Exception as exc:
                result.set_exception(exc)
        def finish():
            if not result.done():
                self.import_job = self.window.after(60, finish)
                return
            self.import_job = None
            self.importing = False
            for widget in self.input_widgets:
                widget.configure(state="normal")
            try:
                imported = result.result()
            except Exception as exc:
                self.error = f"无法导入铃声：{exc}"
                self._draw()
                return
            self._finish_save(values, imported)
        Thread(target=copy, daemon=True).start()
        self.import_job = self.window.after(60, finish)

    def _finish_save(self, values, sound):
        error = self.on_save(*values, sound)
        if error:
            self.error = error
            self._draw()
            return
        self.close()

    def close(self) -> None:
        if self.import_job is not None:
            self.window.after_cancel(self.import_job)
            self.import_job = None
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()


class DaySchedulesDialog:
    """当天日程清单：双击日历格打开，可逐条编辑、删除或新增。"""

    WIDTH = 520
    HEIGHT = 560
    ROW_HEIGHT = 52
    ROW_GAP = 6
    LIST_TOP = 112

    def __init__(
        self,
        root: tk.Tk,
        scale: float,
        kit: VisualKit,
        day: date,
        schedules: list[Any],
        on_add: Callable[[], None],
        on_edit: Callable[[dict[str, Any]], None],
        on_delete: Callable[[dict[str, Any]], None],
        on_close: Callable[[], None] | None = None,
    ):
        self.root = root
        self.scale = max(0.5, float(scale))
        self.kit = kit
        self.day = day
        self.rows = [dict(row) for row in schedules]
        self.on_add = on_add
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.on_close = on_close
        self.offset = 0

        width = round(self.WIDTH * self.scale)
        height = round(self.HEIGHT * self.scale)
        self.window = tk.Toplevel(root)
        self.window.title("当天日程")
        self.window.configure(bg=COLORS["paper"])
        self.window.resizable(False, False)
        self.window.transient(root)
        self.window.geometry(f"{width}x{height}")
        self._center(width, height)
        try:
            self.window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = ScaledCanvas(
            self.window,
            ui_scale=self.scale,
            width=width,
            height=height,
            bg=COLORS["paper"],
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._draw()

    def _center(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - height) // 2
        self.window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    # -- data ------------------------------------------------------------
    def refresh(self, schedules: list[Any]) -> None:
        self.rows = [dict(row) for row in schedules]
        self.offset = min(self.offset, self._max_offset())
        self._draw()

    def _visible_rows(self) -> int:
        bottom = self.HEIGHT - 88
        span = bottom - self.LIST_TOP
        return max(1, int(span // (self.ROW_HEIGHT + self.ROW_GAP)))

    def _max_offset(self) -> int:
        return max(0, len(self.rows) - self._visible_rows())

    def _on_wheel(self, event: tk.Event[Any]) -> str:
        if self._max_offset() <= 0:
            return "break"
        step = -1 if getattr(event, "delta", 0) > 0 else 1
        self.offset = max(0, min(self._max_offset(), self.offset + step))
        self._draw()
        return "break"

    # -- drawing ---------------------------------------------------------
    def _draw(self) -> None:
        self.canvas.delete("all")
        self.kit.draw_round(
            self.canvas,
            12,
            12,
            self.WIDTH - 12,
            self.HEIGHT - 12,
            26,
            COLORS["card"],
            COLORS["line"],
            1,
        )
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][
            self.day.weekday()
        ]
        self.canvas.create_text(
            34,
            30,
            anchor="nw",
            text=f"{self.day.month} 月 {self.day.day} 日 · {weekday}",
            fill=COLORS["ink"],
            font=font(21, serif=True),
        )
        hint = (
            f"共 {len(self.rows)} 条日程 · 点一行编辑，滚轮翻看"
            if self.rows
            else "这一天还没有日程。"
        )
        self.canvas.create_text(
            35,
            66,
            anchor="nw",
            text=hint,
            fill=COLORS["muted"],
            font=font(9),
        )
        self.kit.draw_round(
            self.canvas, 28, 96, self.WIDTH - 28, 97, 1, COLORS["hairline"], None, 0
        )

        visible = self._visible_rows()
        if not self.rows:
            self.canvas.create_text(
                self.WIDTH / 2,
                self.LIST_TOP + 76,
                text="双击日历格随时回来；也可以先添加一条。",
                fill=COLORS["ink_soft"],
                font=font(11),
                justify="center",
                width=self.WIDTH - 120,
            )
        else:
            for slot in range(min(visible, len(self.rows) - self.offset)):
                row = self.rows[self.offset + slot]
                self._draw_row(row, self.LIST_TOP + slot * (self.ROW_HEIGHT + self.ROW_GAP))

        if self._max_offset() > 0:
            page = f"{self.offset + 1}–{min(len(self.rows), self.offset + visible)} / {len(self.rows)}"
            self.canvas.create_text(
                self.WIDTH - 34,
                self.LIST_TOP - 22,
                anchor="ne",
                text=page + "   ↑↓ 滚轮",
                fill=COLORS["muted"],
                font=font(8),
            )

        self._button(
            "day_add",
            28,
            self.HEIGHT - 76,
            268,
            self.HEIGHT - 30,
            "＋ 添加日程",
            self.on_add,
            True,
        )
        self._button(
            "day_done",
            280,
            self.HEIGHT - 76,
            self.WIDTH - 28,
            self.HEIGHT - 30,
            "完成",
            self.close,
            False,
        )

    def _draw_row(self, row: dict[str, Any], top: float) -> None:
        tag = f"day_row_{row.get('id')}"
        x1, x2 = 28.0, self.WIDTH - 28.0
        self.kit.draw_pill(
            self.canvas,
            x1,
            top,
            x2,
            top + self.ROW_HEIGHT,
            18,
            COLORS["sunken"],
            None,
            COLORS["line"],
            1,
            (tag,),
        )
        start = str(row.get("start_time") or "").strip()
        self.kit.draw_pill(
            self.canvas,
            x1 + 12,
            top + 14,
            x1 + 70,
            top + 38,
            12,
            "#FFFFFF",
            None,
            COLORS["line"],
            1,
            (tag,),
        )
        self.canvas.create_text(
            x1 + 41,
            top + 26,
            text=start or "全天",
            fill=COLORS["ink_soft"] if start else COLORS["muted"],
            font=font(8, "bold"),
            anchor="center",
            tags=(tag,),
        )
        title_width = x2 - x1 - 78 - 96
        title_font = tkfont.Font(
            root=self.root,
            family=active_font_family(),
            size=-max(1, round(11 * self.scale * get_font_scale())),
            weight="bold",
        )
        note_font = tkfont.Font(
            root=self.root,
            family=active_font_family(),
            size=-max(1, round(8 * self.scale * get_font_scale())),
        )
        title = self._ellipsize(
            title_font, str(row.get("title") or "（未命名）"), title_width
        )
        self.canvas.create_text(
            x1 + 78,
            top + 8,
            anchor="nw",
            text=title,
            fill=COLORS["ink"],
            font=font(11, "bold"),
            tags=(tag,),
        )
        note = str(row.get("note") or "").strip()
        if note:
            self.canvas.create_text(
                x1 + 78,
                top + 29,
                anchor="nw",
                text=self._ellipsize(note_font, note, title_width),
                fill=COLORS["muted"],
                font=font(8),
                tags=(tag,),
            )
        self._button(
            f"day_edit_{row.get('id')}",
            x2 - 96,
            top + 10,
            x2 - 56,
            top + 42,
            "编辑",
            lambda item=row: self.on_edit(item),
            False,
            size=8,
        )
        self._button(
            f"day_delete_{row.get('id')}",
            x2 - 50,
            top + 10,
            x2 - 10,
            top + 42,
            "×",
            lambda item=row: self.on_delete(item),
            False,
            size=10,
            danger=True,
        )
        self.canvas.tag_bind(
            tag,
            "<Button-1>",
            lambda _event, item=row: self.on_edit(item),
        )
        self.canvas.tag_bind(
            tag, "<Enter>", lambda _event: self.canvas.configure(cursor="hand2")
        )
        self.canvas.tag_bind(tag, "<Leave>", lambda _event: self.canvas.configure(cursor=""))

    @staticmethod
    def _ellipsize(font_obj: tkfont.Font, text: str, max_width: float) -> str:
        limit = max(12.0, float(max_width))
        if font_obj.measure(text) <= limit:
            return text
        trimmed = text
        while trimmed and font_obj.measure(trimmed + "…") > limit:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else "…"

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
        *,
        size: int = 10,
        danger: bool = False,
    ) -> None:
        fill = "#1B2438" if primary else (COLORS["clay_soft"] if danger else "#FFFFFF")
        fill2 = "#2A3652" if primary else None
        outline = None if primary else ("#F4D0C1" if danger else "#E4E9F4")
        ink = "#F7F9FF" if primary else (COLORS["clay"] if danger else COLORS["ink_soft"])
        self.kit.draw_pill(
            self.canvas,
            x1,
            y1,
            x2,
            y2,
            (y2 - y1) / 2,
            fill,
            fill2,
            outline,
            1,
            (tag,),
            highlight=0.7 if primary else 0.2,
        )
        self.canvas.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text=text,
            fill=ink,
            font=font(size, "bold"),
            anchor="center",
            tags=(tag,),
        )
        self.canvas.tag_bind(tag, "<Button-1>", lambda _event: command())
        self.canvas.tag_bind(
            tag, "<Enter>", lambda _event: self.canvas.configure(cursor="hand2")
        )
        self.canvas.tag_bind(tag, "<Leave>", lambda _event: self.canvas.configure(cursor=""))

    def close(self) -> None:
        try:
            self.window.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()
