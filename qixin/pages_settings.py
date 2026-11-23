"""数据与设置页：内容驱动、随字号自适应的布局。

页面显示设置可以管理侧栏入口和页面里的各个区块。其他卡片管理连接、数据、
字体与外观，以及两张四维情境示例。

排版全部通过 :class:`qixin.layout.Block` 游标完成：每张卡片先用
``draw=False`` 探测内容高度，再用 ``draw=True`` 真正绘制，所以字号放大时
页面会自然变长（外层画布支持滚动），文字不会压叠，也不会溢出处卡片。
"""

from __future__ import annotations

from functools import partial

from .content import time_bucket
from .layout import Block
from .theme import COLORS, mix_color

DATA_CARD_FILL = COLORS["card_alt"]
DATA_CARD_LINE = COLORS["line"]
SCENARIO_CARD_FILL = COLORS["sunken"]

FEATURE_GROUPS = (
    ("首页卡片", (
        ("home_focus", "专注计时"),
        ("home_next", "下一件事"),
        ("home_quote", "今日一句"),
        ("home_mood", "心情记录"),
        ("home_tasks", "今日待办"),
        ("home_inbox", "待办收件箱"),
        ("home_care", "每日寄语"),
        ("home_font", "阅读字号"),
    )),
    ("侧栏页面", (
        ("calendar", "情绪日历"),
        ("music", "情境歌单"),
        ("essay", "随笔记录"),
        ("news", "学院新闻"),
    )),
    ("情境歌单", (
        ("music_inputs", "四维共情"),
        ("music_links", "快捷歌单"),
        ("music_recommendation", "此刻推荐"),
        ("music_candidates", "候选曲目"),
    )),
    ("情绪日历", (
        ("calendar_overview", "月度概览"),
        ("calendar_day", "当日详情"),
        ("calendar_notes", "随笔预览"),
        ("calendar_week", "本周回顾"),
    )),
    ("学院新闻", (("news_reminders", "记得抢选"),)),
)
CONFIGURABLE_SECTIONS = frozenset(
    key for _, entries in FEATURE_GROUPS for key, _ in entries
)

PRIVACY_NOTE = (
    "天气请求只包含城市坐标；AI 请求只包含你主动选择的心情、"
    "活动与天气标签，不包含任务原文、情绪历史或设备标识。"
)


# --------------------------------------------------------------------- 页面入口
def draw_settings(app) -> float:
    """渲染设置页，返回内容底部 y（逻辑单位）。"""

    margin, gap, usable = app._page_metrics()
    top = margin + app._flow_card(
        margin, margin, usable, partial(_visibility_body, app),
        fill=COLORS["card_alt"],
    ) + gap
    music_visible = app.feature_visible("music")

    if app._use_two_columns():
        # 两栏：左「连接 + 数据」，右「字体与外观 + 情境」，两列高度接近。
        left_width = round(usable * 0.55)
        right_width = usable - left_width - gap
        right_x = margin + left_width + gap

        y_left = top
        y_left += app._flow_card(
            margin, y_left, left_width, partial(_connections_body, app)
        ) + gap
        y_left += app._flow_card(
            margin,
            y_left,
            left_width,
            partial(_data_body, app),
            fill=DATA_CARD_FILL,
            outline=DATA_CARD_LINE,
        )

        y_right = top
        y_right += app._flow_card(
            right_x, y_right, right_width, partial(_type_look_body, app)
        )
        if music_visible:
            y_right += gap + app._flow_card(
                right_x, y_right + gap, right_width,
                partial(_scenarios_body, app), fill=SCENARIO_CARD_FILL,
            )
        return max(y_left, y_right) + margin

    # 单栏：字号较大时自上而下堆叠，顺序与功能清单一致。
    cards = [
        (partial(_connections_body, app), COLORS["card"], COLORS["line"]),
        (partial(_data_body, app), DATA_CARD_FILL, DATA_CARD_LINE),
        (partial(_type_look_body, app), COLORS["card"], COLORS["line"]),
    ]
    if music_visible:
        cards.append((partial(_scenarios_body, app), SCENARIO_CARD_FILL, COLORS["line"]))
    y = top
    for body, fill, outline in cards:
        y += app._flow_card(margin, y, usable, body, fill=fill, outline=outline) + gap
    return y - gap + margin


