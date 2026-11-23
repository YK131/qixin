from __future__ import annotations

import math
import time
import tkinter as tk
import unittest

from qixin.food_wheel import (
    IDLE_RESULT,
    MEAL_OPTIONS,
    FoodWheelDialog,
    _abbreviate,
)
from qixin.theme import (
    FONT_BOOST,
    VisualKit,
    detect_ui_scale,
    enable_high_dpi,
    set_font_scale,
)


class FoodPoolTests(unittest.TestCase):
    def test_every_meal_offers_at_least_a_dozen_choices(self) -> None:
        self.assertGreaterEqual(len(MEAL_OPTIONS), 3)
        for meal, pool in MEAL_OPTIONS.items():
            with self.subTest(meal=meal):
                self.assertGreaterEqual(len(pool), 12)
                self.assertEqual(
                    len(pool),
                    len(set(pool)),
                    f"{meal} 菜池里有重复菜名",
                )
                for name in pool:
                    self.assertTrue(
                        4 <= len(name) <= 8,
                        f"{meal} 的菜名长度不合适: {name!r}",
                    )

    def test_dish_names_are_unique_across_meals(self) -> None:
        seen: dict[str, str] = {}
        for meal, pool in MEAL_OPTIONS.items():
            for name in pool:
                with self.subTest(dish=name):
                    self.assertNotIn(name, seen, f"{name!r} 同时出现在 {seen.get(name)} 和 {meal}")
                    seen[name] = meal

    def test_labels_abbreviate_past_six_characters(self) -> None:
        self.assertEqual(_abbreviate("黄焖鸡米饭"), "黄焖鸡米饭")
        self.assertEqual(_abbreviate("超级无敌豪华套餐"), "超级无敌豪华…")
        self.assertEqual(len(_abbreviate("超级无敌豪华套餐")), 7)


class FoodWheelDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        enable_high_dpi()
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - headless CI
            raise unittest.SkipTest(f"Tk 不可用: {exc}")
        cls.root.geometry("320x240+20+20")
        cls.root.update_idletasks()
        cls.ui_scale = detect_ui_scale(cls.root)
        cls.kit = VisualKit(cls.root, cls.ui_scale)

    @classmethod
    def tearDownClass(cls) -> None:
        set_font_scale(FONT_BOOST)
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self) -> None:
        self.addCleanup(set_font_scale, FONT_BOOST)

    def _open(self, on_close=None) -> FoodWheelDialog:
        dialog = FoodWheelDialog(
            self.root,
            self.ui_scale,
            self.kit,
            on_close=on_close,
        )
        self.addCleanup(dialog.close)
        self.root.update()
        return dialog

    def test_all_options_fit_on_one_wheel(self) -> None:
        dialog = self._open()
        pool = MEAL_OPTIONS[dialog._meal]
        self.assertEqual(sorted(dialog.options), sorted(pool))
        self.assertEqual(dialog.result, "")

        count = len(dialog.options)
        arcs = [
            item
            for item in dialog.canvas.find_all()
            if dialog.canvas.type(item) == "arc"
        ]
        labels = dialog.canvas.find_withtag("wheel_label")
        self.assertEqual(len(arcs), count)
        self.assertEqual(len(labels), count)
        self.assertEqual(len(dialog.canvas.find_withtag("food_spin")), 2)
        self.assertEqual(len(dialog.canvas.find_withtag("food_close")), 2)
        # The "换一批" button and its callback are gone for good.
        self.assertEqual(len(dialog.canvas.find_withtag("food_change")), 0)
        self.assertFalse(hasattr(dialog, "_shuffle_options"))

    def test_window_and_canvas_stay_inside_the_screen(self) -> None:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        for scale in (0.95, 1.14, 1.45):
            with self.subTest(font_scale=scale):
                set_font_scale(scale)
                dialog = self._open()
                try:
                    width = dialog.window.winfo_width()
                    height = dialog.window.winfo_height()
                    outer_w = width + 2 * dialog._frame_x
                    outer_h = height + dialog._frame_y + dialog._frame_x
                    self.assertGreater(width, 320)
                    self.assertGreater(height, 320)
                    self.assertGreaterEqual(dialog._left, 0)
                    self.assertGreaterEqual(dialog._top, 0)
                    self.assertLessEqual(dialog._left + outer_w, screen_w + 1)
                    self.assertLessEqual(dialog._top + outer_h, screen_h + 1)

                    bbox = dialog.canvas.bbox("all")
                    self.assertIsNotNone(bbox)
                    assert bbox is not None
                    canvas_w = dialog.canvas.winfo_width()
                    canvas_h = dialog.canvas.winfo_height()
                    self.assertGreaterEqual(bbox[0], -2)
                    self.assertGreaterEqual(bbox[1], -2)
                    self.assertLessEqual(bbox[2], canvas_w + 2)
                    self.assertLessEqual(bbox[3], canvas_h + 2)

                    short = min(screen_w, screen_h)
                    ratio = 2 * dialog.radius_px / short
                    # 2026 版把转盘收小、把按钮放大，舒适的直径约为短边的 64%。
                    self.assertGreaterEqual(ratio, 0.48, f"转盘偏小: {ratio:.1%}")
                    self.assertLessEqual(ratio, 0.78, f"转盘可能超出屏幕: {ratio:.1%}")
                finally:
                    dialog.close()

    def test_labels_shrink_to_the_sector_they_sit_in(self) -> None:
        dialog = self._open()
        count = len(dialog.options)
        chord_at_anchor = (
            2.0
            * dialog.radius_px
            * dialog.LABEL_ANCHOR_SHARE
            * math.sin(math.pi / count)
        )
        for text, size in dialog._labels:
            self.assertLessEqual(len(text), 7)
            self.assertGreaterEqual(size, 7.0)
            self.assertLessEqual(size, chord_at_anchor * 0.70)

    def test_small_screen_still_gets_a_big_wheel_that_fits(self) -> None:
        import qixin.food_wheel as food_wheel

        original_work_area = food_wheel._work_area
        original_w = self.root.winfo_screenwidth
        original_h = self.root.winfo_screenheight
        fake_w, fake_h = 1366, 728
        try:
            food_wheel._work_area = lambda _root: (0, 0, fake_w, fake_h)
            self.root.winfo_screenwidth = lambda: fake_w
            self.root.winfo_screenheight = lambda: fake_h
            for scale in (1.0, 1.45):
                with self.subTest(font_scale=scale):
                    set_font_scale(scale)
                    dialog = self._open()
                    try:
                        outer_w = dialog.width_px + 2 * dialog._frame_x
                        outer_h = dialog.height_px + dialog._frame_y + dialog._frame_x
                        self.assertLessEqual(outer_w, fake_w)
                        self.assertLessEqual(outer_h, fake_h)
                        self.assertGreaterEqual(dialog._left, 0)
                        self.assertGreaterEqual(dialog._top, 0)
                        ratio = 2 * dialog.radius_px / min(fake_w, fake_h)
                        # A 768px-tall screen at font 1.45 cannot also keep
                        # the 78% target: the header/footer alone eat ~100px.
                        # The wheel must still dwarf the legacy 208px one.
                        self.assertGreaterEqual(ratio, 0.34)
                        self.assertGreater(2 * dialog.radius_px, 240)
                    finally:
                        dialog.close()
        finally:
            food_wheel._work_area = original_work_area
            self.root.winfo_screenwidth = original_w
            self.root.winfo_screenheight = original_h

    def test_spin_lands_on_the_dish_under_the_pointer(self) -> None:
        dialog = self._open()
        dialog.spin()
        deadline = time.monotonic() + 8.0
        while dialog.spinning and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(dialog.spinning, "旋转动画没有在预期时间内结束")
        self.assertIn(dialog.result, MEAL_OPTIONS[dialog._meal])
        self.assertIn(dialog.result, dialog.options)
        extent = 360.0 / len(dialog.options)
        expected = (-dialog.options.index(dialog.result) * extent) % 360.0
        self.assertAlmostEqual(dialog.rotation % 360.0, expected, places=3)

    def test_show_and_close_callback(self) -> None:
        closed: list[bool] = []
        dialog = FoodWheelDialog(
            self.root,
            self.ui_scale,
            self.kit,
            on_close=lambda: closed.append(True),
        )
        try:
            dialog.show()
            self.root.update()
            self.assertEqual(dialog.result, "")
        finally:
            dialog.close()
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
