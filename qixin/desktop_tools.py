"""Session, capture and reminder logic shared by the pet and main window."""
from __future__ import annotations

import logging
import math
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .desktop_platform import CaptureHotkey, foreground_is_fullscreen
from .news import signup_link
from .pet_panel import GlassPanel, PetAction, PetNotice
from .theme import COLORS, widget_font

if TYPE_CHECKING:
    from .ui import QixinApp


FOCUS_SECONDS = 25 * 60
BREAK_SECONDS = 5 * 60
REMINDER_SECONDS = 10 * 60


@dataclass
class FocusSession:
    task_id: int | None
    title: str
    phase: str
    ends: float
    duration: int

    def remaining(self, now: float) -> int:
        return max(0, math.ceil(self.ends - now))

    def finish_if_due(self, now: float) -> str | None:
        if self.phase not in ("focus", "break") or self.remaining(now):
            return None
        previous = self.phase
        self.phase = "ready" if previous == "focus" else "rested"
        return previous


class QuickCapture(GlassPanel):
    def __init__(self, app: QixinApp, x: int, y: int):
        super().__init__(app.root, app.ui_scale)
        self.app = app
        self.paint(400, 150)
        self.canvas.create_text(
            18, 25, text="随手记一下", anchor="w", fill=COLORS["ink"],
            font=widget_font(15, 1, serif=True),
        )
        self.entry = tk.Entry(
            self.canvas, relief="flat", bg=COLORS["card"], fg=COLORS["ink"],
            insertbackground=COLORS["pine"], font=widget_font(11, self.scale),
            highlightthickness=1, highlightbackground=COLORS["line"],
            highlightcolor=COLORS["sage"],
        )
        self.canvas.create_window(
            round(18 * self.scale), round(53 * self.scale), anchor="nw",
            width=round(364 * self.scale), height=round(38 * self.scale), window=self.entry,
        )
        self.hint = self.canvas.create_text(
            18, 119, text="回车存入收件箱", anchor="w",
            fill=COLORS["muted"], font=widget_font(9, 1),
        )
        self.kit.draw_pill(self.canvas, 289, 102, 380, 136, 12, COLORS["pine"], tags=("save",))
        self.canvas.create_text(
            334, 119, text="保存", fill=COLORS["white"],
            font=widget_font(10, 1, "bold"), tags=("save",),
        )
        self.canvas.tag_bind("save", "<ButtonRelease-1>", self._save)
        self.window.bind("<Return>", self._save)
        self.window.bind("<Escape>", lambda _event: self.close())
        self.show(x, y, focus=True)
        self.entry.focus_set()

    def _save(self, _event: tk.Event | None = None) -> str:
        title = self.entry.get().strip()
        if 0 < len(title) <= 200:
            self.app.store.add_to_inbox(title)
            self.close()
            self.app._desktop_data_changed()
        else:
            self.canvas.itemconfigure(self.hint, text="请输入 1–200 个字")
        return "break"


