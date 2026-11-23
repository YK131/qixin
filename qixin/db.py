from __future__ import annotations

from .files import write_text_atomic

import json
import os
import random
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterator

from .content import LEGACY_MOOD_MAP, MOODS, QUOTES, task_wisdom


APP_NAME = "Qixin"


def app_data_dir() -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


class Store:
    def __init__(self, path: str | Path | None = None, demo: bool = False):
        default_name = "qixin-demo.db" if demo else "qixin.db"
        self.demo = demo
        self.path = Path(path) if path else app_data_dir() / default_name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(schedule_events)")}
            for column in ("alarm_sound", "alarm_fired"):
                if column not in columns:
                    self.conn.execute(f"ALTER TABLE schedule_events ADD COLUMN {column} TEXT")
        self._migrate_legacy_moods()
        if demo:
            self.seed_demo_data()
            self._ensure_demo_schedules()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mood_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                local_date TEXT NOT NULL,
                mood TEXT NOT NULL,
                activity TEXT NOT NULL DEFAULT '',
                weather TEXT NOT NULL DEFAULT '',
                temperature REAL,
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_mood_local_date
            ON mood_entries(local_date);

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                local_date TEXT NOT NULL,
                title TEXT NOT NULL,
                quote_id TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_local_date
            ON tasks(local_date);

            CREATE TABLE IF NOT EXISTS playlist_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                local_date TEXT NOT NULL,
                mood TEXT NOT NULL,
                activity TEXT NOT NULL,
                weather TEXT NOT NULL,
                time_bucket TEXT NOT NULL,
                track_id TEXT NOT NULL,
                track_title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(week_start)
            );

            CREATE TABLE IF NOT EXISTS custom_moods (
                name TEXT PRIMARY KEY,
                color TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_date TEXT NOT NULL,
                start_time TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_schedule_local_date
            ON schedule_events(local_date);

            CREATE TABLE IF NOT EXISTS task_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pet_schedule_reminders (
                schedule_id INTEGER NOT NULL REFERENCES schedule_events(id) ON DELETE CASCADE,
                starts_at TEXT NOT NULL,
                PRIMARY KEY (schedule_id, starts_at)
            );

            CREATE TABLE IF NOT EXISTS signup_reminders (
                news_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                direct_link INTEGER NOT NULL,
                opens_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def _migrate_legacy_moods(self) -> None:
        if self.get_setting("mood_schema_version", "") == "2":
            return
        for old, new in LEGACY_MOOD_MAP.items():
            self.conn.execute(
                "UPDATE mood_entries SET mood = ? WHERE mood = ?",
                (new, old),
            )
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES('mood_schema_version', '2')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def add_custom_mood(self, name: str, color: str) -> None:
        self.conn.execute(
            """
            INSERT INTO custom_moods(name, color, created_at)
            VALUES (?, ?, ?)
            """,
            (
                name,
                color,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def custom_moods(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT name, color, created_at
                FROM custom_moods
                ORDER BY created_at ASC
                """
            ).fetchall()
        )

    def add_schedule(
        self,
        title: str,
        local_date: date,
        start_time: str = "",
        note: str = "",
        alarm_sound: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO schedule_events(
                local_date, start_time, title, note, alarm_sound, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                local_date.isoformat(),
                start_time.strip(),
                title.strip(),
                note.strip(),
                alarm_sound,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_schedule(
        self,
        schedule_id: int,
        title: str,
        local_date: date,
        start_time: str = "",
        note: str = "",
        alarm_sound: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE schedule_events
            SET local_date = ?, start_time = ?, title = ?, note = ?, alarm_sound = ?
            WHERE id = ?
            """,
            (
                local_date.isoformat(),
                start_time.strip(),
                title.strip(),
                note.strip(),
                alarm_sound,
                int(schedule_id),
            ),
        )
        self.conn.commit()

    def schedules_for_day(self, day: date) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE local_date = ?
                ORDER BY
                    CASE WHEN start_time = '' THEN 1 ELSE 0 END,
                    start_time ASC,
                    id ASC
                """,
                (day.isoformat(),),
            ).fetchall()
        )

    def schedules_between(
        self,
        start: date,
        end: date,
    ) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM schedule_events
                WHERE local_date BETWEEN ? AND ?
                ORDER BY local_date ASC,
                    CASE WHEN start_time = '' THEN 1 ELSE 0 END,
                    start_time ASC,
                    id ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        )

    def delete_schedule(self, schedule_id: int) -> None:
        self.conn.execute("DELETE FROM schedule_events WHERE id = ?", (schedule_id,))
        self.conn.commit()

    def add_mood(
        self,
        mood: str,
        activity: str,
        weather: str = "",
        temperature: float | None = None,
        note: str = "",
        when: datetime | None = None,
    ) -> int:
        when = when or datetime.now()
        cur = self.conn.execute(
            """
            INSERT INTO mood_entries(
                created_at, local_date, mood, activity, weather, temperature, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                when.isoformat(timespec="seconds"),
                when.date().isoformat(),
                mood,
                activity,
                weather,
                temperature,
                note,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_task(
        self,
        title: str,
        quote_id: str,
        local_date: date | None = None,
    ) -> int:
        local_date = local_date or date.today()
        cur = self.conn.execute(
            """
            INSERT INTO tasks(created_at, local_date, title, quote_id, done)
            VALUES (?, ?, ?, ?, 0)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                local_date.isoformat(),
                title.strip(),
                quote_id,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_to_inbox(self, title: str) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO task_inbox(created_at, title) VALUES (?, ?)",
                (datetime.now().isoformat(timespec="seconds"), title.strip()),
            )
            return int(cursor.lastrowid)

    def inbox_tasks(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM task_inbox ORDER BY id DESC"))

    def remove_from_inbox(self, item_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM task_inbox WHERE id = ?", (item_id,))

    def move_inbox_task_to_today(self, item_id: int, mood: str) -> bool:
        now = datetime.now()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT title FROM task_inbox WHERE id = ?", (item_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "INSERT INTO tasks(created_at, local_date, title, quote_id) VALUES (?, ?, ?, ?)",
                (now.isoformat(timespec="seconds"), now.date().isoformat(),
                 row["title"], task_wisdom(row["title"], mood)["id"]),
            )
            conn.execute("DELETE FROM task_inbox WHERE id = ?", (item_id,))
        return True

    def complete_task(self, task_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE tasks SET done = 1, completed_at = ? WHERE id = ? AND done = 0",
                (datetime.now().isoformat(timespec="seconds"), task_id),
            )

    def record_pet_schedule_reminder(self, schedule_id: int, starts_at: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO pet_schedule_reminders(schedule_id, starts_at) VALUES (?, ?)",
                (schedule_id, starts_at),
            )
            return cursor.rowcount == 1

    def upcoming_schedules(self, now: datetime) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            """
            SELECT * FROM schedule_events
            WHERE local_date > ?
               OR (local_date = ? AND (start_time = '' OR start_time >= ?))
            ORDER BY local_date, start_time = '', start_time, id
            LIMIT 32
            """,
            (now.date().isoformat(), now.date().isoformat(), now.strftime("%H:%M")),
        ))

    def save_signup_reminder(
        self, key: str, title: str, url: str, direct_link: bool,
        opens_at: int, expires_at: int,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO signup_reminders(news_key, title, url, direct_link, opens_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(news_key) DO UPDATE SET
                    title = excluded.title, url = excluded.url, direct_link = excluded.direct_link,
                    notified = CASE WHEN opens_at = excluded.opens_at THEN notified ELSE 0 END,
                    opens_at = excluded.opens_at, expires_at = excluded.expires_at
                """,
                (key, title, url, direct_link, opens_at, expires_at),
            )

    def signup_reminders(self, now: float) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT * FROM signup_reminders WHERE expires_at > ? ORDER BY opens_at, news_key",
            (now,),
        ))

    def cancel_signup_reminder(self, key: str) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM signup_reminders WHERE news_key = ?", (key,))

    def next_due_signup_reminder(self, now: float) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM signup_reminders
            WHERE notified = 0 AND opens_at <= ? AND expires_at > ?
            ORDER BY opens_at, news_key LIMIT 1
            """,
            (now, now),
        ).fetchone()

    def claim_signup_notification(self, conn: sqlite3.Connection, key: str, opens_at: int, now: float) -> bool:
        cursor = conn.execute(
            """
            UPDATE signup_reminders SET notified = 1
            WHERE news_key = ? AND opens_at = ? AND notified = 0 AND expires_at > ?
            """,
            (key, opens_at, now),
        )
        return cursor.rowcount == 1

    def toggle_task(self, task_id: int) -> None:
        row = self.conn.execute(
            "SELECT done FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return
        done = 0 if row["done"] else 1
        completed_at = datetime.now().isoformat(timespec="seconds") if done else None
        self.conn.execute(
            "UPDATE tasks SET done = ?, completed_at = ? WHERE id = ?",
            (done, completed_at, task_id),
        )
        self.conn.commit()

    def delete_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    def tasks_for_day(self, day: date | None = None) -> list[sqlite3.Row]:
        day = day or date.today()
        return list(
            self.conn.execute(
                """
                SELECT * FROM tasks
                WHERE local_date = ?
                ORDER BY done ASC, id ASC
                """,
                (day.isoformat(),),
            ).fetchall()
        )

    def task_counts_for_day(self, day: date | None = None) -> tuple[int, int]:
        day = day or date.today()
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(SUM(done), 0) AS done
            FROM tasks WHERE local_date = ?
            """,
            (day.isoformat(),),
        ).fetchone()
        return int(row["total"]), int(row["done"])

    def task_counts_between(
        self,
        start: date,
        end: date,
    ) -> dict[str, tuple[int, int]]:
        rows = self.conn.execute(
            """
            SELECT local_date, COUNT(*) AS total, COALESCE(SUM(done), 0) AS done
            FROM tasks
            WHERE local_date BETWEEN ? AND ?
            GROUP BY local_date
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return {
            str(row["local_date"]): (int(row["total"]), int(row["done"]))
            for row in rows
        }

    def latest_mood_for_day(self, day: date | None = None) -> sqlite3.Row | None:
        day = day or date.today()
        return self.conn.execute(
            """
            SELECT * FROM mood_entries
            WHERE local_date = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (day.isoformat(),),
        ).fetchone()

    def moods_for_day(self, day: date) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM mood_entries
                WHERE local_date = ?
                ORDER BY created_at ASC, id ASC
                """,
                (day.isoformat(),),
            ).fetchall()
        )

    def moods_between(self, start: date, end: date) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT * FROM mood_entries
                WHERE local_date BETWEEN ? AND ?
                ORDER BY created_at ASC, id ASC
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        )

    def latest_moods_by_date(
        self, start: date, end: date
    ) -> dict[str, sqlite3.Row]:
        rows = self.moods_between(start, end)
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[str(row["local_date"])] = row
        return latest

    def clear_moods(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM mood_entries").fetchone()
        count = int(row[0])
        self.conn.execute("DELETE FROM mood_entries")
        self.conn.execute("DELETE FROM reports")
        self.conn.commit()
        return count

    def record_playlist(
        self,
        mood: str,
        activity: str,
        weather: str,
        moment: str,
        track_id: str,
        track_title: str,
    ) -> None:
        now = datetime.now()
        self.conn.execute(
            """
            INSERT INTO playlist_history(
                created_at, local_date, mood, activity, weather,
                time_bucket, track_id, track_title
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(timespec="seconds"),
                now.date().isoformat(),
                mood,
                activity,
                weather,
                moment,
                track_id,
                track_title,
            ),
        )
        self.conn.commit()

    def save_report(self, week_start: date, content: str) -> None:
        self.conn.execute(
            """
            INSERT INTO reports(week_start, content, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET
                content = excluded.content,
                created_at = excluded.created_at
            """,
            (
                week_start.isoformat(),
                content,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def weekly_stats(self, anchor: date | None = None) -> dict[str, Any]:
        anchor = anchor or date.today()
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        moods = self.moods_between(start, end)
        tasks = list(
            self.conn.execute(
                """
                SELECT * FROM tasks WHERE local_date BETWEEN ? AND ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        )
        counts = Counter(str(row["mood"]) for row in moods)
        total_tasks = len(tasks)
        done_tasks = sum(int(row["done"]) for row in tasks)
        active_days = len({str(row["local_date"]) for row in moods})
        return {
            "start": start,
            "end": end,
            "moods": moods,
            "mood_counts": dict(counts),
            "active_days": active_days,
            "total_tasks": total_tasks,
            "done_tasks": done_tasks,
            "completion_rate": done_tasks / total_tasks if total_tasks else 0,
        }

    def recap_counts(self) -> dict[str, Any]:
        mood_count = self.conn.execute(
            "SELECT COUNT(*) FROM mood_entries"
        ).fetchone()[0]
        task_count = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        playlist_count = self.conn.execute(
            "SELECT COUNT(*) FROM playlist_history"
        ).fetchone()[0]
        first_day = self.conn.execute(
            "SELECT MIN(local_date) FROM mood_entries"
        ).fetchone()[0]
        return {
            "mood_count": int(mood_count),
            "task_count": int(task_count),
            "playlist_count": int(playlist_count),
            "first_day": first_day,
        }

    def export_payload(self) -> dict[str, Any]:
        mood_rows = self.conn.execute(
            "SELECT * FROM mood_entries ORDER BY id"
        ).fetchall()
        task_rows = self.conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        playlist_rows = self.conn.execute(
            "SELECT * FROM playlist_history ORDER BY id"
        ).fetchall()
        custom_mood_rows = self.custom_moods()
        schedule_rows = self.conn.execute(
            "SELECT * FROM schedule_events ORDER BY local_date, start_time, id"
        ).fetchall()
        # The notes table is created on first use by the editor.
        notes_exist = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'"
        ).fetchone()
        notes = self.conn.execute("SELECT * FROM notes ORDER BY id").fetchall() if notes_exist else []
        return {
            "app": "栖心 Qixin",
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "moods": [dict(row) for row in mood_rows],
            "tasks": [dict(row) for row in task_rows],
            "task_inbox": [dict(row) for row in self.inbox_tasks()],
            "playlists": [dict(row) for row in playlist_rows],
            "custom_moods": [dict(row) for row in custom_mood_rows],
            "schedules": [dict(row) for row in schedule_rows],
            "notes": [dict(row) for row in notes],
        }

    def export_json(self, path: str | Path) -> None:
        write_text_atomic(path,
            json.dumps(self.export_payload(), ensure_ascii=False, indent=2),
        )

    def seed_demo_data(self) -> None:
        if self.get_setting("demo_seeded") == "1":
            return
        today = date.today()
        rng = random.Random(20261108)
        mood_sequence = [
            "精神状态良好",
            "活人微死",
            "心流在线",
            "已老实",
            "无语",
            "美美得很",
            "淹没在作业海",
            "已老实",
            "灵魂出窍",
            "摸鱼中",
        ]
        activities = ["阅读", "复习考试", "运动", "写论文", "放空"]
        weathers = ["晴", "多云", "阴", "雨"]
        for offset in range(29, 0, -1):
            day = today - timedelta(days=offset)
            if offset > 10 and offset % 7 == 1:
                continue
            base_mood = mood_sequence[(offset + day.weekday()) % len(mood_sequence)]
            if offset in {16, 17, 18}:
                base_mood = "灵魂出窍" if offset != 17 else "已老实"
            if offset in {27, 28}:
                base_mood = "淹没在作业海"
            if 1 <= offset <= 10:
                recent = [
                    "美美得很",
                    "摸鱼中",
                    "心流在线",
                    "活人微死",
                    "无语",
                    "精神状态良好",
                    "淹没在作业海",
                    "已老实",
                    "灵魂出窍",
                    "已老实",
                ]
                base_mood = recent[offset - 1]
            mood = base_mood
            when = datetime.combine(
                day,
                time(hour=8 + (offset * 3) % 13, minute=(offset * 7) % 60),
            )
            self.add_mood(
                mood,
                activities[offset % len(activities)],
                weathers[offset % len(weathers)],
                12 + rng.randint(0, 14),
                when=when,
            )
            if offset % 5 == 0 and base_mood in {
                "淹没在作业海",
                "灵魂出窍",
                "无语",
            }:
                later = when + timedelta(hours=5)
                self.add_mood(
                    "已老实",
                    "放空",
                    weathers[(offset + 1) % len(weathers)],
                    15 + rng.randint(0, 8),
                    note="散步之后，情绪缓下来一点。",
                    when=later,
                )
        self.add_mood(
            "已老实",
            "阅读",
            "多云",
            17,
            note="傍晚在窗边读了几页书，心慢慢安静下来。",
            when=datetime.combine(today, time(hour=8, minute=35)),
        )
        task_templates = [
            ("整理《数字信号处理》错题", 1),
            ("给导师发阶段性汇报", 1),
            ("写完实验报告的讨论部分", 0),
            ("去操场走二十分钟", 1),
            ("读一篇无关专业的短篇", 0),
            ("预约图书馆研讨间", 1),
            ("复习概率论第三章", 0),
            ("给家里打个电话", 1),
            ("把论文引言再改一版", 0),
        ]
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            if offset == 0:
                templates = task_templates[2:5]
            else:
                templates = [task_templates[offset % len(task_templates)]]
                templates.append(task_templates[(offset + 3) % len(task_templates)])
            for title, done in templates:
                quote = task_wisdom(title, "心流在线")
                task_id = self.add_task(title, quote["id"], local_date=day)
                if done:
                    self.toggle_task(task_id)
        schedule_templates = [
            ("08:00", "高数早课", "记得带作业本"),
            ("10:00", "图书馆自习", "先完成错题整理"),
            ("14:00", "实验室组会", "准备两页进度"),
            ("16:30", "操场慢跑", "不追配速"),
            ("19:00", "社团例会", "讨论周末活动"),
            ("21:00", "复盘今日", "只写三句话"),
        ]
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            start, title, note = schedule_templates[offset % len(schedule_templates)]
            self.add_schedule(title, day, start, note)
            if offset in {1, 3, 5}:
                start2, title2, note2 = schedule_templates[(offset + 2) % len(schedule_templates)]
                self.add_schedule(title2, day, start2, note2)
        self.set_setting("demo_seeded", "1")

    def _ensure_demo_schedules(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) FROM schedule_events").fetchone()
        if int(row[0]) > 0:
            return
        today = date.today()
        examples = [
            ("08:00", "高数早课", "记得带作业本"),
            ("10:30", "图书馆自习", "先完成错题整理"),
            ("14:00", "实验室组会", "准备两页进度"),
            ("16:30", "操场慢跑", "不追配速"),
            ("19:00", "社团例会", "讨论周末活动"),
            ("21:00", "复盘今日", "只写三句话"),
        ]
        for offset in range(6, -1, -1):
            start, title, note = examples[offset % len(examples)]
            self.add_schedule(title, today - timedelta(days=offset), start, note)


def local_week_bounds(anchor: date | None = None) -> tuple[date, date]:
    anchor = anchor or date.today()
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def mood_label_color(mood: str) -> tuple[str, str]:
    config = MOODS.get(mood, MOODS["已老实"])
    return str(config["color"]), str(config["soft"])


def quote_by_id(quote_id: str) -> dict[str, Any]:
    return next((quote for quote in QUOTES if quote["id"] == quote_id), QUOTES[0])