def _visibility_body(app, block: Block) -> None:
    _section_head(block, "页面显示", "选择会自动保存。")
    expanded = getattr(app, "_visibility_group", None)

    def open_group(title):
        app._visibility_group = None if expanded == title else title
        app.render()

    for index, (title, entries) in enumerate(FEATURE_GROUPS):
        block.gap(8)
        count = sum(app.feature_visible(key) for key, _ in entries)
        block.button(f"visibility_group_{index}",
                     f"{title} · 已显示 {count}/{len(entries)} 项  {'▴' if expanded == title else '▾'}",
                     partial(open_group, title), style="ghost", size=11, height=34)
        if expanded != title:
            continue
        for key, label in entries:
            top = block.y + block.sz(5)
            visible = app.feature_visible(key)
            width = block.button_right(f"visibility_{key}", "● 开" if visible else "○ 关",
                                       partial(app._toggle_feature_visibility, key),
                                       size=10, height=30, style="sage" if visible else "ghost", y=top)
            block.y = top
            block.text(label, 11, COLORS["ink"], width=block.width - width - block.sz(12))
            block.y = max(block.y, top + block.sz(30))
    block.gap(12)
    block.button("visibility_reset", "恢复全部", app._restore_feature_visibility,
                 style="secondary", size=10, height=32)


# --------------------------------------------------------------------- 小工具
def _section_head(block: Block, title: str, subtitle: str) -> None:
    """卡片标题 + 一句说明（宽度由 Block 决定，自动换行）。"""

    block.text(title, 17, COLORS["ink"], weight="bold", serif=True)
    block.gap(3)
    block.text(subtitle, 9, COLORS["muted"], spacing=2)


def _action_head(
    app,
    block: Block,
    title: str,
    subtitle: str,
    action: tuple[str, str, object, str, str],
) -> None:
    """标题行右侧挂一个紧凑按钮，副标题另起一行。"""

    tag, label, command, style, prefix = action
    row_top = block.y
    button_width = block.button_right(
        tag,
        label,
        command,
        size=9,
        height=28,
        style=style,
        prefix=prefix,
        y=row_top,
    )
    block.text(
        title,
        17,
        COLORS["ink"],
        weight="bold",
        serif=True,
        width=max(block.sz(120), block.width - button_width - block.sz(12)),
    )
    block.y = max(block.y, row_top + block.sz(28)) + block.sz(3)
    block.text(subtitle, 9, COLORS["muted"], spacing=2)


def _button_grid(
    block: Block,
    entries: list[tuple[str, str, object, str, str]],
    *,
    size: int = 9,
    height: float = 36,
    gap: float = 8,
    row_gap: float = 8,
    pad: float = 30,
    min_width: float = 72,
) -> None:
    """把 ``(tag, 文案, 回调, 风格, 前缀)`` 按钮自动换行排布。

    同一行的按钮平分剩余宽度，因此右侧不会留下参差不齐的空洞；行数由当前
    字号下的实际文字宽度决定，不写死列数。
    """

    measured: list[tuple[str, str, object, str, str, float]] = []
    for tag, label, command, style, prefix in entries:
        text = (prefix + " " if prefix else "") + label
        natural = block.meter.measure(text, size, "bold") + block.sz(pad)
        measured.append(
            (tag, label, command, style, prefix, max(natural, block.sz(min_width)))
        )

    gap_px = block.sz(gap)
    row_gap_px = block.sz(row_gap)
    rows: list[tuple[list[tuple[str, str, object, str, str, float]], float]] = []
    row: list[tuple[str, str, object, str, str, float]] = []
    used = 0.0
    for item in measured:
        needed = item[5] if not row else item[5] + gap_px
        if row and used + needed > block.width:
            rows.append((row, used))
            row = [item]
            used = item[5]
        else:
            row.append(item)
            used += needed
    if row:
        rows.append((row, used))

    button_height = block.sz(height)
    for index, (row_items, used_width) in enumerate(rows):
        extra = block.width - used_width
        share = extra / len(row_items) if extra > 0 else 0.0
        cursor = block.x
        for tag, label, command, style, prefix, natural in row_items:
            width = natural + share
            block.button_at(
                tag,
                label,
                command,
                cursor,
                block.y,
                width,
                button_height,
                style=style,
                size=size,
                prefix=prefix,
            )
            cursor += width + gap_px
        block.y += button_height
        if index < len(rows) - 1:
            block.y += row_gap_px


