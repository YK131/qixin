from __future__ import annotations

import functools
import json
import shutil
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from qixin.db import Store
from qixin.notes import (
    NoteEditorDialog,
    RichRun,
    count_notes,
    delete_note,
    get_note,
    list_notes,
    note_from_text,
    save_note,
)
from qixin.theme import FONT_BOOST, detect_ui_scale, set_font_scale


def requires_tk(test: Callable[..., object]) -> Callable[..., object]:
    """创建不了 Tk 窗口（例如无显示环境）时跳过界面冒烟测试。"""

    @functools.wraps(test)
    def wrapper(self: unittest.TestCase, *args: object, **kwargs: object) -> object:
        try:
            import tkinter as tk

            probe = tk.Tk()
            probe.withdraw()
            # 先让 Tk 把初始事件跑完，避免销毁后残留 ttk 的 <<ThemeChanged>>。
            probe.update_idletasks()
            probe.destroy()
        except Exception as exc:  # noqa: BLE001 - 任何 Tk 初始化失败都按环境不支持处理
            self.skipTest(f"当前环境无法创建 Tk 窗口：{exc}")
        return test(self, *args, **kwargs)

    return wrapper


_SYSTEM_TEMP_OK: bool | None = None


def _system_temp_usable() -> bool:
    """探测系统临时目录能否完成「建目录→写文件→删目录」的完整流程。"""

    global _SYSTEM_TEMP_OK
    if _SYSTEM_TEMP_OK is None:
        try:
            with tempfile.TemporaryDirectory(prefix="qixin-notes-probe-") as probe:
                Path(probe, "probe.txt").write_text("ok", encoding="utf-8")
            _SYSTEM_TEMP_OK = True
        except OSError:
            _SYSTEM_TEMP_OK = False
    return _SYSTEM_TEMP_OK


class NotesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # 注意不要叫 self._cleanups：unittest.TestCase 自己用这个名字存清理函数。
        self._temp_cleanups: list[Callable[[], None]] = []
        self.store = Store(self._database_path("notes.db"))

    def tearDown(self) -> None:
        self.store.close()
        for cleanup in reversed(self._temp_cleanups):
            try:
                cleanup()
            except OSError:
                # 沙箱可能拒绝删除临时目录，清理失败不影响测试结论。
                pass

    def _database_path(self, name: str) -> Path:
        """优先用系统临时目录；沙箱拒绝写入/删除时退回项目内 .tmp。"""

        if _system_temp_usable():
            temp = tempfile.TemporaryDirectory(prefix="qixin-notes-test-")
            self._temp_cleanups.append(temp.cleanup)
            return Path(temp.name) / name
        fallback = (
            Path(__file__).resolve().parents[1]
            / ".tmp"
            / f"notes-test-{uuid.uuid4().hex[:8]}"
        )
        fallback.mkdir(parents=True, exist_ok=True)

        def remove_fallback() -> None:
            shutil.rmtree(fallback, ignore_errors=True)
            try:
                fallback.parent.rmdir()
            except OSError:
                pass

        self._temp_cleanups.append(remove_fallback)
        return fallback / name


