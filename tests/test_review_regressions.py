import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from queue import SimpleQueue
from unittest.mock import Mock, patch

from qixin.audio import AmbientPlayer
from qixin.db import Store
from qixin.notes import RichRun, save_note
from qixin.services import WeatherService
from qixin.ui import QixinApp, WeeklyReportDialog


class ReviewRegressionTests(unittest.TestCase):
    def test_open_partially_upgraded_alarm_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            with sqlite3.connect(path) as old:
                old.execute(
                    "CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, local_date TEXT, "
                    "start_time TEXT, title TEXT, note TEXT, created_at TEXT, alarm_sound TEXT)"
                )
                old.execute(
                    "INSERT INTO schedule_events VALUES (1, '2026-11-19', '10:30', '课', '', '', '')"
                )
            old.close()
            for _ in range(2):
                store = Store(path)
                row = store.conn.execute("SELECT * FROM schedule_events").fetchone()
                self.assertEqual(row["alarm_sound"], "")
                self.assertIsNone(row["alarm_fired"])
                store.close()

    def test_json_export_includes_rich_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "app.db")
            try:
                self.assertEqual(store.export_payload()["notes"], [])
                self.assertIsNone(store.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='notes'"
                ).fetchone())
                save_note(store, [RichRun("内容", bold=True)], title="标题")
                target = Path(folder) / "export.json"
                store.export_json(target)
                record = json.loads(target.read_text())["notes"][0]
                self.assertEqual(record["title"], "标题")
                self.assertTrue(json.loads(record["body_json"])[0]["bold"])
            finally:
                store.close()

    def test_weather_accepts_zero_and_falls_back_on_invalid_config(self):
        with patch.dict("os.environ", QIXIN_CITY="其他", QIXIN_LAT="", QIXIN_LON="300"):
            service = WeatherService()
            self.assertEqual((service.city, service.latitude, service.longitude),
                             ("南京", 32.0603, 118.7969))
            service = WeatherService(latitude=0, longitude=0)
            self.assertEqual((service.latitude, service.longitude), (0, 0))

    def test_stop_discards_an_audio_job_still_generating(self):
        player = AmbientPlayer()
        entered, release = threading.Event(), threading.Event()
        ready, failed = Mock(), Mock()

        def generate(track):
            entered.set()
            release.wait(3)
            raise OSError("late failure")

        real_thread = threading.Thread
        with patch("qixin.audio.threading.Thread", wraps=real_thread) as launch, patch.object(
            player, "ensure_track", side_effect=generate
        ), patch.object(player, "_start_playback") as start:
            threads = []
            launch.side_effect = lambda **kw: threads.append(real_thread(**kw)) or threads[-1]
            player.play_async({"id": "a"}, ready, failed)
            try:
                self.assertTrue(entered.wait(2))
                player.stop()
            finally:
                release.set()
                threads[0].join(3)
            self.assertFalse(threads[0].is_alive())
        self.assertIsNone(player.current_track_id)
        self.assertFalse(player.playing)
        start.assert_not_called()
        ready.assert_not_called()
        failed.assert_not_called()

    def test_ai_failures_restore_music_and_report_state(self):
        app = QixinApp.__new__(QixinApp)
        app._background_results = SimpleQueue()
        app.ai = Mock(configured=True)
        app.ai.refine_playlist.side_effect = RuntimeError("offline")
        app.ai.weekly_report.side_effect = RuntimeError("offline")
        app.ai_music_busy = False
        app.music_results = []
        app.music_mood = "已老实"
        app.music_activity = "学习"
        app._effective_weather = Mock(return_value="晴")
        app.current_page = "music"
        app.render, app._toast = Mock(), Mock()
        report = WeeklyReportDialog.__new__(WeeklyReportDialog)
        report.app, report.stats = app, {}
        report._ai_busy = False
        report.status_var, report.window = Mock(), Mock()
        with patch("qixin.ui.threading.Thread", side_effect=lambda target, daemon: Mock(start=target)):
            app._run_playlist_ai()
            report._ai_refine()
        app._background_results.get_nowait()()
        app._background_results.get_nowait()()
        self.assertFalse(app.ai_music_busy)
        self.assertFalse(report._ai_busy)
        self.assertIn("offline", report.status_var.set.call_args.args[0])
