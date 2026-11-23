"""随笔记录：本地 SQLite 存储与富文本编辑器。

正文以「格式片段」(runs) 的数组保存在 notes.body_json 里，每个片段携带
文字、字号、加粗、斜体、字体与荧光底色。编辑器用 Tk 的 tag 机制实现
选区格式化：每种格式组合对应一个 tag，保存时再按字符把 tag 还原成片段。
"""

from __future__ import annotations

import json
import re
import sqlite3
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, replace
from datetime import date, datetime
from tkinter import messagebox, ttk
from typing import Any, Callable, Iterable

from .db import Store
from .theme import (
    COLORS,
    active_font_family,
    font as theme_font,
    get_font_scale,
    mix_color,
    widget_font,
)


DEFAULT_RUN_SIZE = 15
MIN_RUN_SIZE = 10
MAX_RUN_SIZE = 48
FONT_SIZE_CHOICES = (12, 14, 16, 18, 20, 24)
PREVIEW_LIMIT = 60

DEFAULT_FONT_LABEL = "默认字体"
TITLE_PLACEHOLDER = "给这段随笔起个名字（可留空）"
EDITOR_HINT = "选中文字后再点工具栏，只改变选中的部分"

# 荧光增亮的四种底色（都足够浅，正文墨色仍然清晰）。
HIGHLIGHT_CHOICES = (
    ("暖黄", "#FDF3C7"),
    ("浅绿", "#DCEFD8"),
    ("浅粉", "#F7DDE2"),
    ("浅蓝", "#DDEAF3"),
)


def _highlight_name(color: str) -> str:
    for name, value in HIGHLIGHT_CHOICES:
        if value.lower() == color.strip().lower():
            return name
    return color or "无"

NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    body_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at DESC);
"""


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class RichRun:
    """一段连续、样式一致的文字。"""

    text: str
    size: int = DEFAULT_RUN_SIZE
    bold: bool = False
    italic: bool = False
    family: str = ""
    highlight: str = ""

    @property
    def style_key(self) -> tuple[int, bool, bool, str, str]:
        return (self.size, self.bold, self.italic, self.family, self.highlight)


@dataclass
class Note:
    id: int
    created_at: str
    updated_at: str
    local_date: str
    title: str
    runs: list[RichRun]

    @property
    def plain_text(self) -> str:
        return "".join(run.text for run in self.runs)

    @property
    def preview(self) -> str:
        # 列表预览只取一行，换行、连续空格都折叠成单个空格。
        one_line = " ".join(self.plain_text.split())
        if len(one_line) <= PREVIEW_LIMIT:
            return one_line
        return one_line[: PREVIEW_LIMIT - 1] + "…"


# ---------------------------------------------------------------------------
# 内部工具：惰性建表与字段容错
# ---------------------------------------------------------------------------


def _now_text() -> str:
    # 微秒级时间戳既能直接按字符串排序，也能让同一秒内的多次保存排出先后。
    return datetime.now().isoformat(timespec="microseconds")


def _ensure_schema(store: Store) -> None:
    """notes 表由本模块惰性建立，避免改动 db.py 的全局 schema。"""

    row = store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notes'"
    ).fetchone()
    if row is None:
        store.conn.executescript(NOTES_SCHEMA)


def _coerce_size(value: Any) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RUN_SIZE
    return max(MIN_RUN_SIZE, min(MAX_RUN_SIZE, size))


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_family(value: Any) -> str:
    return _coerce_text(value).strip()


def _coerce_highlight(value: Any) -> str:
    raw = _coerce_text(value).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", raw):
        return raw
    return ""


def _runs_to_json(runs: Iterable[RichRun]) -> str:
    payload: list[dict[str, Any]] = []
    for run in runs:
        text = run.text
        if not isinstance(text, str) or not text:
            # 空片段不落库，既避免脏数据，也让空正文保存成 "[]"。
            continue
        payload.append(
            {
                "text": text,
                "size": _coerce_size(run.size),
                "bold": bool(run.bold),
                "italic": bool(run.italic),
                "family": _coerce_family(run.family),
                "highlight": _coerce_highlight(run.highlight),
            }
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _runs_from_json(raw: Any) -> list[RichRun]:
    """把 body_json 还原成片段；损坏的数据按空数组处理，不让界面崩掉。"""

    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    runs: list[RichRun] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue
        runs.append(
            RichRun(
                text=text,
                size=_coerce_size(item.get("size", DEFAULT_RUN_SIZE)),
                bold=bool(item.get("bold", False)),
                italic=bool(item.get("italic", False)),
                family=_coerce_family(item.get("family", "")),
                highlight=_coerce_highlight(item.get("highlight", "")),
            )
        )
    return runs


def _note_from_row(row: sqlite3.Row) -> Note:
    return Note(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        local_date=str(row["local_date"]),
        title=str(row["title"]),
        runs=_runs_from_json(row["body_json"]),
    )


# ---------------------------------------------------------------------------
# 存储 API（都接收 Store，业务上不需要知道 SQL 细节）
# ---------------------------------------------------------------------------


def list_notes(store: Store, limit: int = 20) -> list[Note]:
    """按最近修改时间倒序列出随笔。"""

    _ensure_schema(store)
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = 20
    if limit_value <= 0:
        return []
    rows = store.conn.execute(
        """
        SELECT * FROM notes
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (limit_value,),
    ).fetchall()
    return [_note_from_row(row) for row in rows]


