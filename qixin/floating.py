"""The desktop "light whisper" card.

The card is laid out from its text instead of from fixed coordinates: every
font is measured with :class:`tkinter.font.Font`, the quote and the
explanation are wrapped by hand, and the window is resized to the exact height
of the resulting stack.  Enlarging the system font therefore re-flows the card
instead of piling the lines on top of each other.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Any, Callable

from .content import QUOTES, quote_at
from .theme import (
    COLORS,
    ScaledCanvas,
    VisualKit,
    active_font_family,
    get_font_scale,
    mix_color,
    set_font_scale,
    widget_font,
)

# A single soft surface with one hairline and one quiet dot: no other ornament.
CARD_FILL = "#FFFFFF"
CARD_EDGE = mix_color(COLORS["line"], CARD_FILL, 0.2)
RULE_COLOR = mix_color(COLORS["line"], CARD_FILL, 0.05)
DOT_COLOR = mix_color(COLORS["iris"], COLORS["sage"], 0.35)
BODY_COLOR = mix_color(COLORS["ink_soft"], COLORS["muted"], 0.25)

TITLE_TEXT = "轻语 · 今日"
HINT_TEXT = "单击换一句 · 点红字看全文 · 拖动可移动"

TITLE_SIZE = 12
CLOSE_SIZE = 19
QUOTE_SIZE = 22
SOURCE_SIZE = 11
BODY_SIZE = 11
WESTERN_SIZE = 10
HINT_SIZE = 10

# The card may never take more than this share of the desktop.
MAX_SCREEN_WIDTH = 0.46
MAX_SCREEN_HEIGHT = 0.70
# Quote and explanation are capped so that a long line can never flood the card.
MAX_QUOTE_LINES = 3
MAX_BODY_LINES = 3
# Closing punctuation is allowed to hang past the right edge by one glyph so a
# line never begins with "。" or "，"; the card padding absorbs the overhang.
_CLOSING = "，。、；：！？）》」』】”’,.;:!?)"


def _tokens(text: str) -> list[str]:
    """Split into CJK characters and whole Latin/number words."""

    tokens: list[str] = []
    buffer = ""
    for char in text:
        if char.isascii() and (char.isalnum() or char in "-'"):
            buffer += char
            continue
        if buffer:
            tokens.append(buffer)
            buffer = ""
        tokens.append(char)
    if buffer:
        tokens.append(buffer)
    return tokens


def _ellipsize(font: tkfont.Font, line: str, max_width: int) -> str:
    """Trim ``line`` until it fits ``max_width`` together with an ellipsis."""

    suffix = "…"
    trimmed = line.rstrip().rstrip("，。、；：！？,. ;:!?")
    if font.measure(trimmed + suffix) <= max_width:
        return trimmed + suffix
    while trimmed and font.measure(trimmed + suffix) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + suffix) if trimmed else suffix


def _fit_text(font: tkfont.Font, text: str, max_width: int) -> str:
    """Shorten a single-line label so it never runs past ``max_width``."""

    if font.measure(text) <= max_width:
        return text
    return _ellipsize(font, text, max_width)


def _wrap_text(
    font: tkfont.Font,
    text: str,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Greedy wrap in device pixels, capped at ``max_lines`` with an ellipsis."""

    text = " ".join(str(text).split())
    if not text:
        return []
    max_width = max(16, int(max_width))
    tokens = _tokens(text)
    lines: list[str] = []
    current = ""
    truncated = False

    for index, token in enumerate(tokens):
        if token == " " and not current:
            continue
        overhang = (
            token in _CLOSING
            and bool(current.strip())
            and font.measure(current) <= max_width + font.measure(token)
        )
        if font.measure(current + token) <= max_width or overhang:
            current += token
            continue

        if current.strip():
            lines.append(current.rstrip())
            current = ""
            if len(lines) >= max_lines:
                truncated = any(part.strip() for part in tokens[index:])
                break

        current = "" if token == " " else token
        # A single Latin word can be wider than the card; hard-break it.
        while font.measure(current) > max_width and len(current) > 1:
            cut = len(current)
            while cut > 1 and font.measure(current[:cut]) > max_width:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
            if len(lines) >= max_lines:
                truncated = True
                break
        if truncated:
            break

    if not truncated:
        if current.strip():
            lines.append(current.rstrip())
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True

    if truncated:
        lines = lines[:max_lines] or [""]
        lines[-1] = _ellipsize(font, lines[-1], max_width)

    return lines


