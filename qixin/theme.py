"""Visual system for 栖心.

The interface is drawn on Tk canvases, so every "material" in the app is a
Pillow image: rounded surfaces, layered shadows, graded fills, aurora panels and
soft light.  This module owns that vocabulary and caches the expensive parts so
pages can be re-rendered on every interaction without stuttering.

The main window layers translucent surfaces over a cached frosted backdrop.
Dimensions are logical units multiplied by the DPI factor for crisp rendering.
"""

from __future__ import annotations

import ctypes
import math
import random
import sys
import tkinter as tk
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk


# --------------------------------------------------------------------- palette

COLORS = {
    # Warm base and frosted surfaces. Glass tokens use RGBA for Pillow.
    "paper": "#E9EBE3",
    "paper_deep": "#DEE6DB",
    "card": "#FFFEFA",
    "card_alt": "#F3F5EE",
    "sunken": "#EAEEE7",
    "line": "#D7DED3",
    "hairline": "#E1E6DC",
    "glass": "#F5F9EEC5",
    "glass_edge": "#FFFFFFBC",
    "ink": "#202C26",
    "ink_soft": "#41524A",
    "muted": "#5D6C62",
    "pine": "#285040",
    "pine_light": "#35644F",
    "pine_soft": "#48765F",
    "iris": "#4E7568",
    "iris_soft": "#E4EFE9",
    "sage": "#3F6B55",
    "sage_soft": "#DCEBE1",
    "clay": "#914F3D",
    "clay_soft": "#F5E6DE",
    "gold": "#8A6A32",
    "gold_soft": "#F3EBDA",
    "blue": "#43657C",
    "blue_soft": "#E7EDF0",
    "peach_soft": "#F5EADF",
    "white": "#FFFFFF",
    "shadow": "#2A4536",
}

RADII = {
    "backdrop": 34.0,
    "hero": 25.0,
    "card": 32.0,
    "content_card": 24.0,
    "panel": 32.0,
    "input": 13.0,
    "row": 14.0,
    "pill": 999.0,
}

AURORA = ("#8FAE9B", "#6E9C89", "#D5A776")


if sys.platform == "win32":
    DEFAULT_FONT_SANS, DEFAULT_FONT_SERIF = "Microsoft YaHei UI", "SimSun"
elif sys.platform == "darwin":
    DEFAULT_FONT_SANS, DEFAULT_FONT_SERIF = "PingFang SC", "Songti SC"
else:
    DEFAULT_FONT_SANS, DEFAULT_FONT_SERIF = "Noto Sans CJK SC", "Noto Serif CJK SC"
FONT_SANS = DEFAULT_FONT_SANS
FONT_SERIF = DEFAULT_FONT_SERIF
FONT_BOOST = 1.14

_ACTIVE_SANS = DEFAULT_FONT_SANS
_ACTIVE_SERIF = DEFAULT_FONT_SERIF
_ACTIVE_FONT_SCALE = FONT_BOOST


def enable_high_dpi() -> None:
    """Opt into native DPI rendering before Tk creates its first window."""

    if sys.platform != "win32":
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def detect_ui_scale(root: tk.Misc) -> float:
    """Return a crisp render scale that also keeps the window on screen."""

    try:
        dpi_scale = float(root.winfo_fpixels("1i")) / 96.0
    except (tk.TclError, ValueError):
        dpi_scale = 1.0
    dpi_scale = max(1.0, min(2.25, dpi_scale))
    width_cap = root.winfo_screenwidth() / 1700
    height_cap = root.winfo_screenheight() / 1080
    viewport_scale = max(0.65, min(width_cap, height_cap))
    return round(min(dpi_scale, viewport_scale), 3)


def active_font_family(serif: bool = False) -> str:
    return _ACTIVE_SERIF if serif else _ACTIVE_SANS


def set_font_family(family: str) -> None:
    global _ACTIVE_SANS, _ACTIVE_SERIF
    family = family.strip()
    if family:
        _ACTIVE_SANS = family
        _ACTIVE_SERIF = family


def reset_font_family() -> None:
    global _ACTIVE_SANS, _ACTIVE_SERIF
    _ACTIVE_SANS = DEFAULT_FONT_SANS
    _ACTIVE_SERIF = DEFAULT_FONT_SERIF


def set_font_scale(scale: float | str) -> float:
    global _ACTIVE_FONT_SCALE
    try:
        value = float(scale)
    except (TypeError, ValueError):
        value = FONT_BOOST
    _ACTIVE_FONT_SCALE = min(1.6, max(0.9, value))
    return _ACTIVE_FONT_SCALE


def get_font_scale() -> float:
    return _ACTIVE_FONT_SCALE


