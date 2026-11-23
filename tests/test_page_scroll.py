from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from qixin.motion import Tween
from qixin.ui import QixinApp, SCROLL_FRAME_INTERVAL


class TweenTests(unittest.TestCase):
    def test_drawing_delay_does_not_skip_the_transition(self) -> None:
        widget = Mock()
        widget.after.return_value = "frame"
        update, finish = Mock(), Mock()
        with patch("qixin.motion.time.perf_counter", side_effect=[12.0, 12.055, 12.2]):
            tween = Tween(widget, 150, update, finish)
            tween.step()
            update.assert_called_with(0.0)
            tween.step()
            self.assertTrue(0 < update.call_args.args[0] < 1)
            tween.step()
            update.assert_called_with(1.0)
        finish.assert_called_once_with()
        self.assertIsNone(tween.job)

    def test_cancel_drops_the_pending_frame(self) -> None:
        widget = Mock()
        widget.after.return_value = "frame"
        tween = Tween(widget, 150, Mock())
        tween.cancel()
        widget.after_cancel.assert_called_once_with("frame")
        self.assertIsNone(tween.job)


class PageScrollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = app = QixinApp.__new__(QixinApp)
        app.root = Mock()
        app.motion = Mock()
        app.page_canvas = Mock()
        app.page_canvas.canvasy.return_value = 0
        app.page_canvas.winfo_toplevel.return_value = app.root
        app.root.winfo_containing.return_value = app.page_canvas
        app._task_entry = None
        app._scroll_hint = None
        app._closing = False
        app._ui_jobs = set()
        app._scroll_job = None
        app._hidden_sections = frozenset()
        app._update_scroll_hint = Mock()
        app._sz = lambda value: value
        app.ui_scale = 1.25
        app.page_h = 400
        app.page_w = 900
        app._finish_page(1000, 0)
        app.page_canvas.reset_mock()
        self.clock = 10.0
        timer = patch("qixin.ui.time.perf_counter", side_effect=lambda: self.clock)
        timer.start()
        self.addCleanup(timer.stop)

    def wheel(self, delta: int = 0, num: int | str = "??"):
        return self.app._on_page_wheel(SimpleNamespace(
            widget=self.app.page_canvas, x_root=15, y_root=20, delta=delta, num=num,
        ))

    def frame(self) -> None:
        self.clock = self.app._scroll_next_frame + 0.0001
        self.app._apply_scroll()

    def finish_animation(self) -> None:
        for _ in range(20):
            if self.app._scroll_job is None:
                return
            self.frame()
        self.fail("scroll animation never stopped")

    def test_wheel_uses_60hz_deadlines_and_eases_to_a_stop(self) -> None:
        self.assertEqual(self.wheel(-120), "break")
        self.assertEqual(self.app.root.after.call_args.args[0], 17)
        first_deadline = self.app._scroll_next_frame
        self.frame()
        self.assertAlmostEqual(self.app._scroll_next_frame - first_deadline, SCROLL_FRAME_INTERVAL)
        self.finish_animation()
        positions = [call.args[0] for call in self.app.page_canvas.yview_moveto.call_args_list]
        self.assertGreater(len(positions), 5)
        self.assertEqual(positions, sorted(set(positions)))
        self.assertEqual(positions[-1] * self.app._page_height_px, 70)
        self.app.motion.set_scrolling.assert_called_with(self.app.page_canvas, False)

    def test_wheel_clamps_at_bottom_and_reverses_without_backlog(self) -> None:
        self.app._finish_page(1000, self.app._scroll_limit - 12)
        self.app.page_canvas.reset_mock()
        self.wheel(-4800)
        self.finish_animation()
        positions = [call.args[0] for call in self.app.page_canvas.yview_moveto.call_args_list]
        self.assertEqual(positions, sorted(set(positions)))
        self.assertEqual(self.app._scroll_position, self.app._scroll_limit)
        self.assertEqual(self.wheel(num=5), "break")
        self.assertIsNone(self.app._scroll_job)
        self.wheel(num=4)
        self.frame()
        self.assertLess(self.app._scroll_position, self.app._scroll_limit)

    def test_reversal_during_animation_takes_effect_on_next_frame(self) -> None:
        self.app._finish_page(1000, 300)
        self.wheel(-120)
        self.frame()
        position = self.app._scroll_position
        self.wheel(120)
        self.frame()
        self.assertLess(self.app._scroll_position, position)

    def test_render_cancels_inflight_scroll_and_preserves_same_page(self) -> None:
        app = self.app
        app.current_page = app._rendered_page = "today"
        app._destroy_transient_widgets = Mock()
        app._draw_sidebar = Mock()
        app._draw_header = Mock()
        app._draw_page_background = Mock()
        app._draw_today = Mock(return_value=1000)
        app._draw_calendar = Mock(return_value=700)
        self.wheel(-120)
        self.frame()
        position = round(app._scroll_position)
        job = app._scroll_job
        app.render()
        app.root.after_cancel.assert_called_once_with(job)
        self.assertIsNone(app._scroll_job)
        self.assertEqual(app._scroll_position, position)
        app.show_page("calendar")
        self.assertEqual(app._scroll_position, 0)
        self.assertIsNone(app._scroll_job)

    def test_missing_a_frame_does_not_queue_catch_up_frames(self) -> None:
        self.wheel(-120)
        self.clock += 0.09
        self.app._apply_scroll()
        self.assertGreater(self.app._scroll_next_frame, self.clock)
        self.assertLessEqual(self.app._scroll_next_frame - self.clock, SCROLL_FRAME_INTERVAL)
        self.assertGreater(self.app._scroll_position, 60)

    def test_wheel_outside_page_leaves_canvas_untouched(self) -> None:
        self.app.root.winfo_containing.return_value = None
        self.assertIsNone(self.wheel(-120))
        self.app.root.after.assert_not_called()