# --------------------------------------------------------------------- 连接与智能
def _services(app) -> list[tuple[str, str, bool]]:
    ai_online = bool(app.ai.configured)
    weather_online = bool(app.weather.live)
    return [
        (
            "AI 情境理解",
            "已连接兼容 Chat Completions 的模型服务"
            if ai_online
            else "未配置 API Key · 正在使用本地策展规则",
            ai_online,
        ),
        (
            "本地天气",
            f"Open-Meteo · {app.weather.city} · "
            + ("实时已同步" if weather_online else "当前为离线示例"),
            weather_online,
        ),
        (
            "情境音乐",
            "内置程序化音景 × 人工策展标签 × 可选外链音乐服务",
            True,
        ),
    ]


def _connections_body(app, block: Block) -> None:
    _action_head(
        app,
        block,
        "连接与智能",
        "基础体验始终离线可用；外部服务只在你主动配置后参与。",
        (
            "settings_weather_now",
            "立即刷新天气",
            app._fetch_weather_now,
            "ghost",
            "↻",
        ),
    )
    block.gap(7)
    for index, (title, description, online) in enumerate(_services(app)):
        if index:
            block.gap(8)
        _service_row(app, block, title, description, online)
    block.gap(8)
    block.button(
        "settings_ai_help",
        "查看 AI 接入方式",
        app._show_ai_help,
        style="secondary",
        size=10,
        height=36,
        prefix="⌁",
    )


def _service_row(app, block: Block, title: str, description: str, online: bool) -> None:
    pad = block.sz(12)
    dot = block.sz(18)
    inner_dot = block.sz(6)
    badge = "已启用" if online else "本地模式"
    badge_width = block.meter.measure(badge, 8)
    text_x = block.x + pad + dot + block.sz(10)
    text_width = max(
        block.sz(90),
        block.width - (text_x - block.x) - badge_width - block.sz(16),
    )
    title_height = block.meter.height(title, 11, text_width, "bold")
    desc_height = block.meter.height(description, 8, text_width)
    row_height = pad * 2 + title_height + block.sz(4) + desc_height

    top = block.y
    if block.draw:
        canvas = block.canvas
        app.kit.draw_round(
            canvas,
            block.x,
            top,
            block.x + block.width,
            top + row_height,
            round(block.sz(12)),
            COLORS["sunken"] if online else COLORS["card_alt"],
            None,
            0,
        )
        dot_top = top + pad + block.sz(2)
        canvas.create_oval(
            block.x + pad,
            dot_top,
            block.x + pad + dot,
            dot_top + dot,
            fill=COLORS["sage_soft"] if online else COLORS["card_alt"],
            outline="",
        )
        canvas.create_oval(
            block.x + pad + (dot - inner_dot) / 2,
            dot_top + (dot - inner_dot) / 2,
            block.x + pad + (dot + inner_dot) / 2,
            dot_top + (dot + inner_dot) / 2,
            fill=COLORS["sage"] if online else COLORS["muted"],
            outline="",
        )
        app._text(
            canvas,
            text_x,
            top + pad,
            title,
            11,
            COLORS["ink"],
            weight="bold",
            width=text_width,
        )
        app._text(
            canvas,
            text_x,
            top + pad + title_height + block.sz(4),
            description,
            8,
            COLORS["muted"],
            width=text_width,
        )
        app._text(
            canvas,
            block.x + block.width - pad,
            top + pad,
            badge,
            8,
            COLORS["sage"] if online else COLORS["muted"],
            anchor="ne",
        )
    block.y = top + row_height


