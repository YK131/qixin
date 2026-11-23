"""情境歌单页 —— 内容驱动、随字号自适应的布局。

This module owns the music page that used to live as a wall of absolute
coordinates inside ``QixinApp._draw_music``.  Everything here is built from
:class:`~qixin.layout.Block` cursors: a card is measured through
``app._flow_card`` and every element inside it pushes the cursor forward, so
no hard-coded ``y`` survives.  When the font grows the page simply becomes
taller (the page canvas already scrolls instead of clipping).

The card boundaries are the only horizontal anchors in this module — the
``x``/``width`` handed to ``app._flow_card`` — which is exactly what makes the
two-column / single-column switch possible.

Integration is expected to be done by the caller::

    app._draw_music = types.MethodType(lambda self: draw_music(self), app)

2026 版的重点（用户原话：「九龙湖的白噪音零个人愿意听，接入歌单等等」）：
卡片上写明曲种 / BPM / 匹配理由，并直接给出「打开歌单」入口——本地只有
18 秒试听，真正的音乐在平台官方搜索页里。四维卡下方另有一行「不想选？
按此刻心情直接开歌单」，把当前 mood + activity 当作关键词。
"""

from __future__ import annotations

from typing import Any

from . import playlists
from .content import ACTIVITIES, care_note, time_bucket
from .layout import Block, fit_text
from .theme import COLORS, mix_color

__all__ = ["draw_music"]

#: 天气场景 chips (顺序沿用旧页面)。
_WEATHER_MODES = ("自动", "晴", "阴", "雨")

#: 曲种徽章配色：与 :data:`qixin.tracks.KINDS` 一一对应。
_KIND_COLORS = {
    "钢琴": "#9C7A4E",
    "吉他": "#A26B4F",
    "Lo-fi": "#5F7F80",
    "City Pop": "#6B7194",
    "古典": "#8A7350",
    "爵士": "#4E7F85",
    "轻电子": "#6C7F96",
    "民谣": "#A8785A",
    "后摇": "#617B68",
    "Bossa Nova": "#B0854F",
    "古风": "#7E6E92",
    "流行": "#C06A8E",
    "R&B": "#7A6BC4",
    "摇滚": "#B4553F",
    "原声": "#5E8A8A",
}


# --------------------------------------------------------------------- page


def draw_music(app) -> float:
    """渲染歌单页，返回内容底部 y（逻辑单位）。"""

    margin, gap, usable = app._page_metrics()
    inputs = [
        (key, body, fill) for key, body, fill in (
            ("music_inputs", _inputs_body, COLORS["card"]),
            ("music_links", _quick_playlist_body, COLORS["sage_soft"]),
        ) if app.feature_visible(key)
    ]
    recommend = app.feature_visible("music_recommendation")
    candidates = app.feature_visible("music_candidates")
    if not (inputs or recommend or candidates):
        return app._draw_no_visible_sections()

    bottom = margin
    if recommend:
        bottom += app._flow_card(
            margin, bottom, usable, lambda block: _recommend_body(app, block),
            fill=COLORS["iris_soft"], tags=("music_recommendation",),
        ) + gap
    for key, body, fill in inputs:
        bottom += app._flow_card(
            margin, bottom, usable, lambda block, draw=body: draw(app, block),
            fill=fill, tags=(key,),
        ) + gap
    if candidates:
        bottom += app._flow_card(
            margin, bottom, usable, lambda block: _candidates_body(app, block),
            tags=("music_candidates",),
        ) + gap

    bottom -= gap
    bottom += _footer(app, margin, bottom, usable)
    return bottom + margin


def _footer(app, x: float, y: float, width: float) -> float:
    """底部隐私提示，返回它占用的高度。"""

    top = y + app._sz(12)
    block = Block(app, app.page_canvas, x, top, width, draw=True)
    block.text(
        "试听音频仅在你的设备上生成 · 外部歌单在平台官方搜索页打开，不绑定账号",
        11,
        COLORS["muted"],
        width=width,
    )
    return app._sz(12) + block.used


# ------------------------------------------------------------ input card body


