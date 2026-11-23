from __future__ import annotations

import ctypes
import os
import shutil
import struct
import sys
import tkinter as tk
import uuid
from pathlib import Path

from PIL import ImageFont

from .db import Store, app_data_dir
from .theme import reset_font_family, set_font_family


FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
MAX_FONT_BYTES = 24 * 1024 * 1024


def _font_name_candidates(path: Path) -> list[str]:
    """Read localized family names from a TTF/OTF/TTC name table."""

    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) < 12:
        return []
    offset = 0
    if data[:4] == b"ttcf":
        try:
            count = struct.unpack_from(">I", data, 8)[0]
            if count == 0 or len(data) < 12 + count * 4:
                return []
            offset = struct.unpack_from(">I", data, 12)[0]
        except struct.error:
            return []
    try:
        num_tables = struct.unpack_from(">H", data, offset + 4)[0]
    except struct.error:
        return []
    name_offset = None
    for index in range(num_tables):
        record_offset = offset + 12 + index * 16
        try:
            tag, _checksum, table_offset, table_length = struct.unpack_from(
                ">4sIII",
                data,
                record_offset,
            )
        except struct.error:
            return []
        if tag == b"name":
            name_offset = table_offset
            break
    if name_offset is None or name_offset + 6 > len(data):
        return []
    try:
        _format, count, string_offset = struct.unpack_from(">HHH", data, name_offset)
    except struct.error:
        return []
    names: list[str] = []
    records_start = name_offset + 6
    storage_start = name_offset + string_offset
    for index in range(count):
        record = records_start + index * 12
        if record + 12 > len(data):
            break
        platform, encoding, _language, name_id, length, value_offset = struct.unpack_from(
            ">HHHHHH",
            data,
            record,
        )
        if name_id not in {1, 16} or length == 0:
            continue
        start = storage_start + value_offset
        raw = data[start : start + length]
        if platform in {0, 3}:
            value = raw.decode("utf-16-be", errors="ignore")
        elif platform == 1:
            value = raw.decode("mac_roman", errors="ignore")
        else:
            continue
        value = value.strip("\x00 ").strip()
        if value and value not in names:
            names.append(value)
    return names


class FontLibrary:
    """Register a user font privately and keep the choice in local settings."""

    def __init__(self, root: tk.Tk, store: Store):
        self.root = root
        self.store = store
        self.font_dir = app_data_dir() / "fonts"
        self.current_family = ""

    def restore(self) -> bool:
        path_value = self.store.get_setting("font_path")
        if not path_value:
            reset_font_family()
            return False
        path = Path(path_value)
        if not path.exists():
            reset_font_family()
            return False
        try:
            family = self._register(path)
        except (OSError, ValueError):
            reset_font_family()
            return False
        set_font_family(family)
        self.current_family = family
        return True

    def upload(self, source: str | Path) -> str:
        source = Path(source)
        suffix = source.suffix.lower()
        if suffix not in FONT_EXTENSIONS:
            raise ValueError("请选择 TTF、OTF 或 TTC 字体文件。")
        try:
            if source.stat().st_size > MAX_FONT_BYTES:
                raise ValueError("字体文件超过 24 MB，暂时无法安装。")
        except OSError as exc:
            raise ValueError("无法读取这个字体文件。") from exc

        self.font_dir.mkdir(parents=True, exist_ok=True)
        destination = self.font_dir / f"custom-{uuid.uuid4().hex[:10]}{suffix}"
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
            family = self._register(destination)
        except (OSError, ValueError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ValueError("字体文件无效或无法注册。") from exc

        set_font_family(family)
        self.current_family = family
        self.store.set_setting("font_path", str(destination))
        self.store.set_setting("font_family", family)
        return family

    def reset(self) -> None:
        reset_font_family()
        self.current_family = ""
        self.store.set_setting("font_path", "")
        self.store.set_setting("font_family", "")

    @property
    def display_name(self) -> str:
        if self.current_family:
            return self.current_family
        saved = self.store.get_setting("font_family")
        return saved or "默认字体"

    def _register(self, path: Path) -> str:
        try:
            probe = ImageFont.truetype(str(path), 28)
            family, _style = probe.getname()
        except (OSError, ValueError) as exc:
            raise ValueError("无法识别字体文件。") from exc
        if not family:
            raise ValueError("字体文件没有可用的字体名称。")

        if sys.platform == "win32":
            before = {str(value) for value in self.root.tk.call("font", "families")}
            added = ctypes.windll.gdi32.AddFontResourceExW(
                str(path.resolve()),
                0x10,  # FR_PRIVATE
                0,
            )
            if added <= 0:
                raise ValueError("Windows 无法加载这个字体。")
            # Force Tk to enumerate the newly registered family.
            self.root.tk.call("font", "families")
            after = {str(value) for value in self.root.tk.call("font", "families")}
            candidates = [family, *_font_name_candidates(path)]
            for candidate in candidates:
                if candidate in after or candidate in before:
                    return candidate
            normalized = {
                value.replace(" ", "").casefold(): value
                for value in after
                if not value.startswith("@")
            }
            for candidate in candidates:
                matched = normalized.get(candidate.replace(" ", "").casefold())
                if matched:
                    return matched
            new_families = sorted(value for value in after - before if not value.startswith("@"))
            if new_families:
                return new_families[0]
        return family