class NotesStorageTests(NotesTestCase):
    def test_save_and_get_note_roundtrip(self) -> None:
        runs = [
            RichRun(
                "今天在图书馆",
                size=16,
                bold=True,
                family="SimSun",
                highlight="#FDF3C7",
            ),
            RichRun("，读到一段很喜欢的句子。", size=18, italic=True),
        ]
        note_id = save_note(self.store, runs, title="图书馆的下午")
        note = get_note(self.store, note_id)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.title, "图书馆的下午")
        self.assertEqual(note.plain_text, "今天在图书馆，读到一段很喜欢的句子。")
        self.assertEqual(len(note.runs), len(runs))
        for expected, actual in zip(runs, note.runs):
            self.assertEqual(actual.text, expected.text)
            self.assertEqual(actual.size, expected.size)
            self.assertEqual(actual.bold, expected.bold)
            self.assertEqual(actual.italic, expected.italic)
            self.assertEqual(actual.family, expected.family)
            self.assertEqual(actual.highlight, expected.highlight)
        # 空 family / 空 highlight 也要保留为空字符串，表示跟随应用字体与无高亮。
        self.assertEqual(note.runs[1].family, "")
        self.assertEqual(note.runs[1].highlight, "")
        self.assertEqual(note.created_at, note.updated_at)

    def test_note_survives_store_reopen(self) -> None:
        note_id = save_note(
            self.store,
            [RichRun("关掉数据库再打开，字还在。", size=20, italic=True)],
            title="持久化",
        )
        path = self.store.path
        self.store.close()
        self.store = Store(path)

        note = get_note(self.store, note_id)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.title, "持久化")
        self.assertEqual(note.runs[0].size, 20)
        self.assertTrue(note.runs[0].italic)

    def test_list_notes_orders_by_recent_update_and_truncates_preview(self) -> None:
        first = save_note(self.store, [RichRun("第一条")], title="一")
        time.sleep(0.005)
        second = save_note(self.store, [RichRun("第二条")], title="二")
        time.sleep(0.005)
        third = save_note(self.store, [RichRun("第三条")], title="三")
        time.sleep(0.005)
        # 重新编辑最早的那条，它应该跳到列表最前面。
        save_note(self.store, [RichRun("更新后的第一条")], title="一", note_id=first)

        notes = list_notes(self.store)
        self.assertEqual([note.id for note in notes], [first, third, second])
        self.assertEqual([note.title for note in notes], ["一", "三", "二"])
        self.assertEqual(len(list_notes(self.store, limit=2)), 2)

        long_text = "长" * 80
        long_note = get_note(self.store, note_from_text(self.store, long_text))
        self.assertIsNotNone(long_note)
        assert long_note is not None
        self.assertLessEqual(len(long_note.preview), 60)
        self.assertTrue(long_text.startswith(long_note.preview.rstrip("…")))

        multiline = get_note(
            self.store,
            note_from_text(self.store, "第一行\n第二行\n第三行"),
        )
        self.assertIsNotNone(multiline)
        assert multiline is not None
        self.assertNotIn("\n", multiline.preview)
        self.assertEqual(multiline.preview, "第一行 第二行 第三行")

    def test_note_from_text_creates_single_run(self) -> None:
        text = "把今天写成一段话。\n第二行也保留。"
        note_id = note_from_text(self.store, text, title="今天")
        note = get_note(self.store, note_id)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(len(note.runs), 1)
        self.assertEqual(note.runs[0].text, text)
        self.assertEqual(note.runs[0].size, 15)
        self.assertFalse(note.runs[0].bold)
        self.assertFalse(note.runs[0].italic)
        self.assertEqual(note.plain_text, text)

    def test_delete_note_reduces_count(self) -> None:
        keep_id = save_note(self.store, [RichRun("留下的")], title="留下")
        gone_id = save_note(self.store, [RichRun("要删掉的")], title="删除")
        self.assertEqual(count_notes(self.store), 2)

        delete_note(self.store, gone_id)
        self.assertEqual(count_notes(self.store), 1)
        self.assertIsNone(get_note(self.store, gone_id))
        self.assertIsNotNone(get_note(self.store, keep_id))
        # 重复删除不存在的笔记也不应该抛错。
        delete_note(self.store, 999_999)

    def test_empty_runs_save_without_crashing(self) -> None:
        note_id = save_note(self.store, [])
        note = get_note(self.store, note_id)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.runs, [])
        self.assertEqual(note.plain_text, "")
        self.assertEqual(note.preview, "")

        row = self.store.conn.execute(
            "SELECT body_json FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        self.assertEqual(json.loads(row["body_json"]), [])

        # 只有空文本的片段同样落成空数组。
        empty_run_id = save_note(self.store, [RichRun(text="")])
        empty_run_note = get_note(self.store, empty_run_id)
        assert empty_run_note is not None
        self.assertEqual(empty_run_note.runs, [])


class NotesEditorTests(NotesTestCase):
    @requires_tk
    def test_editor_dialog_smoke(self) -> None:
        import tkinter as tk

        note_id = save_note(
            self.store,
            [
                RichRun(
                    "今天在图书馆",
                    size=16,
                    bold=True,
                    family="SimSun",
                    highlight="#FDF3C7",
                ),
                RichRun("，读到一段很喜欢的句子。", size=15, italic=True),
            ],
            title="图书馆的下午",
        )

        root = tk.Tk()
        try:
            root.geometry("900x700+60+60")
            root.update_idletasks()
            app = SimpleNamespace(root=root, ui_scale=detect_ui_scale(root))
            dialog = NoteEditorDialog(app, self.store, note_id=note_id)
            dialog.show()
            root.update_idletasks()
            root.update()

            self.assertTrue(dialog.window.winfo_exists())
            width = dialog.window.winfo_width()
            height = dialog.window.winfo_height()
            self.assertGreater(width, 1)
            self.assertGreater(height, 1)
            self.assertLessEqual(width, int(root.winfo_screenwidth() * 0.8) + 1)
            self.assertLessEqual(height, int(root.winfo_screenheight() * 0.8) + 1)

            # 已存在的笔记要按 runs 还原出带格式的正文。
            self.assertEqual(
                dialog.text.get("1.0", "end-1c"),
                "今天在图书馆，读到一段很喜欢的句子。",
            )
            tags = dialog.text.tag_names("1.0")
            self.assertTrue(any("FDF3C7" in tag for tag in tags), tags)
            font_spec = dialog.text.tag_cget(tags[0], "font")
            self.assertIn("SimSun", font_spec)

            # 工具栏、正文、底栏都真的显示出来了。
            self.assertEqual(dialog.family_box.winfo_ismapped(), 1)
            self.assertGreater(dialog.text.winfo_height(), 100)
            self.assertGreater(dialog.hint_label.winfo_height(), 1)

            # 选区格式化的核心路径冒烟。
            dialog.text.tag_remove("sel", "1.0", "end")
            dialog.text.tag_add("sel", "1.0", "1.4")
            dialog._apply_highlight("#DCEFD8")
            self.assertTrue(
                any("DCEFD8" in tag for tag in dialog.text.tag_names("1.0"))
            )

            dialog._close()
            root.update()
            self.assertFalse(dialog.window.winfo_exists())
        finally:
            root.destroy()

    @requires_tk
    def test_editor_fits_at_four_font_scales(self) -> None:
        import tkinter as tk

        note_id = save_note(
            self.store,
            [
                RichRun("正文", size=16, bold=True, highlight="#FDF3C7"),
                RichRun("在四种字号设置下都要能正常使用。"),
            ],
            title="缩放检查",
        )

        root = tk.Tk()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        try:
            root.geometry("900x700+60+60")
            root.update_idletasks()
            app = SimpleNamespace(root=root, ui_scale=detect_ui_scale(root))
            for scale in (0.95, 1.14, 1.30, 1.45):
                set_font_scale(scale)
                dialog = NoteEditorDialog(app, self.store, note_id=note_id)
                dialog.show()
                root.update_idletasks()
                root.update()
                try:
                    self.assertLessEqual(
                        dialog.window.winfo_width(),
                        int(screen_width * 0.8) + 1,
                        f"scale={scale}",
                    )
                    self.assertLessEqual(
                        dialog.window.winfo_height(),
                        int(screen_height * 0.8) + 1,
                        f"scale={scale}",
                    )
                    # 工具栏不被裁切：所有子控件右边缘都在工具栏行内。
                    row = dialog.family_box.master
                    rights = [
                        child.winfo_x() + child.winfo_width()
                        for child in row.winfo_children()
                    ]
                    self.assertLessEqual(max(rights), row.winfo_width() + 1, f"scale={scale}")
                    # 正文区与底栏仍有可用高度。
                    self.assertGreater(dialog.text.winfo_height(), 150, f"scale={scale}")
                    self.assertGreater(
                        dialog.hint_label.winfo_height(), 1, f"scale={scale}"
                    )
                    self.assertEqual(
                        dialog.text.get("1.0", "end-1c"),
                        "正文在四种字号设置下都要能正常使用。",
                    )
                finally:
                    dialog._close()
                    root.update()
        finally:
            set_font_scale(FONT_BOOST)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