def _inputs_body(app, block: Block) -> None:
    expanded = getattr(app, "_music_context_open", False)

    def toggle():
        app._music_context_open = not expanded
        app.render()

    top = block.y
    button_width = block.button_right(
        "music_context", "收起情境" if expanded else "调整情境", toggle,
        size=11, height=32, style="ghost",
    )
    block.text("四维共情", 17, COLORS["ink"], serif=True, weight="bold",
               width=block.width - button_width - block.sz(12))
    block.y = max(block.y, top + block.sz(32))
    block.text(f"{app.music_mood} · {app.music_activity} · {app._effective_weather()} · {time_bucket()}",
               12, COLORS["ink_soft"])
    if not expanded:
        return
    block.gap(16)

    # 01 心情：每个心情带自己的颜色。
    block.label("此刻心情", 12, COLORS["sage"], spacing=6)
    block.chip_rows(_mood_entries(app), size=12, gap=8, row_gap=8)
    block.gap(14)

    # 02 准备做什么。
    block.label("准备做什么", 12, COLORS["sage"], spacing=6)
    block.chip_rows(_activity_entries(app), size=12, gap=8, row_gap=8)
    block.gap(14)

    # 03 天气场景。
    block.label("天气场景", 12, COLORS["sage"], spacing=6)
    block.chip_rows(_weather_entries(app), size=12, gap=8, row_gap=8)
    block.gap(12)

    # 04 当前时间：只读展示，左右一行（放不下时自动换成两行）。
    _split_row(
        app,
        block,
        "当前时间",
        12,
        COLORS["sage"],
        f"{time_bucket()} · 只读",
        12,
        COLORS["ink_soft"],
    )
    block.gap(16)

    block.button(
        "generate_playlist",
        "生成此刻歌单",
        app._generate_playlist,
        style="primary",
        size=14,
        height=44,
        prefix="≈",
    )


def _mood_entries(app) -> list[tuple[str, str, bool, object, str]]:
    entries: list[tuple[str, str, bool, object, str]] = []
    for index, mood in enumerate(app.mood_order):
        config = app.moods[mood]
        entries.append(
            (
                f"music_mood_{index}",
                mood,
                mood == app.music_mood,
                lambda value=mood: app._set_music_mood(value),
                str(config["color"]),
            )
        )
    return entries


def _activity_entries(app) -> list[tuple[str, str, bool, object, str]]:
    return [
        (
            f"music_activity_{index}",
            activity,
            activity == app.music_activity,
            lambda value=activity: app._set_music_activity(value),
            COLORS["blue"],
        )
        for index, activity in enumerate(ACTIVITIES)
    ]


def _weather_entries(app) -> list[tuple[str, str, bool, object, str]]:
    return [
        (
            f"weather_mode_{index}",
            mode,
            mode == app.weather_mode,
            lambda value=mode: app._set_weather_mode(value),
            COLORS["gold"],
        )
        for index, mode in enumerate(_WEATHER_MODES)
    ]


# ------------------------------------------------------- quick playlist card


def _quick_playlist_body(app, block: Block) -> None:
    """「不想选？按此刻心情直接开歌单」——两个平台按钮。"""

    block.label("不想选？按此刻心情直接开歌单", 13, COLORS["ink"], spacing=5)
    keyword = playlists.mood_keyword(app.music_mood, app.music_activity)
    block.text(
        f"关键词「{keyword}」· 在平台官方搜索页打开，不登录也能看",
        11,
        COLORS["muted"],
        spacing=3,
    )
    block.gap(8)

    links = playlists.mood_links(app.music_mood, app.music_activity)
    gap = block.sz(8)
    button_width = (block.width - gap * (len(links) - 1)) / max(1, len(links))
    button_height = block.sz(34)
    top = block.y
    for index, link in enumerate(links):
        left = block.x + index * (button_width + gap)
        block.button_at(
            f"quick_playlist_{index}",
            link["platform"],
            lambda item=link: _open_link(app, item),
            left,
            top,
            button_width,
            button_height,
            style="sage",
            size=11,
            prefix="↗",
        )
    block.y = top + button_height


# ------------------------------------------------- recommendation card body


