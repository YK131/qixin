"""栖心 · 吴健雄学院活动信息（自包含模块，仅用标准库）。

职责：从东南大学吴健雄学院官网首页抓取近期条目，跟进详情页
（含微信公众号文章），把「导师交流 / 人文讲座 / 通知」解析成
一眼能看懂的字段，供上层 UI 分条罗列与“抢选提醒”。

对外 API::

    NewsItem / NewsFeed
    parse_article(title, text, url="", published="") -> NewsItem   # 纯函数
    extract_fields(text) -> dict[str, str]                        # 纯函数
    clean_name(raw) -> str                                        # 纯函数
    NewsService(cache_dir=None).fetch(force=False, limit=8)
    NewsService(cache_dir=None).fetch_async(on_done, force=False)

设计约定：
* 任何网络/解析异常都在内部消化，不抛给调用方；
* 网络全挂时返回 30 分钟缓存，无缓存时返回 2 条内置示例（live=False）；
* 缺失字段一律留空字符串，绝不编造（例如导师交流每场的时间可能只在图片里）。
"""

from __future__ import annotations

from .files import write_text_atomic

import hashlib
import html as html_lib
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import app_data_dir

__all__ = [
    "NewsItem",
    "NewsFeed",
    "NewsService",
    "parse_article",
    "reminder_items",
    "extract_fields",
    "clean_name",
    "HOME_URL",
    "CACHE_TTL_MINUTES",
    "MAX_DETAIL_PAGES",
]


HOME_URL = "https://wjx.seu.edu.cn/"
CACHE_TTL_MINUTES = 30
CACHE_FILE = "news.json"
REQUEST_TIMEOUT = 15          # 秒：10-20 秒之间
MAX_DETAIL_PAGES = 6          # 最多跟进 6 个详情页
MAX_BYTES = 6 * 1024 * 1024   # 单页最大 6MB
MAX_TEXT_CHARS = 200_000      # 正文截断，防御性上限

KIND_MENTOR = "导师交流"
KIND_LECTURE = "人文讲座"
KIND_NOTICE = "通知"
REMINDER_KINDS = (KIND_MENTOR, KIND_LECTURE)

SOURCE_SITE = "吴健雄学院官网"
SOURCE_WECHAT = "微信公众号"
SOURCE_SAMPLE = "内置示例"
SIGNUP_TIMEZONE = timezone(timedelta(hours=8))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 QixinDesktop/0.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Connection": "close",
}


# --------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------


@dataclass
class NewsItem:
    """一条活动/通知信息。字段缺失时保持空字符串，不猜测。"""

    key: str
    title: str
    kind: str
    url: str
    source: str
    published: str
    speakers: list[str] = field(default_factory=list)
    speaker_detail: str = ""
    topic: str = ""
    when_text: str = ""
    place: str = ""
    signup_text: str = ""
    seats: str = ""
    summary: str = ""
    needs_reminder: bool = False
    signup_url: str = ""


@dataclass
class NewsFeed:
    items: list[NewsItem] = field(default_factory=list)
    fetched_at: str = ""
    live: bool = False
    source_note: str = ""
    error: str = ""


# --------------------------------------------------------------------------
# 文本清洗与正则工具
# --------------------------------------------------------------------------

_SPACE_RE = re.compile(r"[ \t\f\v\u00a0\u3000]+")
_NEWLINE_RE = re.compile(r"\n{3,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_DATE_RE = re.compile(r"((?:19|20)\d{2})[^\d]{0,3}(\d{1,2})[^\d]{0,3}(\d{1,2})")
_EVENT_DATE = re.compile(
    r"(?<![\d:：])(?:(?:(?P<year>(?:19|20)\d{2})\s*[年./-]\s*)?"
    r"(?P<month>0?[1-9]|1[0-2])\s*[月./-]\s*(?P<day>\d{1,2})(?:\s*日|(?![\d:：]))"
    r"|(?P<short_day>\d{1,2})\s*日)"
)
_EVENT_CLOCK = re.compile(r"(?<!\d)(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2})(?!\d)")
_DEADLINE = re.compile(r"(?:报名|抢选)(?:已|将于)?\s*(?:截止|结束)|截止(?:报名|抢选)|截[止至](?:时间|于)?")
_TIME_RANGE = re.compile(r"[至到~～—–]\s*(?=\d)|\s-\s(?=\d)|(?<=\d)\s*-\s*(?=\d{1,2}\s*[:：])")
_SIGNUP_OPEN = re.compile(r"(?:(?:开放|开始)(?:报名|抢选)|(?:报名|抢选)(?:开放|开始))")
_TITLE_SUFFIX_RE = re.compile(
    r"(?:教授|副教授|讲师|老师|博士|硕士|研究员|副研究员|院士|主任|副主任|院长|副院长|"
    r"导师|工程师|高级工程师|总经理|董事长|书记|校长)$"
)
_BIO_HINTS = (
    "教授",
    "副教授",
    "讲师",
    "研究员",
    "博士",
    "硕士",
    "研究生",
    "校友",
    "工程师",
    "学位",
    "实验室",
    "医院",
)

_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章"
    "云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安"
    "常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋"
    "茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊"
    "胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑"
    "裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班"
    "仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸"
    "籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈"
    "燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡"
    "国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰"
    "巢关蒯相查后荆红游竺权逯盖益桓公闫肖覃佘尧帅况邸亢完才念宇密区冒柒第独皇令仪厚"
)

