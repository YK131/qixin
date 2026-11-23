"""Pointer-driven motion for the 栖心 canvas UI.

Tk has no animation primitives, so this module keeps three small pieces of
state and repaints *only* what the pointer touches:

``Surface``
    A rounded control (button, chip, nav row).  Hover brightens the fill and
    slides a soft highlight towards the cursor; pressing compresses the pill.
``CardHover``
    Swaps a card between its resting and lifted shadow.  The two images are
    pre-rendered by :class:`~qixin.theme.VisualKit`, so hover costs one
    ``itemconfigure``.
``PointerLight``
    A large, very soft light that eases towards the cursor.  It sits above the
    page backdrop and below the cards, which is what makes the light look like
    it is sliding *under* the interface.

Pointer effects share a timer that stops when the pointer rests. Short state
transitions also stop scheduling frames as soon as they settle.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Any, Callable

from .theme import COLORS, VisualKit, mix_color, rgba


class Tween:
    """A cancellable, time-based transition that drops late frames."""

    def __init__(
        self, widget: tk.Misc, duration_ms: int, update: Callable[[float], None],
        finish: Callable[[], None] | None = None,
    ) -> None:
        self.widget = widget
        self.duration = duration_ms / 1000
        self.update = update
        self.finish = finish
        self.started: float | None = None
        self.update(0.0)
        self.job: str | None = self.widget.after(16, self.step)

    def step(self) -> None:
        self.job = None
        now = time.perf_counter()
        if self.started is None:
            self.started = now
        progress = min(1.0, (now - self.started) / self.duration)
        self.update(1 - (1 - progress) ** 3)
        if progress < 1:
            self.job = self.widget.after(16, self.step)
        elif self.finish:
            self.finish()

    def cancel(self) -> None:
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None


def _luminance(color: str) -> float:
    value = color.lstrip("#")
    r = int(value[0:2], 16) / 255
    g = int(value[2:4], 16) / 255
    b = int(value[4:6], 16) / 255
    return 0.299 * r + 0.587 * g + 0.114 * b


def _blend_fill(start: str, end: str, progress: float) -> str:
    color = mix_color(start, end, progress)
    if len(start) == 9 or len(end) == 9:
        opacity = round(rgba(start)[3] * (1 - progress) + rgba(end)[3] * progress)
        color += f"{opacity:02X}"
    return color


class Surface:
    """An animated rounded surface backed by one canvas image item."""

    def __init__(
        self,
        engine: "MotionEngine",
        canvas: tk.Canvas,
        item: int,
        box: tuple[float, float, float, float],
        radius: float,
        fill: str,
        fill2: str | None = None,
        outline: str | None = None,
        outline_width: int = 1,
        *,
        hover_fill: str | None = None,
        hover_outline: str | None = None,
        sheen_color: str | None = None,
        sheen_strength: float = 0.55,
        highlight: float = 0.0,
        press_scale: float = 0.045,
    ) -> None:
        self.engine = engine
        self.canvas = canvas
        self.item = item
        self.box = box
        self.radius = max(0.0, float(radius))
        self.fill = fill
        self.fill2 = fill2
        self.outline = outline
        self.outline_width = max(1, int(outline_width))
        self.press_scale = max(0.0, press_scale)

        dark = _luminance(fill) < 0.52
        self.hover_fill = hover_fill or (
            mix_color(fill, "#FFFFFF", 0.12) if dark else mix_color(fill, COLORS["iris"], 0.055)
        )
        if self.fill2:
            self.hover_fill2 = (
                mix_color(self.fill2, "#FFFFFF", 0.12)
                if dark
                else mix_color(self.fill2, COLORS["iris"], 0.055)
            )
        else:
            self.hover_fill2 = None
        self.hover_outline = hover_outline or (
            None if dark or not outline else mix_color(outline, COLORS["iris"], 0.35)
        )
        self.sheen_color = sheen_color or ("#FFFFFF" if dark else COLORS["iris"])
        self.sheen_strength = max(0.0, min(1.0, sheen_strength))
        if highlight <= 0 and dark:
            highlight = 0.9
        self.highlight = highlight

        self.hover = 0.0
        self.press = 0.0
        self.hover_target = 0.0
        self.press_target = 0.0
        self.pointer: tuple[float, float] | None = None
        self.ripple = 0.0
        self.ripple_active = False
        self.ripple_xy: tuple[float, float] | None = None
        self._photo: Any = None
        self._dirty = True
        self._draw_accum = 0.0
        self._redraw()

    # -- state ------------------------------------------------------------
    @property
    def alive(self) -> bool:
        try:
            return bool(self.canvas.type(self.item))
        except tk.TclError:
            return False

    def contains(self, x: float, y: float) -> bool:
        x1, y1, x2, y2 = self.box
        return x1 <= x <= x2 and y1 <= y <= y2

    def set_hover(self, hovering: bool) -> None:
        target = 1.0 if hovering else 0.0
        if target != self.hover_target:
            self.hover_target = target
            self._dirty = True
            self.engine.wake()

    def set_pointer(self, x: float, y: float) -> None:
        if self.pointer is None or abs(x - self.pointer[0]) > 2.0 or abs(y - self.pointer[1]) > 2.0:
            self.pointer = (x, y)
            self._dirty = True
            self.engine.wake()

    def press_now(self) -> None:
        self.press_target = 1.0
        self.ripple = 0.0
        self.ripple_active = True
        self.ripple_xy = self.pointer or (
            (self.box[0] + self.box[2]) / 2,
            (self.box[1] + self.box[3]) / 2,
        )
        self.engine.wake()

    def release_now(self) -> None:
        if self.press_target:
            self.press_target = 0.0
            self.engine.wake()

    # -- animation --------------------------------------------------------
    def advance(self, dt: float) -> bool:
        busy = False
        for name, target in (("hover", self.hover_target), ("press", self.press_target)):
            value = getattr(self, name)
            if abs(value - target) > 0.004:
                step = 1.0 - math.exp(-dt / 0.075)
                setattr(self, name, value + (target - value) * step)
                busy = True
                self._dirty = True
            elif value != target:
                setattr(self, name, target)
                self._dirty = True
        if self.ripple_active:
            self.ripple += dt / 0.34
            if self.ripple >= 1.0:
                self.ripple = 0.0
                self.ripple_active = False
            self._dirty = True
            busy = True
        if self._dirty:
            # Rebuilding a pill costs a few milliseconds; 30fps is enough for
            # a soft fade and leaves the UI thread room to scroll smoothly.
            self._draw_accum += dt
            if self._draw_accum >= 0.028 or not busy:
                self._draw_accum = 0.0
                if self.alive:
                    self._redraw()
                self._dirty = False
        return busy or self.ripple_active

    def _redraw(self) -> None:
        scale = self.engine.scale
        x1, y1, x2, y2 = self.box
        inset = round(self.press * self.press_scale * (y2 - y1) * scale)
        width = max(4, round((x2 - x1) * scale) - inset * 2)
        height = max(4, round((y2 - y1) * scale) - inset * 2)
        radius = round(self.radius * scale)

        hover = self.hover
        fill = _blend_fill(self.fill, self.hover_fill, hover) if hover > 0.004 else self.fill
        fill2 = None
        if self.fill2:
            fill2 = mix_color(self.fill2, self.hover_fill2 or self.fill2, hover) if hover > 0.004 else self.fill2
        outline = self.outline
        if hover > 0.004 and self.hover_outline:
            outline = mix_color(self.outline or self.hover_outline, self.hover_outline, hover)
        if hover > 0.004 and self.press > 0.004:
            fill = _blend_fill(fill, f"#0B1020{fill[7:]}", 0.06 * self.press)
            if fill2:
                fill2 = mix_color(fill2, "#0B1020", 0.06 * self.press)

        sheen_xy = None
        strength = 0.0
        if self.pointer is not None and hover > 0.004:
            sheen_xy = ((self.pointer[0] - x1) * scale - inset, (self.pointer[1] - y1) * scale - inset)
            strength = hover * self.sheen_strength

        ripple_xy = None
        ripple = 0.0
        if self.ripple_active and self.ripple_xy is not None:
            ripple_xy = (
                (self.ripple_xy[0] - x1) * scale - inset,
                (self.ripple_xy[1] - y1) * scale - inset,
            )
            ripple = self.ripple

        photo = self.engine.kit.pill_face(
            width,
            height,
            radius,
            fill,
            fill2,
            outline,
            max(1, round(self.outline_width * scale)),
            sheen_xy=sheen_xy,
            sheen=strength,
            sheen_color=self.sheen_color,
            highlight=self.highlight * hover,
            ripple_xy=ripple_xy,
            ripple=ripple,
            cache=hover <= 0.004 and not self.ripple_active,
        )
        try:
            tk.Canvas.coords(
                self.canvas,
                self.item,
                round(x1 * scale) + inset,
                round(y1 * scale) + inset,
            )
            self.canvas.itemconfigure(self.item, image=photo)
        except tk.TclError:
            return
        self._photo = photo


class CardHover:
    """Lifts a card shadow when the pointer is over it."""

    def __init__(
        self,
        engine: "MotionEngine",
        canvas: tk.Canvas,
        item: int,
        box: tuple[float, float, float, float],
        radius: float,
        fill: str,
        outline: str | None,
        outline_width: int,
    ) -> None:
        self.engine = engine
        self.canvas = canvas
        self.item = item
        self.box = box
        self.radius = radius
        self.fill = fill
        self.outline = outline
        self.outline_width = outline_width
        self.hovering = False
        self._photo: Any = None

    @property
    def alive(self) -> bool:
        try:
            return bool(self.canvas.type(self.item))
        except tk.TclError:
            return False

    def contains(self, x: float, y: float) -> bool:
        x1, y1, x2, y2 = self.box
        return x1 <= x <= x2 and y1 <= y <= y2

    def set_hover(self, hovering: bool) -> None:
        if hovering == self.hovering or not self.alive:
            return
        self.hovering = hovering
        x1, y1, x2, y2 = self.box
        scale = self.engine.scale
        photo = self.engine.kit.card_face(
            round((x2 - x1) * scale),
            round((y2 - y1) * scale),
            max(1, round(self.radius * scale)),
            self.fill,
            self.outline,
            max(1, round(self.outline_width * scale)),
            hover=hovering,
        )
        try:
            self.canvas.itemconfigure(self.item, image=photo)
        except tk.TclError:
            return
        self._photo = photo


class PointerLight:
    """A soft light that eases towards the pointer inside a canvas."""

    def __init__(
        self,
        engine: "MotionEngine",
        canvas: tk.Canvas,
        item: int,
        size: float,
        bounds: tuple[float, float, float, float],
    ) -> None:
        self.engine = engine
        self.canvas = canvas
        self.item = item
        self.size = max(32.0, float(size))
        self.bounds = bounds
        x1, y1, x2, y2 = bounds
        self.x = (x1 + x2) / 2
        self.y = (y1 + y2) / 2
        self.tx = self.x
        self.ty = self.y
        self._apply()

    @property
    def alive(self) -> bool:
        try:
            return bool(self.canvas.type(self.item))
        except tk.TclError:
            return False

    @property
    def moving(self) -> bool:
        return abs(self.tx - self.x) > 0.6 or abs(self.ty - self.y) > 0.6

    def target(self, x: float, y: float) -> None:
        x1, y1, x2, y2 = self.bounds
        half = self.size / 2
        self.tx = min(max(x, x1 + half), x2 - half) if x2 - x1 > half * 2 else (x1 + x2) / 2
        self.ty = min(max(y, y1 + half), y2 - half) if y2 - y1 > half * 2 else (y1 + y2) / 2
        self.engine.wake()

    def advance(self, dt: float) -> bool:
        if not self.alive:
            return False
        dx = self.tx - self.x
        dy = self.ty - self.y
        if abs(dx) < 0.6 and abs(dy) < 0.6:
            if dx or dy:
                self.x, self.y = self.tx, self.ty
                self._apply()
            return False
        step = 1.0 - math.exp(-dt / 0.13)
        self.x += dx * step
        self.y += dy * step
        self._apply()
        return True

    def _apply(self) -> None:
        try:
            tk.Canvas.coords(
                self.canvas,
                self.item,
                round(self.x * self.engine.scale),
                round(self.y * self.engine.scale),
            )
        except tk.TclError:
            pass


class MotionEngine:
    """Registry + timer shared by every canvas in one window."""

    TICK_MS = 16
    MAX_TICK_MS = 48
    #: Pointer-following highlights are coalesced to ~30fps. Rebuilding a
    #: sheen at 60fps was the main source of stutter while the mouse moved.
    POINTER_INTERVAL = 0.030
    LIGHT_INTERVAL = 0.034

    def __init__(self, root: tk.Misc, kit: VisualKit, scale: float) -> None:
        self.root = root
        self.kit = kit
        self.scale = max(0.5, float(scale))
        self._surfaces: list[Surface] = []
        self._cards: list[CardHover] = []
        self._lights: list[PointerLight] = []
        self._attached: list[tk.Canvas] = []
        self._hover_surface: Surface | None = None
        self._hover_card: CardHover | None = None
        self._job: str | None = None
        self._last = time.perf_counter()
        self._last_pointer = 0.0
        self._last_light = 0.0
        self._pending_motion: tuple[tk.Canvas, float, float] | None = None
        self._scrolling: set[tk.Canvas] = set()
        self._in_tick = False
        self._closed = False
        self._tweens: dict[tuple[tk.Canvas, str], Tween] = {}

    # -- lifecycle -------------------------------------------------------
    def attach(self, canvas: tk.Canvas) -> None:
        if any(existing is canvas for existing in self._attached):
            return
        self._attached.append(canvas)
        canvas.bind(
            "<Motion>",
            lambda event, target=canvas: self._on_motion(target, event),
            add="+",
        )
        canvas.bind(
            "<Leave>",
            lambda event, target=canvas: self._on_leave(target),
            add="+",
        )
        canvas.bind(
            "<ButtonRelease-1>",
            lambda event, target=canvas: self._release_stuck(target),
            add="+",
        )

    def forget_items(self, canvas, items):
        def removed(control):
            return control is not None and control.canvas is canvas and control.item in items

        for controls in (self._surfaces, self._cards, self._lights):
            controls[:] = [control for control in controls if not removed(control)]
        if removed(self._hover_card):
            self._hover_card = None
        if removed(self._hover_surface):
            self._hover_surface = None

    def begin(self, canvas: tk.Canvas) -> None:
        """Drop stale registrations before a canvas is re-rendered."""

        self._surfaces = [s for s in self._surfaces if s.canvas is not canvas]
        self._cards = [c for c in self._cards if c.canvas is not canvas]
        self._lights = [light for light in self._lights if light.canvas is not canvas]
        self._clear_pending_motion(canvas)
        self._scrolling.discard(canvas)
        for key in tuple(self._tweens):
            if key[0] is canvas:
                self._tweens.pop(key).cancel()
        if self._hover_surface is not None and self._hover_surface.canvas is canvas:
            self._hover_surface = None
        if self._hover_card is not None and self._hover_card.canvas is canvas:
            self._hover_card = None

    def shutdown(self) -> None:
        self._closed = True
        for tween in self._tweens.values():
            tween.cancel()
        self._tweens.clear()
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        self._surfaces.clear()
        self._cards.clear()
        self._lights.clear()
        self._scrolling.clear()
        self._pending_motion = None

    def animate(
        self, canvas: tk.Canvas, name: str, duration_ms: int,
        update: Callable[[float], None], finish: Callable[[], None] | None = None,
    ) -> None:
        key = (canvas, name)
        previous = self._tweens.pop(key, None)
        if previous is not None:
            previous.cancel()

        def completed() -> None:
            self._tweens.pop(key, None)
            if finish:
                finish()

        self._tweens[key] = Tween(self.root, duration_ms, update, completed)

    def fade_text(
        self, canvas: tk.Canvas, tag: str, duration_ms: int, background: str,
    ) -> None:
        fills = {item: canvas.itemcget(item, "fill") for item in canvas.find_withtag(tag)}
        if not fills:
            return

        def paint(progress: float) -> None:
            for item, fill in fills.items():
                canvas.itemconfigure(item, fill=mix_color(background, fill, 0.12 + 0.88 * progress))

        self.animate(canvas, tag, duration_ms, paint)

    def slide_item(
        self, canvas: tk.Canvas, tag: str, start: list[float], duration_ms: int,
    ) -> None:
        target = canvas.coords(tag)
        if len(start) != 2 or len(target) != 2 or start == target:
            return

        def paint(progress: float) -> None:
            x, y = (a + (b - a) * progress for a, b in zip(start, target))
            tk.Canvas.coords(canvas, tag, round(x), round(y))

        self.animate(canvas, tag, duration_ms, paint)

    # -- registration ----------------------------------------------------
    def add_surface(self, *args: Any, **kwargs: Any) -> Surface:
        surface = Surface(self, *args, **kwargs)
        self._surfaces.append(surface)
        return surface

    def add_card(self, *args: Any, **kwargs: Any) -> CardHover:
        card = CardHover(self, *args, **kwargs)
        self._cards.append(card)
        return card

    def add_light(
        self,
        canvas: tk.Canvas,
        size: float,
        color: str,
        bounds: tuple[float, float, float, float],
        *,
        alpha: int = 34,
        below_tag: str | None = "page_bg",
        disabled: bool = True,
    ) -> PointerLight | None:
        size_px = max(64, round(size * self.scale))
        try:
            photo = self.kit.light_sprite(size_px, color, alpha=alpha)
            item = tk.Canvas.create_image(
                canvas,
                round(bounds[0] * self.scale),
                round(bounds[1] * self.scale),
                image=photo,
                anchor="center",
            )
            if disabled:
                # A disabled canvas item never becomes the "current" item, so
                # a full-page light cannot steal clicks from cards or controls.
                tk.Canvas.itemconfigure(canvas, item, state="disabled")
        except tk.TclError:
            return None
        if below_tag:
            try:
                if canvas.find_withtag(below_tag):
                    canvas.tag_raise(item, below_tag)
            except tk.TclError:
                pass
        light = PointerLight(self, canvas, item, size, bounds)
        self._lights = [existing for existing in self._lights if existing.alive]
        self._lights.append(light)
        # The photo must outlive the item; keep it on the light.
        light._photo = photo  # type: ignore[attr-defined]
        return light

    # -- pointer ---------------------------------------------------------
    def _to_logical(self, canvas: tk.Canvas, event: tk.Event[Any]) -> tuple[float, float]:
        try:
            x = canvas.canvasx(event.x) / self.scale
            y = canvas.canvasy(event.y) / self.scale
        except tk.TclError:
            return 0.0, 0.0
        return float(x), float(y)

    def _on_motion(self, canvas: tk.Canvas, event: tk.Event[Any]) -> None:
        if self._closed or canvas in self._scrolling:
            return
        x, y = self._to_logical(canvas, event)
        # Coalesce the OS motion stream; the timer picks the latest position.
        self._pending_motion = (canvas, x, y)
        self.wake()

    def _dispatch_motion(self, canvas: tk.Canvas, x: float, y: float) -> None:
        hovered: Surface | None = None
        for surface in self._surfaces:
            if surface.canvas is not canvas or not surface.contains(x, y):
                continue
            if not surface.alive:
                continue
            hovered = surface  # later items are drawn on top
        if hovered is not self._hover_surface:
            if self._hover_surface is not None:
                self._hover_surface.set_hover(False)
            self._hover_surface = hovered
            if hovered is not None:
                hovered.set_hover(True)
        if hovered is not None:
            hovered.set_pointer(x, y)

        card: CardHover | None = None
        for candidate in self._cards:
            if candidate.canvas is not canvas or not candidate.contains(x, y):
                continue
            if not candidate.alive:
                continue
            card = candidate
        if card is not self._hover_card:
            if self._hover_card is not None:
                self._hover_card.set_hover(False)
            self._hover_card = card
            if card is not None:
                card.set_hover(True)

        for light in self._lights:
            if light.canvas is canvas:
                light.target(x, y)
        self.wake()

    def _on_leave(self, canvas: tk.Canvas) -> None:
        self._clear_pending_motion(canvas)
        self.reset_hover(canvas)
        self._release_stuck(canvas)

    def _clear_pending_motion(self, canvas: tk.Canvas) -> None:
        if self._pending_motion is not None and self._pending_motion[0] is canvas:
            self._pending_motion = None

    def reset_hover(self, canvas: tk.Canvas) -> None:
        if self._hover_surface is not None and self._hover_surface.canvas is canvas:
            self._hover_surface.set_hover(False)
            self._hover_surface = None
        if self._hover_card is not None and self._hover_card.canvas is canvas:
            self._hover_card.set_hover(False)
            self._hover_card = None

    def _release_stuck(self, canvas: tk.Canvas) -> None:
        for surface in self._surfaces:
            if surface.canvas is canvas:
                surface.release_now()

    def set_scrolling(self, canvas: tk.Canvas, scrolling: bool) -> None:
        if scrolling:
            self._scrolling.add(canvas)
            self._clear_pending_motion(canvas)
            self.reset_hover(canvas)
        else:
            self._scrolling.discard(canvas)

        # The decorative light is expensive to composite and must never
        # become the canvas' current item when it is restored.
        if not scrolling:
            self.wake()
        state = "hidden" if scrolling else "disabled"
        for light in self._lights:
            if light.canvas is canvas and light.alive:
                light.canvas.itemconfigure(light.item, state=state)

    # -- timer -----------------------------------------------------------
    def wake(self) -> None:
        if self._closed or self._job is not None or self._in_tick:
            return
        now = time.perf_counter()
        dt = min(self.MAX_TICK_MS / 1000.0, max(0.001, now - self._last))
        self._last = now
        try:
            self._job = self.root.after(self.TICK_MS, lambda: self._tick(dt))
        except tk.TclError:
            self._job = None

    def _tick(self, dt: float) -> None:
        self._job = None
        self._in_tick = True
        if self._closed:
            self._in_tick = False
            return
        now = time.perf_counter()
        dt = min(self.MAX_TICK_MS / 1000.0, max(0.001, now - self._last))
        self._last = now

        pending = self._pending_motion
        if pending is not None and (now - self._last_pointer) >= self.POINTER_INTERVAL:
            self._pending_motion = None
            self._last_pointer = now
            self._dispatch_motion(*pending)
        moving_light = (now - self._last_light) >= self.LIGHT_INTERVAL
        if moving_light:
            self._last_light = now

        busy = False
        for surface in self._surfaces:
            if surface.canvas not in self._scrolling:
                busy = surface.advance(dt) or busy
        for light in list(self._lights):
            if light.canvas in self._scrolling:
                continue
            if not light.alive:
                self._lights.remove(light)
                continue
            if moving_light:
                busy = light.advance(dt * 2.2) or busy
            elif light.moving:
                busy = True
        pending = self._pending_motion is not None
        self._in_tick = False
        if busy or pending:
            if self._job is not None:
                try:
                    self.root.after_cancel(self._job)
                except tk.TclError:
                    pass
                self._job = None
            try:
                self._job = self.root.after(self.TICK_MS, lambda: self._tick(dt))
            except tk.TclError:
                self._job = None