def _recommend_body(app, block: Block) -> None:
    results = app.music_results or []
    if not results:
        block.text("还没有可用的曲目。", 12, COLORS["ink"], weight="bold")
        block.gap(6)
        block.text("点一下「生成此刻歌单」，先跑一次规则策展。", 12, COLORS["muted"])
        return

    index = app.music_index % len(results)
    recommendation = results[index]

    _split_row(
        app,
        block,
        "此刻推荐",
        12,
        COLORS["sage"],
        f"{recommendation['score_percent']}% 匹配",
        11,
        COLORS["clay"],
        bold_left=True,
        bold_right=True,
    )
    block.gap(10)

    # 标题（衬线）+ 副标题 + 右侧唱片装饰。装饰只借用右侧的宽度，行高仍由
    # 文字决定，所以大字号下标题和副标题之间不会裂开一道空白。
    artwork = block.sz(48)
    row_top = block.y
    text_width = block.width - artwork - block.sz(14)
    title_height = block.meter.height(
        recommendation["title"],
        19,
        text_width,
        "bold",
        True,
    )
    subtitle_height = block.meter.height(
        recommendation["subtitle"],
        12,
        text_width,
        spacing=block.sz(4),
    )
    subtitle_top = row_top + block.sz(2) + title_height + block.sz(8)
    if block.draw:
        _record_motif(
            app,
            block,
            block.x + block.width - artwork / 2,
            row_top + artwork / 2,
            artwork / 2,
        )
        app._text(
            block.canvas,
            block.x,
            row_top + block.sz(2),
            recommendation["title"],
            19,
            COLORS["ink"],
            weight="bold",
            serif=True,
            width=text_width,
            tags=("recommendation_title",),
        )
        app._text(
            block.canvas,
            block.x,
            subtitle_top,
            recommendation["subtitle"],
            12,
            COLORS["ink_soft"],
            width=text_width,
            spacing2=block.sz(4),
        )
    block.y = max(row_top + artwork, subtitle_top + subtitle_height)
    block.gap(10)

    # 曲种徽章 + BPM + 平台名。
    _meta_row(app, block, recommendation)
    block.gap(8)

    # 一句人话版的匹配理由（AI 有补充时另起一行）。
    short_reason = str(recommendation.get("match_reason", "")).strip()
    if short_reason:
        block.label("匹配理由", 11, COLORS["sage"], spacing=4)
        block.text(short_reason, 12, COLORS["ink_soft"], spacing=5)
        block.gap(8)
    if app.ai_music_reason:
        block.text(f"AI 补充：{app.ai_music_reason}", 11, COLORS["muted"], spacing=4)
        block.gap(8)

    # 一句轻语（嵌套圆角盒，高度由文字量决定）。
    care = app.ai_music_note or care_note(app.music_mood, app.music_activity)
    mood_color = str(app.moods.get(app.music_mood, {}).get("color", COLORS["sage"]))
    _care_box(app, block, care, mood_color)
    block.gap(14)

    # 标签 chips：展示用，点击不改变状态。
    block.chip_rows(
        [
            (f"music_tag_{tag_index}", tag_text, False, lambda: None, COLORS["sage"])
            for tag_index, tag_text in enumerate(recommendation["tags"][:3])
        ],
        size=11,
        gap=7,
        row_gap=7,
    )
    block.gap(14)

    playing = _is_playing(app, recommendation)
    loading = _is_loading(app, recommendation)
    if recommendation.get("platform_only"):
        play_label = "平台试听"
        play_prefix = "↗"
        play_style = "primary"
    elif loading:
        play_label = "取消准备试听"
        play_prefix = "…"
        play_style = "primary"
    elif playing:
        play_label = "停下声音"
        play_prefix = "◉"
        play_style = "accent"
    else:
        play_label = "试听 18 秒"
        play_prefix = "▶"
        play_style = "primary"

    button_height = block.sz(40)
    button_gap = block.sz(10)
    play_width = (block.width - button_gap) * 0.62
    top = block.y
    block.button_at(
        "play_recommendation",
        play_label,
        lambda: app._toggle_play(recommendation),
        block.x,
        top,
        play_width,
        button_height,
        style=play_style,
        size=12,
        prefix=play_prefix,
    )
    block.button_at(
        "next_recommendation",
        "换一首",
        app._next_recommendation,
        block.x + play_width + button_gap,
        top,
        block.width - play_width - button_gap,
        button_height,
        style="ghost",
        size=12,
        prefix="↻",
    )
    block.y = top + button_height
    block.gap(button_gap)

    # 完整听感交给平台：按钮上写明会打开哪个平台。
    platforms = str(
        recommendation.get("platform_names")
        or playlists.platform_names(recommendation)
    )
    playlist_label = "打开歌单"
    if platforms:
        playlist_label = fit_text(
            app.meter,
            f"打开歌单 · {platforms}",
            block.width - block.sz(28),
            12,
            "bold",
        )
    block.button(
        "open_recommendation_playlist",
        playlist_label,
        lambda: _open_track_playlist(app, recommendation),
        style="ghost",
        size=12,
        height=36,
        prefix="↗",
    )
    block.gap(10)

    if app.ai_music_busy:
        status = "AI 正在听你的四维情境…"
    elif app.ai_music_note:
        status = "AI 已在人工曲库中重新校准"
    elif app.ai.configured:
        status = "本地策展完成 · AI 将二次校准"
    else:
        status = "离线可用 · 规则策展完成"
    block.text(status, 11, COLORS["muted"])