class DesktopTools:
    def __init__(self, app: QixinApp):
        self.app = app
        self.session: FocusSession | None = None
        self.capture: QuickCapture | None = None
        self.signup_notice: PetNotice | None = None
        self.hotkey = CaptureHotkey()
        self.fullscreen = False
        self._home_state = None
        self._alarm_minute = None
        self.alarm_dirty = True
        self._next_poll = 0.0
        self._next_schedule_poll = 0.0
        self._next_signup_poll = 0.0
        try:
            self.muted_until = float(app.store.get_setting("pet_quiet_until", "0"))
        except ValueError:
            self.muted_until = 0.0
        self.job = app.root.after(120, self._tick)

    def open_capture(self) -> None:
        pet = self.app._pet
        if pet is not None:
            pet.close_menu()
        if self.capture is not None and self.capture.window.winfo_exists():
            self.capture.window.lift()
            self.capture.entry.focus_force()
            return
        x, y = self.app.root.winfo_pointerxy()
        self.capture = QuickCapture(self.app, x + 12, y + 12)

    def start(self, task_id: int | None, title: str) -> None:
        self.session = FocusSession(task_id, title, "focus", time.time() + FOCUS_SECONDS, FOCUS_SECONDS)
        if self.app._pet is not None:
            self.app._pet.hide_notice()
        self._update_badge()

    def rest(self) -> None:
        session = self.session
        if session is not None and session.phase == "ready":
            session.phase, session.duration = "break", BREAK_SECONDS
            session.ends = time.time() + BREAK_SECONDS
            self._update_badge()

    def continue_focus(self) -> None:
        session = self.session
        if session is not None and session.phase in ("ready", "rested"):
            self.start(session.task_id, session.title)

    def finish(self, *, complete_task: bool = False) -> None:
        session, self.session = self.session, None
        self._update_badge()
        if complete_task and session is not None and session.task_id is not None:
            self.app.store.complete_task(session.task_id)
            self.app._desktop_data_changed()

    def toggle_quiet(self) -> None:
        now = time.time()
        self.muted_until = 0 if self.muted_until > now else now + 3600
        self.app.store.set_setting("pet_quiet_until", str(self.muted_until))
        if self.muted_until and self.app._pet is not None:
            self.app._pet.hide_notice()

    def is_quiet(self, now: float) -> bool:
        return (
            self.fullscreen or self.muted_until > now
            or (self.session is not None and self.session.phase == "focus")
        )

    @staticmethod
    def _start_time(row) -> datetime | None:
        if not row["start_time"]:
            return None
        try:
            return datetime.fromisoformat(f"{row['local_date']}T{row['start_time']}")
        except ValueError:
            return None

    def next_schedule_row(self, now: datetime):
        for row in self.app.store.upcoming_schedules(now):
            start = self._start_time(row)
            if not row["start_time"] or (start is not None and start >= now):
                return row
        return None

    def next_schedule(self) -> tuple[str, str]:
        now = datetime.now()
        row = self.next_schedule_row(now)
        if row is None:
            return "下一件事", "近期没有日程"
        start = self._start_time(row)
        if start is None:
            return row["title"], f"{row['local_date'][5:]}  ·  全天"
        seconds = (start - now).total_seconds()
        when = start.strftime("%H:%M") if start.date() == now.date() else start.strftime("%m-%d %H:%M")
        if seconds < 3600:
            when += f"  ·  还有 {math.ceil(seconds / 60)} 分钟"
        return row["title"], when

    def _schedule_reminder(self) -> None:
        pet = self.app._pet
        if pet is None or pet.menu_is_open():
            return
        now = datetime.now()
        for row in self.app.store.upcoming_schedules(now):
            start = self._start_time(row)
            if start is None:
                continue
            seconds = (start - now).total_seconds()
            if seconds > REMINDER_SECONDS:
                break
            if seconds >= 0 and self.app.store.record_pet_schedule_reminder(
                row["id"], start.isoformat(timespec="minutes"),
            ):
                pet.notify(row["title"], f"{start:%H:%M}  ·  还有 {math.ceil(seconds / 60)} 分钟")
                break

    def signup_notice_open(self) -> bool:
        return self.signup_notice is not None and bool(self.signup_notice.window.winfo_exists())

    def _signup_reminder(self, now: float) -> None:
        if self.signup_notice_open():
            return
        pet = self.app._pet
        if pet is not None and pet.menu_is_open():
            return
        row = self.app.store.next_due_signup_reminder(now)
        if row is None:
            return
        url = signup_link(row["url"])
        if not url:
            return
        root, scale = self.app.root, self.app.ui_scale
        if pet is None:
            x = root.winfo_vrootx() + root.winfo_vrootwidth() - round(385 * scale)
            y = root.winfo_vrooty() + root.winfo_vrootheight() - round(160 * scale)
        else:
            pet.hide_notice()
            x = pet.window.winfo_rootx()
            y = pet.window.winfo_rooty() - round(132 * scale)
        label = "打开报名页" if row["direct_link"] else "打开原文"
        try:
            with self.app.store.transaction() as conn:
                if not self.app.store.claim_signup_notification(conn, row["news_key"], row["opens_at"], now):
                    return
                self.signup_notice = PetNotice(
                    root, scale, "抢选报名时间到", row["title"], x, y,
                    action=PetAction(label, lambda: webbrowser.open(url)),
                )
        except tk.TclError:
            return
        if self.app.current_page == "news":
            self.app.render()

    def _update_badge(self) -> None:
        if self.app._pet is not None:
            self.app._pet.show_focus(self.session)

    def _tick(self) -> None:
        now = time.time()
        tick = time.monotonic()
        try:
            for callback in (self._poll_desktop, self._poll_focus, self._poll_alarms,
                             self._poll_signup, self._poll_schedule):
                try:
                    callback(now, tick)
                except Exception:
                    logging.getLogger(__name__).exception("Desktop timer failed: %s", callback.__name__)
        finally:
            if not self.app._closing:
                self.job = self.app.root.after(120, self._tick)

    def _poll_desktop(self, now, tick):
        if self.hotkey.take():
            self.open_capture()
        pet = self.app._pet
        if tick >= self._next_poll:
            self._next_poll = tick + 0.65
            app_fullscreen_active = (
                self.app._fullscreen and self.app.root.focus_displayof() is not None
            )
            self.fullscreen = app_fullscreen_active or foreground_is_fullscreen()
            if pet is not None:
                pet.set_fullscreen_quiet(self.fullscreen)

    def _poll_focus(self, now, tick):
        pet = self.app._pet
        session = self.session
        if session is not None:
            finished = session.finish_if_due(now)
            if finished and pet is not None:
                if pet.menu_is_open():
                    pet.refresh_focus_menu()
                elif not self.is_quiet(now):
                    label = "专注结束" if finished == "focus" else "休息结束"
                    pet.notify(label, "右键桌宠选择下一步")
            self._update_badge()

        if self.app.current_page == "today":
            state = (session.phase if session else "idle", session.remaining(now) if session else 1500)
            if self._home_state != state:
                if self._home_state and self._home_state[0] != state[0]:
                    self.app.render()
                self.app._update_home_focus()
                self._home_state = state

    def _poll_alarms(self, now, tick):
        minute = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
        if self._alarm_minute != minute or self.alarm_dirty:
            start = min(self._alarm_minute or minute, minute)
            self.app._check_alarms(minute, start)
            self._alarm_minute = minute
            self.alarm_dirty = False

    def _poll_signup(self, now, tick):
        quiet = self.is_quiet(now)
        if quiet and self.signup_notice_open():
            self.signup_notice.close()
        if tick >= self._next_signup_poll and not quiet:
            self._next_signup_poll = tick + 1
            self._signup_reminder(now)

    def _poll_schedule(self, now, tick):
        if tick >= self._next_schedule_poll and not self.is_quiet(now) and not self.signup_notice_open():
            self._next_schedule_poll = tick + 15
            self._schedule_reminder()


    def close(self) -> None:
        self.app.root.after_cancel(self.job)
        self.hotkey.close()
        if self.capture is not None:
            self.capture.close()
        if self.signup_notice is not None:
            self.signup_notice.close()