def font(size: int, weight: str = "normal", serif: bool = False) -> tuple[str, int, str]:
    return active_font_family(serif), -round(abs(size) * _ACTIVE_FONT_SCALE), weight


def scaled(value: float) -> float:
    """Scale a logical dimension by the user's font scale.

    Text is already scaled inside :func:`font`; icons, paddings and gaps must
    follow the same factor so a larger font never ends up cramped inside
    shapes that stayed small.
    """

    return value * _ACTIVE_FONT_SCALE


def widget_font(
    size: int,
    ui_scale: float = 1.0,
    weight: str = "normal",
    serif: bool = False,
) -> tuple[str, int, str]:
    return (
        active_font_family(serif),
        -round(abs(size) * ui_scale * _ACTIVE_FONT_SCALE),
        weight,
    )


class ScaledCanvas(tk.Canvas):
    """A Canvas whose public drawing API accepts logical coordinates."""

    SHAPE_METHODS = (
        "create_arc",
        "create_line",
        "create_oval",
        "create_polygon",
        "create_rectangle",
    )

    def __init__(self, master: tk.Misc, *, ui_scale: float = 1.0, **kwargs: Any):
        self.ui_scale = ui_scale
        super().__init__(master, **kwargs)

        self._tag_callbacks: dict[tuple[int | str, str], list[str]] = {}

    def tag_bind(self, tag_or_id, sequence=None, func=None, add=None):
        key = (tag_or_id, sequence)
        if func is not None and not add and key in self._tag_callbacks:
            self.tag_unbind(tag_or_id, sequence)
        callback = super().tag_bind(tag_or_id, sequence, func, add)
        if callable(func) and callback:
            self._tag_callbacks.setdefault(key, []).append(callback)
        return callback

    def tag_unbind(self, tag_or_id, sequence, funcid=None):
        key = (tag_or_id, sequence)
        callbacks = self._tag_callbacks.get(key, [])
        if funcid is None:
            super().tag_unbind(tag_or_id, sequence)
            for callback in self._tag_callbacks.pop(key, []):
                self.deletecommand(callback)
        else:
            super().tag_unbind(tag_or_id, sequence, funcid)
            if funcid in callbacks:
                callbacks.remove(funcid)
                if not callbacks:
                    self._tag_callbacks.pop(key, None)

    def clear_scene(self) -> None:
        """Release item callbacks as well as items when replacing a scene."""

        for tag, sequence in tuple(self._tag_callbacks):
            self.tag_unbind(tag, sequence)
        self.delete("all")
        self.configure(cursor="")

    def _px(self, value: Any) -> Any:
        if isinstance(value, (int, float)):
            return round(float(value) * self.ui_scale)
        return value

    def _coords(self, values: tuple[Any, ...]) -> tuple[Any, ...]:
        scaled: list[Any] = []
        for value in values:
            if isinstance(value, (tuple, list)):
                scaled.append(tuple(self._px(item) for item in value))
            else:
                scaled.append(self._px(value))
        return tuple(scaled)

    def _scaled_options(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(kwargs)
        if isinstance(options.get("width"), (int, float)):
            options["width"] = self._px(options["width"])
        font_value = options.get("font")
        if isinstance(font_value, (tuple, list)) and len(font_value) >= 2:
            parts = list(font_value)
            size = parts[1]
            if isinstance(size, int):
                if size < 0:
                    parts[1] = -self._px(abs(size))
                else:
                    parts[1] = max(1, round(size * self.ui_scale))
            options["font"] = tuple(parts)
        return options

    def create_text(self, x: Any, y: Any, **kwargs: Any) -> int:
        return tk.Canvas.create_text(
            self,
            self._px(x),
            self._px(y),
            **self._scaled_options(kwargs),
        )

    def create_image(self, x: Any, y: Any, **kwargs: Any) -> int:
        return tk.Canvas.create_image(
            self,
            self._px(x),
            self._px(y),
            **kwargs,
        )

    def coords(self, *args: Any) -> Any:
        if len(args) <= 2:
            return super().coords(*args)
        return super().coords(args[0], *self._coords(tuple(args[1:])))


def _shape_method(name: str):
    def draw(self: ScaledCanvas, *args: Any, **kwargs: Any) -> int:
        return getattr(tk.Canvas, name)(
            self,
            *self._coords(args),
            **self._scaled_options(kwargs),
        )

    draw.__name__ = name
    return draw


for _method_name in ScaledCanvas.SHAPE_METHODS:
    setattr(ScaledCanvas, _method_name, _shape_method(_method_name))


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def mix_color(a: str, b: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    ca = hex_rgb(a)
    cb = hex_rgb(b)
    result = tuple(round(x * (1 - amount) + y * amount) for x, y in zip(ca, cb))
    return "#{:02X}{:02X}{:02X}".format(*result)


def rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) == 8:
        return (
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
            int(value[6:8], 16),
        )
    r, g, b = hex_rgb(color)
    return (r, g, b, max(0, min(255, int(alpha))))


def _vertical(width: int, height: int, top: str, bottom: str) -> Image.Image:
    """A one-pixel-wide vertical gradient stretched to size."""

    width = max(1, int(width))
    height = max(1, int(height))
    strip = Image.new("RGBA", (1, height), rgba(top))
    pixels = strip.load()
    ca = rgba(top)
    cb = rgba(bottom)
    for y in range(height):
        ratio = y / max(1, height - 1)
        pixels[0, y] = (
            round(ca[0] * (1 - ratio) + cb[0] * ratio),
            round(ca[1] * (1 - ratio) + cb[1] * ratio),
            round(ca[2] * (1 - ratio) + cb[2] * ratio),
            round(ca[3] * (1 - ratio) + cb[3] * ratio),
        )
    return strip.resize((width, height), Image.Resampling.BILINEAR)


class VisualKit:
    """Factories for every rounded, glowing or shadowed surface in the app."""

    def __init__(self, root: tk.Misc, scale: float = 1.0):
        self.root = root
        self.scale = max(0.5, float(scale))
        self._rounded_cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}
        self._pill_cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}
        self._card_cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}
        self._gradient_cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}
        self._paper_cache: dict[tuple[int, int], ImageTk.PhotoImage] = {}
        self._sprite_cache: dict[tuple[Any, ...], Image.Image] = {}
        self._panel_cache: dict[tuple[Any, ...], ImageTk.PhotoImage] = {}
        self._mask_cache: dict[tuple[int, int, int], Image.Image] = {}
        self._background_cache: ImageTk.PhotoImage | None = None

    # -- low level -------------------------------------------------------
    def px(self, value: float) -> int:
        return max(1, round(float(value) * self.scale))

    def shadow_pad(self) -> int:
        return max(6, round(15 * self.scale))

    def round_image(self, image: Image.Image, radius_px: int) -> Image.Image:
        """Clip an image to a rounded rectangle (corners become transparent)."""

        width, height = image.size
        mask = self._mask(width, height, radius_px)
        out = image.convert("RGBA").copy()
        out.putalpha(mask)
        return out

    def soft_shadow(
        self,
        width: int,
        height: int,
        radius: int,
        *,
        alpha: int = 40,
        blur: int = 20,
        dy: int = 8,
        color: str | None = None,
    ) -> tuple[ImageTk.PhotoImage, int]:
        """A free-floating soft shadow; returns ``(photo, padding)``."""

        width = max(4, int(width))
        height = max(4, int(height))
        blur = max(1, int(blur))
        padding = max(8, round(blur * 1.5))
        full_w = width + padding * 2
        full_h = height + padding * 2
        key = ("soft", width, height, radius, alpha, blur, dy, color, padding)
        cached = self._card_cache.get(key)
        if cached is not None:
            return cached, padding
        shadow_color = color or COLORS["shadow"]
        small_w = max(8, full_w // 2)
        small_h = max(8, full_h // 2)
        factor = full_w / small_w
        layer = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle(
            (
                padding / factor,
                (padding + dy) / factor,
                (padding + width) / factor,
                (padding + height + dy) / factor,
            ),
            radius=max(1, round(radius / factor)),
            fill=rgba(shadow_color, alpha),
        )
        layer = layer.filter(ImageFilter.GaussianBlur(max(0.5, blur / factor)))
        layer = layer.resize((full_w, full_h), Image.Resampling.BILINEAR)
        photo = ImageTk.PhotoImage(layer, master=self.root)
        if len(self._card_cache) > 140:
            self._card_cache.clear()
        self._card_cache[key] = photo
        return photo, padding

    def draw_soft_shadow(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        *,
        alpha: int = 40,
        blur: float = 20,
        dy: float = 8,
        color: str | None = None,
    ) -> int:
        photo, padding = self.soft_shadow(
            round((x2 - x1) * self.scale),
            round((y2 - y1) * self.scale),
            max(1, round(radius * self.scale)),
            alpha=alpha,
            blur=max(1, round(blur * self.scale)),
            dy=round(dy * self.scale),
            color=color,
        )
        return tk.Canvas.create_image(
            canvas,
            round(x1 * self.scale) - padding,
            round(y1 * self.scale) - padding,
            image=photo,
            anchor="nw",
        )

    def _mask(self, width: int, height: int, radius: int) -> Image.Image:
        width = max(2, int(width))
        height = max(2, int(height))
        radius = max(0, min(int(radius), width // 2, height // 2))
        key = (width, height, radius)
        cached = self._mask_cache.get(key)
        if cached is not None:
            return cached
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle(
            (0, 0, width - 1, height - 1),
            radius=radius,
            fill=255,
        )
        if len(self._mask_cache) > 260:
            self._mask_cache.clear()
        self._mask_cache[key] = mask
        return mask

    def _radial(self, size: int) -> Image.Image:
        """A soft round falloff used for sheen, pointer light and aurora blobs."""

        size = max(16, int(size))
        cached = self._sprite_cache.get(("radial", size))
        if cached is not None:
            return cached
        image = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(image)
        inset = size * 0.16
        draw.ellipse((inset, inset, size - inset, size - inset), fill=255)
        image = image.filter(ImageFilter.GaussianBlur(max(2, size * 0.14)))
        if len(self._sprite_cache) > 40:
            self._sprite_cache.clear()
        self._sprite_cache[("radial", size)] = image
        return image

    def light_sprite(
        self,
        size: int,
        color: str = "#FFFFFF",
        *,
        alpha: int = 40,
    ) -> ImageTk.PhotoImage:
        """An ambient light sprite, used to make light follow the pointer."""

        size = max(64, int(size))
        alpha = max(0, min(255, int(alpha)))
        key = ("light", size, color, alpha)
        cached = self._sprite_cache.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        mask = self._radial(size)
        if alpha < 255:
            mask = mask.point(lambda value: int(value * alpha / 255))
        image = Image.new("RGBA", (size, size), rgba(color, 0))
        image.putalpha(mask)
        photo = ImageTk.PhotoImage(image, master=self.root)
        if len(self._sprite_cache) > 40:
            self._sprite_cache.clear()
        self._sprite_cache[key] = photo  # type: ignore[assignment]
        return photo

    # -- rounded fills ---------------------------------------------------
    def rounded(
        self,
        width: int,
        height: int,
        radius: int,
        fill: str,
        outline: str | None = None,
        outline_width: int = 1,
    ) -> ImageTk.PhotoImage:
        width = max(2, int(width))
        height = max(2, int(height))
        radius = min(int(radius), width // 2, height // 2)
        key = (width, height, radius, fill, outline, outline_width)
        cached = self._rounded_cache.get(key)
        if cached is not None:
            return cached
        scale = 2
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        box = (
            0,
            0,
            width * scale - 1,
            height * scale - 1,
        )
        draw.rounded_rectangle(
            box,
            radius=radius * scale,
            fill=fill,
            outline=outline,
            width=max(1, outline_width * scale) if outline else 0,
        )
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image, master=self.root)
        # Keep the cache bounded while the app is running.
        if len(self._rounded_cache) > 900:
            self._rounded_cache.clear()
        self._rounded_cache[key] = photo
        return photo

    def draw_round(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: int,
        fill: str,
        outline: str | None = None,
        outline_width: int = 1,
        tags: tuple[str, ...] | str | None = None,
    ) -> int:
        photo = self.rounded(
            round((x2 - x1) * self.scale),
            round((y2 - y1) * self.scale),
            max(1, round(radius * self.scale)),
            fill,
            outline,
            max(1, round(outline_width * self.scale)),
        )
        return tk.Canvas.create_image(
            canvas,
            round(x1 * self.scale),
            round(y1 * self.scale),
            image=photo,
            anchor="nw",
            tags=tags,
        )

    # -- animated pill faces --------------------------------------------
    def pill_face(
        self,
        width: int,
        height: int,
        radius: int,
        fill: str,
        fill2: str | None = None,
        outline: str | None = None,
        outline_width: int = 1,
        *,
        sheen_xy: tuple[float, float] | None = None,
        sheen: float = 0.0,
        sheen_color: str = "#FFFFFF",
        highlight: float = 0.0,
        ripple_xy: tuple[float, float] | None = None,
        ripple: float = 0.0,
        cache: bool = True,
    ) -> ImageTk.PhotoImage:
        """A rounded control surface, optionally lit from a pointer position.

        All arguments are in device pixels. ``sheen_xy`` is the pointer inside
        the control, so the highlight can slide along with the mouse instead of
        being a static gloss.
        """

        width = max(4, int(width))
        height = max(4, int(height))
        radius = max(0, min(int(radius), width // 2, height // 2))
        sheen = max(0.0, min(1.0, float(sheen)))
        highlight = max(0.0, min(1.0, float(highlight)))
        idle = sheen <= 0.004
        key = (
            "pill",
            width,
            height,
            radius,
            fill,
            fill2,
            outline,
            outline_width,
            round(highlight, 2),
        )
        if cache and idle:
            cached = self._pill_cache.get(key)
            if cached is not None:
                return cached

        ss = 2 if width * height <= 180_000 else 1
        w = width * ss
        h = height * ss
        r = radius * ss

        if fill2 and fill2 != fill:
            base = _vertical(w, h, fill, fill2)
        else:
            base = Image.new("RGBA", (w, h), rgba(fill))

        mask = self._mask(w, h, r)
        # Respect the fill's own alpha so callers can ask for a fully
        # transparent idle pill (nav rows fade in only on hover).
        base.putalpha(ImageChops.multiply(mask, base.getchannel("A")))

        if outline:
            edge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            edge_draw = ImageDraw.Draw(edge)
            half = max(0.5, ss * 0.5)
            edge_draw.rounded_rectangle(
                (half, half, w - half, h - half),
                radius=max(0, r - half),
                outline=rgba(outline),
                width=max(1, round(outline_width * ss)),
            )
            base = Image.alpha_composite(base, edge)

        if highlight > 0.004:
            rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            rim_draw = ImageDraw.Draw(rim)
            inset = max(1, round(1.0 * ss))
            rim_draw.rounded_rectangle(
                (inset, inset, w - inset, h - inset),
                radius=max(0, r - inset),
                outline=(255, 255, 255, round(72 * highlight)),
                width=max(1, round(1.1 * ss)),
            )
            base = Image.alpha_composite(
                base, Image.composite(rim, Image.new("RGBA", (w, h), (0, 0, 0, 0)), mask)
            )

        if sheen > 0.004 and sheen_xy is not None:
            sprite_size = max(32, round(max(width, height) * 2.1))
            sprite = self._radial(sprite_size // 2).resize(
                (sprite_size, sprite_size), Image.Resampling.BILINEAR
            )
            glow = Image.new("L", (w, h), 0)
            left = round(sheen_xy[0] * ss - sprite_size / 2)
            top = round(sheen_xy[1] * ss - sprite_size / 2)
            glow.paste(sprite, (left, top))
            glow = glow.point(lambda value: int(value * sheen * 0.52))
            glow = ImageChops.multiply(glow, mask)
            layer = Image.new("RGBA", (w, h), rgba(sheen_color, 0))
            layer.putalpha(glow)
            base = Image.alpha_composite(base, layer)

        if ripple > 0.004 and ripple_xy is not None:
            # A soft ring expands from the press point and fades out, giving
            # every click a visible "something happened" moment.
            radius = max(2.0, max(width, height) * 0.85 * ripple) * ss
            pulse = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            pulse_draw = ImageDraw.Draw(pulse)
            cx = ripple_xy[0] * ss
            cy = ripple_xy[1] * ss
            pulse_draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=rgba(sheen_color, int(16 * (1.0 - ripple))),
                outline=rgba(sheen_color, int(120 * (1.0 - ripple))),
                width=max(1, round(2.2 * ss)),
            )
            pulse = pulse.filter(ImageFilter.GaussianBlur(max(1, 1.6 * ss)))
            pulse.putalpha(ImageChops.multiply(pulse.getchannel("A"), mask))
            base = Image.alpha_composite(base, pulse)

        if ss > 1:
            base = base.resize((width, height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(base, master=self.root)
        if cache and idle:
            if len(self._pill_cache) > 420:
                self._pill_cache.clear()
            self._pill_cache[key] = photo
        return photo

    def draw_pill(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        fill: str,
        fill2: str | None = None,
        outline: str | None = None,
        outline_width: int = 1,
        tags: tuple[str, ...] | str | None = None,
        highlight: float = 0.0,
    ) -> int:
        photo = self.pill_face(
            round((x2 - x1) * self.scale),
            round((y2 - y1) * self.scale),
            max(1, round(radius * self.scale)),
            fill,
            fill2,
            outline,
            max(1, round(outline_width * self.scale)),
            highlight=highlight,
        )
        return tk.Canvas.create_image(
            canvas,
            round(x1 * self.scale),
            round(y1 * self.scale),
            image=photo,
            anchor="nw",
            tags=tags,
        )

    # -- cards -----------------------------------------------------------
    def card_face(
        self,
        width: int,
        height: int,
        radius: int,
        fill: str,
        outline: str | None = None,
        outline_width: int = 1,
        *,
        hover: bool = False,
    ) -> ImageTk.PhotoImage:
        """Paint a rounded card with soft, fully feathered shadow edges."""

        width = max(4, int(width))
        height = max(4, int(height))
        radius = max(0, min(int(radius), width // 2, height // 2))
        padding = self.shadow_pad()
        pad_x = padding
        pad_y = padding
        full_w = width + pad_x * 2
        full_h = height + pad_y * 2
        key = (
            "card",
            width,
            height,
            radius,
            fill,
            outline,
            outline_width,
            hover,
            padding,
        )
        cached = self._card_cache.get(key)
        if cached is not None:
            return cached

        shadow_rgb = hex_rgb(COLORS["shadow"])
        accent = hex_rgb(COLORS["iris"])

        # Build the shadows at quarter size, blur, then stretch over the card.
        # A blur is smooth by nature, so this is visually identical and four
        # times cheaper than filtering at full resolution.
        small_w = max(8, full_w // 4)
        small_h = max(8, full_h // 4)
        factor = full_w / small_w

        def shadow_layer(
            color: tuple[int, int, int, int],
            offset_y: float,
            blur: float,
            grow: float,
        ) -> Image.Image:
            canvas = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            left = (pad_x - grow) / factor
            top = (pad_y - grow + offset_y) / factor
            right = (pad_x + width + grow) / factor
            bottom = (pad_y + height + grow + offset_y) / factor
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=max(1, round(radius / factor)),
                fill=color,
            )
            canvas = canvas.filter(ImageFilter.GaussianBlur(max(0.5, blur / factor)))
            return canvas.resize((full_w, full_h), Image.Resampling.BILINEAR)

        if hover:
            ambient = shadow_layer((*shadow_rgb, 27), 6.0 * self.scale, 15 * self.scale, 1.0)
            contact = shadow_layer((*shadow_rgb, 20), 2.2 * self.scale, 5 * self.scale, 0.0)
            halo = shadow_layer((*accent, 12), 8.0 * self.scale, 19 * self.scale, 1.0)
        else:
            ambient = shadow_layer((*shadow_rgb, 18), 5.0 * self.scale, 13 * self.scale, 0.0)
            contact = shadow_layer((*shadow_rgb, 13), 1.6 * self.scale, 4 * self.scale, 0.0)
            halo = None

        image = Image.new("RGBA", (full_w, full_h), (0, 0, 0, 0))
        if halo is not None:
            image = Image.alpha_composite(image, halo)
        image = Image.alpha_composite(image, ambient)
        image = Image.alpha_composite(image, contact)

        # The card's bitmap ends within a fixed gutter. Fade the last pixels
        # to zero so the shadow cannot leave a straight cut along that edge.
        fade = max(2, round(padding * 0.70))
        ramp = Image.new("L", (1, fade))
        stops = []
        for row in range(fade):
            progress = row / (fade - 1)
            stops.append(round(255 * progress * progress * (3 - 2 * progress)))
        ramp.putdata(stops)

        def feather_profile(length: int) -> Image.Image:
            profile = Image.new("L", (1, length), 255)
            profile.paste(ramp, (0, 0))
            profile.paste(ImageOps.flip(ramp), (0, length - fade))
            return profile

        across = feather_profile(full_w).transpose(Image.Transpose.TRANSPOSE)
        down = feather_profile(full_h)
        alpha = ImageChops.multiply(image.getchannel("A"), across.resize(image.size, Image.Resampling.NEAREST))
        image.putalpha(ImageChops.multiply(alpha, down.resize(image.size, Image.Resampling.NEAREST)))

        ss = 2
        card = Image.new(
            "RGBA",
            (width * ss + pad_x * 2 * ss, height * ss + pad_y * 2 * ss),
            (0, 0, 0, 0),
        )
        draw = ImageDraw.Draw(card)
        bounds = (
            pad_x * ss, pad_y * ss,
            (pad_x + width) * ss - 1, (pad_y + height) * ss - 1,
        )
        _, _, _, opacity = rgba(fill)
        solid_fill = fill
        if opacity < 255:
            face_size = (width * ss, height * ss)
            highlight = mix_color(fill, COLORS["white"], 0.45)
            glass = _vertical(
                *face_size,
                f"{highlight}{min(255, opacity + 12):02X}",
                f"{fill[:7]}{max(0, opacity - 14):02X}",
            )
            face_mask = Image.new("L", face_size, 0)
            ImageDraw.Draw(face_mask).rounded_rectangle(
                (0, 0, face_size[0] - 1, face_size[1] - 1),
                radius=radius * ss,
                fill=255,
            )
            card.paste(glass, bounds[:2], face_mask)
            solid_fill = None
        draw.rounded_rectangle(
            bounds,
            radius=radius * ss,
            fill=solid_fill,
            outline=outline,
            width=max(1, outline_width * ss) if outline else 0,
        )
        card = card.resize((full_w, full_h), Image.Resampling.LANCZOS)
        image = Image.alpha_composite(image, card)

        photo = ImageTk.PhotoImage(image, master=self.root)
        if len(self._card_cache) > 140:
            self._card_cache.clear()
        self._card_cache[key] = photo
        return photo

    def draw_card(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: int,
        fill: str,
        outline: str | None = None,
        outline_width: int = 1,
        tags: tuple[str, ...] | str | None = None,
        *,
        hover: bool = False,
    ) -> int:
        photo = self.card_face(
            round((x2 - x1) * self.scale),
            round((y2 - y1) * self.scale),
            max(1, round(radius * self.scale)),
            fill,
            outline,
            max(1, round(outline_width * self.scale)),
            hover=hover,
        )
        padding = self.shadow_pad()
        return tk.Canvas.create_image(
            canvas,
            round(x1 * self.scale) - padding,
            round(y1 * self.scale) - padding,
            image=photo,
            anchor="nw",
            tags=tags,
        )

    # -- gradients / panels --------------------------------------------
    def draw_gradient(
        self,
        canvas: tk.Canvas,
        width: int,
        height: int,
        top: str,
        bottom: str,
    ) -> int:
        width_px = max(2, round(width * self.scale))
        height_px = max(2, round(height * self.scale))
        key = (width_px, height_px, top, bottom)
        photo = self._gradient_cache.get(key)
        if photo is None:
            image = _vertical(width_px, height_px, top, bottom).convert("RGB")
            photo = ImageTk.PhotoImage(image, master=self.root)
            if len(self._gradient_cache) > 24:
                self._gradient_cache.clear()
            self._gradient_cache[key] = photo
        return tk.Canvas.create_image(
            canvas,
            0,
            0,
            image=photo,
            anchor="nw",
        )

    def panel_image(
        self,
        width: int,
        height: int,
        radius: float,
        top: str,
        bottom: str,
        *,
        glows: tuple[tuple[str, float, float, float, int], ...] = (),
        border: str | None = "#FFFFFF",
        border_alpha: int = 26,
        grain: int = 0,
    ) -> ImageTk.PhotoImage:
        """A full-bleed rounded panel: gradient + aurora blobs + inner rim.

        ``glows`` entries are ``(color, x_ratio, y_ratio, radius_device, alpha)``.
        """

        width = max(8, int(width))
        height = max(8, int(height))
        radius_px = max(0, round(radius * self.scale))
        key = (
            "panel",
            width,
            height,
            radius_px,
            top,
            bottom,
            glows,
            border,
            border_alpha,
            grain,
        )
        cached = self._panel_cache.get(key)
        if cached is not None:
            return cached

        image = _vertical(width, height, top, bottom)

        if glows:
            small_w = max(8, width // 2)
            small_h = max(8, height // 2)
            fx = small_w / width
            fy = small_h / height
            halo = Image.new("RGBA", (small_w, small_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(halo)
            for color, xr, yr, size, alpha in glows:
                cx = width * xr * fx
                cy = height * yr * fy
                r = size * min(fx, fy)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgba(color, alpha))
            halo = halo.filter(ImageFilter.GaussianBlur(max(4, round(width * 0.05))))
            halo = halo.resize((width, height), Image.Resampling.BILINEAR)
            image = Image.alpha_composite(image, halo)

        if grain > 0:
            noise = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            noise_draw = ImageDraw.Draw(noise)
            rng = random.Random(9182 + grain)
            for _ in range(max(1, width * height // 320)):
                noise_draw.point(
                    (rng.randrange(width), rng.randrange(height)),
                    fill=(255, 255, 255, rng.randint(3, 9)),
                )
            image = Image.alpha_composite(image, noise)

        mask = self._mask(width, height, radius_px)
        image.putalpha(mask)

        if border:
            rim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            rim_draw = ImageDraw.Draw(rim)
            rim_draw.rounded_rectangle(
                (1, 1, width - 2, height - 2),
                radius=max(0, radius_px - 1),
                outline=rgba(border, border_alpha),
                width=1,
            )
            image = Image.alpha_composite(image, rim)

        photo = ImageTk.PhotoImage(image, master=self.root)
        if len(self._panel_cache) > 32:
            self._panel_cache.clear()
        self._panel_cache[key] = photo
        return photo

    # -- page backdrop ---------------------------------------------------
    def draw_background(self, canvas: tk.Canvas, width: int, height: int) -> int:
        photo = self.paper_background(
            round(width * self.scale),
            round(height * self.scale),
        )
        return tk.Canvas.create_image(
            canvas,
            0,
            0,
            image=photo,
            anchor="nw",
        )

    def background(self, width: int, height: int) -> ImageTk.PhotoImage:
        return self.paper_background(width, height)

    def paper_background(self, width: int, height: int) -> ImageTk.PhotoImage:
        """Return the cached frosted paper texture for a standalone canvas."""
        width = max(8, int(width))
        height = max(8, int(height))
        key = (width, height)
        cached = self._paper_cache.get(key)
        if cached is not None:
            return cached

        photo = ImageTk.PhotoImage(self._paper_image(width, height), master=self.root)
        if len(self._paper_cache) > 6:
            self._paper_cache.clear()
        self._paper_cache[key] = photo
        return photo

    @staticmethod
    def _paper_image(width: int, height: int) -> Image.Image:
        """Render the washes at quarter resolution for fast, gentle gradients."""
        factor = 0.25
        small_w = max(4, round(width * factor))
        small_h = max(4, round(height * factor))
        image = _vertical(small_w, small_h, "#F2F0E6", "#CFDFD4")

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        spread = min(small_w, small_h)
        glows = (
            (AURORA[0], small_w * 0.80, small_h * 0.08, spread * 0.82, 92),
            (AURORA[2], small_w * 0.85, small_h * 0.37, spread * 0.59, 55),
            (AURORA[1], small_w * 0.26, small_h * 0.94, spread * 0.86, 82),
        )
        for color, cx, cy, radius, alpha in glows:
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=rgba(color, alpha),
            )
        overlay = overlay.filter(ImageFilter.GaussianBlur(max(3, spread // 6)))
        image = Image.alpha_composite(image, overlay)
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        grain = Image.new("RGBA", image.size, (0, 0, 0, 0))
        grain_draw = ImageDraw.Draw(grain)
        rng = random.Random(612)
        for _ in range(max(1, width * height // 420)):
            x = rng.randrange(width)
            y = rng.randrange(height)
            grain_draw.point((x, y), fill=(61, 55, 45, rng.randint(4, 10)))
        return Image.alpha_composite(image, grain).convert("RGB")

    def window_backdrop(
        self, width: int, height: int, source: Image.Image | None,
    ) -> Image.Image:
        """Create one rounded, frosted surface for the entire main window."""
        inset = min(self.px(7), (width - 1) // 2, (height - 1) // 2)
        inner = (width - 2 * inset, height - 2 * inset)
        if source is None:
            texture = self._paper_image(*inner)
        else:
            texture = self.frosted_wallpaper(source, inner)
        frame = Image.new("RGB", (width, height), COLORS["paper"])
        mask = Image.new("L", inner, 0)
        radius = min(self.px(RADII["backdrop"]), min(inner) // 2)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, inner[0] - 1, inner[1] - 1), radius=radius, fill=255,
        )
        frame.paste(texture, (inset, inset), mask.filter(ImageFilter.GaussianBlur(0.7)))
        return frame

    @staticmethod
    def frosted_wallpaper(source: Image.Image, size: tuple[int, int]) -> Image.Image:
        """Soften an uploaded image before it shows through the glass."""

        width, height = size
        factor = min(1.0, 520 / max(width, height))
        sample = (max(1, round(width * factor)), max(1, round(height * factor)))
        fitted = ImageOps.fit(source, sample, method=Image.Resampling.LANCZOS)
        blurred = fitted.filter(ImageFilter.GaussianBlur(max(2, min(sample) * 0.075)))
        tint = Image.new("RGB", sample, COLORS["paper"])
        return Image.blend(blurred.convert("RGB"), tint, 0.60).resize(
            size, Image.Resampling.BILINEAR,
        )

    # -- icon -------------------------------------------------------------
    def app_icon(self) -> ImageTk.PhotoImage:
        size = 128
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        base = _vertical(size, size, COLORS["pine_light"], COLORS["pine"])
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((2, 2, size - 3, size - 3), radius=32, fill=255)
        base.putalpha(mask)
        image = Image.alpha_composite(image, base)

        halo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((52, -34, 162, 76), fill=rgba(AURORA[0], 120))
        ImageDraw.Draw(halo).ellipse((-36, 64, 74, 174), fill=rgba(AURORA[1], 90))
        halo = halo.filter(ImageFilter.GaussianBlur(18))
        halo.putalpha(ImageChops.multiply(halo.getchannel("A"), mask))
        image = Image.alpha_composite(image, halo)

        try:
            font_path = Path("C:/Windows/Fonts/NotoSerifSC-VF.ttf")
            loaded = ImageFont.truetype(str(font_path), 66)
        except OSError:
            loaded = ImageFont.load_default()
        draw = ImageDraw.Draw(image)
        bbox = draw.textbbox((0, 0), "栖", font=loaded)
        x = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
        y = (size - (bbox[3] - bbox[1])) / 2 - bbox[1] - 2
        draw.text((x, y), "栖", font=loaded, fill=COLORS["white"])
        return ImageTk.PhotoImage(image, master=self.root)


def text_width(text: str, text_font: tuple[str, int, str]) -> int:
    # Canvas text has a width option; this rough estimate is only used for spacing.
    size = abs(text_font[1])
    return int(sum(size * (0.55 if ord(char) < 128 else 1.0) for char in text))