def _care_box(app, block: Block, text: str, color: str) -> float:
    """「给你的一句轻语」盒：高度、圆角与圆点都随字号缩放。"""

    pad_x = block.sz(14)
    pad_y = block.sz(12)
    dot = block.sz(8)
    head_size = 10
    head_height = block.meter.line_height(head_size, "bold")
    text_width = block.width - pad_x * 2
    text_height = block.meter.height(text, 12, text_width, spacing=block.sz(4))
    height = pad_y * 2 + head_height + block.sz(8) + text_height
    top = block.y
    if block.draw:
        canvas = block.canvas
        app.kit.draw_round(
            canvas,
            block.x,
            top,
            block.x + block.width,
            top + height,
            round(block.sz(14)),
            COLORS["card_alt"],
            None,
            0,
        )
        dot_top = top + pad_y + head_height / 2 - dot / 2
        app.kit.draw_round(
            canvas,
            block.x + pad_x,
            dot_top,
            block.x + pad_x + dot,
            dot_top + dot,
            round(dot / 2),
            color,
            mix_color(color, COLORS["white"], 0.55),
            1,
        )
        app._text(
            canvas,
            block.x + pad_x + dot + block.sz(8),
            top + pad_y,
            "给你的一句轻语",
            head_size,
            COLORS["sage"],
            weight="bold",
        )
        app._text(
            canvas,
            block.x + pad_x,
            top + pad_y + head_height + block.sz(8),
            text,
            12,
            COLORS["ink_soft"],
            width=text_width,
            spacing2=block.sz(4),
        )
    block.y = top + height
    return height


def _record_motif(app, block: Block, cx: float, cy: float, radius: float) -> None:
    """唱片装饰：同心圆 + 金色轴心（尺寸全部来自 ``block.sz``）。"""

    canvas = block.canvas
    canvas.create_oval(
        cx - radius,
        cy - radius,
        cx + radius,
        cy + radius,
        fill=COLORS["sage_soft"],
        outline="",
        tags=("recommendation_artwork",),
    )
    for ratio in (0.56, 0.82):
        ring = radius * ratio
        canvas.create_oval(
            cx - ring,
            cy - ring,
            cx + ring,
            cy + ring,
            outline=mix_color(COLORS["sage"], COLORS["white"], 0.45),
            width=1,
            tags=("recommendation_artwork",),
        )
    dot = max(2.0, radius * 0.13)
    canvas.create_oval(
        cx - dot,
        cy - dot,
        cx + dot,
        cy + dot,
        fill=COLORS["gold"],
        outline="",
        tags=("recommendation_artwork",),
    )
    canvas.create_oval(
        cx - dot * 0.7,
        cy - dot * 0.9,
        cx + dot * 0.7,
        cy + dot * 0.1,
        fill=COLORS["clay"],
        outline="",
        tags=("recommendation_artwork",),
    )


# ---------------------------------------------------- candidate sound cards


def _candidates_body(app, block: Block) -> None:
    _split_row(
        app,
        block,
        "三段曲目，按此刻的匹配度排列",
        15,
        COLORS["ink"],
        "音乐是陪伴，不是指令",
        11,
        COLORS["muted"],
        bold_left=True,
        bold_right=False,
    )
    block.gap(14)

    visible = (app.music_results or [])[:3]
    if not visible:
        block.text("还没有生成候选曲目。", 12, COLORS["muted"])
        return

    spacing = block.sz(12)
    if app._use_two_columns():
        # 宽屏：三列并排，卡片等高（高度取三者最大值）。
        columns = len(visible)
        column_width = (block.width - spacing * (columns - 1)) / columns
        top = block.y
        heights = [
            _track_height(app, track, index, column_width)
            for index, track in enumerate(visible)
        ]
        card_height = max(heights)
        for index, track in enumerate(visible):
            _track_card(
                app,
                block,
                index,
                track,
                block.x + index * (column_width + spacing),
                top,
                column_width,
                card_height,
            )
        block.y = top + card_height
    else:
        # 大字号的窄屏：纵向堆叠，宁可页面变长。
        for index, track in enumerate(visible):
            if index:
                block.gap(12)
            block.y += _track_card(
                app,
                block,
                index,
                track,
                block.x,
                block.y,
                block.width,
            )