_NAME_STOPWORDS = {
    "常规场次",
    "活动介绍",
    "报名方式",
    "报名时间",
    "主讲人简介",
    "推荐理由",
    "讲座简介",
    "活动安排",
    "时间安排",
    "说明",
    "主办",
    "承办",
    "协办",
    "联系方式",
    "温馨提示",
    "注意事项",
}


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _collapse_spaces(text: str) -> str:
    return _SPACE_RE.sub(" ", text or "").strip()


def _normalize_text(text: str) -> str:
    """正文纯文本归一化：统一空白、去空行，但保留行结构。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\u00a0", " ").replace("\u3000", " ")
    lines = [_collapse_spaces(line) for line in raw.split("\n")]
    joined = "\n".join(lines)
    joined = _NEWLINE_RE.sub("\n\n", joined)
    return joined.strip()[:MAX_TEXT_CHARS]


def _clip(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip("，、；;：: 　")


def clean_name(raw: str) -> str:
    """姓名清洗：合并「吴 俊」「闫　浩」这类被空格拆开的两字姓名。"""
    value = (raw or "").replace("\u3000", " ").replace("\u00a0", " ")
    value = re.sub(r"\s+", "", value)
    return value.strip("·・-—_,，、;；:：()（）[]【】\"'“”‘’")


def _norm_date(value: str) -> str:
    """把 '2026-11-09' / '2026年11月9日' / '2026 11-09' 归一成 ISO 日期。"""
    text = (value or "").strip()
    if not text:
        return ""
    match = _DATE_RE.search(text)
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


def _schedule_points(value: str, reference: datetime) -> list[tuple[datetime, bool]]:
    """Read calendar dates and clocks, using the announcement date for omitted years."""
    dates = list(_EVENT_DATE.finditer(value))
    points: list[tuple[datetime, bool]] = []
    for index, match in enumerate(dates):
        anchor = points[-1][0] if points else reference
        try:
            day = reference.replace(
                year=int(match["year"] or anchor.year),
                month=int(match["month"] or anchor.month),
                day=int(match["day"] or match["short_day"]),
                hour=0, minute=0, second=0, microsecond=0,
            )
            if not match["year"] and match["month"]:
                difference = (day - anchor).days
                if abs(difference) > 180:
                    day = day.replace(year=day.year + (1 if difference < 0 else -1))
        except ValueError:
            continue
        tail = value[match.end() : dates[index + 1].start() if index + 1 < len(dates) else None]
        clocks = list(_EVENT_CLOCK.finditer(tail))
        if not clocks:
            points.append((day, False))
        for clock in clocks:
            hour, minute = int(clock["hour"]), int(clock["minute"])
            period = re.search(r"(下午|晚上|傍晚|凌晨|上午|中午)\s*$", tail[:clock.start()])
            if period and period[1] in {"下午", "晚上", "傍晚"} and hour < 12:
                hour += 12
            if (hour < 24 and minute < 60) or (hour == 24 and minute == 0):
                points.append((day + timedelta(hours=hour, minutes=minute), True))
    return points


def _registration_deadline(value: str, reference: datetime) -> datetime | None:
    for clause in re.split(r"[。！!；;\n]", value):
        if _DEADLINE.search(clause) and "退选" not in clause:
            points = _schedule_points(clause, reference)
            if points:
                end, has_clock = points[-1]
                return end if has_clock else end + timedelta(days=1)
    points = _schedule_points(value, reference)
    if len(points) <= 1 or not _TIME_RANGE.search(value):
        return None
    end, has_clock = points[-1]
    return end if has_clock else end + timedelta(days=1)


def _announcement_date(item: NewsItem, fetched_at: str, now: datetime) -> datetime:
    return datetime.fromisoformat(
        _norm_date(item.published) or _norm_date(fetched_at) or now.date().isoformat()
    ).replace(tzinfo=SIGNUP_TIMEZONE)


def signup_opening(item: NewsItem, fetched_at: str = "") -> datetime | None:
    """Suggest a Beijing opening time only when there is a date and clock."""
    reference = _announcement_date(item, fetched_at, datetime.now(SIGNUP_TIMEZONE))
    for clause in re.split(r"[。！!；;\n]", item.signup_text):
        if _SIGNUP_OPEN.search(clause):
            before_deadline = _DEADLINE.split(clause, maxsplit=1)[0]
            points = _schedule_points(before_deadline, reference)
        elif _DEADLINE.search(clause) is None and _TIME_RANGE.search(clause):
            points = _schedule_points(clause, reference)
        else:
            continue
        if points and points[0][1]:
            return points[0][0]
    return None


def signup_cutoff(item: NewsItem, fetched_at: str, now: datetime) -> datetime | None:
    reference = _announcement_date(item, fetched_at, now)
    cutoff = _registration_deadline(item.signup_text, reference)
    event_text = item.when_text.strip("。 ")
    event_points = _schedule_points(event_text, reference) if event_text not in item.signup_text else []
    if event_points:
        start, has_clock = event_points[0]
        event_cutoff = start if has_clock else start + timedelta(days=1)
        cutoff = min(cutoff, event_cutoff) if cutoff else event_cutoff
    return cutoff


def reminder_items(feed: NewsFeed, now: datetime | None = None) -> list[NewsItem]:
    """Return announcements whose registration or event time has yet to expire."""
    if now is None:
        now = datetime.now(SIGNUP_TIMEZONE)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=SIGNUP_TIMEZONE)
    else:
        now = now.astimezone(SIGNUP_TIMEZONE)
    reminders = []
    for item in feed.items:
        if not item.needs_reminder or not (item.signup_text or item.when_text):
            continue
        if re.search(r"(?:报名|抢选)已(?:结束|截止)|名额已满", item.signup_text):
            continue
        cutoff = signup_cutoff(item, feed.fetched_at, now)
        if cutoff is None:
            reference = _announcement_date(item, feed.fetched_at, now)
            opening_points = _schedule_points(item.signup_text, reference)
            if opening_points:
                opening, _ = opening_points[-1]
                cutoff = opening.replace(hour=0, minute=0) + timedelta(days=1)
        if cutoff is None or now < cutoff:
            reminders.append(item)
    return reminders


def _split_leading_date(text: str) -> tuple[str, str]:
    """拆出官网列表里「2026-11-09 标题」形式的前置日期。"""
    match = re.match(
        r"^((?:19|20)\d{2}[^\d]{0,3}\d{1,2}[^\d]{0,3}\d{1,2}\s*日?)", text or ""
    )
    if not match:
        return "", (text or "")
    rest = (text or "")[match.end() :].lstrip(" ·・|｜-—:：,，")
    return _norm_date(match.group(1)), rest


def _strip_title_suffix(name: str) -> str:
    value = name
    for _ in range(3):
        trimmed = _TITLE_SUFFIX_RE.sub("", value)
        if trimmed == value:
            break
        value = trimmed
    return value


def _looks_like_name(value: str) -> bool:
    """是否是“像姓名”的字符串：2-5 个汉字、姓在百家姓表内、不是停用词。"""
    name = _strip_title_suffix(clean_name(value))
    if not 2 <= len(name) <= 5:
        return False
    if not all(_is_cjk(ch) for ch in name):
        return False
    if name in _NAME_STOPWORDS:
        return False
    return name[0] in _SURNAMES


def _looks_like_bio(line: str) -> bool:
    """简介行：开头就带职称/学位（挡掉「大学生活」这类正文误判）。"""
    text = (line or "").strip()
    if len(text) < 12:
        return False
    if text[0] in "“”「」『』\"'—–-·":
        return False
    window = text[:30]
    return any(hint in window for hint in _BIO_HINTS)


# --------------------------------------------------------------------------
# 字段抽取（纯函数）
# --------------------------------------------------------------------------

_FIELD_PATTERNS = {
    "place": r"(?:讲座地点|活动地点|报告地点|交流地点|地\s*点|地\s*址)",
    "topic": r"(?:讲座题目|报告题目|主\s*题|题\s*目)",
    "speakers": r"(?:演\s*讲\s*人|主\s*讲\s*人|报\s*告\s*人|主\s*讲\s*嘉\s*宾|演\s*讲\s*嘉\s*宾|嘉\s*宾|导\s*师)",
}


def _line_value(lines: list[str], labels: str) -> str:
    pattern = re.compile(
        r"^\s*[【\[(（]?\s*(?:%s)\s*[】\])）]?\s*[：:]\s*(?P<value>.+)$" % labels
    )
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        value = _collapse_spaces(match.group("value"))
        value = re.split(r"\s{2,}", value)[0]
        if not value:
            continue
        return _clip(value, 80)
    return ""


def _split_top_level(value: str) -> list[str]:
    """按「、，,；;」切分，但括号内的分隔符不切（避免切开单位职称）。"""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    for char in value or "":
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(0, depth - 1)
        if depth == 0 and char in "、，,；;":
            parts.append("".join(buffer))
            buffer = []
            continue
        buffer.append(char)
    parts.append("".join(buffer))
    return [part for part in (piece.strip() for piece in parts) if part]


def _parse_speaker_value(value: str) -> tuple[list[str], str]:
    """从「胡汉辉（东南大学经管学院退休教授）」这类值里拆出姓名与单位职称。"""
    names: list[str] = []
    detail = ""
    for part in _split_top_level(value):
        if "（" in part or "(" in part:
            sides = [part]
        elif "和" in part or "及" in part:
            candidates = [side.strip() for side in re.split(r"[和及]", part) if side.strip()]
            if len(candidates) > 1 and all(_looks_like_name(c) for c in candidates):
                sides = candidates
            else:
                sides = [part]
        else:
            sides = [part]
        for side in sides:
            name = ""
            part_detail = ""
            match = re.match(r"^([^（(]{1,20})[（(]([^）)]{1,80})[）)]", side)
            if match:
                name = clean_name(match.group(1))
                part_detail = match.group(2).strip()
            else:
                name = _strip_title_suffix(clean_name(side))
                if not _looks_like_name(name):
                    # 「东南大学…教授胡汉辉」式写法：兜底找紧邻职称的姓名
                    for pattern in (
                        r"([\u4e00-\u9fff]{2,4})(?=(?:教授|副教授|老师|博士|研究员|院长|主任))",
                        r"(?:教授|副教授|老师|博士|研究员|院长|主任)\s*([\u4e00-\u9fff]{2,4})$",
                    ):
                        hit = re.search(pattern, side)
                        if hit and _looks_like_name(hit.group(1)):
                            name = clean_name(hit.group(1))
                            break
            if _looks_like_name(name):
                if name not in names:
                    names.append(name)
                if part_detail and not detail:
                    detail = part_detail
    return names, detail


def _find_signup(text: str) -> str:
    """抽取报名/抢选开放时间原文，优先 【报名时间】 段。"""
    deadline = next((
        part.strip() for part in re.split(r"[。！!；;\n]+", text)
        if _DEADLINE.search(part) and _EVENT_DATE.search(part) and "退选" not in part
    ), "")
    marker = re.search(r"【\s*报\s*名\s*时\s*间\s*】", text)
    if marker:
        tail = text[marker.end() :].lstrip()
        cut = min(len(tail), 240)
        for stop in ("【", "\n如因", "\n主办", "\n图文", "\n一审", "\n编辑", "\n排版", "\n来源"):
            index = tail.find(stop)
            if index > 0:
                cut = min(cut, index)
        chunk = _collapse_spaces(tail[:cut].replace("\n", " "))
        chunk = re.split(r"(?<=[。！!])", chunk)[0] or chunk
        if chunk:
            if deadline and deadline not in chunk:
                return f"{_clip(chunk, 120)} {_clip(deadline, 120)}"
            return _clip(chunk, 160)
    for pattern in (
        r"(?m)^\s*(?:报名|抢选)\s*时间\s*[:：]\s*[^\n。；;]+",
        rf"[^\n。；;]{{0,60}}{_SIGNUP_OPEN.pattern}[^\n。；;]{{0,60}}",
        r"(?:(?:报名|抢选)[^\n。；;]{0,40}\d{1,2}\s*[:：]\s*\d{2}[^\n。；;]{0,30})",
    ):
        hit = re.search(pattern, text)
        if hit:
            chunk = _collapse_spaces(hit.group(0))
            if deadline and deadline not in chunk and _SIGNUP_OPEN.search(chunk):
                return f"{_clip(chunk, 120)}。{_clip(deadline, 120)}"
            return _clip(chunk, 160)
    return _clip(deadline, 160)


def signup_link(url: str) -> str:
    """Accept only ordinary web links as notification actions."""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
            return url
    except ValueError:
        pass
    return ""


def _find_signup_url(text: str) -> str:
    section = re.search(r"【\s*报名方式\s*】([^【]{1,1000})", text)
    candidates = [section[1]] if section else []
    candidates.extend(line for line in text.splitlines() if re.search(r"报名|抢选|登录|选课", line))
    for line in candidates:
        match = re.search(r"https?://[^\s<>\"'，。；、（）【】！？]+", line, re.I)
        if match:
            url = signup_link(match.group().rstrip(").,;"))
            if url:
                return url
    return ""


def _plausible_place(value: str) -> bool:
    """挡掉页脚里的邮政地址（「江苏省…市…路2号…」），那不是活动地点。"""
    text = (value or "").strip()
    if not text or len(text) > 40:
        return False
    if re.search(r"省[^。]{0,12}市", text) and re.search(r"(号|路|大道)", text):
        return False
    return True


def _find_seats(text: str) -> str:
    for pattern in (
        r"(\d{1,4})\s*个?\s*名\s*额",
        r"名\s*额\s*[：:]\s*(\d{1,4})",
        r"(\d{1,4})\s*个?\s*(?:人|位)\s*(?:名额|限额)",
        r"限\s*(\d{1,4})\s*(?:人|位)",
    ):
        hit = re.search(pattern, text)
        if hit:
            return f"{int(hit.group(1))} 个名额"
    return ""


def _find_when_fallback(text: str, signup_text: str) -> str:
    """没有「时间：」标签时，只认同时带日期与钟点、且没有前置标签的写法。"""
    matches = re.finditer(
        r"((?:19|20)\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日[^\n。]{0,45}?"
        r"\d{1,2}\s*[:：]\s*\d{2}[^\n。]{0,12})",
        text,
    )
    for match in matches:
        value = _collapse_spaces(match.group(1))
        if value.strip("。 ") not in signup_text and not re.search(r"报名|抢选|退选|截止", value):
            return _clip(value, 80)
    return ""


def _find_when(text: str, signup_text: str) -> str:
    """时间：优先标签；排除「报名时间」等行；再尝试正文兜底。"""
    for line in text.splitlines():
        if re.search(r"(报名|退选|截止|开放|发布|更新)时\s*间", line):
            continue
        match = re.match(
            r"^\s*[【\[(（]?\s*(?:讲座时间|活动时间|报告时间|交流时间|时\s*间)\s*[】\])）]?\s*[：:]\s*(?P<v>.+)$",
            line,
        )
        if match:
            value = _collapse_spaces(match.group("v"))
            if value:
                return _clip(value, 80)
    return _find_when_fallback(text, signup_text)


def _extract_bare_names(
    lines: list[str],
) -> tuple[list[str], str]:
    """导师交流正文：姓名单独成行 + 下一行是该导师简介。"""
    names: list[str] = []
    detail = ""
    for index, line in enumerate(lines):
        raw = line.strip()
        if not raw or len(raw) > 8:
            continue
        if re.search(r"[0-9A-Za-z]", raw):
            continue
        if not _looks_like_name(raw):
            continue
        bio = ""
        for later in lines[index + 1 : index + 3]:
            if later.strip():
                bio = later.strip()
                break
        if not _looks_like_bio(bio):
            continue
        name = _strip_title_suffix(clean_name(raw))
        if not _looks_like_name(name):
            continue
        if name not in names:
            names.append(name)
        if not detail and bio:
            detail = _clip(re.split(r"[。；;，,（(]", bio)[0].strip(), 40)
    return names, detail


def extract_fields(text: str) -> dict[str, str]:
    """纯函数：从正文纯文本抽取 演讲人/主题/时间/地点/报名时间/名额。"""
    result = {
        "speakers": "",
        "speaker_detail": "",
        "topic": "",
        "when": "",
        "place": "",
        "signup": "",
        "seats": "",
    }
    try:
        body = _normalize_text(text)
    except Exception:  # pragma: no cover - 防御性
        return result
    if not body:
        return result

    lines = body.splitlines()

    speaker_value = _line_value(lines, _FIELD_PATTERNS["speakers"])
    names, detail = _parse_speaker_value(speaker_value) if speaker_value else ([], "")
    if not names:
        names, detail = _extract_bare_names(lines)

    result["speakers"] = "、".join(names)
    result["speaker_detail"] = _clip(detail, 60)
    result["topic"] = _line_value(lines, _FIELD_PATTERNS["topic"])
    place = _line_value(lines, _FIELD_PATTERNS["place"])
    result["place"] = place if _plausible_place(place) else ""
    result["signup"] = _find_signup(body)
    result["when"] = _find_when(body, result["signup"])
    result["seats"] = _find_seats(body)
    return result


# --------------------------------------------------------------------------
# 分类 / 概述 / 键
# --------------------------------------------------------------------------


def _classify(title: str, text: str) -> str:
    head = title or ""
    if KIND_MENTOR in head:
        return KIND_MENTOR
    if KIND_LECTURE in head or "讲座" in head:
        return KIND_LECTURE
    body = text or ""
    if KIND_MENTOR in body:
        return KIND_MENTOR
    if KIND_LECTURE in body or "讲座" in body:
        return KIND_LECTURE
    return KIND_NOTICE


def _topic_from_title(title: str) -> str:
    value = title or ""
    value = re.sub(r"^(?:【[^】]*】\s*)?", "", value)
    for prefix in (KIND_LECTURE, KIND_MENTOR, "通知", "讲座"):
        value = re.sub(rf"^\s*{prefix}\s*[|｜·:：\-—]\s*", "", value)
    value = re.sub(r"^\s*(?:20\d{2}[^\d]{0,3}\d{1,2}[^\d]{0,3}\d{1,2})\s*", "", value)
    value = re.sub(r"^\s*[|｜·:：\-—]\s*", "", value)
    value = _clip(_collapse_spaces(value), 60)
    if len(value) < 4 or value in {KIND_MENTOR, KIND_LECTURE, KIND_NOTICE}:
        return ""
    return value


_SUMMARY_TAIL = "，具体以学院原文通知为准。"
_SUMMARY_FILLERS = (
    "打开原文可查看完整安排与报名入口。",
    "如有变动，请以学院最新通知为准。",
)


def _build_summary(
    kind: str,
    title: str,
    speakers: list[str],
    speaker_detail: str,
    topic: str,
    when_text: str,
    place: str,
    seats: str,
    signup_text: str,
) -> str:
    who = "、".join(speakers[:3])
    if who and speaker_detail:
        who = f"{who}（{speaker_detail}）"
    if topic in {kind, title}:
        topic = ""
    bits = [who, topic, when_text, place, seats]
    body = "，".join(bit for bit in bits if bit)
    if not body:
        body = title
    summary = f"{kind}｜{body}" if body else kind
    if len(summary) < 60 and signup_text and signup_text not in summary:
        summary = f"{summary}，{signup_text}"
    if len(summary) < 60:
        summary = summary.rstrip("，、；;：: ") + _SUMMARY_TAIL
    for filler in _SUMMARY_FILLERS:
        if len(summary) >= 60:
            break
        summary = summary + filler
    if len(summary) > 90:
        summary = summary[:89].rstrip("，、；;：: ") + "…"
    return summary


def _make_key(url: str, title: str = "", text: str = "") -> str:
    basis = (url or "").strip()
    if not basis:
        basis = f"{title}\n{(text or '')[:120]}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _source_for(url: str) -> str:
    host = (url or "").lower()
    if "mp.weixin.qq.com" in host or "weixin.qq.com" in host:
        return SOURCE_WECHAT
    return SOURCE_SITE


def parse_article(
    title: str,
    text: str,
    url: str = "",
    published: str = "",
) -> NewsItem:
    """纯函数：把「标题 + 正文纯文本」解析成 NewsItem，可离线单测。"""
    safe_title = _collapse_spaces(title or "")[:160]
    safe_text = text or ""
    try:
        fields = extract_fields(safe_text)
    except Exception:  # pragma: no cover - 防御性
        fields = {"speakers": "", "speaker_detail": "", "topic": "", "when": "", "place": "", "signup": "", "seats": ""}

    speakers = [name for name in fields["speakers"].split("、") if name]
    kind = _classify(safe_title, safe_text)
    topic = fields["topic"] or _topic_from_title(safe_title)
    when_text = fields["when"]
    place = fields["place"]
    seats = fields["seats"]
    signup_text = fields["signup"]
    speaker_detail = fields["speaker_detail"]
    return NewsItem(
        key=_make_key(url, safe_title, safe_text),
        title=safe_title,
        kind=kind,
        url=(url or "").strip(),
        source=_source_for(url),
        published=_norm_date(published),
        speakers=speakers,
        speaker_detail=speaker_detail,
        topic=topic,
        when_text=when_text,
        place=place,
        signup_text=signup_text,
        seats=seats,
        summary=_build_summary(
            kind,
            safe_title,
            speakers,
            speaker_detail,
            topic,
            when_text,
            place,
            seats,
            signup_text,
        ),
        needs_reminder=kind in REMINDER_KINDS,
        signup_url=_find_signup_url(safe_text),
    )


# --------------------------------------------------------------------------
# HTML → 纯文本
# --------------------------------------------------------------------------

_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?href\s*=\s*[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<inner>.*?)</a>",
    re.S | re.I,
)
_SKIP_EXT_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z|jpe?g|png|gif)(?:$|\?)", re.I)
_HOME_KEYWORDS = (
    "讲座",
    "导师交流",
    "交流计划",
    "导师制",
    "讲堂",
    "报告会",
    "沙龙",
    "通知",
    "公示",
    "名单",
)
_WECHAT_TAIL_MARKERS = (
    'id="js_pc_qr_code"',
    'class="rich_media_tool',
    'id="js_article_comment"',
    'id="js_power_by"',
    "预览时标签不可点",
)
_SITE_BLOCK_PATTERNS = (
    r'<div[^>]*class="[^"]*v_news_content[^"]*"[^>]*>',
    r'<div[^>]*id="vsb_content"[^>]*>',
    r'<div[^>]*class="[^"]*wp_articlecontent[^"]*"[^>]*>',
    r'<div[^>]*id="js_content"[^>]*>',
)


def _html_to_text(fragment: str) -> str:
    """HTML 片段转纯文本：块级标签断行，保留标点与原文顺序。"""
    if not fragment:
        return ""
    text = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    text = re.sub(
        r"<(script|style|noscript|svg|iframe)\b[^>]*>.*?</\1\s*>",
        "",
        text,
        flags=re.S | re.I,
    )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(
        r"</(?:p|div|section|li|tr|h[1-6]|table|blockquote|article|td|dd|dt)\s*>",
        "\n",
        text,
        flags=re.I,
    )
    text = re.sub(r"<[^>]+>", "", text)
    try:
        text = html_lib.unescape(text)
    except Exception:  # pragma: no cover - 防御性
        pass
    lines = [_collapse_spaces(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _main_block(html: str) -> str:
    """尽量只取正文容器，避免导航/页脚噪声。"""
    for pattern in _SITE_BLOCK_PATTERNS:
        match = re.search(pattern, html, re.I)
        if not match:
            continue
        tail = html[match.end() :]
        for marker in _WECHAT_TAIL_MARKERS:
            index = tail.find(marker)
            if index > 0:
                tail = tail[:index]
        trimmed = tail[:MAX_TEXT_CHARS]
        return trimmed
    return html


def _wechat_title(html: str) -> str:
    for pattern in (
        r'<meta[^>]*property\s*=\s*["\']og:title["\'][^>]*content\s*=\s*["\'](?P<v>[^"\']*)["\']',
        r'<meta[^>]*content\s*=\s*["\'](?P<v>[^"\']*)["\'][^>]*property\s*=\s*["\']og:title["\']',
    ):
        match = re.search(pattern, html, re.I)
        if match and match.group("v").strip():
            return _collapse_spaces(html_lib.unescape(match.group("v")))
    return ""


def _wechat_published(html: str) -> str:
    for pattern in (
        r'var\s+ct\s*=\s*["\']?(\d{10,13})',
        r'"create_time"\s*:\s*"?(\d{10,13})',
        r'property\s*=\s*["\']og:release_date["\'][^>]*content\s*=\s*["\']([^"\']+)',
    ):
        match = re.search(pattern, html)
        if not match:
            continue
        value = match.group(1)
        if value.isdigit():
            stamp = int(value)
            if stamp > 10_000_000_000:
                stamp //= 1000
            try:
                return datetime.fromtimestamp(stamp).date().isoformat()
            except (OverflowError, OSError, ValueError):
                continue
        normalized = _norm_date(value)
        if normalized:
            return normalized
    return ""


def _detail_text(html: str) -> tuple[str, str]:
    """返回 (标题, 正文纯文本)。微信文章取 js_content，站内页取正文容器。"""
    title = _wechat_title(html)
    block = _main_block(html)
    return title, _html_to_text(block)


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------


def _http_get(url: str, timeout: int = REQUEST_TIMEOUT, limit: int = MAX_BYTES) -> tuple[str, str]:
    """GET 一个页面，返回 (解码后的内容, 跟随重定向后的最终 URL)。"""
    if not re.match(r"^https?://", url or "", re.I):
        raise ValueError("不支持的链接")
    request = urllib.request.Request(url, headers=dict(_HEADERS))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status and int(status) >= 400:
            raise RuntimeError(f"HTTP {status}")
        raw = response.read(limit)
        final_url = getattr(response, "geturl", lambda: url)() or url
        charset = ""
        headers = getattr(response, "headers", None)
        if headers is not None and hasattr(headers, "get_content_charset"):
            charset = headers.get_content_charset() or ""
    return _decode(raw, charset), final_url


def _decode(raw: bytes, charset: str = "") -> str:
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_home(html: str) -> list[dict[str, str]]:
    """从官网首页抽候选条目：标题、绝对链接、列表日期、来源提示。"""
    candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: dict[str, dict[str, str]] = {}

    for match in _ANCHOR_RE.finditer(html or ""):
        href = (match.group("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        inner = re.sub(r"<[^>]+>", " ", match.group("inner") or "")
        try:
            inner = html_lib.unescape(inner)
        except Exception:  # pragma: no cover - 防御性
            pass
        text = _collapse_spaces(inner)
        if len(text) < 8:
            continue
        if not any(keyword in text for keyword in _HOME_KEYWORDS):
            continue
        url = urllib.parse.urljoin(HOME_URL, href)
        if _SKIP_EXT_RE.search(url):
            continue
        published, clean_title = _split_leading_date(text)
        clean_title = _collapse_spaces(clean_title)
        if len(clean_title) < 6:
            continue
        if url in seen_urls:
            existing = seen_titles.get(clean_title)
            if existing and not existing.get("published") and published:
                existing["published"] = published
            continue
        seen_urls.add(url)
        entry = {
            "title": clean_title[:160],
            "url": url,
            "published": published,
        }
        candidates.append(entry)
        seen_titles.setdefault(clean_title, entry)
    return candidates


def _priority(candidate: dict[str, str]) -> int:
    title = candidate.get("title", "")
    if KIND_MENTOR in title or KIND_LECTURE in title or "讲座" in title:
        return 0
    if "公示" in title or "名单" in title:
        return 2
    return 1


def _sort_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    ordered = sorted(
        enumerate(candidates),
        key=lambda pair: pair[1].get("published", ""),
        reverse=True,
    )
    ordered.sort(key=lambda pair: _priority(pair[1]))
    return [item for _, item in ordered]


def _sort_items(items: list[NewsItem]) -> list[NewsItem]:
    ordered = sorted(items, key=lambda item: item.published or "", reverse=True)
    ordered.sort(key=lambda item: 0 if item.needs_reminder else 1)
    return ordered


# --------------------------------------------------------------------------
# 内置示例（网络不可用时的兜底，明确标记来源）
# --------------------------------------------------------------------------

_SAMPLE_LECTURE_TITLE = "人文讲座 | 示例：数智时代的领导力（内置示例）"
_SAMPLE_LECTURE_TEXT = """健雄书院高端人文讲座（示例）
演讲人：李明远（东南大学经济管理学院教授）
主 题：数智时代的领导力（内置示例）
时 间：2026年11月18日（周三）下午16:00-18:00
地 点：九龙湖校区健雄书院报告厅
【报名方式】
吴健雄学院学生登录 http://jxsy.seu.edu.cn 报名。
【报名时间】
本场讲座将面向吴健雄学院各年级学子开放60个名额，将于11月17日（周二）中午12:30开放报名，请提前做好准备。
"""

_SAMPLE_MENTOR_TITLE = "导师交流 | 示例：第204期导师交流（内置示例）"
_SAMPLE_MENTOR_TEXT = """“健雄书院导师交流时间”安排（示例）
常规场次
周文清
东南大学信息科学与工程学院教授，研究方向为智能感知与信号处理。
顾南舟
东南大学计算机科学与工程学院副教授，研究方向为具身智能与机器人。
【报名方式】
登录 http://jxsy.seu.edu.cn，在导师制部分选择批次并完成报名。
【报名时间】
本期导师交流将于11月13日（周五）中午12:30开放报名，请提前做好准备。
"""


def sample_items() -> list[NewsItem]:
    """两条内置示例，source 明确标记为「内置示例」。"""
    lecture = parse_article(
        _SAMPLE_LECTURE_TITLE,
        _SAMPLE_LECTURE_TEXT,
        url="https://wjx.seu.edu.cn/",
        published="",
    )
    mentor = parse_article(
        _SAMPLE_MENTOR_TITLE,
        _SAMPLE_MENTOR_TEXT,
        url="https://wjx.seu.edu.cn/",
        published="",
    )
    return [
        replace(lecture, source=SOURCE_SAMPLE),
        replace(mentor, source=SOURCE_SAMPLE),
    ]


# --------------------------------------------------------------------------
# 服务
# --------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _short_error(exc: BaseException) -> str:
    detail = str(exc).strip().splitlines()
    text = detail[0] if detail else exc.__class__.__name__
    return _clip(f"{exc.__class__.__name__}: {text}", 120)


def _item_to_dict(item: NewsItem) -> dict[str, object]:
    return {
        "key": item.key,
        "title": item.title,
        "kind": item.kind,
        "url": item.url,
        "source": item.source,
        "published": item.published,
        "speakers": list(item.speakers),
        "speaker_detail": item.speaker_detail,
        "topic": item.topic,
        "when_text": item.when_text,
        "place": item.place,
        "signup_text": item.signup_text,
        "signup_url": item.signup_url,
        "seats": item.seats,
        "summary": item.summary,
        "needs_reminder": bool(item.needs_reminder),
    }


def _item_from_dict(payload: object) -> NewsItem | None:
    if not isinstance(payload, dict):
        return None
    try:
        speakers = payload.get("speakers") or []
        if not isinstance(speakers, list):
            speakers = [str(speakers)]
        kind = str(payload.get("kind") or KIND_NOTICE)
        return NewsItem(
            key=str(payload.get("key") or ""),
            title=str(payload.get("title") or ""),
            kind=kind,
            url=str(payload.get("url") or ""),
            source=str(payload.get("source") or SOURCE_SITE),
            published=str(payload.get("published") or ""),
            speakers=[str(name) for name in speakers if name],
            speaker_detail=str(payload.get("speaker_detail") or ""),
            topic=str(payload.get("topic") or ""),
            when_text=str(payload.get("when_text") or ""),
            place=str(payload.get("place") or ""),
            signup_text=str(payload.get("signup_text") or ""),
            signup_url=signup_link(str(payload.get("signup_url") or "")),
            seats=str(payload.get("seats") or ""),
            summary=str(payload.get("summary") or ""),
            needs_reminder=bool(payload.get("needs_reminder", kind in REMINDER_KINDS)),
        )
    except (TypeError, ValueError):
        return None


class NewsService:
    """抓取吴健雄学院活动信息，带 30 分钟缓存与离线兜底。"""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else app_data_dir() / "news"
        self.cache_path = self.cache_dir / CACHE_FILE

    # -- 缓存 -------------------------------------------------------------
    def _read_cache(self, max_age: timedelta | None) -> NewsFeed | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        stamp = str(payload.get("fetched_at") or "")
        if max_age is not None:
            try:
                if datetime.now() - datetime.fromisoformat(stamp) >= max_age:
                    return None
            except ValueError:
                return None
        items = [
            item
            for item in (_item_from_dict(raw) for raw in payload.get("items") or [])
            if item is not None and item.title
        ]
        if not items:
            return None
        return NewsFeed(
            items=items,
            fetched_at=stamp or _now_iso(),
            live=bool(payload.get("live", True)),
            source_note=re.sub(r"，其中 \d+ 条可抢选$", "", str(payload.get("source_note") or "")),
            error=str(payload.get("error") or ""),
        )

    def _write_cache(self, feed: NewsFeed) -> None:
        payload = {
            "version": 1,
            "fetched_at": feed.fetched_at or _now_iso(),
            "live": bool(feed.live),
            "source_note": feed.source_note,
            "error": feed.error,
            "items": [_item_to_dict(item) for item in feed.items],
        }
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            write_text_atomic(self.cache_path,
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        except OSError:
            pass

    # -- 详情页 -----------------------------------------------------------
    def _load_detail(self, candidate: dict[str, str]) -> NewsItem | None:
        """跟进一个详情页；任何失败都退化为「只有标题/链接」的条目。"""
        url = candidate.get("url", "")
        title = candidate.get("title", "")
        published = candidate.get("published", "")
        text = ""
        final_url = url
        try:
            html, final_url = _http_get(url)
        except Exception:
            html = ""
            final_url = url
        if html:
            try:
                page_title, text = _detail_text(html)
            except Exception:
                page_title, text = "", ""
            if page_title:
                title = page_title
            if not published and "mp.weixin.qq.com" in final_url:
                try:
                    published = _wechat_published(html)
                except Exception:
                    published = ""
        if not title and not text:
            return None
        try:
            item = parse_article(title, text, url=final_url or url, published=published)
            if item.needs_reminder and not item.signup_url and html:
                for anchor in _ANCHOR_RE.finditer(_main_block(html)):
                    label = _html_to_text(anchor["inner"])
                    if re.search(r"点击报名|立即报名|报名链接|报名入口|抢选入口", label):
                        href = html_lib.unescape(anchor["href"]).strip()
                        if href and not href.startswith("#"):
                            item.signup_url = signup_link(urllib.parse.urljoin(item.url, href))
                            if item.signup_url:
                                break
            return item
        except Exception:
            return None

    def _fetch_live(self, limit: int) -> tuple[list[NewsItem], str]:
        html, _ = _http_get(HOME_URL)
        candidates = _parse_home(html)
        if not candidates:
            raise RuntimeError("官网首页未找到可解析的条目")
        wanted = max(1, min(MAX_DETAIL_PAGES, limit))
        picked = _sort_candidates(candidates)[:wanted]
        items: list[NewsItem] = []
        seen: set[str] = set()
        for candidate in picked:
            item = self._load_detail(candidate)
            if item is None or not item.title or item.key in seen:
                continue
            seen.add(item.key)
            items.append(item)
        if not items:
            raise RuntimeError("详情页解析失败")
        items = _sort_items(items)[:limit]
        return items, f"已从学院官网同步 {len(items)} 条"

    # -- 对外 -------------------------------------------------------------
    def fetch(self, force: bool = False, limit: int = 8) -> NewsFeed:
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 8

        if not force:
            cached = self._read_cache(timedelta(minutes=CACHE_TTL_MINUTES))
            if cached is not None:
                return cached

        error = ""
        try:
            items, note = self._fetch_live(limit)
        except Exception as exc:
            items, note = [], ""
            error = _short_error(exc)

        if items:
            feed = NewsFeed(
                items=items[:limit],
                fetched_at=_now_iso(),
                live=True,
                source_note=note,
                error="",
            )
            self._write_cache(feed)
            return feed

        stale = self._read_cache(None)
        if stale is not None and stale.items:
            stale.live = False
            stale.error = error or "网络不可用"
            stale.source_note = (
                f"{stale.source_note or '离线缓存'}（离线缓存 {stale.fetched_at[:10]}）"
            )
            return stale

        samples = sample_items()[:2]
        return NewsFeed(
            items=samples,
            fetched_at=_now_iso(),
            live=False,
            source_note="暂时连不上学院官网，先看 2 条内置示例",
            error=error or "网络不可用",
        )

    def fetch_async(
        self,
        on_done,
        force: bool = False,
    ) -> None:
        """后台线程抓取；on_done(feed) 在工作线程里执行，调用方自行 after(0)。"""

        def runner() -> None:
            try:
                feed = self.fetch(force=force)
            except Exception as exc:  # pragma: no cover - fetch 本身已兜底
                feed = NewsFeed(
                    items=sample_items(),
                    fetched_at=_now_iso(),
                    live=False,
                    source_note="暂时连不上学院官网，先看 2 条内置示例",
                    error=_short_error(exc),
                )
            try:
                on_done(feed)
            except Exception:
                pass

        thread = threading.Thread(target=runner, name="qixin-news", daemon=True)
        thread.start()