# --------------------------------------------------------------------- 只属于你的数据
def _data_body(app, block: Block) -> None:
    counts = app.store.recap_counts()
    subtitle = "SQLite 保存在本机，不做云端同步，不用于训练。"
    if app.demo:
        subtitle += "   ·   演示数据"
    _section_head(block, "只属于你的数据", subtitle)
    block.gap(7)
    _metrics_band(app, block, counts)
    block.gap(7)
    _path_panel(app, block)
    block.gap(7)
    _button_grid(
        block,
        [
            ("export_json", "导出 JSON", app._export_json, "secondary", "↓"),
            (
                "open_data_folder",
                "打开数据目录",
                app._open_data_folder,
                "ghost",
                "↗",
            ),
        ],
    )
    block.gap(7)
    block.divider()
    block.gap(7)
    block.label("隐私原则", 8, COLORS["sage"], spacing=4)
    block.text(PRIVACY_NOTE, 9, COLORS["ink_soft"], spacing=3)
    block.gap(7)
    block.button(
        "export_report",
        "导出本周《情绪与哲思周报》",
        app._export_report,
        style="ghost",
        size=9,
        height=38,
        prefix="↗",
    )


def _metrics_band(app, block: Block, counts: dict) -> None:
    pad = block.sz(12)
    number_height = block.meter.line_height(24, serif=True)
    label_height = block.meter.line_height(9)
    band_height = pad * 2 + number_height + block.sz(3) + label_height
    top = block.y
    if block.draw:
        canvas = block.canvas
        app.kit.draw_round(
            canvas,
            block.x,
            top,
            block.x + block.width,
            top + band_height,
            round(block.sz(14)),
            COLORS["card"],
            None,
            0,
        )
        cell = block.width / 3
        metrics = (
            ("心情", counts["mood_count"], COLORS["pine"]),
            ("计划", counts["task_count"], COLORS["clay"]),
            ("音景", counts["playlist_count"], COLORS["sage"]),
        )
        for index, (label, value, color) in enumerate(metrics):
            cell_x = block.x + cell * index + block.sz(14)
            if index:
                canvas.create_line(
                    block.x + cell * index,
                    top + block.sz(12),
                    block.x + cell * index,
                    top + band_height - block.sz(12),
                    fill=COLORS["line"],
                    width=1,
                )
            app._text(canvas, cell_x, top + pad, str(value), 24, color, serif=True)
            app._text(
                canvas,
                cell_x,
                top + pad + number_height + block.sz(3),
                label,
                9,
                COLORS["muted"],
            )
    block.y = top + band_height


def _path_panel(app, block: Block) -> None:
    pad = block.sz(12)
    label_height = block.meter.line_height(8, "bold")
    inner_width = block.width - pad * 2
    path_text = _fit_tail(app, str(app.store.path), inner_width, 8)
    path_height = block.meter.height(path_text, 8, inner_width)
    panel_height = pad * 2 + label_height + block.sz(4) + path_height
    top = block.y
    if block.draw:
        canvas = block.canvas
        app.kit.draw_round(
            canvas,
            block.x,
            top,
            block.x + block.width,
            top + panel_height,
            round(block.sz(12)),
            COLORS["card"],
            None,
            0,
        )
        app._text(
            canvas,
            block.x + pad,
            top + pad,
            "本地位置",
            8,
            COLORS["sage"],
            weight="bold",
        )
        app._text(
            canvas,
            block.x + pad,
            top + pad + label_height + block.sz(4),
            path_text,
            8,
            COLORS["ink_soft"],
            width=inner_width,
        )
    block.y = top + panel_height