def _track_text(
    app,
    block: Block,
    index: int,
    track: dict[str, Any],
    inline_score: bool = False,
) -> None:
    """候选卡的文字部分（序号圆点、标题、曲种/BPM、副标题、理由、标签）。"""

    badge = block.sz(26)
    row_top = block.y
    score_text = f"{track['score_percent']}%"
    score_width = block.meter.measure(score_text, 12, "bold")
    label_width = block.meter.measure("匹配", 10)
    right_width = score_width + block.sz(5) + label_width
    title_x = block.x + badge + block.sz(10)
    available = block.width - badge - block.sz(10) - right_width - block.sz(16)
    if inline_score and available >= block.sz(60):
        # TextMeter 与画布字体之间存在 1px 级别的取整差异，量出来的宽度会
        # 略小于 Tk 真正渲染的宽度；留 10% 余量，避免标题在等宽处被折行。
        natural = block.meter.measure(track["title"], 12, "bold") * 1.10
        title_width = max(block.sz(60), min(natural + block.sz(2), available))
        score_left = title_x + title_width + block.sz(16)
    else:
        title_width = block.width - badge - block.sz(10) - right_width - block.sz(10)
        score_left = block.x + block.width - right_width
    if block.draw:
        canvas = block.canvas
        canvas.create_oval(
            block.x,
            row_top,
            block.x + badge,
            row_top + badge,
            fill=str(track["color"]),
            outline="",
        )
        app._text(
            canvas,
            block.x + badge / 2,
            row_top + badge / 2,
            f"0{index + 1}",
            9,
            COLORS["paper"],
            anchor="center",
            weight="bold",
        )
        score_top = row_top + block.sz(1)
        score_height = block.meter.line_height(12, "bold")
        label_height = block.meter.line_height(10)
        app._text(
            canvas,
            score_left,
            score_top,
            score_text,
            12,
            COLORS["clay"],
            weight="bold",
        )
        app._text(
            canvas,
            score_left + score_width + block.sz(5),
            score_top + score_height - label_height,
            "匹配",
            10,
            COLORS["muted"],
        )
    title_height = block.meter.height(track["title"], 12, title_width, "bold")
    if block.draw:
        app._text(
            block.canvas,
            title_x,
            row_top + block.sz(2),
            track["title"],
            12,
            COLORS["ink"],
            weight="bold",
            width=title_width,
        )
    block.y = row_top + max(badge, title_height + block.sz(2))
    block.gap(6)

    _meta_row(app, block, track)
    block.gap(6)
    block.text(track["subtitle"], 11, COLORS["muted"], spacing=4)
    block.gap(6)

    short_reason = str(track.get("match_reason", "")).strip()
    if short_reason:
        block.text(f"匹配理由 · {short_reason}", 11, COLORS["ink_soft"], spacing=4)
        block.gap(6)
    block.text(" · ".join(track["tags"][:3]), 10, COLORS["ink_soft"])


def _meta_row(app, block: Block, track: dict[str, Any]) -> None:
    """曲种徽章 + ``BPM`` + 平台名；一行放不下时自动折成两行。"""

    kind = str(track.get("kind") or "").strip()
    bpm = track.get("bpm")
    parts: list[str] = []
    if isinstance(bpm, int) and bpm > 0:
        parts.append(f"{bpm} BPM")
    platforms = str(
        track.get("platform_names") or playlists.platform_names(track)
    ).strip()
    if platforms:
        parts.append(platforms)
    meta = " · ".join(parts)

    badge_height = max(
        block.sz(18),
        block.meter.line_height(10, "bold") + block.sz(6),
    )
    badge_width = 0.0
    if kind:
        badge_width = block.meter.measure(kind, 10, "bold") + block.sz(16)
    meta_width = block.meter.measure(meta, 10) * 1.08 if meta else 0.0

    top = block.y
    if kind and block.draw:
        color = _KIND_COLORS.get(kind, COLORS["sage"])
        app.kit.draw_round(
            block.canvas,
            block.x,
            top,
            block.x + badge_width,
            top + badge_height,
            round(block.sz(9)),
            mix_color(color, COLORS["white"], 0.82),
            mix_color(color, COLORS["white"], 0.45),
            1,
            (f"music_kind_badge_{track['id']}",),
        )
        app._text(
            block.canvas,
            block.x + badge_width / 2,
            top + badge_height / 2,
            kind,
            10,
            color,
            anchor="center",
            weight="bold",
            tags=(f"music_kind_badge_{track['id']}",),
        )

    if meta and kind and badge_width + block.sz(10) + meta_width <= block.width:
        if block.draw:
            app._text(
                block.canvas,
                block.x + badge_width + block.sz(10),
                top + badge_height / 2,
                meta,
                10,
                COLORS["muted"],
                anchor="w",
            )
        block.y = top + badge_height
        return
    block.y = top + badge_height
    if meta:
        block.gap(2)
        block.text(meta, 10, COLORS["muted"])


