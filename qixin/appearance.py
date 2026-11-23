from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .db import app_data_dir


APPEARANCE_DIR = app_data_dir() / "appearance"
BACKGROUND_PATH = APPEARANCE_DIR / "background.png"
ICON_PATH = APPEARANCE_DIR / "sidebar-icon.png"


def prepare_background(source: str | Path) -> Path:
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取这张背景图。") from exc
    image = ImageOps.fit(
        image,
        (2560, 1600),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    APPEARANCE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = BACKGROUND_PATH.with_suffix(".tmp.png")
    image.save(temporary, "PNG", optimize=True)
    temporary.replace(BACKGROUND_PATH)
    return BACKGROUND_PATH


def prepare_icon(source: str | Path) -> Path:
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取这个图标文件。") from exc
    image = ImageOps.fit(
        image,
        (512, 512),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    mask = Image.new("L", (512, 512), 0)
    ImageDraw.Draw(mask).ellipse((8, 8, 504, 504), fill=255)
    image.putalpha(Image.composite(image.getchannel("A"), Image.new("L", (512, 512), 0), mask))
    APPEARANCE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = ICON_PATH.with_suffix(".tmp.png")
    image.save(temporary, "PNG", optimize=True)
    temporary.replace(ICON_PATH)
    return ICON_PATH