def get_note(store: Store, note_id: int) -> Note | None:
    _ensure_schema(store)
    try:
        key = int(note_id)
    except (TypeError, ValueError):
        return None
    row = store.conn.execute("SELECT * FROM notes WHERE id = ?", (key,)).fetchone()
    return _note_from_row(row) if row else None


def save_note(
    store: Store,
    runs: list[RichRun],
    title: str = "",
    note_id: int | None = None,
) -> int:
    """新建或更新一条随笔，返回它的 id。"""

    _ensure_schema(store)
    payload = _runs_to_json(runs or [])
    clean_title = (title or "").strip()
    now = _now_text()
    with store.transaction():
        if note_id is None:
            cursor = store.conn.execute(
                """
                INSERT INTO notes(created_at, updated_at, local_date, title, body_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, now, date.today().isoformat(), clean_title, payload),
            )
            return int(cursor.lastrowid)
        cursor = store.conn.execute(
            """
            UPDATE notes
            SET updated_at = ?, title = ?, body_json = ?
            WHERE id = ?
            """,
            (now, clean_title, payload, int(note_id)),
        )
        if cursor.rowcount == 0:
            raise ValueError("这条随笔已经不存在了。")
        return int(note_id)


def delete_note(store: Store, note_id: int) -> None:
    _ensure_schema(store)
    with store.transaction():
        store.conn.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))


def count_notes(store: Store) -> int:
    _ensure_schema(store)
    row = store.conn.execute("SELECT COUNT(*) AS total FROM notes").fetchone()
    return int(row["total"]) if row else 0


def note_from_text(
    store: Store,
    text: str,
    title: str = "",
    note_id: int | None = None,
) -> int:
    """便捷入口：纯文本转成单个默认格式片段后保存。"""

    runs = [RichRun(text=_coerce_text(text))]
    return save_note(store, runs, title=title, note_id=note_id)


# ---------------------------------------------------------------------------
# 编辑器内部：不可变的样式描述
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RunStyle:
    size: int = DEFAULT_RUN_SIZE
    bold: bool = False
    italic: bool = False
    family: str = ""
    highlight: str = ""

    @classmethod
    def from_run(cls, run: RichRun) -> "_RunStyle":
        return cls(
            size=_coerce_size(run.size),
            bold=bool(run.bold),
            italic=bool(run.italic),
            family=_coerce_family(run.family),
            highlight=_coerce_highlight(run.highlight),
        )

    def to_run(self, text: str) -> RichRun:
        return RichRun(
            text=text,
            size=self.size,
            bold=self.bold,
            italic=self.italic,
            family=self.family,
            highlight=self.highlight,
        )

    @property
    def key(self) -> tuple[int, bool, bool, str, str]:
        return (self.size, self.bold, self.italic, self.family, self.highlight)

    def tk_font(self, font_scale: float) -> tuple[Any, ...]:
        """Tk 字体元组：正文字号是用户内容，只跟 get_font_scale() 相乘。"""

        family = self.family.strip() or active_font_family()
        pixel = -max(1, round(self.size * font_scale))
        styles: tuple[str, ...] = ()
        if self.bold and self.italic:
            styles = ("bold", "italic")
        elif self.bold:
            styles = ("bold",)
        elif self.italic:
            styles = ("italic",)
        return (family, pixel, *styles)


_TAG_UNSAFE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]+")


def _tag_fragment(value: str) -> str:
    cleaned = _TAG_UNSAFE.sub("_", value.strip()).strip("_")
    return cleaned or "default"


# ---------------------------------------------------------------------------
# 富文本编辑器弹窗
# ---------------------------------------------------------------------------


class NoteEditorDialog:
    """随笔编辑器：选中文字 → 点工具栏 → 只有选区带上格式。"""

    WIDTH = 880
    HEIGHT = 640

    _IGNORED_KEYS = frozenset(
        {
            "BackSpace",
            "Delete",
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Prior",
            "Next",
            "Tab",
            "Escape",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
        }
    )

    def __init__(
        self,
        app: Any,
        store: Store,
        note_id: int | None = None,
        on_saved: Callable[[int], None] | None = None,
    ):
        self.app = app
        self.store = store
        self.on_saved = on_saved
        self.ui_scale = max(0.6, float(getattr(app, "ui_scale", 1.0) or 1.0))
        self.font_scale = get_font_scale()
        # 界面控件跟着字号设置一起放大，正文片段字号由 _RunStyle.tk_font 单独处理。
        self.scale = max(0.6, self.ui_scale * self.font_scale)

        self._tag_styles: dict[str, _RunStyle] = {}
        self._tag_by_key: dict[tuple[int, bool, bool, str, str], str] = {}
        self._caret_style = _RunStyle()
        self._fonts: list[tkfont.Font] = []
        self._hint_job: str | None = None
        self._closed = False

        self.note = get_note(store, note_id) if note_id is not None else None
        self.note_id = self.note.id if self.note is not None else None

        self.window = tk.Toplevel(app.root)
        self.window.title("随笔记录")
        self.window.configure(bg=COLORS["paper"])
        self.window.transient(app.root)

        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        # 窗口不越过屏幕的 80%，再把默认的 880×640 按界面缩放系数放大。
        max_width = max(1, int(screen_width * 0.8))
        max_height = max(1, int(screen_height * 0.8))
        self.width = min(self._px(self.WIDTH), max_width)
        self.height = min(self._px(self.HEIGHT), max_height)
        self.window.minsize(
            min(self._px(640), max_width),
            min(self._px(460), max_height),
        )
        self.window.geometry(f"{self.width}x{self.height}")
        self._center(self.width, self.height)
        self.window.protocol("WM_DELETE_WINDOW", self._close)
        self.window.bind("<Escape>", lambda _event: self._close())
        self.window.bind("<Control-s>", self._save_shortcut)

        self._build()
        self._load_content()

    # -- 布局 ------------------------------------------------------------

    def _px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def _center(self, width: int, height: int) -> None:
        self.window.update_idletasks()
        root = self.app.root
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        if root.winfo_width() > 1 and root.winfo_height() > 1:
            x = root.winfo_rootx() + (root.winfo_width() - width) // 2
            y = root.winfo_rooty() + (root.winfo_height() - height) // 2
        else:
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
        x = max(0, min(x, screen_width - width))
        y = max(0, min(y, screen_height - height))
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _build(self) -> None:
        outer = tk.Frame(
            self.window,
            bg=COLORS["paper"],
            padx=self._px(30),
            pady=self._px(22),
        )
        outer.pack(fill="both", expand=True)

        heading = tk.Frame(outer, bg=COLORS["paper"])
        heading.pack(fill="x")
        tk.Label(
            heading,
            text="随笔记录",
            bg=COLORS["paper"],
            fg=COLORS["ink"],
            font=widget_font(20, self.ui_scale, serif=True),
            anchor="w",
        ).pack(side="left")
        meta = (
            f"创建于 {self.note.local_date}"
            if self.note is not None
            else "只保存在这台设备上"
        )
        tk.Label(
            heading,
            text=meta,
            bg=COLORS["paper"],
            fg=COLORS["muted"],
            font=widget_font(9, self.ui_scale),
            anchor="e",
        ).pack(side="right")

        title_shell = tk.Frame(
            outer,
            bg=COLORS["card"],
            highlightbackground=COLORS["line"],
            highlightthickness=self._px(1),
        )
        title_shell.pack(fill="x", pady=(self._px(12), self._px(10)))
        self.title_entry = tk.Entry(
            title_shell,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=COLORS["card"],
            fg=COLORS["ink"],
            insertbackground=COLORS["pine"],
            font=widget_font(13, self.ui_scale),
        )
        self.title_entry.pack(
            fill="x",
            padx=self._px(14),
            pady=self._px(9),
        )
        self.title_entry.bind("<FocusIn>", self._on_title_focus_in)
        self.title_entry.bind("<FocusOut>", self._on_title_focus_out)

        self._build_toolbar(outer)

        # 先占住底栏，再让正文吃掉剩余高度；否则正文的请求高度会把按钮挤出视野。
        footer = tk.Frame(outer, bg=COLORS["paper"])
        footer.pack(side="bottom", fill="x", pady=(self._px(2), 0))
        if self.note_id is not None:
            self._action_button(
                footer, "删除", self._delete, danger=True
            ).pack(side="left")
        self.hint_var = tk.StringVar(value=EDITOR_HINT)
        self.hint_label = tk.Label(
            footer,
            textvariable=self.hint_var,
            bg=COLORS["paper"],
            fg=COLORS["muted"],
            font=widget_font(9, self.ui_scale),
            anchor="w",
            justify="left",
        )
        self.hint_label.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(self._px(12), self._px(8)),
        )
        self._action_button(footer, "保存", self._save, primary=True).pack(side="right")
        self._action_button(footer, "取消", self._close).pack(
            side="right", padx=(0, self._px(8))
        )

        body_shell = tk.Frame(
            outer,
            bg=COLORS["card"],
            highlightbackground=COLORS["line"],
            highlightthickness=self._px(1),
        )
        body_shell.pack(
            fill="both",
            expand=True,
            pady=(self._px(10), self._px(10)),
        )
        self.text = tk.Text(
            body_shell,
            wrap="word",
            height=10,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=COLORS["card"],
            fg=COLORS["ink"],
            insertbackground=COLORS["pine"],
            selectbackground=COLORS["sage_soft"],
            selectforeground=COLORS["ink"],
            font=theme_font(DEFAULT_RUN_SIZE),
            padx=self._px(16),
            pady=self._px(14),
            spacing1=self._px(2),
            spacing2=self._px(4),
            spacing3=self._px(6),
            undo=True,
            autoseparators=True,
            maxundo=-1,
        )
        self.scrollbar = ttk.Scrollbar(
            body_shell,
            orient="vertical",
            command=self.text.yview,
        )
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.text.bind("<KeyPress>", self._on_text_keypress)
        self.text.bind("<Button-1>", self._on_text_click)
        self.text.bind("<<Selection>>", self._on_selection_changed)

    def _build_toolbar(self, parent: tk.Widget) -> None:
        shell = tk.Frame(
            parent,
            bg=COLORS["card"],
            highlightbackground=COLORS["line"],
            highlightthickness=self._px(1),
        )
        shell.pack(fill="x")
        row = tk.Frame(
            shell,
            bg=COLORS["card"],
            padx=self._px(10),
            pady=self._px(7),
        )
        row.pack(fill="x")

        self._tool_button(row, "A−", self._shrink_size).pack(side="left")
        self._tool_button(row, "A＋", self._grow_size).pack(
            side="left", padx=(self._px(4), 0)
        )
        self._toolbar_gap(row)

        self._tool_font_button(row, "B", self._toggle_bold, bold=True).pack(side="left")
        self._tool_font_button(row, "I", self._toggle_italic, italic=True).pack(
            side="left", padx=(self._px(4), 0)
        )
        self._toolbar_gap(row)

        tk.Label(
            row,
            text="字体",
            bg=COLORS["card"],
            fg=COLORS["sage"],
            font=widget_font(9, self.ui_scale, "bold"),
        ).pack(side="left", padx=(0, self._px(5)))

        self.family_var = tk.StringVar(value=DEFAULT_FONT_LABEL)
        combo_style = self._configure_combobox_style()
        self.family_box = ttk.Combobox(
            row,
            textvariable=self.family_var,
            values=self._font_choices(),
            state="readonly",
            width=16,
            font=widget_font(9, self.ui_scale),
            style=combo_style,
        )
        self.family_box.pack(side="left")
        self.family_box.bind("<<ComboboxSelected>>", self._on_family_selected)

        self._toolbar_gap(row)
        tk.Label(
            row,
            text="荧光笔",
            bg=COLORS["card"],
            fg=COLORS["sage"],
            font=widget_font(9, self.ui_scale, "bold"),
        ).pack(side="left", padx=(0, self._px(5)))
        for name, color in HIGHLIGHT_CHOICES:
            self._swatch(row, name, color)
        self._tool_button(row, "清除高亮", self._clear_highlight).pack(
            side="left", padx=(self._px(6), 0)
        )

    def _toolbar_gap(self, parent: tk.Widget) -> None:
        tk.Frame(
            parent,
            bg=COLORS["line"],
            width=max(1, self._px(1)),
            height=self._px(22),
        ).pack(side="left", padx=self._px(9))

    def _configure_combobox_style(self) -> str:
        style_name = "Qixin.TCombobox"
        try:
            style = ttk.Style(self.window)
            style.configure(
                style_name,
                fieldbackground=COLORS["card_alt"],
                background=COLORS["card_alt"],
                foreground=COLORS["ink"],
                arrowcolor=COLORS["ink_soft"],
                borderwidth=0,
                padding=self._px(3),
            )
        except tk.TclError:
            return "TCombobox"
        return style_name

    def _tool_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], None],
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            padx=self._px(6),
            pady=self._px(4),
            bg=COLORS["card_alt"],
            fg=COLORS["ink_soft"],
            activebackground=COLORS["sage_soft"],
            activeforeground=COLORS["ink"],
            cursor="hand2",
            font=widget_font(10, self.ui_scale, "bold"),
        )

    def _tool_font_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], None],
        *,
        bold: bool = False,
        italic: bool = False,
    ) -> tk.Button:
        # B / I 按钮用真正的中文字体变体，让工具栏一眼能看出含义。
        button_font = tkfont.Font(
            self.window,
            family=active_font_family(),
            size=-max(1, round(11 * self.ui_scale * self.font_scale)),
            weight="bold" if bold else "normal",
            slant="italic" if italic else "roman",
        )
        self._fonts.append(button_font)
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=2,
            relief="flat",
            bd=0,
            padx=self._px(2),
            pady=self._px(2),
            bg=COLORS["card_alt"],
            fg=COLORS["ink"],
            activebackground=COLORS["sage_soft"],
            activeforeground=COLORS["ink"],
            cursor="hand2",
            font=button_font,
        )

    def _action_button(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], Any],
        *,
        primary: bool = False,
        danger: bool = False,
    ) -> tk.Button:
        if primary:
            bg, fg = COLORS["pine"], COLORS["paper"]
        elif danger:
            bg, fg = COLORS["clay_soft"], COLORS["clay"]
        else:
            bg, fg = COLORS["card_alt"], COLORS["ink_soft"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            padx=self._px(16),
            pady=self._px(7),
            bg=bg,
            fg=fg,
            activebackground=mix_color(bg, COLORS["white"], 0.12),
            activeforeground=fg,
            cursor="hand2",
            font=widget_font(10, self.ui_scale, "bold"),
        )

    def _swatch(self, parent: tk.Widget, name: str, color: str) -> None:
        chip = tk.Frame(
            parent,
            bg=color,
            width=self._px(24),
            height=self._px(20),
            highlightbackground=COLORS["line"],
            highlightthickness=self._px(1),
            cursor="hand2",
        )
        chip.pack(side="left", padx=(0, self._px(4)))
        chip.bind("<Button-1>", lambda _event, value=color: self._apply_highlight(value))
        chip.bind("<Enter>", lambda _event: chip.configure(highlightbackground=COLORS["sage"]))
        chip.bind("<Leave>", lambda _event: chip.configure(highlightbackground=COLORS["line"]))

    # -- 初始内容 ---------------------------------------------------------

    def _font_choices(self) -> list[str]:
        try:
            families = [
                str(name)
                for name in tkfont.families(self.window)
                if not str(name).startswith("@")
            ]
        except tk.TclError:
            families = []
        available = set(families)
        choices: list[str] = [DEFAULT_FONT_LABEL]
        seen = {DEFAULT_FONT_LABEL}

        preferred = [
            active_font_family(),
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "SimSun",
            "SimHei",
            "KaiTi",
            "FangSong",
            "Noto Serif SC",
            "Segoe UI",
            "Arial",
            "Times New Roman",
            "Consolas",
        ]
        # 已有笔记若用了某个已安装字体，也让它在列表里可选。
        if self.note is not None:
            for run in self.note.runs:
                if run.family:
                    preferred.insert(1, run.family)
        for family in preferred:
            family = family.strip()
            if family and family in available and family not in seen:
                choices.append(family)
                seen.add(family)
        for family in sorted(families, key=str.casefold):
            if family not in seen:
                choices.append(family)
                seen.add(family)
        return choices

    def _load_content(self) -> None:
        if self.note is None:
            self.title_entry.insert(0, TITLE_PLACEHOLDER)
            self.title_entry.configure(fg=COLORS["muted"])
            self.family_var.set(DEFAULT_FONT_LABEL)
            self.text.mark_set("insert", "1.0")
            return

        self.title_entry.configure(fg=COLORS["ink"])
        if self.note.title:
            self.title_entry.delete(0, "end")
            self.title_entry.insert(0, self.note.title)
        else:
            self.title_entry.insert(0, TITLE_PLACEHOLDER)
            self.title_entry.configure(fg=COLORS["muted"])
        first = self.note.runs[0] if self.note.runs else None
        family = first.family if first is not None else ""
        self.family_var.set(family or DEFAULT_FONT_LABEL)
        self._render_runs(self.note.runs)
        if first is not None:
            self._caret_style = _RunStyle.from_run(first)
        self.text.mark_set("insert", "1.0")

    def _render_runs(self, runs: list[RichRun]) -> None:
        """把片段还原成带 tag 的 Text 内容（逐段插入，避免字符宽度换算）。"""

        self.text.delete("1.0", "end")
        for run in runs:
            if not run.text:
                continue
            style = _RunStyle.from_run(run)
            tag = self._style_tag(style)
            start = self.text.index("end-1c")
            self.text.insert("end", run.text)
            self.text.tag_add(tag, start, "end-1c")
        self.text.edit_reset()
        self.text.edit_modified(False)

    # -- tag 管理 ---------------------------------------------------------

    def _style_tag(self, style: _RunStyle) -> str:
        existing = self._tag_by_key.get(style.key)
        if existing is not None:
            return existing
        base = (
            f"run_{style.size}_{int(style.bold)}{int(style.italic)}_"
            f"{_tag_fragment(style.family)}_{_tag_fragment(style.highlight)}"
        )
        tag = base
        suffix = 2
        # 字体名/颜色名清洗后可能撞名，加序号保证唯一。
        while tag in self._tag_styles:
            tag = f"{base}_{suffix}"
            suffix += 1
        self.text.tag_configure(
            tag,
            font=style.tk_font(self.font_scale),
            background=style.highlight or "",
        )
        # 让选中态始终盖住荧光底色，否则选区会看不出来。
        self.text.tag_raise("sel")
        self._tag_styles[tag] = style
        self._tag_by_key[style.key] = tag
        return tag

    def _style_at(self, index: str) -> _RunStyle:
        try:
            names = set(self.text.tag_names(index))
        except tk.TclError:
            return self._caret_style
        style: _RunStyle | None = None
        # 字典顺序即 tag 建立顺序，越晚建立优先级越高。
        for tag, candidate in self._tag_styles.items():
            if tag in names:
                style = candidate
        return style or _RunStyle()

    # -- 工具栏动作 -------------------------------------------------------

    def _selected_range(self) -> tuple[str, str] | None:
        try:
            if not self.text.tag_ranges("sel"):
                return None
            return self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return None

    def _apply_style_change(
        self,
        transform: Callable[[_RunStyle], _RunStyle],
        describe: Callable[[_RunStyle], str],
    ) -> None:
        selection = self._selected_range()
        if selection is None:
            style = transform(self._caret_style)
            self._caret_style = style
            self.family_var.set(style.family or DEFAULT_FONT_LABEL)
            self._flash(f"已记下：{describe(style)}。接着输入就会生效。")
            self.text.focus_set()
            return

        start, end = selection
        style = transform(self._style_at(start))
        self._caret_style = style
        for tag in list(self._tag_styles):
            self.text.tag_remove(tag, start, end)
        self.text.tag_add(self._style_tag(style), start, end)
        self.family_var.set(style.family or DEFAULT_FONT_LABEL)
        self._flash(f"{describe(style)} · 已应用到选中的文字。")
        self.text.focus_set()

    def _grow_size(self) -> None:
        self._apply_style_change(
            lambda style: replace(style, size=_step_size(style.size, 1)),
            lambda style: f"字号 {style.size}",
        )

    def _shrink_size(self) -> None:
        self._apply_style_change(
            lambda style: replace(style, size=_step_size(style.size, -1)),
            lambda style: f"字号 {style.size}",
        )

    def _toggle_bold(self) -> None:
        self._apply_style_change(
            lambda style: replace(style, bold=not style.bold),
            lambda style: "加粗" if style.bold else "取消加粗",
        )

    def _toggle_italic(self) -> None:
        self._apply_style_change(
            lambda style: replace(style, italic=not style.italic),
            lambda style: "斜体" if style.italic else "取消斜体",
        )

    def _apply_highlight(self, color: str) -> None:
        self._apply_style_change(
            lambda style: replace(style, highlight=color),
            lambda style: f"荧光高亮（{_highlight_name(style.highlight)}）",
        )

    def _clear_highlight(self) -> None:
        self._apply_style_change(
            lambda style: replace(style, highlight=""),
            lambda style: "清除高亮",
        )

    def _on_family_selected(self, _event: tk.Event | None = None) -> None:
        family = self.family_var.get().strip()
        if family == DEFAULT_FONT_LABEL:
            family = ""
        self._apply_style_change(
            lambda style: replace(style, family=family),
            lambda style: f"字体 {style.family or DEFAULT_FONT_LABEL}",
        )

    # -- 事件 -------------------------------------------------------------

    def _on_title_focus_in(self, _event: tk.Event | None = None) -> None:
        if self.title_entry.get() == TITLE_PLACEHOLDER:
            self.title_entry.delete(0, "end")
            self.title_entry.configure(fg=COLORS["ink"])

    def _on_title_focus_out(self, _event: tk.Event | None = None) -> None:
        if not self.title_entry.get().strip():
            self.title_entry.delete(0, "end")
            self.title_entry.insert(0, TITLE_PLACEHOLDER)
            self.title_entry.configure(fg=COLORS["muted"])

    def _on_text_click(self, _event: tk.Event | None = None) -> None:
        # 点选正文后，用光标处已有格式作为后续输入的样式。
        try:
            self.window.after_idle(self._sync_caret_style)
        except tk.TclError:
            pass

    def _sync_caret_style(self) -> None:
        if self._closed:
            return
        try:
            self._caret_style = self._style_at("insert")
        except tk.TclError:
            return

    def _on_selection_changed(self, _event: tk.Event | None = None) -> None:
        selection = self._selected_range()
        if selection is None or self._closed:
            return
        try:
            style = self._style_at(selection[0])
        except tk.TclError:
            return
        self.family_var.set(style.family or DEFAULT_FONT_LABEL)

    def _on_text_keypress(self, event: tk.Event) -> None:
        if event.keysym in self._IGNORED_KEYS or bool(event.state & 0x0004):
            return
        start = self.text.index("insert")
        try:
            self.window.after_idle(lambda: self._style_typed_text(start))
        except tk.TclError:
            pass

    def _style_typed_text(self, start: str) -> None:
        """给刚输入的字符补上「待输入样式」的 tag。"""

        if self._closed:
            return
        try:
            end = self.text.index("insert")
            if self.text.compare(end, "<=", start):
                return
            if self.text.tag_ranges("sel"):
                return
            tag = self._style_tag(self._caret_style)
            for other in list(self._tag_styles):
                if other != tag:
                    self.text.tag_remove(other, start, end)
            self.text.tag_add(tag, start, end)
        except tk.TclError:
            return

    # -- 序列化 -----------------------------------------------------------

    def _serialize(self) -> list[RichRun]:
        """按字符把 tag 集合还原成片段，合并相邻的同格式区间。"""

        raw = self.text.get("1.0", "end-1c")
        if not raw:
            return []
        length = len(raw)
        offset_cache: dict[str, int] = {}

        def offset(index: str) -> int:
            value = offset_cache.get(index)
            if value is None:
                # 用前缀文本长度换算，避免 Tk 与 Python 在宽字符上的差异。
                value = len(self.text.get("1.0", index))
                offset_cache[index] = value
            return value

        events: dict[int, list[tuple[int, _RunStyle | None]]] = {}
        for priority, (tag, style) in enumerate(self._tag_styles.items()):
            ranges = self.text.tag_ranges(tag)
            for position in range(0, len(ranges) - 1, 2):
                start = offset(str(ranges[position]))
                end = offset(str(ranges[position + 1]))
                start = max(0, min(length, start))
                end = max(start, min(length, end))
                if end <= start:
                    continue
                events.setdefault(start, []).append((priority, style))
                events.setdefault(end, []).append((priority, None))

        runs: list[RichRun] = []
        active: dict[int, _RunStyle] = {}
        current = _RunStyle()
        previous = 0
        for position in sorted(events):
            if position > previous:
                self._append_run(runs, raw[previous:position], current)
            for priority, style in events[position]:
                if style is None:
                    active.pop(priority, None)
                else:
                    active[priority] = style
            current = active[max(active)] if active else _RunStyle()
            previous = position
        if previous < length:
            self._append_run(runs, raw[previous:], current)
        return runs

    @staticmethod
    def _append_run(runs: list[RichRun], text: str, style: _RunStyle) -> None:
        if not text:
            return
        if runs and runs[-1].style_key == style.key:
            runs[-1].text += text
            return
        runs.append(style.to_run(text))

    # -- 保存 / 删除 / 关闭 -----------------------------------------------

    def _title_value(self) -> str:
        value = self.title_entry.get()
        if value == TITLE_PLACEHOLDER:
            return ""
        return value.strip()

    def _save(self) -> None:
        title = self._title_value()
        runs = self._serialize()
        if not runs and not title and self.note_id is None:
            self._flash("先写一句，或者给这段随笔起个名字。", error=True)
            self.title_entry.focus_set()
            return
        try:
            note_id = save_note(self.store, runs, title=title, note_id=self.note_id)
        except (sqlite3.Error, ValueError) as exc:
            self._flash(f"保存失败：{exc}", error=True)
            return
        self.note_id = note_id
        callback = self.on_saved
        self._close()
        if callback is not None:
            callback(note_id)

    def _save_shortcut(self, _event: tk.Event | None = None) -> str:
        self._save()
        return "break"

    def _delete(self) -> None:
        if self.note_id is None:
            return
        confirmed = messagebox.askyesno(
            "删除随笔",
            "删除后无法恢复，确定要删除这条随笔吗？",
            parent=self.window,
        )
        if not confirmed:
            return
        try:
            delete_note(self.store, self.note_id)
        except sqlite3.Error as exc:
            self._flash(f"删除失败：{exc}", error=True)
            return
        self._close()

    def _flash(self, message: str, *, error: bool = False) -> None:
        if self._closed:
            return
        self.hint_var.set(message)
        self.hint_label.configure(
            fg=COLORS["clay"] if error else COLORS["sage"],
        )
        if self._hint_job is not None:
            try:
                self.window.after_cancel(self._hint_job)
            except tk.TclError:
                pass
        self._hint_job = self.window.after(3200, self._restore_hint)

    def _restore_hint(self) -> None:
        self._hint_job = None
        if self._closed:
            return
        self.hint_var.set(EDITOR_HINT)
        self.hint_label.configure(fg=COLORS["muted"])

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._hint_job is not None:
            try:
                self.window.after_cancel(self._hint_job)
            except tk.TclError:
                pass
            self._hint_job = None
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    # -- 对外 -------------------------------------------------------------

    def show(self) -> None:
        if self._closed:
            return
        try:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
        except tk.TclError:
            return
        # 直接进入正文，标题占位符保持可见，点进标题框时再清空。
        self.text.focus_set()


def _step_size(size: int, direction: int) -> int:
    """在 12/14/16/18/20/24 之间跳档，超出档位后按 2px 增减。"""

    if direction > 0:
        for value in FONT_SIZE_CHOICES:
            if value > size:
                return value
        return min(MAX_RUN_SIZE, size + 2)
    for value in reversed(FONT_SIZE_CHOICES):
        if value < size:
            return value
    return max(MIN_RUN_SIZE, size - 2)