def _track_height(app, track: dict[str, Any], index: int, width: float) -> float:
    """候选卡只量高度（三列并排时用来取齐）。"""

    geometry = _track_geometry(app, width)
    probe = Block(app, app.page_canvas, 0.0, 0.0, geometry["text_width"], draw=False)
    _track_text(app, probe, index, track, bool(geometry["wide"]))
    return _track_needed(app, geometry, probe.used)


def _track_geometry(app, width: float) -> dict[str, float | bool]:
    """候选卡的两套排版：宽卡把按钮放到右侧，窄卡让按钮通栏靠底。"""

    pad = app._sz(14)
    button_height = app._sz(34)
    button_gap = app._sz(8)
    actions_height = button_height * 2 + button_gap
    inner_width = width - pad * 2
    wide = width >= app._sz(520)
    if wide:
        action_width = app._sz(140)
        action_gap = app._sz(16)
        text_width = inner_width - action_width - action_gap
    else:
        action_width = inner_width
        action_gap = 0.0
        text_width = inner_width
    return {
        "pad": pad,
        "button_height": button_height,
        "button_gap": button_gap,
        "actions_height": actions_height,
        "button_width": action_width,
        "inner_width": inner_width,
        "text_width": text_width,
        "wide": wide,
    }


def _track_needed(app, geometry: dict[str, float | bool], text_height: float) -> float:
    pad = float(geometry["pad"])
    actions_height = float(geometry["actions_height"])
    if geometry["wide"]:
        return pad * 2 + max(text_height, actions_height)
    return pad * 2 + text_height + app._sz(10) + actions_height


def _track_card(
    app,
    block: Block,
    index: int,
    track: dict[str, Any],
    x: float,
    top: float,
    width: float,
    height: float | None = None,
) -> float:
    """画一张候选卡，返回它的高度（游标推进由调用方决定）。"""

    geometry = _track_geometry(app, width)
    pad = float(geometry["pad"])
    button_height = float(geometry["button_height"])
    button_gap = float(geometry["button_gap"])
    actions_height = float(geometry["actions_height"])
    button_width = float(geometry["button_width"])
    text_width = float(geometry["text_width"])
    probe = Block(app, block.canvas, 0.0, 0.0, text_width, draw=False)
    _track_text(app, probe, index, track, bool(geometry["wide"]))
    card_height = max(height or 0.0, _track_needed(app, geometry, probe.used))
    card_tag = f"music_track_card_{index}"

    if block.draw:
        playing = _is_playing(app, track)
        loading = _is_loading(app, track)
        platform_only = bool(track.get("platform_only"))
        if platform_only:
            play_label = "平台试听"
        elif loading:
            play_label = "取消准备试听"
        elif playing:
            play_label = "停下这段"
        else:
            play_label = "试听这段"
        card_radius = block.sz(20)
        card_item = app.kit.draw_round(
            block.canvas,
            x,
            top,
            x + width,
            top + card_height,
            round(card_radius),
            COLORS["sunken"],
            COLORS["line"],
            1,
            (card_tag,),
        )
        app.motion.add_surface(
            block.canvas,
            card_item,
            (x, top, x + width, top + card_height),
            card_radius,
            COLORS["sunken"],
            None,
            COLORS["line"],
            1,
            hover_fill=mix_color(COLORS["sunken"], COLORS["iris"], 0.05),
            hover_outline=mix_color(COLORS["line"], COLORS["iris"], 0.45),
            sheen_color=COLORS["iris"],
            sheen_strength=0.26,
            press_scale=0.0,
        )
        painter = Block(app, block.canvas, x + pad, top + pad, text_width, draw=True)
        _track_text(app, painter, index, track, bool(geometry["wide"]))
        if geometry["wide"]:
            # 宽卡：两个按钮竖排在右侧，整组垂直居中。
            button_left = x + width - pad - button_width
            button_top = max(top + pad, top + (card_height - actions_height) / 2)
        else:
            button_left = x + pad
            button_top = top + card_height - pad - actions_height
        block.button_at(
            f"music_play_{index}",
            play_label,
            lambda item=track: app._toggle_play(item),
            button_left,
            button_top,
            button_width,
            button_height,
            style="accent" if playing else "secondary",
            size=11,
            prefix=("↗" if platform_only else ("◉" if playing else ("…" if loading else "▶"))),
        )
        block.button_at(
            f"music_playlist_{index}",
            "打开歌单",
            lambda item=track: _open_track_playlist(app, item),
            button_left,
            button_top + button_height + button_gap,
            button_width,
            button_height,
            style="ghost",
            size=11,
            prefix="↗",
        )
        canvas = block.canvas
        canvas.tag_bind(
            card_tag,
            "<Button-1>",
            lambda _event, value=index: app._choose_music(value),
        )
        canvas.tag_bind(
            card_tag,
            "<Enter>",
            lambda _event: canvas.configure(cursor="hand2"),
        )
        canvas.tag_bind(card_tag, "<Leave>", lambda _event: canvas.configure(cursor=""))
    return card_height


