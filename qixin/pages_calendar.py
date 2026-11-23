"""情绪日历页：内容驱动布局，随字号自适应。

月历格子、周视图、右侧回顾栏全部按当前字号重新计算尺寸；右侧原来的
「本月情绪分布」统计被替换为「随笔记录」面板。
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from .content import quote_at
from .layout import Block
from .notes import count_notes, list_notes
from .services import local_weekly_report
from .theme import COLORS, get_font_scale, mix_color


def draw_calendar(app) -> float:
    margin, gap, usable = app._page_metrics()
    anchor: date = app.calendar_anchor
    year, month = anchor.year, anchor.month
    first_weekday, days_in_month = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    moods_by_day = app.store.latest_moods_by_date(month_start, month_end)
    month_moods = app.store.moods_between(month_start, month_end)
    schedules = app.store.schedules_between(month_start, month_end)
    schedules_by_day: dict[str, list[Any]] = {}
    for schedule in schedules:
        schedules_by_day.setdefault(str(schedule["local_date"]), []).append(schedule)

    context = {
        "year": year,
        "month": month,
        "first_weekday": first_weekday,
        "days_in_month": days_in_month,
        "month_start": month_start,
        "moods_by_day": moods_by_day,
        "month_moods": month_moods,
        "schedules_by_day": schedules_by_day,
        "counts_by_day": _counts_by_day(month_moods),
    }
    side_cards = [
        (key, body, fill) for key, body, fill in (
            ("calendar_overview", lambda block: _overview_body(app, block, context), COLORS["card_alt"]),
            ("calendar_day", lambda block: _selected_day_body(app, block), COLORS["card"]),
            ("calendar_notes", lambda block: _essay_panel_body(app, block), COLORS["sunken"]),
            ("calendar_week", lambda block: _weekly_preview_body(app, block), COLORS["card_alt"]),
        ) if app.feature_visible(key)
    ]
    split = bool(side_cards and app._use_two_columns())
    if split:
        left_width = round(usable * 0.63)
        right_width = usable - left_width - gap
        right_x = margin + left_width + gap
    else:
        left_width = usable
        right_width = usable
        right_x = margin

    y_left = margin
    y_left += app._flow_card(
        margin,
        y_left,
        left_width,
        lambda block: _calendar_left_body(app, block, context),
    )

    y_right = margin if split else y_left + gap
    for key, body, fill in side_cards:
        y_right += app._flow_card(
            right_x, y_right, right_width, body, fill=fill, tags=(key,),
        ) + gap
    app.page_canvas.tag_raise("calendar_selection")
    return max(y_left, y_right - gap) + margin


# --------------------------------------------------------------------- left card
def _calendar_left_body(app, block: Block, ctx: dict[str, Any]) -> None:
    """标题、切换控件、月历/周视图与图例共用一张卡片，避免多余留白。"""

    _calendar_head_body(app, block, ctx)
    block.gap(9)
    block.divider(color=COLORS["hairline"])
    block.gap(9)
    if app.calendar_view == "agenda":
        _agenda_body(app, block)
    else:
        _month_grid_body(app, block, ctx)
        block.gap(10)
        block.divider(color=COLORS["hairline"])
        block.gap(8)
        _legend_body(app, block, ctx)


# --------------------------------------------------------------------- head
def _calendar_head_body(app, block: Block, ctx: dict[str, Any]) -> None:
    block.text(
        f"{ctx['year']} 年 {ctx['month']} 月",
        21,
        COLORS["ink"],
        weight="bold",
        serif=True,
    )
    block.gap(2)
    block.text(
        f"{len(ctx['moods_by_day'])} 天有记录 · 双击日期编辑日程",
        10,
        COLORS["muted"],
    )
    block.gap(10)
    block.chip_rows(
        [
            (
                "calendar_view_month",
                "月历",
                app.calendar_view == "month",
                lambda: app._set_calendar_view("month"),
                COLORS["sage"],
            ),
            (
                "calendar_view_agenda",
                "周视图",
                app.calendar_view == "agenda",
                lambda: app._set_calendar_view("agenda"),
                COLORS["sage"],
            ),
        ],
        color=COLORS["sage"],
        size=10,
        gap=8,
        row_gap=8,
    )
    block.gap(10)
    # 月份切换与操作按钮：按可用宽度自动换行
    actions = [
        ("calendar_prev", "‹ 上月", lambda: app._shift_month(-1), "ghost", 10, 34),
        ("calendar_today", "今天", app._calendar_today, "ghost", 10, 34),
        ("calendar_next", "下月 ›", lambda: app._shift_month(1), "ghost", 10, 34),
        ("calendar_add_schedule", "＋ 日程", app._open_schedule_dialog, "primary", 10, 34),
        ("calendar_clear", "清空情绪", app._clear_mood_history, "accent", 10, 34),
    ]
    cursor_x = block.x
    row_top = block.y
    button_height = block.sz(34)
    for tag, label, command, style, size, height in actions:
        button_width = block.meter.measure(label, size, "bold") + block.sz(28)
        if cursor_x > block.x and cursor_x + button_width > block.x + block.width:
            row_top += button_height + block.sz(8)
            cursor_x = block.x
        block.button_at(
            tag,
            label,
            command,
            cursor_x,
            row_top,
            button_width,
            button_height,
            style=style,
            size=size,
        )
        cursor_x += button_width + block.sz(8)
    block.y = row_top + button_height


# --------------------------------------------------------------------- grid
def _counts_by_day(month_moods: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in month_moods:
        key = str(row["local_date"])
        counts[key] = counts.get(key, 0) + 1
    return counts


def _month_grid_body(app, block: Block, ctx: dict[str, Any]) -> None:
    """月历网格：用整格色块表达当天心情，格子做大做亮。"""

    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    gap = block.sz(9)
    cell_width = (block.width - gap * 6) / 7
    day_line = block.meter.line_height(11, "bold")
    mood_line = block.meter.line_height(9, "bold")
    meta_line = block.meter.line_height(8)
    # 一个格子里尽量多放几条日程：默认 4 条，字号越大越少。
    font_scale = get_font_scale()
    max_schedules = 4 if font_scale <= 1.28 else (3 if font_scale <= 1.45 else 2)
    pad = block.sz(10)
    cell_height = max(
        block.sz(104),
        pad * 2 + day_line + mood_line + meta_line * max_schedules + block.sz(9),
    )

    # weekday header
    for index, label in enumerate(weekdays):
        x = block.x + index * (cell_width + gap)
        if block.draw:
            app._text(
                block.canvas,
                x + cell_width / 2,
                block.y,
                label,
                9,
                COLORS["sage"],
                anchor="n",
                weight="bold",
            )
    block.y += block.meter.line_height(9, "bold") + block.sz(6)

    today = date.today()
    counts = ctx.get("counts_by_day", {})
    for day_number in range(1, ctx["days_in_month"] + 1):
        current = date(ctx["year"], ctx["month"], day_number)
        position = ctx["first_weekday"] + day_number - 1
        row, column = divmod(position, 7)
        x1 = block.x + column * (cell_width + gap)
        y1 = block.y + row * (cell_height + gap)
        x2 = x1 + cell_width
        y2 = y1 + cell_height

        mood_row = ctx["moods_by_day"].get(current.isoformat())
        mood = str(mood_row["mood"]) if mood_row else ""
        config = app.moods.get(mood, {})
        mood_color = str(config.get("color", COLORS["ink_soft"]))
        # 明亮但不刺眼：整格淡色底 + 左侧实色条，比原来的小字更醒目。
        fill = mix_color(mood_color, COLORS["white"], 0.80) if mood else COLORS["card_alt"]
        outline = mix_color(mood_color, COLORS["white"], 0.45) if mood else COLORS["line"]
        stroke = 1.5 if mood else 1
        if current == today:
            outline = COLORS["sage"]
            stroke = 2.5
        tag = f"calendar_day_{day_number}"
        day_schedules = ctx["schedules_by_day"].get(current.isoformat(), [])
        records = counts.get(current.isoformat(), 1 if mood else 0)

        if block.draw:
            canvas = block.canvas
            cell_radius = block.sz(16)
            cell_item = app.kit.draw_round(
                canvas,
                x1,
                y1,
                x2,
                y2,
                round(cell_radius),
                fill,
                outline,
                round(stroke),
                (tag,),
            )
            app.motion.add_surface(
                canvas,
                cell_item,
                (x1, y1, x2, y2),
                cell_radius,
                fill,
                None,
                outline,
                round(stroke),
                hover_fill=mix_color(fill, COLORS["iris"], 0.06),
                hover_outline=mix_color(outline, COLORS["iris"], 0.4),
                sheen_color=COLORS["iris"],
                sheen_strength=0.24,
                press_scale=0.0,
            )
            if current == app.selected_day:
                _day_outline(app, block, (x1, y1, x2, y2), cell_radius)
            if mood:
                bar = block.sz(5)
                app.kit.draw_pill(
                    canvas,
                    x1 + block.sz(4),
                    y1 + block.sz(13),
                    x1 + block.sz(4) + bar,
                    y2 - block.sz(13),
                    bar / 2,
                    mood_color,
                    None,
                    None,
                    0,
                    (tag,),
                )
            number_width = block.meter.measure(
                str(day_number),
                11,
                "bold" if current == today else "normal",
            )
            app._text(
                canvas,
                x1 + pad,
                y1 + pad - block.sz(2),
                str(day_number),
                11,
                COLORS["ink"] if mood else COLORS["ink_soft"],
                weight="bold" if current == today else "normal",
                tags=(tag,),
            )
            if current == today:
                app._text(
                    canvas,
                    x1 + pad + number_width + block.sz(3),
                    y1 + pad - block.sz(1),
                    "今",
                    7,
                    COLORS["sage"],
                    weight="bold",
                    tags=(tag,),
                )
            if mood:
                app._text(
                    canvas,
                    x1 + pad,
                    y1 + pad - block.sz(2) + day_line,
                    mood,
                    9,
                    mood_color,
                    weight="bold",
                    width=cell_width - pad * 2,
                    tags=(tag,),
                )
                if records > 1:
                    dot_r = block.sz(2.2)
                    for index in range(min(records, 4)):
                        cx = x2 - pad - dot_r - index * (dot_r * 2 + block.sz(2))
                        canvas.create_oval(
                            cx - dot_r,
                            y2 - pad - dot_r * 2,
                            cx + dot_r,
                            y2 - pad,
                            fill=mood_color,
                            outline="",
                            tags=(tag,),
                        )
            schedule_top = (
                y1 + pad - block.sz(2) + day_line + (mood_line if mood else 0)
            )
            schedule_width = cell_width - pad * 2
            bottom_limit = y2 - block.sz(7)
            cursor = schedule_top
            shown = 0
            for schedule in day_schedules:
                if shown >= max_schedules:
                    break
                prefix = str(schedule["start_time"] or "").strip()
                title = str(schedule["title"])
                text = f"{prefix} {title}".strip() if prefix else title
                line_height = block.meter.height(text, 8, schedule_width)
                if cursor + line_height > bottom_limit:
                    break
                if block.draw:
                    app._text(
                        canvas,
                        x1 + pad,
                        cursor,
                        text,
                        8,
                        COLORS["ink_soft"],
                        width=schedule_width,
                        tags=(tag,),
                    )
                cursor += line_height
                shown += 1
            if len(day_schedules) > shown and block.draw:
                if cursor + block.meter.line_height(7) <= y2 - block.sz(4):
                    app._text(
                        canvas,
                        x2 - block.sz(8),
                        cursor,
                        f"+{len(day_schedules) - shown}",
                        7,
                        COLORS["muted"],
                        anchor="ne",
                        tags=(tag,),
                    )
            canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda _event, day_value=current: app._select_calendar_day(day_value),
            )
            canvas.tag_bind(tag, "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
            canvas.tag_bind(tag, "<Leave>", lambda _e: canvas.configure(cursor=""))

    rows = (ctx["first_weekday"] + ctx["days_in_month"] - 1) // 7 + 1
    block.y += rows * cell_height + (rows - 1) * gap


def _legend_body(app, block: Block, ctx: dict[str, Any]) -> None:
    block.label("情绪图例 · 颜色即状态", 9, COLORS["muted"], spacing=6)
    dot = block.sz(8)
    line_height = block.meter.line_height(8) + block.sz(6)
    top = block.y
    cursor = block.x
    for mood in app.mood_order:
        config = app.moods[mood]
        item_width = block.meter.measure(mood, 8) + dot + block.sz(14)
        if cursor > block.x and cursor + item_width > block.x + block.width:
            cursor = block.x
            top += line_height
        if block.draw:
            center_y = top + block.meter.line_height(8) / 2
            block.canvas.create_oval(
                cursor,
                center_y - dot / 2,
                cursor + dot,
                center_y + dot / 2,
                fill=str(config["color"]),
                outline="",
            )
            app._text(
                block.canvas,
                cursor + dot + block.sz(5),
                top,
                mood,
                8,
                COLORS["ink_soft"],
            )
        cursor += item_width + block.sz(8)
    block.y = top + line_height


# --------------------------------------------------------------------- agenda
def _agenda_body(app, block: Block) -> None:
    week_start = app.selected_day - timedelta(days=app.selected_day.weekday())
    week_end = week_start + timedelta(days=6)
    block.label(
        f"本周记录 · {week_start.strftime('%m.%d')}—{week_end.strftime('%m.%d')}",
        9,
        COLORS["sage"],
        spacing=10,
    )
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for index in range(7):
        current = week_start + timedelta(days=index)
        mood_row = app.store.latest_mood_for_day(current)
        mood = str(mood_row["mood"]) if mood_row else ""
        config = app.moods.get(mood, {})
        fill = (
            mix_color(str(config.get("soft", COLORS["card_alt"])), COLORS["white"], 0.55)
            if mood
            else COLORS["sunken"]
        )
        schedules = app.store.schedules_for_day(current)
        selected = current == app.selected_day
        tag = f"agenda_day_{current.isoformat()}"
        top = block.y

        pad = block.sz(12)
        left_block = block.sz(74)
        text_x = block.x + left_block
        text_width = block.width - left_block - block.sz(78)

        if schedules:
            detail = "  ·  ".join(
                (
                    f"{str(item['start_time'] or '').strip()} {str(item['title'])}".strip()
                    if str(item["start_time"] or "").strip()
                    else str(item["title"])
                )
                for item in schedules[:2]
            )
            if len(schedules) > 2:
                detail += f"  ·  另有{len(schedules) - 2}项"
        elif mood_row:
            detail = str(mood_row["activity"] or "").strip() or "记录了一段心情"
            note = str(mood_row["note"] or "").strip()
            if note:
                detail = f"{detail} · {note}"
        else:
            detail = "点击补上一笔，或添加一条日程。"

        mood_text = f"{config['short']} {mood}" if mood else "○ 未记录状态"
        mood_height = block.meter.height(mood_text, 11, text_width, "bold")
        detail_height = block.meter.height(detail, 9, text_width)
        row_height = max(block.sz(64), pad * 2 + mood_height + block.sz(4) + detail_height)

        if block.draw:
            canvas = block.canvas
            row_radius = block.sz(18)
            row_item = app.kit.draw_round(
                canvas,
                block.x,
                top,
                block.x + block.width,
                top + row_height,
                round(row_radius),
                fill,
                COLORS["line"],
                1,
                (tag,),
            )
            app.motion.add_surface(
                canvas,
                row_item,
                (block.x, top, block.x + block.width, top + row_height),
                row_radius,
                fill,
                None,
                COLORS["line"],
                1,
                hover_fill=mix_color(fill, COLORS["iris"], 0.06),
                hover_outline=mix_color(COLORS["line"], COLORS["iris"], 0.4),
                sheen_color=COLORS["iris"],
                sheen_strength=0.24,
                press_scale=0.0,
            )
            if selected:
                _day_outline(app, block, (block.x, top, block.x + block.width, top + row_height), row_radius)
            if mood:
                bar = block.sz(5)
                app.kit.draw_pill(
                    canvas,
                    block.x + block.sz(9),
                    top + block.sz(13),
                    block.x + block.sz(9) + bar,
                    top + row_height - block.sz(13),
                    bar / 2,
                    str(config["color"]),
                    None,
                    None,
                    0,
                    (tag,),
                )
            app._text(
                canvas,
                block.x + block.sz(18),
                top + pad,
                f"{current.month:02d}.{current.day:02d}",
                8,
                COLORS["muted"],
                weight="bold",
                tags=(tag,),
            )
            app._text(
                canvas,
                block.x + block.sz(18),
                top + pad + block.meter.line_height(8, "bold") + block.sz(2),
                weekday_names[current.weekday()],
                7,
                COLORS["muted"],
                tags=(tag,),
            )
            app._text(
                canvas,
                text_x,
                top + pad,
                mood_text,
                11,
                str(config.get("color", COLORS["muted"])),
                weight="bold",
                width=text_width,
                tags=(tag,),
            )
            app._text(
                canvas,
                text_x,
                top + pad + mood_height + block.sz(4),
                detail,
                9,
                COLORS["ink_soft"],
                width=text_width,
                tags=(tag,),
            )
            total, done = app.store.task_counts_for_day(current)
            if total:
                app._text(
                    canvas,
                    block.x + block.width - block.sz(12),
                    top + pad,
                    f"计划 {done}/{total}",
                    8,
                    COLORS["muted"],
                    anchor="ne",
                    tags=(tag,),
                )
            canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda _event, day_value=current: app._select_calendar_day(day_value),
            )
            canvas.tag_bind(tag, "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
            canvas.tag_bind(tag, "<Leave>", lambda _e: canvas.configure(cursor=""))

        block.y = top + row_height + block.sz(8)


def _day_outline(app, block: Block, bounds: tuple[float, ...], radius: float) -> None:
    item = app.kit.draw_round(
        block.canvas, *bounds, round(radius), "#00000000", COLORS["sage"], 2,
        tags=("calendar_selection",),
    )
    block.canvas.itemconfigure(item, state="disabled")


# --------------------------------------------------------------------- panels
def _overview_body(app, block: Block, ctx: dict[str, Any]) -> None:
    block.text("这个月，心走过的路", 15, COLORS["ink"], weight="bold", serif=True)
    block.gap(12)
    days_seen = len(ctx["moods_by_day"])
    total = len(ctx["month_moods"])
    stat_height = block.sz(64)
    top = block.y
    if block.draw:
        canvas = block.canvas
        app.kit.draw_round(
            canvas,
            block.x,
            top,
            block.x + block.width,
            top + stat_height,
            round(block.sz(16)),
            COLORS["sunken"],
            None,
            0,
        )
        third = block.width / 3
        values = [(str(days_seen), "天有记录"), (str(total), "次打卡")]
        for index, (value, label) in enumerate(values):
            app._text(
                canvas,
                block.x + block.sz(18) + index * third,
                top + block.sz(10),
                value,
                24,
                COLORS["pine"] if index == 0 else COLORS["clay"],
                serif=True,
            )
            app._text(
                canvas,
                block.x + block.sz(18) + index * third,
                top + block.sz(44),
                label,
                9,
                COLORS["ink_soft"],
            )
        canvas.create_line(
            block.x + third * 2,
            top + block.sz(12),
            block.x + third * 2,
            top + stat_height - block.sz(12),
            fill=COLORS["line"],
            width=1,
        )
        tasks_total, tasks_done = app.store.task_counts_for_day(date.today())
        app._text(
            canvas,
            block.x + third * 2 + block.sz(18),
            top + block.sz(10),
            f"{tasks_done}/{tasks_total}",
            18,
            COLORS["sage"],
            serif=True,
        )
        app._text(
            canvas,
            block.x + third * 2 + block.sz(18),
            top + block.sz(42),
            "今日计划",
            9,
            COLORS["ink_soft"],
        )
    block.y = top + stat_height


def _selected_day_body(app, block: Block) -> None:
    prior_items = block.canvas.find_all() if block.draw else ()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    selected = app.selected_day
    block.text(
        f"{selected.month} 月 {selected.day} 日 · {weekday_names[selected.weekday()]}",
        10,
        COLORS["sage"],
        weight="bold",
    )
    block.gap(10)
    selected_moods = app.store.moods_for_day(selected)
    tasks_total, tasks_done = app.store.task_counts_for_day(selected)
    if selected_moods:
        latest = selected_moods[-1]
        mood = str(latest["mood"])
        config = app.moods.get(mood, app.moods[next(iter(app.moods))])
        row_top = block.y
        circle = block.sz(28)
        text_x = block.x + circle + block.sz(12)
        text_width = max(block.sz(40), block.width - circle - block.sz(12))
        meta_text = (
            f"{latest['activity'] or '没有填写活动'} · "
            f"{str(latest['created_at'])[11:16]}"
        )
        mood_height = block.meter.height(mood, 12, text_width, "bold")
        meta_height = block.meter.height(meta_text, 9, text_width)
        if block.draw:
            canvas = block.canvas
            canvas.create_oval(
                block.x,
                row_top,
                block.x + circle,
                row_top + circle,
                fill=config["soft"],
                outline="",
            )
            dot = circle * 0.18
            cx, cy = block.x + circle / 2, row_top + circle / 2
            canvas.create_oval(
                cx - dot, cy - dot, cx + dot, cy + dot,
                fill=config["color"], outline="",
            )
            app._text(
                canvas,
                text_x,
                row_top,
                mood,
                12,
                config["color"],
                weight="bold",
                width=text_width,
            )
            app._text(
                canvas,
                text_x,
                row_top + mood_height,
                meta_text,
                9,
                COLORS["muted"],
                width=text_width,
            )
        block.y = row_top + max(circle, mood_height + meta_height) + block.sz(6)
        note = str(latest["note"] or "").strip()
        block.text(
            note or f"当日计划 {tasks_done}/{tasks_total} 项完成",
            9,
            COLORS["ink_soft"],
            spacing=3,
        )
        if len(selected_moods) > 1:
            block.gap(4)
            block.text(f"{len(selected_moods)} 次记录", 8, COLORS["muted"])
    else:
        block.text("这一天还没有心情记录。", 11, COLORS["ink_soft"])
        block.gap(4)
        block.text(
            "空白不代表没有感受，只是还没有被写下。",
            9,
            COLORS["muted"],
        )
        if app.feature_visible("home_mood"):
            block.gap(10)
            block.button(
                "calendar_checkin",
                "去记一下",
                lambda: app.show_page("today"),
                style="secondary",
                size=9,
                height=32,
                width=min(block.sz(110), block.width),
            )

    # 当日日程：大字号下日期格只放得下一条，详情卡里完整列出。
    day_schedules = app.store.schedules_for_day(selected)
    if day_schedules:
        block.gap(12)
        block.divider(color=COLORS["hairline"])
        block.gap(8)
        block.label(
            f"当日日程 · {len(day_schedules)} 条",
            9,
            COLORS["sage"],
            spacing=6,
        )
        for schedule in day_schedules[:8]:
            stamp = str(schedule["start_time"] or "").strip()
            title = str(schedule["title"])
            line = f"{stamp}  {title}".strip() if stamp else title
            block.text(line, 10, COLORS["ink_soft"], spacing=3)
        if len(day_schedules) > 8:
            block.text(f"另有 {len(day_schedules) - 8} 项", 8, COLORS["muted"])
        block.gap(8)
        block.button(
            "calendar_day_manage",
            "编辑当天日程",
            lambda: app._open_day_schedules(selected),
            style="ghost",
            size=9,
            height=32,
        )
    if block.draw:
        last_previous_id = max(prior_items, default=0)
        for item in block.canvas.find_all():
            if item > last_previous_id and block.canvas.type(item) == "text":
                block.canvas.addtag_withtag("calendar_detail_text", item)


def _essay_panel_body(app, block: Block) -> None:
    row_top = block.y
    block.text("随笔记录", 15, COLORS["ink"], weight="bold", serif=True, width=block.width - block.sz(120))
    block.button_right(
        "calendar_note_new",
        "＋ 写一篇",
        app._open_note_editor,
        size=9,
        height=28,
        style="ghost",
        y=row_top,
    )
    block.y = max(block.y, row_top + block.sz(28)) + block.sz(6)
    block.text(
        f"共 {count_notes(app.store)} 篇 · 可自选字号、加粗、斜体、字体与荧光高亮",
        9,
        COLORS["muted"],
    )
    block.gap(10)
    notes = list_notes(app.store, limit=3)
    if not notes:
        block.text(
            "还没有随笔。写下今天的一小段，哪怕只有一句话。",
            10,
            COLORS["ink_soft"],
            spacing=3,
        )
        block.gap(10)
        block.button(
            "calendar_note_first",
            "开始第一篇",
            app._open_note_editor,
            style="primary",
            size=10,
            height=34,
        )
        return
    for note in notes:
        row_top = block.y
        title = note.title or "未命名随笔"
        title_height = block.meter.height(title, 11, block.width, "bold")
        if block.draw:
            app._text(
                block.canvas,
                block.x,
                row_top,
                title,
                11,
                COLORS["ink"],
                weight="bold",
                width=block.width,
            )
        block.y = row_top + title_height + block.sz(3)
        preview = note.plain_text.strip().replace("\n", " ")
        if len(preview) > 42:
            preview = preview[:42] + "…"
        block.text(preview, 9, COLORS["ink_soft"], spacing=2)
        block.gap(2)
        stamp = note.updated_at[:16].replace("T", " ")
        if block.draw:
            app._text(
                block.canvas,
                block.x,
                block.y,
                f"{stamp} · 打开",
                8,
                COLORS["sage"],
                tags=(f"calendar_note_open_{note.id}",),
            )
            block.canvas.tag_bind(
                f"calendar_note_open_{note.id}",
                "<Button-1>",
                lambda _event, note_id=note.id: app._open_note_editor(note_id),
            )
            block.canvas.tag_bind(
                f"calendar_note_open_{note.id}",
                "<Enter>",
                lambda _e: block.canvas.configure(cursor="hand2"),
            )
            block.canvas.tag_bind(
                f"calendar_note_open_{note.id}",
                "<Leave>",
                lambda _e: block.canvas.configure(cursor=""),
            )
        block.y += block.meter.line_height(8) + block.sz(10)
    if app.feature_visible("essay"):
        block.gap(2)
        block.button(
            "calendar_note_all",
            "查看全部随笔",
            lambda: app.show_page("essay"),
            style="ghost",
            size=9,
            height=32,
        )


def _weekly_preview_body(app, block: Block) -> None:
    block.text("本周 · 情绪与感想", 12, COLORS["sage"], weight="bold")
    block.gap(8)
    report = local_weekly_report(app.store.weekly_stats()).replace("\n", " ")
    preview = report[report.find("这一周") :] if "这一周" in report else report
    if not preview.strip():
        preview = report
    preview = preview[:150] + ("…" if len(preview) > 150 else "")
    block.text(preview, 9, COLORS["ink_soft"], spacing=3)
    block.gap(8)
    block.text("AI 可深度整理" if app.ai.configured else "本地叙事生成", 8, COLORS["muted"])
    block.gap(10)
    block.button(
        "open_weekly_report",
        "打开《情绪与哲思周报》",
        app._open_weekly_report,
        style="primary",
        size=10,
        height=36,
        prefix="↗",
    )