class FloatingWisdom:
    """A quiet, always-on-top quote card that re-flows when fonts change."""

    WIDTH = 396
    HEIGHT = 276
    TRANSPARENT_KEY = "#F2F5FB"

    def __init__(
        self,
        root: tk.Tk,
        kit: VisualKit,
        initial_index: int,
        on_quote_change: Callable[[int], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ):
        self.root = root
        self.kit = kit
        self.scale = max(0.5, float(kit.scale))
        self.font_scale = get_font_scale()
        self.index = initial_index % len(QUOTES)
        self.on_quote_change = on_quote_change
        self.on_close = on_close

        self.window = tk.Toplevel(root)
        self.window.title("栖心轻语")
        self.window.overrideredirect(True)
        self.window.configure(bg=self.TRANSPARENT_KEY)
        try:
            self.window.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
            self.window.wm_attributes("-topmost", True)
            self.window.wm_attributes("-alpha", 0.975)
        except tk.TclError:
            pass

        width = round(self.WIDTH * self.scale)
        height = round(self.HEIGHT * self.scale)
        # The canvas works in device pixels; all measurement happens with the
        # exact same pixel-sized fonts that are painted, so nothing drifts.
        self.canvas = ScaledCanvas(
            self.window,
            ui_scale=1.0,
            width=width,
            height=height,
            bg=self.TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self._drag_start: tuple[int, int, int, int] | None = None
        self._dragged = False
        self._closed = False
        self._font_cache: dict[tuple[str, int, str], tkfont.Font] = {}
        self._layout: dict[str, Any] = {}
        self._x = 0
        self._y = 0
        self._width = width
        self._height = height
        self._right_edge: int | None = None
        self._top: int | None = None
        self._card_photo: Any = None

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)


        self.relayout()

    # ------------------------------------------------------------ measuring
    def _load_font(
        self,
        size: int,
        weight: str = "normal",
        serif: bool = False,
    ) -> tuple[tkfont.Font, tuple[str, int, str]]:
        """Return a measuring font and the matching canvas font spec."""

        family = active_font_family(serif)
        pixels = max(1, round(abs(size) * self.font_scale * self.scale))
        key = (family, pixels, weight)
        loaded = self._font_cache.get(key)
        if loaded is None:
            loaded = tkfont.Font(root=self.root, family=family, size=-pixels, weight=weight)
            self._font_cache[key] = loaded
        return loaded, (family, -pixels, weight)

    def _compose(
        self,
        width: int,
        quote_cap: int,
        body_cap: int,
    ) -> dict[str, Any]:
        """Measure the whole card and return its geometry without drawing."""

        quote = quote_at(self.index)
        fs = self.font_scale
        ui = self.scale

        def gap(value: float) -> int:
            return max(1, round(value * fs * ui))

        def pad(value: float) -> int:
            return max(2, round(value * fs * ui))

        title_font, title_spec = self._load_font(TITLE_SIZE, "bold")
        close_font, close_spec = self._load_font(CLOSE_SIZE)
        quote_font, quote_spec = self._load_font(QUOTE_SIZE, serif=True)
        source_font, source_spec = self._load_font(SOURCE_SIZE)
        body_font, body_spec = self._load_font(BODY_SIZE)
        western_font, western_spec = self._load_font(WESTERN_SIZE)
        hint_font, hint_spec = self._load_font(HINT_SIZE)

        pad_x = pad(32)
        pad_top = pad(24)
        pad_bottom = pad(24)
        content_width = max(80, width - 2 * pad_x)

        title_height = title_font.metrics("linespace")
        close_height = close_font.metrics("linespace")
        row_height = max(title_height, close_height)
        dot_size = max(4, round(7 * fs * ui))
        dot_center_x = pad_x + dot_size // 2
        title_x = pad_x + dot_size + gap(11)

        quote_lines = _wrap_text(quote_font, quote["text"], content_width, quote_cap) or [
            ""
        ]
        source_text = _fit_text(source_font, f"— {quote['source']}", content_width)
        body_lines = _wrap_text(
            body_font,
            quote["explanation"],
            content_width,
            body_cap,
        ) or [""]
        western_text = str(quote.get("western", "")).strip()
        western_lines = (
            _wrap_text(
                western_font,
                f"西方视角 · {western_text}",
                content_width,
                2,
            )
            if western_text
            else []
        )
        hint_text = _fit_text(hint_font, HINT_TEXT, content_width)

        quote_line_height = quote_font.metrics("linespace")
        source_line_height = source_font.metrics("linespace")
        body_line_height = body_font.metrics("linespace")
        western_line_height = western_font.metrics("linespace")
        hint_line_height = hint_font.metrics("linespace")

        quote_top = pad_top + row_height + gap(26)
        quote_pitch = quote_line_height + gap(10)
        quote_bottom = (
            quote_top + (len(quote_lines) - 1) * quote_pitch + quote_line_height
        )

        source_top = quote_bottom + gap(18)
        source_bottom = source_top + source_line_height
        rule_y = source_bottom + gap(18)

        body_top = rule_y + 1 + gap(16)
        body_pitch = body_line_height + gap(7)
        body_bottom = body_top + (len(body_lines) - 1) * body_pitch + body_line_height

        western_top = body_bottom + gap(12)
        western_pitch = western_line_height + gap(4)
        western_bottom = (
            western_top + (len(western_lines) - 1) * western_pitch + western_line_height
            if western_lines
            else body_bottom
        )
        hint_top = western_bottom + gap(20)
        height = hint_top + hint_line_height + pad_bottom

        blocks: list[dict[str, Any]] = [
            {
                "kind": "title",
                "x": title_x,
                "y": pad_top + (row_height - title_height) // 2,
                "lines": [TITLE_TEXT],
                "pitch": title_height,
                "font": title_spec,
                "fill": COLORS["ink_soft"],
            },
            {
                "kind": "quote",
                "x": pad_x,
                "y": quote_top,
                "lines": quote_lines,
                "pitch": quote_pitch,
                "font": quote_spec,
                "fill": COLORS["ink"],
            },
            {
                "kind": "source",
                "x": pad_x,
                "y": source_top,
                "lines": [source_text],
                "pitch": source_line_height,
                "font": source_spec,
                "fill": COLORS["ink_soft"],
            },
            {
                "kind": "explanation",
                "x": pad_x,
                "y": body_top,
                "lines": body_lines,
                "pitch": body_pitch,
                "font": body_spec,
                "fill": BODY_COLOR,
            },
        ]
        if western_lines:
            blocks.append(
                {
                    "kind": "western",
                    "x": pad_x,
                    "y": western_top,
                    "lines": western_lines,
                    "pitch": western_pitch,
                    "font": western_spec,
                    "fill": COLORS["clay"],
                }
            )
        blocks.append(
            {
                "kind": "hint",
                "x": pad_x,
                "y": hint_top,
                "lines": [hint_text],
                "pitch": hint_line_height,
                "font": hint_spec,
                "fill": COLORS["sage"],
            }
        )

        return {
            "width": width,
            "height": height,
            "blocks": blocks,
            "dot": (dot_center_x, pad_top + row_height // 2, dot_size // 2),
            "rule": (pad_x, rule_y, width - pad_x, rule_y),
            "close": {
                "x": width - pad_x,
                "y": pad_top + (row_height - close_height) // 2,
                "font": close_spec,
            },
        }

    # -------------------------------------------------------------- layout
    def relayout(self) -> None:
        """Re-measure for the current font scale, resize the card and redraw."""

        self.font_scale = get_font_scale()
        fs = self.font_scale
        ui = self.scale

        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        max_width = max(160, int(screen_w * MAX_SCREEN_WIDTH) - 2)
        max_height = max(160, int(screen_h * MAX_SCREEN_HEIGHT) - 2)

        preferred = round((self.WIDTH + 92 * ((fs - 0.95) / 0.5)) * ui)
        width = max(160, min(preferred, max_width))

        # Start generous, then give back quote/explanation lines only if the
        # screen's height cap demands it.  Three lines each is the normal cap.
        candidates = (
            (MAX_QUOTE_LINES, MAX_BODY_LINES),
            (3, 2),
            (3, 1),
            (2, 2),
            (2, 1),
            (1, 1),
        )
        layout: dict[str, Any] | None = None
        for quote_cap, body_cap in candidates:
            candidate = self._compose(width, quote_cap, body_cap)
            if layout is None or candidate["height"] < layout["height"]:
                layout = candidate
            if candidate["height"] <= max_height:
                layout = candidate
                break
        assert layout is not None
        if layout["height"] > max_height:
            # Extremely small screen: keep the window legal rather than let it
            # run off the desktop.  The line caps above normally prevent this.
            layout["height"] = max_height

        self._layout = layout
        self._place(width, layout["height"])
        self._render()

    def _place(self, width: int, height: int) -> None:
        """Pin the card's right edge, then keep it on screen as it grows."""

        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        margin = max(8, round(24 * self.scale))

        if self._right_edge is None:
            right = screen_w - max(margin, round(30 * self.scale))
        else:
            right = self._right_edge
        x = right - width
        x = max(margin, x)
        x = max(margin, min(x, screen_w - margin - width))

        if self._top is None:
            y = max(margin, round(96 * self.scale))
        else:
            y = self._top
        y = max(margin, y)
        if y + height > screen_h - margin:
            y = max(margin, screen_h - margin - height)

        self._x, self._y = x, y
        self._width, self._height = width, height
        # Remember the edge, not the origin, so the card stays right-aligned
        # when a larger font makes it wider.
        self._right_edge = x + width
        self._top = y

        self.canvas.configure(width=width, height=height)
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------- drawing
    def _draw(self) -> None:
        """Repaint the card, re-flowing first if the theme fonts changed.

        ``ui.py`` calls this after a font-family or font-size change, so it has
        to re-measure rather than paint the old geometry.
        """

        if self._closed:
            return
        self.relayout()

    def _render(self) -> None:
        layout = self._layout
        self.canvas.delete("all")

        radius = max(6, round(24 * self.scale))
        self._card_photo = self.kit.rounded(
            layout["width"],
            layout["height"],
            radius,
            CARD_FILL,
            CARD_EDGE,
            1,
        )
        self.canvas.create_image(0, 0, image=self._card_photo, anchor="nw")

        dot_x, dot_y, dot_radius = layout["dot"]
        self.canvas.create_oval(
            dot_x - dot_radius,
            dot_y - dot_radius,
            dot_x + dot_radius,
            dot_y + dot_radius,
            fill=DOT_COLOR,
            outline="",
        )
        self.canvas.create_line(*layout["rule"], fill=RULE_COLOR, width=1)

        for block in layout["blocks"]:
            for offset, line in enumerate(block["lines"]):
                self.canvas.create_text(
                    block["x"],
                    block["y"] + offset * block["pitch"],
                    text=line,
                    anchor="nw",
                    fill=block["fill"],
                    font=block["font"],
                    tags=(block["kind"], "text"),
                )

        close = layout["close"]
        self.canvas.create_text(
            close["x"],
            close["y"],
            text="×",
            anchor="ne",
            fill=COLORS["muted"],
            font=close["font"],
            tags=("close", "text"),
        )
        self.canvas.tag_bind("close", "<Button-1>", self._close)

    # -------------------------------------------------------------- public
    def set_scale(self, scale: float | None = None) -> None:
        """Re-read the theme font scale (or set a new one) and re-flow."""

        if scale is not None:
            set_font_scale(scale)
        self.relayout()

    def set_quote(self, index: int) -> None:
        self.index = index % len(QUOTES)
        self.relayout()

    def next_quote(self) -> None:
        self.index = (self.index + 1) % len(QUOTES)
        self.relayout()
        if self.on_quote_change:
            self.on_quote_change(self.index)

    def show(self) -> None:
        if self._closed:
            return
        self.window.deiconify()
        self.window.lift()
        self.window.attributes("-topmost", True)

    # --------------------------------------------------------- interaction
    def _press(self, event: tk.Event[Any]) -> None:
        self._drag_start = (
            event.x_root,
            event.y_root,
            self.window.winfo_x(),
            self.window.winfo_y(),
        )
        self._dragged = False

    def _drag(self, event: tk.Event[Any]) -> None:
        if not self._drag_start:
            return
        start_x, start_y, window_x, window_y = self._drag_start
        dx = event.x_root - start_x
        dy = event.y_root - start_y
        if abs(dx) + abs(dy) > 4:
            self._dragged = True
        x = window_x + dx
        y = window_y + dy
        self._x, self._y = x, y
        self._right_edge = x + self._width
        self._top = y
        self.window.geometry(f"+{x}+{y}")

    def _release(self, _event: tk.Event[Any]) -> None:
        start = self._drag_start
        self._drag_start = None
        if start is None:
            return
        if self._dragged:
            self._dragged = False
            return
        if "close" in self.canvas.gettags("current"):
            return
        if "western" in self.canvas.gettags("current"):
            self._read_explanation()
        else:
            self.next_quote()

    def _read_explanation(self):
        show_quote_detail(self.window, quote_at(self.index))

    def _close(self, _event: tk.Event[Any] | None = None) -> str:
        if self._closed:
            return "break"
        self._closed = True
        self.window.destroy()
        if self.on_close:
            self.on_close()
        return "break"

def show_quote_detail(parent, quote):
    """Open the shared reading window beside its owner."""
    from tkinter.scrolledtext import ScrolledText

    previous = getattr(parent, "_quote_detail", None)
    if previous is not None and previous.winfo_exists():
        previous.destroy()
    dialog = tk.Toplevel(parent, bg=COLORS["card"])
    parent._quote_detail = dialog
    dialog.title("完整解读")
    dialog.transient(parent)
    screen_w, screen_h = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
    width, height = min(580, screen_w - 24), min(460, screen_h - 80)
    x = min(max(12, parent.winfo_rootx() + (parent.winfo_width() - width) // 2), screen_w - width)
    y = min(max(24, parent.winfo_rooty() + 42), screen_h - height)
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    body = ScrolledText(dialog, wrap="char", bg=COLORS["card"], fg=COLORS["ink"],
                        padx=24, pady=20, relief="flat", font=widget_font(14))
    body.pack(fill="both", expand=True)
    body.tag_configure("quote", font=widget_font(23, serif=True), spacing3=12)
    body.tag_configure("source", foreground=COLORS["muted"], spacing3=18)
    body.tag_configure("heading", foreground=COLORS["pine"], font=widget_font(13, weight="bold"), spacing1=12)
    body.insert("end", quote["text"] + "\n", "quote")
    body.insert("end", quote["source"] + "\n", "source")
    body.insert("end", "释义 · " + quote["concept"] + "\n", "heading")
    body.insert("end", quote["explanation"] + "\n")
    if quote.get("western"):
        body.insert("end", "西方视角\n", "heading")
        body.insert("end", quote["western"] + "\n")
    body.configure(state="disabled")
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    body.focus_set()