# ------------------------------------------------------------- playlist links


def _open_link(app, link: dict[str, str]) -> None:
    """把一条官方搜索页链接交给系统浏览器，并给出轻提示。"""

    platform = str(link.get("platform", "平台"))
    if playlists.open_url(str(link.get("url", ""))):
        _toast(app, f"已在浏览器打开 {platform} 搜索页")
    else:
        _toast(app, "浏览器没有响应，可以手动搜索这条关键词")


def _open_track_playlist(app, track: dict[str, Any]) -> None:
    """打开曲目的第一个官方歌单链接（卡片上已写明平台名）。"""

    link = playlists.first_link(track)
    if link is None:
        _toast(app, "这条曲目还没有可用的歌单链接")
        return
    _open_link(app, link)


def _toast(app, text: str) -> None:
    callback = getattr(app, "_toast", None)
    if callable(callback):
        callback(text)


# ------------------------------------------------------------------ helpers


def _is_playing(app, track: dict[str, Any]) -> bool:
    return bool(app.player.playing and app.player.current_track_id == track["id"])


def _is_loading(app, track: dict[str, Any]) -> bool:
    return getattr(app, "_audio_loading_id", None) == track["id"]


def _split_row(
    app,
    block: Block,
    left: str,
    left_size: int,
    left_color: str,
    right: str,
    right_size: int,
    right_color: str,
    *,
    bold_left: bool = True,
    bold_right: bool = False,
    gap: float = 12.0,
) -> None:
    """一行放「左标签 + 右说明」；放不下时自动改成上下两行。

    A right-aligned caption next to a left-aligned title is the one place where
    a fixed split would collide once the font grows, so both widths are
    measured first and the row collapses instead of overlapping.
    """

    left_weight = "bold" if bold_left else "normal"
    right_weight = "bold" if bold_right else "normal"
    # 留一点余量：TextMeter 量出的宽度会比 Tk 实际渲染略窄（字体像素取整），
    # 刚好卡在边界上时右侧说明会压住左侧标题。
    left_width = block.meter.measure(left, left_size, left_weight) * 1.08
    right_width = block.meter.measure(right, right_size, right_weight) * 1.08
    row_top = block.y
    if left_width + right_width + block.sz(gap) <= block.width:
        if block.draw:
            app._text(
                block.canvas,
                block.x,
                row_top,
                left,
                left_size,
                left_color,
                weight=left_weight,
            )
            app._text(
                block.canvas,
                block.x + block.width,
                row_top,
                right,
                right_size,
                right_color,
                anchor="ne",
                weight=right_weight,
            )
        block.y = row_top + max(
            block.meter.line_height(left_size, left_weight),
            block.meter.line_height(right_size, right_weight),
        )
        return
    block.text(left, left_size, left_color, weight=left_weight, width=block.width)
    block.text(right, right_size, right_color, weight=right_weight, width=block.width)