def _fit_tail(app, text: str, width: float, size: int) -> str:
    """把过长的路径从左侧截断，保留信息更多的目录尾部。"""

    meter = app.meter
    if meter.measure(text, size) <= width:
        return text
    trimmed = text
    while trimmed and meter.measure("…" + trimmed, size) > width:
        trimmed = trimmed[1:]
    return "…" + trimmed if trimmed else "…"


# --------------------------------------------------------------------- 字体与外观
def _type_look_body(app, block: Block) -> None:
    _section_head(
        block,
        "字体与外观",
        "阅读字体、背景、左上角图标与桌宠，都只保存在本机。",
    )
    block.gap(10)
    _font_section(app, block)
    block.gap(10)
    block.divider()
    block.gap(8)
    _appearance_section(app, block)


def _font_section(app, block: Block) -> None:
    block.label("阅读字体", 8, COLORS["sage"], spacing=4)
    block.text(app.font_library.display_name, 13, COLORS["ink"], weight="bold")
    block.gap(8)
    _button_grid(
        block,
        [
            ("settings_change_font", "更换字体", app._choose_custom_font, "secondary", "Aa"),
            ("settings_reset_font", "恢复默认字体", app._reset_custom_font, "ghost", "↺"),
        ],
    )
    block.gap(6)
    block.text(
        "在首页底部「阅读字号」用 A− / A＋ 调整文字与卡片大小。",
        8,
        COLORS["muted"],
        spacing=2,
    )


def _appearance_section(app, block: Block) -> None:
    block.label("背景与图标", 8, COLORS["sage"], spacing=6)
    _button_grid(
        block,
        [
            ("settings_background", "更换背景", app._choose_background, "ghost", "▤"),
            (
                "settings_background_reset",
                "恢复默认背景",
                app._reset_background,
                "ghost",
                "↺",
            ),
            ("settings_icon", "更换左上角图标", app._choose_app_icon, "ghost", "◈"),
            ("settings_icon_reset", "恢复默认图标", app._reset_app_icon, "ghost", "↺"),
            (
                "settings_change_pet",
                "更换桌宠外观",
                app._choose_pet_image,
                "secondary",
                "✦",
            ),
        ],
        pad=22,
    )


# --------------------------------------------------------------------- 四维情境
def _scenarios(app) -> list[dict]:
    bucket = time_bucket()
    return [
        {
            "tag": "demo_sunny",
            "number": "场景 01",
            "title": "晴天 · 美美得很 · 写论文",
            "desc": "上午的光落在桌上，准备推进论文引言。",
            "dims": ("晴", "美美得很", "写论文", bucket),
            "fill": COLORS["gold_soft"],
            "accent": COLORS["gold"],
            "command": partial(app._launch_scenario, "晴", "美美得很", "写论文"),
        },
        {
            "tag": "demo_cloudy",
            "number": "场景 02",
            "title": "阴天 · 活人微死 · 复习考试",
            "desc": "夜色和云层压低，考试周还要继续翻一页。",
            "dims": ("阴", "活人微死", "复习考试", bucket),
            "fill": COLORS["iris_soft"],
            "accent": COLORS["blue"],
            "command": partial(app._launch_scenario, "阴", "活人微死", "复习考试"),
        },
    ]


def _scenarios_body(app, block: Block) -> None:
    _section_head(
        block,
        "两组四维情境",
        "天气 × 心情 × 活动 × 时段，点一下就能生成对应的歌单与寄语。",
    )
    block.gap(8)
    items = _scenarios(app)
    if block.width >= block.sz(760):
        # 单栏宽卡：两张场景卡并排，避免右侧留下大片空白。
        gap = block.sz(12)
        width = (block.width - gap) / 2
        top = block.y
        tallest = 0.0
        for index, scenario in enumerate(items):
            tallest = max(
                tallest,
                _scenario_panel(
                    app,
                    block,
                    scenario,
                    x=block.x + index * (width + gap),
                    width=width,
                    advance=False,
                ),
            )
        block.y = top + tallest
        return
    for index, scenario in enumerate(items):
        if index:
            block.gap(6)
        _scenario_panel(app, block, scenario)


