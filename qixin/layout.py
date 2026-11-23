"""Layout helpers for a font-scale aware, content-driven UI.

The canvas layer in :mod:`qixin.theme` converts *logical* units into device
pixels with a single DPI factor. Everything in this module therefore works in
logical units: measurements are taken in device pixels and divided back by
``ui_scale`` so that page layout code can keep using the original numbers.

Text height is the only thing a hand-written absolute layout cannot guess, so
``TextMeter`` asks Tk for real font metrics and simulates wrapping. Cards then
size themselves from their content instead of from hard-coded coordinates,
which is what keeps the interface readable when the user enlarges the font.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Iterable

from .theme import active_font_family, get_font_scale


class TextMeter:
    """Measure text in logical units for the current font scale."""

    def __init__(self, root: tk.Misc, ui_scale: float, *, family: str | None = None) -> None:
        self.root = root
        self.family = family
        self.ui_scale = max(0.5, float(ui_scale))
        self._fonts: dict[tuple[int, str, bool], tkfont.Font] = {}
        self._glyph_widths: dict[tuple[int, str, bool], dict[str, int]] = {}

    # -- font objects -----------------------------------------------------
    def _font(self, size: int, weight: str = "normal", serif: bool = False) -> tkfont.Font:
        key = (int(size), weight, bool(serif))
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        # Mirror theme.font() + ScaledCanvas exactly: the font scale is applied
        # first (and rounded), then the canvas multiplies by ui_scale. Measuring
        # with a different rounding order would drift from what is rendered.
        scaled_size = max(1, round(abs(size) * get_font_scale()))
        pixels = max(1, round(scaled_size * self.ui_scale))
        loaded = tkfont.Font(
            root=self.root,
            family=self.family or active_font_family(serif),
            size=-pixels,
            weight=weight,
        )
        self._fonts[key] = loaded
        return loaded

    def invalidate(self) -> None:
        """Drop cached fonts after the global font scale or family changes."""

        self._fonts.clear()
        self._glyph_widths.clear()

    # -- metrics ----------------------------------------------------------
    def line_height(self, size: int, weight: str = "normal", serif: bool = False) -> float:
        return self._font(size, weight, serif).metrics("linespace") / self.ui_scale

    def measure(
        self,
        text: str,
        size: int,
        weight: str = "normal",
        serif: bool = False,
    ) -> float:
        if not text:
            return 0.0
        return self._font(size, weight, serif).measure(text) / self.ui_scale

    def wrap(
        self,
        text: str,
        size: int,
        width: float,
        weight: str = "normal",
        serif: bool = False,
    ) -> list[str]:
        """Break ``text`` into lines that fit ``width`` logical units.

        Chinese text wraps per character, Latin text prefers spaces; this mixed
        strategy mirrors what Tk's canvas does, closely enough for height
        estimation (the canvas still performs the real rendering wrap).
        """

        if not text:
            return []
        if width <= 0:
            return [text]
        loaded = self._font(size, weight, serif)
        # Layout probes and redraws reuse the same glyph measurements, keeping
        # wrapping from calling Tcl once per character on every page switch.
        widths = self._glyph_widths.setdefault((int(size), weight, bool(serif)), {})
        limit = width * self.ui_scale
        lines: list[str] = []
        current = ""
        current_width = 0.0
        for char in text:
            if char == "\n":
                lines.append(current)
                current = ""
                current_width = 0.0
                continue
            char_width = widths.get(char)
            if char_width is None:
                char_width = loaded.measure(char)
                widths[char] = char_width
            if current and current_width + char_width > limit:
                # Keep a trailing space with the previous line, and let Latin
                # words move down whole when possible.
                if char in "，。！？；：、）》】”’" and len(current) > 1:
                    lines.append(current[:-1])
                    current = current[-1]
                    current_width = loaded.measure(current)
                elif char not in " " and current[-1:] not in " ":
                    cut = current.rfind(" ")
                    if 0 < cut < len(current) - 1 and current[-1].isascii():
                        lines.append(current[: cut + 1].rstrip())
                        current = current[cut + 1 :]
                        current_width = loaded.measure(current)
                    else:
                        lines.append(current)
                        current = ""
                        current_width = 0.0
                else:
                    lines.append(current.rstrip())
                    current = ""
                    current_width = 0.0
            current += char
            current_width += char_width
        if current:
            lines.append(current)
        return lines

    def height(
        self,
        text: str,
        size: int,
        width: float | None = None,
        weight: str = "normal",
        serif: bool = False,
        spacing: float = 0.0,
    ) -> float:
        """Total height of ``text`` when wrapped into ``width``."""

        line_height = self.line_height(size, weight, serif)
        if not text:
            return line_height
        if width is None:
            return line_height
        lines = self.wrap(text, size, width, weight, serif)
        count = max(1, len(lines))
        return count * line_height + (count - 1) * spacing

    def natural_width(
        self,
        text: str,
        size: int,
        weight: str = "normal",
        serif: bool = False,
    ) -> float:
        return self.measure(text, size, weight, serif)

    # -- wrapping helpers -------------------------------------------------
    def chunk_into_rows(
        self,
        items: Iterable[tuple[str, float]],
        width: float,
        gap: float,
    ) -> list[list[tuple[str, float]]]:
        """Group `(label, item_width)` pairs into rows that fit ``width``."""

        rows: list[list[tuple[str, float]]] = []
        row: list[tuple[str, float]] = []
        used = 0.0
        for label, item_width in items:
            needed = item_width if not row else item_width + gap
            if row and used + needed > width:
                rows.append(row)
                row = [(label, item_width)]
                used = item_width
            else:
                row.append((label, item_width))
                used += needed
        if row:
            rows.append(row)
        return rows


def fit_text(
    meter: TextMeter,
    text: str,
    max_width: float,
    size: int,
    weight: str = "normal",
    serif: bool = False,
) -> str:
    """Shorten ``text`` with an ellipsis until it fits ``max_width``."""

    if meter.measure(text, size, weight, serif) <= max_width:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and meter.measure(trimmed + ellipsis, size, weight, serif) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


class Flow:
    """A vertical cursor that also remembers the available width."""

    def __init__(self, meter: TextMeter, x: float, y: float, width: float) -> None:
        self.meter = meter
        self.x = x
        self.y = y
        self.width = width
        self.start_y = y

    def gap(self, amount: float) -> None:
        self.y += amount

    def advance(self, amount: float) -> None:
        self.y += amount

    def text_height(
        self,
        text: str,
        size: int,
        width: float | None = None,
        weight: str = "normal",
        serif: bool = False,
        spacing: float = 0.0,
    ) -> float:
        return self.meter.height(
            text,
            size,
            self.width if width is None else width,
            weight,
            serif,
            spacing,
        )

    @property
    def used(self) -> float:
        return self.y - self.start_y


class Block:
    """A measuring/drawing cursor.

    The same body function runs twice: once with ``draw=False`` to learn how
    tall the content is, then with ``draw=True`` to render it. Cards can
    therefore grow with their text instead of relying on fixed coordinates,
    which is what keeps the UI readable at larger font scales.

    ``host`` only needs the drawing helpers of :class:`qixin.ui.QixinApp`
    (``_text``, ``_button``, ``_chip``) plus ``kit`` and ``meter``.
    """

    def __init__(
        self,
        host,
        canvas: tk.Canvas,
        x: float,
        y: float,
        width: float,
        *,
        draw: bool = True,
    ) -> None:
        self.host = host
        self.canvas = canvas
        self.x = float(x)
        self.y = float(y)
        self.width = float(width)
        self.draw = draw
        self.meter: TextMeter = host.meter
        self.kit = host.kit
        self._start = float(y)
        self._signature = 0

    # -- primitives -------------------------------------------------------
    @staticmethod
    def sz(value: float) -> float:
        return value * get_font_scale()

    def gap(self, amount: float) -> None:
        self.y += self.sz(amount)

    def reserve(self, height: float) -> None:
        self.y += self.sz(height)

    @property
    def used(self) -> float:
        return self.y - self._start

    # -- text -------------------------------------------------------------
    def text(
        self,
        text: str,
        size: int,
        color: str | None = None,
        *,
        weight: str = "normal",
        serif: bool = False,
        width: float | None = None,
        spacing: float = 0.0,
        anchor: str = "nw",
        tags: tuple[str, ...] | str | None = None,
        min_lines: int = 1,
    ) -> float:
        wrap_width = self.width if width is None else float(width)
        height = self.meter.height(
            text,
            size,
            wrap_width,
            weight,
            serif,
            self.sz(spacing),
        )
        if min_lines > 1:
            height = max(
                height,
                min_lines * self.meter.line_height(size, weight, serif),
            )
        if self.draw:
            self.host._text(
                self.canvas,
                self.x,
                self.y,
                text,
                size,
                color,
                anchor=anchor,
                weight=weight,
                serif=serif,
                width=wrap_width,
                spacing2=self.sz(spacing),
                tags=tags,
            )
        self.y += height
        return height

    def label(
        self,
        text: str,
        size: int,
        color: str | None = None,
        *,
        weight: str = "bold",
        serif: bool = False,
        spacing: float = 2.0,
        tags: tuple[str, ...] | str | None = None,
    ) -> float:
        """A one-line label that never wraps (already short by design)."""

        from .theme import COLORS as _COLORS  # local import keeps cycles out

        height = self.meter.line_height(size, weight, serif)
        if self.draw:
            self.host._text(
                self.canvas,
                self.x,
                self.y,
                text,
                size,
                color or _COLORS["sage"],
                weight=weight,
                serif=serif,
                anchor="nw",
                tags=tags,
            )
        self.y += height + self.sz(spacing)
        return height + self.sz(spacing)

    def divider(self, color: str | None = None, inset: float = 0.0) -> None:
        from .theme import COLORS as _COLORS

        if self.draw:
            self.canvas.create_line(
                self.x + self.sz(inset),
                self.y,
                self.x + self.width - self.sz(inset),
                self.y,
                fill=color or _COLORS["line"],
                width=1,
            )
        self.y += self.sz(1)

    # -- interactive ------------------------------------------------------
    def chip(
        self,
        tag: str,
        text: str,
        selected: bool,
        command,
        *,
        color: str | None = None,
        size: int = 11,
        x: float | None = None,
        width: float | None = None,
        height: float | None = None,
    ) -> float:
        chip_height = self.sz(height if height is not None else 28)
        text_width = self.meter.measure(text, size, "bold" if selected else "normal")
        chip_width = width if width is not None else text_width + self.sz(26)
        left = self.x if x is None else x
        if self.draw:
            self.host._chip(
                self.canvas,
                tag,
                left,
                self.y,
                left + chip_width,
                self.y + chip_height,
                text,
                selected,
                command,
                color,
                size,
            )
        return chip_width

    def chip_rows(
        self,
        entries: list[tuple[str, str, bool, object]],
        *,
        color: str | None = None,
        size: int = 11,
        gap: float = 8.0,
        row_gap: float = 8.0,
        min_width: float = 0.0,
    ) -> float:
        """Lay out ``(tag, label, selected, command)`` chips into wrapped rows."""

        if not entries:
            return 0.0
        measured: list[tuple[str, str, bool, object, float, str | None]] = []
        for entry in entries:
            if len(entry) >= 5:
                tag, label, selected, command, item_color = entry[0], entry[1], entry[2], entry[3], entry[4]
            else:
                tag, label, selected, command = entry[0], entry[1], entry[2], entry[3]
                item_color = color
            text_width = self.meter.measure(
                label, size, "bold" if selected else "normal"
            )
            measured.append(
                (
                    tag,
                    label,
                    selected,
                    command,
                    max(min_width, text_width + self.sz(26)),
                    item_color,
                )
            )
        row_gap_px = self.sz(row_gap)
        gap_px = self.sz(gap)
        rows: list[list[tuple[str, str, bool, object, float, str | None]]] = []
        row: list[tuple[str, str, bool, object, float, str | None]] = []
        used = 0.0
        for item in measured:
            needed = item[4] if not row else item[4] + gap_px
            if row and used + needed > self.width:
                rows.append(row)
                row = [item]
                used = item[4]
            else:
                row.append(item)
                used += needed
        if row:
            rows.append(row)

        chip_height = self.sz(28)
        start_y = self.y
        for index, row_items in enumerate(rows):
            cursor = self.x
            for tag, label, selected, command, chip_width, item_color in row_items:
                if self.draw:
                    self.host._chip(
                        self.canvas,
                        tag,
                        cursor,
                        self.y,
                        cursor + chip_width,
                        self.y + chip_height,
                        label,
                        selected,
                        command,
                        item_color,
                        size,
                    )
                cursor += chip_width + gap_px
            self.y += chip_height
            if index < len(rows) - 1:
                self.y += row_gap_px
        return self.y - start_y

    def button(
        self,
        tag: str,
        text: str,
        command,
        *,
        style: str = "secondary",
        size: int = 11,
        height: float = 36,
        width: float | None = None,
        radius: float = 14,
        prefix: str = "",
        x: float | None = None,
    ) -> float:
        button_height = self.sz(height)
        button_width = self.width if width is None else width
        left = self.x if x is None else x
        if self.draw:
            self.host._button(
                self.canvas,
                tag,
                left,
                self.y,
                left + button_width,
                self.y + button_height,
                text,
                command,
                style,
                size,
                round(self.sz(radius)),
                prefix,
            )
        self.y += button_height
        return button_height

    def row(self, height: float) -> tuple[float, float]:
        """Reserve a fixed-height band and return its top/bottom."""

        top = self.y
        self.y += self.sz(height)
        return top, self.y

    def button_at(
        self,
        tag: str,
        text: str,
        command,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        style: str = "secondary",
        size: int = 11,
        radius: float = 12,
        prefix: str = "",
    ) -> None:
        if not self.draw:
            return
        self.host._button(
            self.canvas,
            tag,
            x,
            y,
            x + width,
            y + height,
            text,
            command,
            style,
            size,
            round(self.sz(radius)),
            prefix,
        )

    def button_right(
        self,
        tag: str,
        text: str,
        command,
        *,
        style: str = "ghost",
        size: int = 10,
        height: float = 26,
        y: float | None = None,
        prefix: str = "",
        radius: float = 11,
        pad: float = 24,
    ) -> float:
        """Place a compact button on the right edge; returns its width."""

        label = (prefix + " " if prefix else "") + text
        button_width = self.meter.measure(label, size, "bold") + self.sz(pad)
        top = self.y if y is None else y
        left = self.x + self.width - button_width
        self.button_at(
            tag,
            text,
            command,
            left,
            top,
            button_width,
            self.sz(height),
            style=style,
            size=size,
            radius=radius,
            prefix=prefix,
        )
        return button_width


def card_height(
    host,
    canvas: tk.Canvas,
    x: float,
    y: float,
    width: float,
    body,
    *,
    pad_x: float = 20,
    pad_y: float = 18,
) -> tuple[float, float, float]:
    """Measure ``body`` then return (content_x, content_y, card_height)."""

    scale = get_font_scale()
    inner_x = x + pad_x * scale
    inner_y = y + pad_y * scale
    inner_width = width - 2 * pad_x * scale
    probe = Block(host, canvas, inner_x, inner_y, inner_width, draw=False)
    body(probe)
    total = probe.used + 2 * pad_y * scale
    return inner_x, inner_y, total

