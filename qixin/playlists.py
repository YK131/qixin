"""外部歌单链接构造与平台适配。

用户原话里最刺耳的一句是「九龙湖的白噪音零个人愿意听」——本地合成再精致，
也不该假装自己能替代真正的音乐库。所以这个模块只做两件事：

* 把「此刻的 kind / 心情 / 活动」翻译成**平台官方搜索页**的合法 URL
  （``https://music.163.com/#/search/m/?s=...&type=1000`` 与
  ``https://y.qq.com/n/ryqq/search?w=...&t=song``）。这里刻意不写任何歌单
  ID：写死的 ID 一定会随着平台改版失效，搜索页不会。
* 校验 URL 再交给 :mod:`webbrowser`，避免把用户带到非官方域名。

所有函数都是纯函数（只有 :func:`open_url` 会真的拉起浏览器），方便离线测试。
"""

from __future__ import annotations

import webbrowser
from typing import Any, Iterable, Sequence
from urllib.parse import quote, urlparse

__all__ = [
    "ALLOWED_HOSTS",
    "PLATFORM_NETEASE",
    "PLATFORM_QQ",
    "build_playlist_links",
    "is_official_url",
    "mood_keyword",
    "mood_links",
    "open_url",
    "platform_names",
    "search_url",
]


PLATFORM_NETEASE = "网易云音乐"
PLATFORM_QQ = "QQ音乐"

#: 平台 → (搜索页模板, URL 里已经写死的检索类型参数说明)。
#: ``keyword`` 只做 URL 编码，不拼进 path，避免空格/中文被平台二次转义。
_SEARCH_TEMPLATES: dict[str, str] = {
    PLATFORM_NETEASE: "https://music.163.com/#/search/m/?s={keyword}&type=1000",
    PLATFORM_QQ: "https://y.qq.com/n/ryqq/search?w={keyword}&t=song",
}

#: 只允许这两个官方域名，防止配置或数据被替换成钓鱼链接。
ALLOWED_HOSTS = frozenset({"music.163.com", "y.qq.com"})

#: 卡片上展示平台名时用的简称（按钮宽度有限）。
_PLATFORM_SHORT = {
    PLATFORM_NETEASE: "网易云",
    PLATFORM_QQ: "QQ音乐",
}


def _clean_keyword(keyword: str) -> str:
    """压掉连续空白；关键词不允许为空。"""

    text = " ".join(str(keyword).split())
    if not text:
        raise ValueError("歌单关键词不能为空")
    if "<" in text or ">" in text:
        raise ValueError(f"歌单关键词里不该出现占位符：{text!r}")
    return text


def search_url(platform: str, keyword: str) -> str:
    """构造平台官方搜索页 URL（关键词做 percent-encoding）。"""

    template = _SEARCH_TEMPLATES.get(platform)
    if template is None:
        raise ValueError(f"未知音乐平台：{platform!r}")
    return template.format(keyword=quote(_clean_keyword(keyword), safe=""))


def is_official_url(url: str) -> bool:
    """URL 必须是 https 且落在官方域名上。"""

    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


def build_playlist_links(
    kind: str,
    keywords: Sequence[str],
    *,
    limit: int = 3,
) -> list[dict[str, str]]:
    """为一条曲目生成 2–3 个「平台官方搜索页」链接。

    ``keywords`` 是两三个可检索的中文/英文关键词（越具体越好，例如
    ``"Lo-fi 学习"``），返回值的每一项都包含 ``platform`` / ``label`` /
    ``url`` 三个字符串字段，可直接放进 :data:`qixin.tracks.TRACKS`。
    """

    words: list[str] = []
    for keyword in keywords:
        cleaned = _clean_keyword(keyword)
        if cleaned not in words:
            words.append(cleaned)
    if not words:
        words = [_clean_keyword(kind)]
    while len(words) < 2:
        # 至少两个关键词，保证「网易云 + QQ音乐」两个平台都有内容。
        words.append(f"{kind} 纯音乐")

    candidates = [
        (PLATFORM_NETEASE, f"{words[0]}歌单", words[0]),
        (PLATFORM_QQ, f"{words[1]}歌单", words[1]),
        (PLATFORM_NETEASE, f"{kind} 精选合辑", f"{kind} 精选"),
    ]

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for platform, label, keyword in candidates:
        url = search_url(platform, keyword)
        if url in seen:
            continue
        seen.add(url)
        links.append({"platform": platform, "label": label, "url": url})
        if len(links) >= max(2, min(3, limit)):
            break
    return links


def platform_names(track: dict[str, Any]) -> str:
    """卡片上写明的平台名，例如 ``"网易云音乐 / QQ音乐"``。"""

    names: list[str] = []
    for link in track.get("playlists") or []:
        name = str(link.get("platform", "")).strip()
        if name and name not in names:
            names.append(name)
    return " / ".join(names)


def short_platform(platform: str) -> str:
    return _PLATFORM_SHORT.get(platform, platform)


def first_link(track: dict[str, Any]) -> dict[str, str] | None:
    for link in track.get("playlists") or []:
        if is_official_url(str(link.get("url", ""))):
            return {
                "platform": str(link.get("platform", "")),
                "label": str(link.get("label", "")),
                "url": str(link.get("url", "")),
            }
    return None


def mood_keyword(mood: str, activity: str) -> str:
    """快捷歌单的关键词：同时带上心情与活动。"""

    return f"{mood} {activity} 歌单"


def mood_links(mood: str, activity: str) -> list[dict[str, str]]:
    """顶部「按此刻心情直接开歌单」用的两条链接（一平台一条）。"""

    keyword = mood_keyword(mood, activity)
    return [
        {
            "platform": PLATFORM_NETEASE,
            "label": f"{mood} · {activity}",
            "url": search_url(PLATFORM_NETEASE, keyword),
        },
        {
            "platform": PLATFORM_QQ,
            "label": f"{mood} · {activity}",
            "url": search_url(PLATFORM_QQ, keyword),
        },
    ]


def open_url(url: str) -> bool:
    """校验后交给系统浏览器；返回是否真的发起了打开请求。"""

    if not is_official_url(url):
        return False
    try:
        opened = webbrowser.open(url)
    except Exception:
        return False
    # 某些环境里 ``webbrowser.open`` 返回 None（视为已提交给系统）。
    return opened is not False


def open_first(track: dict[str, Any]) -> str:
    """打开曲目的第一个官方歌单，返回平台名（失败返回空串）。"""

    link = first_link(track)
    if link is None:
        return ""
    return link["platform"] if open_url(link["url"]) else ""


def unique_platforms(links: Iterable[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for link in links:
        platform = str(link.get("platform", ""))
        if platform and platform not in names:
            names.append(platform)
    return names