def _scenario_panel(
    app,
    block: Block,
    scenario: dict,
    *,
    x: float | None = None,
    width: float | None = None,
    advance: bool = True,
) -> float:
    """在 ``block`` 当前位置画一张场景卡；高度由卡内内容测量得出。"""

    tag = str(scenario["tag"])
    left = block.x if x is None else x
    panel_width = block.width if width is None else width
    pad_x = block.sz(16)
    pad_y = block.sz(10)
    inner_width = max(block.sz(80), panel_width - pad_x * 2)

    probe = Block(app, block.canvas, left + pad_x, block.y + pad_y, inner_width, draw=False)
    _scenario_content(app, probe, scenario)
    panel_height = probe.used + pad_y * 2

    top = block.y
    if block.draw:
        canvas = block.canvas
        panel_radius = block.sz(20)
        panel_item = app.kit.draw_round(
            canvas,
            left,
            top,
            left + panel_width,
            top + panel_height,
            round(panel_radius),
            scenario["fill"],
            mix_color(scenario["accent"], COLORS["white"], 0.55),
            1,
            (tag,),
        )
        app.motion.add_surface(
            canvas,
            panel_item,
            (left, top, left + panel_width, top + panel_height),
            panel_radius,
            scenario["fill"],
            None,
            mix_color(scenario["accent"], COLORS["white"], 0.55),
            1,
            hover_fill=mix_color(scenario["fill"], scenario["accent"], 0.06),
            hover_outline=mix_color(scenario["accent"], COLORS["white"], 0.25),
            sheen_color=scenario["accent"],
            sheen_strength=0.22,
            press_scale=0.0,
        )
        painter = Block(
            app, canvas, left + pad_x, top + pad_y, inner_width, draw=True
        )
        _scenario_content(app, painter, scenario)
        canvas.tag_bind(tag, "<Button-1>", lambda _event, fn=scenario["command"]: fn())
        canvas.tag_bind(tag, "<Enter>", lambda _event: canvas.configure(cursor="hand2"))
        canvas.tag_bind(tag, "<Leave>", lambda _event: canvas.configure(cursor=""))
    if advance:
        block.y = top + panel_height
    return panel_height


def _scenario_content(app, inner: Block, scenario: dict) -> None:
    tag = str(scenario["tag"])
    row_top = inner.y
    dot = inner.sz(10)
    number_height = inner.meter.line_height(8, "bold")
    if inner.draw:
        canvas = inner.canvas
        canvas.create_oval(
            inner.x,
            row_top + inner.sz(4),
            inner.x + dot,
            row_top + inner.sz(4) + dot,
            fill=scenario["accent"],
            outline="",
            tags=(tag,),
        )
        app._text(
            canvas,
            inner.x + dot + inner.sz(8),
            row_top,
            str(scenario["number"]),
            8,
            COLORS["sage"],
            weight="bold",
            tags=(tag,),
        )
    inner.y = row_top + max(dot + inner.sz(4), number_height) + inner.sz(4)

    inner.text(
        str(scenario["title"]),
        15,
        COLORS["ink"],
        weight="bold",
        serif=True,
        spacing=2,
        tags=(tag,),
    )
    inner.gap(4)
    inner.text(
        str(scenario["desc"]),
        9,
        COLORS["ink_soft"],
        spacing=3,
        tags=(tag,),
    )
    inner.gap(8)
    inner.chip_rows(
        [
            (
                f"{tag}_dim_{index}",
                str(dim),
                True,
                scenario["command"],
                scenario["accent"],
            )
            for index, dim in enumerate(scenario["dims"])
        ],
        size=9,
        gap=6,
        row_gap=6,
    )
    inner.gap(8)
    inner.button(
        f"{tag}_go",
        "进入这段情境",
        scenario["command"],
        style="primary",
        size=10,
        height=36,
        prefix="→",
    )
