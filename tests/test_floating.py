from __future__ import annotations

import tkinter as tk
import unittest
from itertools import combinations

from qixin.content import QUOTES
from qixin.floating import FloatingWisdom
from qixin.theme import (
    FONT_BOOST,
    VisualKit,
    detect_ui_scale,
    set_font_scale,
)

SCALES = (0.95, 1.14, 1.30, 1.45)


def _text_items(canvas: tk.Canvas) -> list[int]:
    return [item for item in canvas.find_all() if canvas.type(item) == "text"]


class FloatingWisdomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.ui_scale = detect_ui_scale(cls.root)
        cls.kit = VisualKit(cls.root, cls.ui_scale)
        cls.screen_width = cls.root.winfo_screenwidth()
        cls.screen_height = cls.root.winfo_screenheight()

    @classmethod
    def tearDownClass(cls) -> None:
        set_font_scale(FONT_BOOST)
        cls.root.destroy()

    def setUp(self) -> None:
        set_font_scale(FONT_BOOST)
        self.card = FloatingWisdom(self.root, self.kit, 0)
        self.addCleanup(self._dispose_card, self.card)

    @staticmethod
    def _dispose_card(card: FloatingWisdom) -> None:
        if not card._closed:
            card._close()
        set_font_scale(FONT_BOOST)

    def _refresh(self) -> None:
        self.root.update_idletasks()
        self.root.update()

    def _assert_card_is_clean(self, card: FloatingWisdom) -> dict[str, int]:
        """Assert size caps, canvas containment and non-overlapping text."""

        canvas = card.canvas
        width = card.window.winfo_width()
        height = card.window.winfo_height()
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()

        self.assertLessEqual(width, self.screen_width * 0.46)
        self.assertLessEqual(height, self.screen_height * 0.70)
        # geometry and canvas have to move together
        self.assertEqual(width, canvas_width)
        self.assertEqual(height, canvas_height)

        bounds = canvas.bbox("all")
        self.assertIsNotNone(bounds)
        assert bounds is not None
        self.assertGreaterEqual(bounds[0], 0)
        self.assertGreaterEqual(bounds[1], 0)
        self.assertLessEqual(bounds[2], canvas_width)
        self.assertLessEqual(bounds[3], canvas_height)

        self.assertGreaterEqual(card.window.winfo_x(), 0)
        self.assertGreaterEqual(card.window.winfo_y(), 0)
        self.assertLessEqual(card.window.winfo_x() + width, self.screen_width)
        self.assertLessEqual(card.window.winfo_y() + height, self.screen_height)

        items = _text_items(canvas)
        counts = {
            tag: sum(1 for item in items if tag in canvas.gettags(item))
            for tag in (
                "title",
                "close",
                "quote",
                "source",
                "explanation",
                "western",
                "hint",
            )
        }
        self.assertEqual(counts["title"], 1)
        self.assertEqual(counts["close"], 1)
        self.assertEqual(counts["source"], 1)
        self.assertEqual(counts["hint"], 1)
        self.assertGreaterEqual(counts["quote"], 1)
        self.assertGreaterEqual(counts["explanation"], 1)
        self.assertLessEqual(counts["quote"], 3)
        self.assertLessEqual(counts["explanation"], 3)
        self.assertLessEqual(counts["western"], 2)
        # Every visual line is its own item, so a wrapped quote cannot silently
        # grow past the height that was reserved for it.
        self.assertEqual(
            len(items),
            4 + counts["quote"] + counts["explanation"] + counts["western"],
        )

        boxes = [(canvas.itemcget(item, "text"), canvas.bbox(item)) for item in items]
        for (text_a, box_a), (text_b, box_b) in combinations(boxes, 2):
            if box_a is None or box_b is None:
                continue
            x_overlap = box_a[0] < box_b[2] and box_b[0] < box_a[2]
            y_overlap = box_a[1] < box_b[3] and box_b[1] < box_a[3]
            if x_overlap and y_overlap:
                self.fail(
                    f"text items overlap: {text_a!r} {box_a} / {text_b!r} {box_b}"
                )
        return counts

    def test_layout_reflows_and_stays_inside_every_scale(self) -> None:
        sizes: list[tuple[int, int]] = []
        right_edges: list[int] = []

        for scale in SCALES:
            set_font_scale(scale)
            self.card.relayout()
            self._refresh()

            self.assertEqual(self.card.font_scale, scale)
            counts = self._assert_card_is_clean(self.card)
            width = self.card.window.winfo_width()
            height = self.card.window.winfo_height()
            sizes.append((width, height))
            right_edges.append(self.card.window.winfo_x() + width)

            # The content itself is still visible, not just an empty frame.
            self.assertIn(QUOTES[0]["text"][:4], "".join(
                self.card.canvas.itemcget(item, "text")
                for item in _text_items(self.card.canvas)
                if "quote" in self.card.canvas.gettags(item)
            ))
            self.assertGreaterEqual(counts["explanation"], 1)

        # Bigger fonts may reflow to more lines, but never into a tiny card.
        self.assertGreaterEqual(sizes[-1][1], sizes[0][1])
        self.assertGreater(sizes[-1][0], sizes[0][0])
        # The card is right-aligned: growing keeps the right edge in place.
        self.assertLessEqual(max(right_edges) - min(right_edges), 1)

    def test_layout_survives_every_quote_at_max_scale(self) -> None:
        set_font_scale(SCALES[-1])
        self.card.set_scale(SCALES[-1])
        for index in range(len(QUOTES)):
            self.card.set_quote(index)
            self._refresh()
            counts = self._assert_card_is_clean(self.card)
            self.assertTrue(1 <= counts["quote"] <= 3)
            self.assertTrue(1 <= counts["explanation"] <= 3)

    def test_set_scale_reruns_layout(self) -> None:
        self.card.set_scale(SCALES[0])
        self._refresh()
        small = self.card.window.winfo_width()
        self.assertEqual(self.card.font_scale, SCALES[0])

        self.card.set_scale(SCALES[-1])
        self._refresh()
        large = self.card.window.winfo_width()
        self.assertEqual(self.card.font_scale, SCALES[-1])
        self.assertGreater(large, small)
        self._assert_card_is_clean(self.card)

    def test_draw_reflows_after_font_scale_change(self) -> None:
        """ui.py repaints via ``_draw()`` after a font change."""

        self.card.set_scale(SCALES[0])
        self._refresh()
        small = (self.card.window.winfo_width(), self.card.window.winfo_height())

        set_font_scale(SCALES[-1])
        self.card._draw()
        self._refresh()
        large = (self.card.window.winfo_width(), self.card.window.winfo_height())
        self.assertEqual(self.card.font_scale, SCALES[-1])
        self.assertGreater(large[0], small[0])
        self._assert_card_is_clean(self.card)

    def test_public_api_and_close_callback(self) -> None:
        seen: list[int] = []
        closed: list[bool] = []
        card = FloatingWisdom(
            self.root,
            self.kit,
            len(QUOTES) - 1,
            on_quote_change=seen.append,
            on_close=lambda: closed.append(True),
        )
        self.addCleanup(self._dispose_card, card)
        self.assertEqual(card.index, len(QUOTES) - 1)

        card.set_quote(0)
        self.assertEqual(card.index, 0)
        quote_texts = [
            card.canvas.itemcget(item, "text")
            for item in _text_items(card.canvas)
            if "quote" in card.canvas.gettags(item)
        ]
        self.assertIn(QUOTES[0]["text"], "".join(quote_texts))

        card.next_quote()
        self.assertEqual(card.index, 1)
        self.assertEqual(seen, [1])
        self.assertIsNotNone(card.window)

        card.show()
        card._close()
        self.assertTrue(card._closed)
        self.assertEqual(closed, [True])
        self.assertFalse(card.window.winfo_exists())
        # Closing twice must not fire the callback again.
        card._close()
        self.assertEqual(closed, [True])

    def test_interaction_bindings_are_present(self) -> None:
        canvas = self.card.canvas
        self.assertTrue(canvas.bind("<ButtonPress-1>"))
        self.assertTrue(canvas.bind("<B1-Motion>"))
        self.assertTrue(canvas.bind("<ButtonRelease-1>"))
        self.assertFalse(canvas.bind("<Double-Button-1>"))
        self.assertTrue(canvas.find_withtag("close"))


if __name__ == "__main__":
    unittest.main()
