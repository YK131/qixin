from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from qixin.db import Store
from qixin.desktop_tools import DesktopTools, FocusSession


class DesktopToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "desktop-tools.db")
        self.addCleanup(self.store.close)

    def test_signup_reminder_persists_and_only_shows_once(self) -> None:
        self.store.save_signup_reminder("event", "导师交流", "https://example.com/signup", True, 100, 120)
        self.assertIsNone(self.store.next_due_signup_reminder(99))
        self.assertIsNone(self.store.next_due_signup_reminder(120))
        tools = DesktopTools.__new__(DesktopTools)
        tools.app = Mock()
        tools.app.store = self.store
        tools.app._pet = None
        tools.app.ui_scale = 1
        tools.app.root.winfo_vrootwidth.return_value = 1366
        tools.app.root.winfo_vrootheight.return_value = 768
        tools.app.root.winfo_vrootx.return_value = 0
        tools.app.root.winfo_vrooty.return_value = 0
        tools.signup_notice = None
        with patch("qixin.desktop_tools.PetNotice") as popup:
            tools._signup_reminder(100)
            self.assertEqual(popup.call_args.kwargs["action"].label, "打开报名页")
            with patch("qixin.desktop_tools.webbrowser.open") as open_url:
                popup.call_args.kwargs["action"].run()
                open_url.assert_called_once_with("https://example.com/signup")
            tools.signup_notice = None
            tools._signup_reminder(107)
            popup.assert_called_once()
        with closing(Store(self.store.path)) as reopened:
            self.assertEqual(reopened.conn.execute("SELECT notified FROM signup_reminders").fetchone()[0], 1)
        self.store.cancel_signup_reminder("event")
        self.assertEqual(self.store.signup_reminders(107), [])

    def test_capture_moves_to_today_once_and_keeps_other_items(self) -> None:
        item = self.store.add_to_inbox("  补实验数据  ")
        other = self.store.add_to_inbox("复习高数")
        self.assertTrue(self.store.move_inbox_task_to_today(item, "已老实"))
        self.assertFalse(self.store.move_inbox_task_to_today(item, "已老实"))
        task, = self.store.tasks_for_day()
        self.assertEqual(task["title"], "补实验数据")
        self.assertTrue(task["quote_id"])
        self.assertEqual([row["id"] for row in self.store.inbox_tasks()], [other])

    def test_complete_does_not_reopen_existing_completion(self) -> None:
        task = self.store.add_task("复习", "test")
        self.store.complete_task(task)
        self.store.complete_task(task)
        self.store.complete_task(-1)
        row, = self.store.tasks_for_day()
        self.assertEqual(row["done"], 1)
        self.assertIsNotNone(row["completed_at"])

    def test_focus_and_break_pass_through_each_deadline_once(self) -> None:
        session = FocusSession(1, "复习", "focus", 1600, 1500)
        self.assertEqual(session.remaining(1599.8), 1)
        self.assertIsNone(session.finish_if_due(1599.8))
        self.assertEqual(session.finish_if_due(1600), "focus")
        self.assertEqual(session.phase, "ready")
        self.assertIsNone(session.finish_if_due(1700))
        session.phase, session.ends, session.duration = "break", 2000, 300
        self.assertEqual(session.finish_if_due(2500), "break")
        self.assertEqual(session.phase, "rested")

    def test_reminder_is_deduplicated_and_rescheduling_changes_identity(self) -> None:
        day = date.today()
        event = self.store.add_schedule("上课", day, "14:00")
        starts = f"{day.isoformat()}T14:00"
        self.assertTrue(self.store.record_pet_schedule_reminder(event, starts))
        self.assertFalse(self.store.record_pet_schedule_reminder(event, starts))
        self.store.update_schedule(event, "上课", day, "15:00")
        self.assertTrue(self.store.record_pet_schedule_reminder(event, f"{day.isoformat()}T15:00"))
        self.store.delete_schedule(event)
        self.assertIsNone(self.store.conn.execute(
            "SELECT 1 FROM pet_schedule_reminders WHERE schedule_id = ?", (event,),
        ).fetchone())

    def test_upcoming_includes_next_day_but_filters_past_timed_events(self) -> None:
        day = date.today()
        self.store.add_schedule("已结束", day, "09:00")
        self.store.add_schedule("全天", day)
        tomorrow = self.store.add_schedule("明天上课", day + timedelta(days=1), "08:30")
        now = datetime.combine(day, datetime.strptime("10:10", "%H:%M").time())
        rows = self.store.upcoming_schedules(now)
        self.assertEqual([row["title"] for row in rows], ["全天", "明天上课"])
        self.assertEqual(rows[1]["id"], tomorrow)

    def test_quiet_mode_combines_manual_fullscreen_and_focus(self) -> None:
        tools = DesktopTools.__new__(DesktopTools)
        tools.app = Mock()
        tools.app.store = self.store
        tools.fullscreen = False
        tools.session = None
        tools.muted_until = 0
        with patch("qixin.desktop_tools.time.time", return_value=100):
            tools.toggle_quiet()
            self.assertTrue(tools.is_quiet(101))
            self.assertEqual(float(self.store.get_setting("pet_quiet_until")), 3700)
            tools.toggle_quiet()
        self.assertFalse(tools.is_quiet(101))
        tools.fullscreen = True
        self.assertTrue(tools.is_quiet(101))
        tools.fullscreen = False
        tools.session = FocusSession(None, "自由专注", "focus", 1500, 1500)
        self.assertTrue(tools.is_quiet(101))
