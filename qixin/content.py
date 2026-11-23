"""人文内容的门面：情绪、活动、任务寄语。

典藏语句在 :mod:`qixin.quotes`，音景与歌单在 :mod:`qixin.tracks`，这里
重新导出它们，旧的 ``from .content import ...`` 依然可用。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .quotes import QUOTES, quote_at, quote_for_day, quote_index
from .tracks import (
    TRACKS,
    TRACK_BY_ID,
    recommend_tracks,
    track_reason,
    weather_group,
)


MOODS: dict[str, dict[str, Any]] = {
    "精神状态良好": {
        "color": "#D49B36",
        "soft": "#F7EACB",
        "short": "☀",
        "description": "今天勉强算个人类高质量样本",
        "score": 5,
    },
    "美美得很": {
        "color": "#D6855E",
        "soft": "#F7E8DF",
        "short": "♡",
        "description": "允许自己有一点小得意",
        "score": 5,
    },
    "已老实": {
        "color": "#78957E",
        "soft": "#E6EFE7",
        "short": "◡",
        "description": "没有大悲大喜，先稳定活着",
        "score": 4,
    },
    "心流在线": {
        "color": "#4E7F85",
        "soft": "#E0EDEE",
        "short": "⌁",
        "description": "大脑终于和任务连上 Wi-Fi",
        "score": 4,
    },
    "摸鱼中": {
        "color": "#82996B",
        "soft": "#EAF0DE",
        "short": "≈",
        "description": "注意力正在工位附近自由散步",
        "score": 3,
    },
    "活人微死": {
        "color": "#8A7A66",
        "soft": "#EEE9E1",
        "short": "◌",
        "description": "人还在，电量只剩百分之三",
        "score": 2,
    },
    "淹没在作业海": {
        "color": "#C36D50",
        "soft": "#F6E5DC",
        "short": "≋",
        "description": "DDL 像浪一样一页接一页",
        "score": 2,
    },
    "无语": {
        "color": "#B8554B",
        "soft": "#F5E2DF",
        "short": "…",
        "description": "今天的世界有点不按说明书运行",
        "score": 2,
    },
    "灵魂出窍": {
        "color": "#737D96",
        "soft": "#E9EAF0",
        "short": "☁",
        "description": "身体还在，灵魂正在缓存",
        "score": 1,
    },
}

MOOD_ORDER = [
    "精神状态良好",
    "美美得很",
    "已老实",
    "心流在线",
    "摸鱼中",
    "活人微死",
    "淹没在作业海",
    "无语",
    "灵魂出窍",
]

LEGACY_MOOD_MAP = {
    "开心": "精神状态良好",
    "舒展": "美美得很",
    "平静": "已老实",
    "专注": "心流在线",
    "疲惫": "活人微死",
    "焦虑": "淹没在作业海",
    "烦躁": "无语",
    "低落": "灵魂出窍",
    "孤独": "灵魂出窍",
}

MOOD_TAG_ALIASES = {
    "精神状态良好": "开心",
    "美美得很": "舒展",
    "已老实": "平静",
    "心流在线": "专注",
    "摸鱼中": "舒展",
    "活人微死": "疲惫",
    "淹没在作业海": "焦虑",
    "无语": "烦躁",
    "灵魂出窍": "低落",
}

ACTIVITIES = ["写论文", "复习考试", "阅读", "运动", "放空"]

def time_bucket(hour: int | None = None) -> str:
    hour = datetime.now().hour if hour is None else hour
    if 5 <= hour < 9:
        return "清晨"
    if 9 <= hour < 12:
        return "上午"
    if 12 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "夜晚"
    return "深夜"


def task_wisdom(title: str, mood: str = "已老实") -> dict[str, Any]:
    text = title.lower()
    tag_mood = MOOD_TAG_ALIASES.get(mood, mood)
    score: dict[str, int] = {}
    keyword_groups = [
        (("论文", "报告", "写作", "开题", "文献"), ["写论文", "review", "report"]),
        (("复习", "考试", "刷题", "背诵", "课设"), ["复习考试", "期末", "考研"]),
        (("跑", "运动", "健身", "操场", "散步"), ["运动", "跑步"]),
        (("代码", "编程", "实验", "仿真", "debug"), ["实验", "代码", "编程"]),
        (("休息", "睡", "放松", "发呆"), ["休息", "放空"]),
        (("朋友", "聚餐", "聊天", "联系"), ["社交", "朋友"]),
    ]
    for quote in QUOTES:
        value = 2 if tag_mood in quote["tags"] else 0
        for words, tags in keyword_groups:
            if any(word in text for word in words):
                value += sum(5 for tag in tags if tag in quote["tags"])
        score[quote["id"]] = value
    chosen = max(QUOTES, key=lambda q: (score[q["id"]], -QUOTES.index(q)))
    return chosen


def care_note(mood: str, activity: str) -> str:
    notes = {
        "精神状态良好": "把今天让你状态在线的小事记下来。以后回头看，会知道这种轻盈有迹可循。",
        "美美得很": "允许自己真心高兴一会儿。好状态不需要先证明自己配得上。",
        "已老实": "稳定不是无趣，是你暂时找到了一种不内耗的活法。",
        "心流在线": "珍惜这段连上 Wi-Fi 的注意力，也记得每四十分钟让眼睛休息。",
        "摸鱼中": "摸鱼可以，但给自己设一个小小结束点。休息要尽兴，回来也要容易。",
        "活人微死": "低电量模式也算模式。今天只做最低限度，再把恢复写进日程。",
        "淹没在作业海": "先抓住最近的一块浮木：写下一个题目、打开一页材料，只做两分钟。",
        "无语": "先不对世界发表长篇评论。离开屏幕三十秒，让这口无语先散一散。",
        "灵魂出窍": "身体还在坚持，已经值得被照顾。先喝水、吃点东西，再做下一件小事。",
    }
    if activity in {"复习考试", "写论文"} and mood not in {"美美得很", "精神状态良好"}:
        return notes[mood]
    if activity == "运动":
        return notes[mood] + " 出门前记得看一眼天气。"
    if activity == "放空":
        return notes[mood] + " 发呆不需要产出。"
    return notes.get(mood, "按自己的速度来，今天也算数。")

__all__ = [
    "ACTIVITIES",
    "MOODS",
    "MOOD_ORDER",
    "QUOTES",
    "TRACKS",
    "TRACK_BY_ID",
    "care_note",
    "quote_at",
    "quote_for_day",
    "quote_index",
    "recommend_tracks",
    "task_wisdom",
    "time_bucket",
    "track_reason",
    "weather_group",
]
