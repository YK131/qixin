from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch

from PIL import Image, ImageChops, ImageTk

from qixin.db import Store
from qixin.pages_settings import FEATURE_GROUPS
from qixin.theme import COLORS, FONT_BOOST, hex_rgb, set_font_scale
from qixin.ui import PAGE_HEIGHT, PAGE_WIDTH, QixinApp


PAGES = ("today", "music", "calendar", "essay", "news", "settings")


class UISmokeTests(unittest.TestCase):
    def assert_page_fits(self, app: QixinApp, page: str) -> None:
        bounds = app.page_canvas.bbox("all")
        self.assertIsNotNone(bounds, page)
        assert bounds is not None
        # The window is resizable, so the live shell width decides, not the
        # module constant. Height may exceed the viewport (content-driven pages
        # scroll) but must match what the canvas declared as its scroll region.
        self.assertLessEqual(
            bounds[2],
            round(app.page_w * app.ui_scale) + 2,
            page,
        )
        self.assertLessEqual(
            bounds[3],
            round(app._page_content_height * app.ui_scale) + 2,
            page,
        )

    def assert_no_text_overlap(self, app: QixinApp, label: str) -> None:
        """Two text items sharing pixels means the layout squeezed them."""

        items = []
        for item in app.page_canvas.find_all():
            if app.page_canvas.type(item) != "text":
                continue
            box = app.page_canvas.bbox(item)
            if box:
                items.append((box, app.page_canvas.itemcget(item, "text")[:16]))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i][0], items[j][0]
                if min(a[2], b[2]) - max(a[0], b[0]) > 3 and min(a[3], b[3]) - max(a[1], b[1]) > 3:
                    self.fail(f"{label}: text overlap {items[i][1]!r} x {items[j][1]!r}")

    @patch.object(QixinApp, "_refresh_news")
    @patch.object(QixinApp, "_refresh_weather")
    def test_glass_backdrop_joins_at_both_seams_and_stays_fixed(self, _weather, _news) -> None:
        with tempfile.TemporaryDirectory(prefix="qixin-glass-") as temp:
            folder = Path(temp)
            app = QixinApp(Store(folder / "glass.db", demo=True), demo=True)
            try:
                app.root.update_idletasks()
                app.show_page("settings")

                def verify_backdrop() -> None:
                    width, height = (round(value * app.ui_scale) for value in (app.win_w, app.win_h))
                    side, head = app.sidebar_canvas.winfo_width(), app.header_canvas.winfo_height()
                    joined = Image.new("RGB", (width, height))
                    for canvas, position in (
                        (app.sidebar_canvas, (0, 0)),
                        (app.header_canvas, (side, 0)),
                        (app.page_canvas, (side, head)),
                    ):
                        self.assertTrue(canvas.find_withtag("window_backdrop"))
                        joined.paste(ImageTk.getimage(app._backdrop_layers[canvas]).convert("RGB"), position)
                    expected = app.kit.window_backdrop(width, height, app._custom_background_source)
                    self.assertIsNone(ImageChops.difference(joined, expected).getbbox())
                    frame = hex_rgb(COLORS["paper"])
                    inset = app.kit.px(7)
                    self.assertEqual(joined.getpixel((inset, height - inset - 1)), frame)
                    self.assertNotEqual(joined.getpixel((width // 2, height - inset - 2)), frame)

                verify_backdrop()
                sidebar = app.sidebar_canvas
                self.assertEqual(sidebar.bbox("window_bottom_glass")[3], sidebar.winfo_height())
                photo = app._backdrop_layers[app.page_canvas]
                fade_top = app.page_canvas.coords("window_bottom_glass")[1]
                self.assertGreater(app._scroll_limit, 0)
                app._move_page_view(app._scroll_limit)
                self.assertGreater(app.page_canvas.canvasy(0), 0)
                self.assertEqual(
                    app.page_canvas.coords("window_backdrop"),
                    [0, app.page_canvas.canvasy(0)],
                )
                self.assertIs(app._backdrop_layers[app.page_canvas], photo)
                self.assertEqual(
                    app.page_canvas.coords("window_bottom_glass"),
                    [0, fade_top + app.page_canvas.canvasy(0)],
                )

                wallpaper = folder / "wallpaper.png"
                Image.new("RGB", (240, 200), "#54876A").save(wallpaper)
                app.store.set_setting("custom_background_path", str(wallpaper))
                app._reload_appearance()
                app.root.update_idletasks()
                verify_backdrop()
            finally:
                app._on_close()

    @patch.object(QixinApp, "_refresh_news")
    @patch.object(QixinApp, "_refresh_weather")
    def test_page_visibility_controls_and_restart(self, _weather, _news) -> None:
        with tempfile.TemporaryDirectory(prefix="qixin-visibility-") as temp:
            path = Path(temp) / "visibility.db"
            app = QixinApp(Store(path, demo=True), demo=True)

            def click_setting(tag: str) -> None:
                canvas = app.page_canvas
                bounds = canvas.bbox(tag)
                self.assertIsNotNone(bounds, tag)
                x, y = (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2
                for event in ("<Motion>", "<ButtonPress-1>", "<ButtonRelease-1>"):
                    canvas.event_generate(event, x=x, y=y)
                app.root.update()

            try:
                app.root.update()
                app.show_page("settings")
                click_setting("visibility_group_0")
                click_setting("visibility_home_quote")
                click_setting("visibility_group_1")
                click_setting("visibility_music")
                self.assertFalse(app.sidebar_canvas.find_withtag("nav_music"))
                app.show_page("today")
                self.assertFalse(app.page_canvas.find_withtag("home_quote"))
                self.assertTrue(app.page_canvas.find_withtag("home_mood"))
                self.assertFalse(app.page_canvas.find_withtag("today_to_music"))
                self.assert_page_fits(app, "custom-today")
                self.assert_no_text_overlap(app, "custom-today")
            finally:
                app._on_close()

            app = QixinApp(Store(path, demo=True), demo=True)
            try:
                self.assertFalse(app.feature_visible("home_quote"))
                self.assertFalse(app.feature_visible("music"))
                app.show_page("music")
                self.assertEqual(app.current_page, "today")
                for key, _ in FEATURE_GROUPS[0][1]:
                    if app.feature_visible(key):
                        app._toggle_feature_visibility(key)
                self.assertTrue(app.page_canvas.find_withtag("page_display_settings"))
                app.show_page("settings")
                app.root.update()
                click_setting("visibility_reset")
                self.assertTrue(app.sidebar_canvas.find_withtag("nav_music"))
                app.show_page("today")
                self.assertTrue(app.page_canvas.find_withtag("home_quote"))
                app.show_page("music")
                app._toggle_feature_visibility("music_inputs")
                self.assertFalse(app.page_canvas.find_withtag("music_inputs"))
                self.assertTrue(app.page_canvas.find_withtag("music_recommendation"))
                self.assert_page_fits(app, "custom-music")
            finally:
                app._on_close()

    def test_window_can_resize_and_fullscreen(self) -> None:
        """The shell must re-fit canvases when the window changes size."""

        with tempfile.TemporaryDirectory(prefix="qixin-resize-") as temp:
            store = Store(Path(temp) / "resize.db", demo=True)
            app = QixinApp(store, demo=True)
            try:
                app.root.update_idletasks()
                app.root.update()
                start_w = app.page_w
                screen_w = app.root.winfo_screenwidth()
                screen_h = app.root.winfo_screenheight()
                target_w = int(screen_w * 0.62)
                target_h = int(screen_h * 0.60)
                app.root.geometry(f"{target_w}x{target_h}")
                for _ in range(4):
                    app.root.update_idletasks()
                    app.root.update()
                    time.sleep(0.06)
                app._sync_shell_geometry()
                app.meter.invalidate()
                app.render()
                app.root.update()

                width = app.root.winfo_width()
                height = app.root.winfo_height()
                self.assertNotEqual(round(app.page_w), round(start_w))
                self.assertLessEqual(
                    abs(app.page_canvas.winfo_width() - round(app.page_w * app.ui_scale)),
                    2,
                )
                self.assertLessEqual(
                    abs(app.page_canvas.winfo_height() - round(app.page_h * app.ui_scale)),
                    2,
                )
                self.assertLessEqual(app.page_canvas.winfo_width(), width + 1)
                self.assertLessEqual(app.page_canvas.winfo_height(), height + 1)
                for page in PAGES:
                    app.show_page(page)
                    app.root.update()
                    self.assert_page_fits(app, f"resized-{page}")
                    self.assert_no_text_overlap(app, f"resized-{page}")

                if hasattr(app.root, "attributes"):
                    app._toggle_fullscreen()
                    for _ in range(5):
                        app.root.update_idletasks()
                        app.root.update()
                        time.sleep(0.06)
                    self.assertTrue(app._fullscreen)
                    app._after_window_resize()
                    app.root.update()
                    if app.root.winfo_width() == screen_w:
                        self.assert_page_fits(app, "fullscreen-settings")
                        self.assert_no_text_overlap(app, "fullscreen-settings")
                    app._toggle_fullscreen()
                    for _ in range(3):
                        app.root.update_idletasks()
                        app.root.update()
                        time.sleep(0.06)
                    self.assertFalse(app._fullscreen)
            finally:
                app._on_close()

    def test_all_pages_render_inside_canvas(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qixin-ui-test-") as temp:
            store = Store(Path(temp) / "test.db", demo=True)
            app = QixinApp(store, demo=True)
            app.root.withdraw()
            try:
                for page in PAGES:
                    app.show_page(page)
                    app.root.update_idletasks()
                    app.root.update()
                    self.assert_page_fits(app, page)
                    self.assert_no_text_overlap(app, page)
                app.show_page("calendar")
                app._set_calendar_view("agenda")
                app.root.update_idletasks()
                self.assert_page_fits(app, "calendar-agenda")
                app._set_calendar_view("month")
                app.show_page("today")

                app._change_font_size(0.06)
                self.assertEqual(app.store.get_setting("font_scale"), str(app.font_scale))
                self.assertIsNone(app._save_custom_mood("期待", "#D49B36"))
                self.assertIsNone(app._save_custom_mood("灵感", "#6E9270"))
                self.assertIsNone(app._save_custom_mood("复杂", "#66778F"))
                self.assertIn("期待", app.moods)
                self.assertEqual(app.store.custom_moods()[0]["name"], "期待")
                self.assertEqual(len(app.mood_order), 12)
                app._save_mood()
                app._save_schedule(date.today(), "23:10", "测试日程", "自动测试添加")

                # 逐档放大字号：页面可以变长，但绝不能横向溢出或超出滚动区域。
                for delta in (0.06, 0.1, 0.1):
                    app._change_font_size(delta)
                    for page in PAGES:
                        app.show_page(page)
                        app.root.update_idletasks()
                        app.root.update()
                        label = f"font-{app.font_scale:.2f}-{page}"
                        self.assert_page_fits(app, label)
                        self.assert_no_text_overlap(app, label)

                app.show_page("calendar")
                app.root.update_idletasks()
                texts = [
                    app.page_canvas.itemcget(item, "text")
                    for item in app.page_canvas.find_all()
                    if app.page_canvas.type(item) == "text"
                ]
                self.assertTrue(any("测试日程" in text for text in texts))
                # 日期格只显示短标记，长心情名交给图例。
                self.assertTrue(any(text.strip() in {"✦", "复杂"} for text in texts))

                app._open_food_wheel()
                self.assertIsNotNone(app._food_wheel)
                assert app._food_wheel is not None
                self.assertGreaterEqual(len(app._food_wheel.options), 12)
                app._food_wheel.close()
                app.show_page("today")
                app._change_font_size(1.0)
                for page in PAGES:
                    app.show_page(page)
                    app.root.update_idletasks()
                    app.root.update()
                    label = f"max-font-{page}"
                    self.assert_page_fits(app, label)
                    self.assert_no_text_overlap(app, label)

                app._show_pet()
                self.assertIsNotNone(app._pet)
                assert app._pet is not None
                app._pet.bounce()
                app.root.update()
                self.assertEqual(len(app._pet._frame_cache), 37)
                menu_labels = [action.label for action in app._pet._main_actions()]
                for label in ("专注计时", "随手记一下", "下一件事", "暂停提醒一小时",
                              "今天吃什么？", "桌宠外观与动画", "更多操作"):
                    self.assertIn(label, menu_labels)
                self.assertTrue(app._pet.canvas.bind("<Button-3>"))
                self.assertTrue(app._pet.click_sway)
                self.assertTrue(app._pet.click_bounce)
                app._pet._set_animation_option("sway", False)
                self.assertFalse(app._pet.click_sway)
                app._pet._set_animation_option("sway", True)
                app._hide_pet()
                self.assertIsNone(app._pet)
            finally:
                app._on_close()
                set_font_scale(FONT_BOOST)


if __name__ == "__main__":
    unittest.main()
