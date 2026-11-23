from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from qixin.audio import AmbientPlayer
from qixin.content import MOODS, QUOTES, TRACKS, recommend_tracks, task_wisdom
from qixin.db import Store
from qixin.services import local_weekly_report


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="qixin-test-")
        self.store = Store(Path(self.temp_dir.name) / "test.db", demo=True)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_demo_profile_has_records(self) -> None:
        counts = self.store.recap_counts()
        self.assertGreater(counts["mood_count"], 20)
        self.assertGreater(counts["task_count"], 10)
        self.assertIsNotNone(self.store.latest_mood_for_day())
        self.assertTrue(self.store.schedules_for_day(date.today()))

    def test_expanded_mood_and_quote_catalog(self) -> None:
        self.assertGreaterEqual(len(MOODS), 9)
        self.assertGreaterEqual(len(QUOTES), 700)
        self.assertEqual(len({quote["id"] for quote in QUOTES}), len(QUOTES))
        self.assertEqual(len({quote["text"] for quote in QUOTES}), len(QUOTES))

    def test_every_quote_has_a_western_reading(self) -> None:
        missing = [quote["id"] for quote in QUOTES if not str(quote.get("western", "")).strip()]
        self.assertFalse(missing, f"缺少西方视角解读: {missing[:5]}")
        for quote in QUOTES[:200]:
            self.assertTrue(quote["source"])
            self.assertTrue(quote["explanation"])
            self.assertTrue(quote["tags"])

    def test_quote_order_is_shuffled_not_chronological(self) -> None:
        ids = [quote["id"] for quote in QUOTES]
        prefixes = [identifier.split("-", 1)[0] for identifier in ids]
        # A pure concatenation of batches would put every c1a1 entry together.
        changes = sum(1 for a, b in zip(prefixes, prefixes[1:]) if a != b)
        self.assertGreater(changes, len(prefixes) * 0.5)

    def test_mood_history_can_be_cleared(self) -> None:
        self.assertGreater(self.store.recap_counts()["mood_count"], 0)
        removed = self.store.clear_moods()
        self.assertGreater(removed, 0)
        self.assertEqual(self.store.recap_counts()["mood_count"], 0)

    def test_custom_mood_is_persisted(self) -> None:
        self.store.add_custom_mood("期待", "#D49B36")
        rows = self.store.custom_moods()
        self.assertEqual(rows[0]["name"], "期待")
        self.assertEqual(rows[0]["color"], "#D49B36")

    def test_schedule_rows_are_grouped_and_time_ordered(self) -> None:
        day = date.today()
        late_id = self.store.add_schedule("晚间复盘", day, "21:00")
        early_id = self.store.add_schedule("早课", day, "08:00")
        schedules = self.store.schedules_for_day(day)
        positions = {int(row["id"]): index for index, row in enumerate(schedules)}
        self.assertLess(positions[early_id], positions[late_id])

    def test_schedule_can_be_edited_in_place(self) -> None:
        day = date.today()
        schedule_id = self.store.add_schedule("旧名字", day, "09:00", "旧备注")
        self.store.update_schedule(schedule_id, "新名字", day, "10:30", "新备注")
        rows = self.store.schedules_for_day(day)
        row = next(item for item in rows if int(item["id"]) == schedule_id)
        self.assertEqual(row["title"], "新名字")
        self.assertEqual(row["start_time"], "10:30")
        self.assertEqual(row["note"], "新备注")

    def test_legacy_mood_labels_are_migrated(self) -> None:
        path = Path(self.temp_dir.name) / "legacy.db"
        legacy = Store(path)
        legacy.add_mood("平静", "阅读")
        legacy.conn.execute("DELETE FROM settings WHERE key = 'mood_schema_version'")
        legacy.conn.commit()
        legacy.close()

        migrated = Store(path)
        try:
            self.assertEqual(migrated.latest_mood_for_day()["mood"], "已老实")
        finally:
            migrated.close()

    def test_four_dimension_recommendation_is_ranked(self) -> None:
        results = recommend_tracks("无语", "复习考试", "阴", "夜晚")
        self.assertGreaterEqual(len(results), 3)
        # 多样性排序会为了「前三条不同曲种」调整顺序，所以这里验证展示用
        # 的 score_percent 单调不增，而不是原始 score 严格递减。
        percents = [item["score_percent"] for item in results]
        self.assertEqual(percents, sorted(percents, reverse=True))
        self.assertEqual(len({item["kind"] for item in results[:3]}), 3)
        self.assertGreater(results[0]["score_percent"], results[-1]["score_percent"])
        self.assertTrue(results[0]["reasons"])
        self.assertTrue(results[0]["match_reason"])

    def test_task_wisdom_is_contextual(self) -> None:
        paper_quote = task_wisdom("写完论文引言", "淹没在作业海")
        self.assertIn("焦虑", paper_quote["tags"])
        self.assertTrue(paper_quote["explanation"])

    def test_weekly_report_contains_data(self) -> None:
        report = local_weekly_report(self.store.weekly_stats())
        self.assertIn("情绪与哲思周报", report)
        self.assertIn("下周的小建议", report)

    def test_ambient_audio_is_generated(self) -> None:
        player = AmbientPlayer(Path(self.temp_dir.name) / "audio")
        path = player.ensure_track(TRACKS[0])
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
