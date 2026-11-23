import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from qixin.db import Store
from qixin.desktop_tools import DesktopTools
from qixin.files import write_text_atomic
from qixin.ui import QixinApp


class RecoveryTests(unittest.TestCase):
    def test_catch_up_across_midnight_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "test.db")
            app = SimpleNamespace(store=store, _alarm_queue=Mock())
            store.add_schedule("晚课", date(2026, 11, 19), "23:59", alarm_sound="")
            store.add_schedule("次日", date(2026, 11, 20), "00:01", alarm_sound="a.mp3")
            store.add_schedule("静音", date(2026, 11, 20), "00:01")
            store.add_schedule("以后", date(2026, 11, 20), "00:10", alarm_sound="")
            for _ in range(2):
                QixinApp._check_alarms(app, "2026-11-20 00:03", "2026-11-19 23:58")
            app._alarm_queue.add.assert_called_once()
            self.assertEqual([r["title"] for r in app._alarm_queue.add.call_args.args[0]], ["晚课", "次日"])
            store.conn.close()

    def test_focus_error_does_not_stop_reminders(self):
        tools = Mock()
        tools.app._closing = False
        def fail(*args):
            raise RuntimeError("test fault")
        tools._poll_focus = fail
        with self.assertLogs("qixin.desktop_tools", level="ERROR"):
            DesktopTools._tick(tools)
        tools._poll_alarms.assert_called_once()
        tools._poll_schedule.assert_called_once()
        tools.app.root.after.assert_called_once()

    def test_failed_export_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "data.json"
            target.write_text("previous")
            with patch("qixin.files.os.replace", side_effect=OSError("write failed")), self.assertRaises(OSError):
                write_text_atomic(target, "new")
            self.assertEqual(target.read_text(), "previous")
            self.assertEqual(list(target.parent.iterdir()), [target])
