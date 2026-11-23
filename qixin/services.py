from __future__ import annotations

from .files import write_text_atomic

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .content import MOOD_TAG_ALIASES, MOODS, MOOD_ORDER, QUOTES, quote_for_day
from .db import app_data_dir


@dataclass
class WeatherSnapshot:
    city: str
    temperature: float | None
    condition: str
    is_day: bool
    live: bool
    updated_at: datetime

    @property
    def temperature_text(self) -> str:
        if self.temperature is None:
            return "--℃"
        return f"{round(self.temperature)}℃"

    @property
    def summary(self) -> str:
        suffix = "" if self.live else " · 示例"
        return f"{self.city} {self.condition} {self.temperature_text}{suffix}"


WMO_WEATHER = {
    0: ("晴", True),
    1: ("晴间多云", True),
    2: ("多云", True),
    3: ("阴", False),
    45: ("雾", False),
    48: ("雾凇", False),
    51: ("细雨", False),
    53: ("小雨", False),
    55: ("雨", False),
    56: ("冻雨", False),
    57: ("冻雨", False),
    61: ("小雨", False),
    63: ("中雨", False),
    65: ("大雨", False),
    66: ("冻雨", False),
    67: ("冻雨", False),
    71: ("小雪", False),
    73: ("中雪", False),
    75: ("大雪", False),
    77: ("雪粒", False),
    80: ("阵雨", False),
    81: ("阵雨", False),
    82: ("强阵雨", False),
    85: ("阵雪", False),
    86: ("强阵雪", False),
    95: ("雷雨", False),
    96: ("雷雨", False),
    99: ("强雷雨", False),
}


class WeatherService:
    """Open-Meteo adapter with a local cache and graceful offline fallback."""

    def __init__(
        self,
        city: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ):
        self.city = city or os.getenv("QIXIN_CITY", "南京")
        try:
            self.latitude = self._coordinate(latitude, "QIXIN_LAT", 32.0603, 90)
            self.longitude = self._coordinate(longitude, "QIXIN_LON", 118.7969, 180)
        except (TypeError, ValueError):
            self.city, self.latitude, self.longitude = "南京", 32.0603, 118.7969
        self.cache_path = app_data_dir() / "weather-cache.json"

    @staticmethod
    def _coordinate(value: float | None, env: str, default: float, limit: int) -> float:
        coordinate = float(os.getenv(env, str(default)) if value is None else value)
        if not -limit <= coordinate <= limit:
            raise ValueError(f"Invalid coordinate: {env}")
        return coordinate

    def _read_cache(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(payload["fetched_at"])
            if datetime.now() - fetched_at < timedelta(minutes=30):
                return payload
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return None

    def _write_cache(self, payload: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(self.cache_path,
                json.dumps(payload, ensure_ascii=False),
            )
        except OSError:
            pass

    def current(self, force: bool = False) -> WeatherSnapshot:
        cached = None if force else self._read_cache()
        if cached and cached.get("city") == self.city:
            return WeatherSnapshot(
                city=self.city,
                temperature=cached.get("temperature"),
                condition=cached.get("condition", "多云"),
                is_day=bool(cached.get("is_day", True)),
                live=True,
                updated_at=datetime.fromisoformat(cached["fetched_at"]),
            )

        params = urllib.parse.urlencode(
            {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "current": "temperature_2m,weather_code,is_day",
                "timezone": "Asia/Shanghai",
            }
        )
        request = urllib.request.Request(
            f"https://api.open-meteo.com/v1/forecast?{params}",
            headers={"User-Agent": "QixinDesktop/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            current = payload["current"]
            code = int(current.get("weather_code", 2))
            fallback_label, fallback_day = WMO_WEATHER.get(code, ("多云", True))
            condition = fallback_label
            is_day = bool(current.get("is_day", fallback_day))
            snapshot = {
                "city": self.city,
                "temperature": float(current["temperature_2m"]),
                "condition": condition,
                "is_day": is_day,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._write_cache(snapshot)
            return WeatherSnapshot(
                city=self.city,
                temperature=snapshot["temperature"],
                condition=condition,
                is_day=is_day,
                live=True,
                updated_at=datetime.now(),
            )
        except (
            KeyError,
            ValueError,
            TypeError,
            OSError,
            socket.timeout,
            urllib.error.URLError,
            ssl.SSLError,
        ):
            hour = datetime.now().hour
            condition = "晴" if 8 <= hour <= 17 else "多云"
            return WeatherSnapshot(
                city=self.city,
                temperature=None,
                condition=condition,
                is_day=6 <= hour < 18,
                live=False,
                updated_at=datetime.now(),
            )


class AIService:
    """Small OpenAI-compatible chat adapter, optional at runtime."""

    def __init__(self) -> None:
        self.api_key = (
            os.getenv("QIXIN_AI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ).strip()
        self.base_url = (
            os.getenv("QIXIN_AI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = (
            os.getenv("QIXIN_AI_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "gpt-4.1-mini"
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.65,
        json_mode: bool = False,
        timeout: int = 30,
    ) -> str:
        if not self.configured:
            raise RuntimeError("AI 尚未配置")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "QixinDesktop/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            return str(content).strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"AI 接口返回 {exc.code}: {detail}") from exc
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise RuntimeError(f"AI 请求失败：{exc}") from exc

    def refine_playlist(
        self,
        mood: str,
        activity: str,
        weather: str,
        moment: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        simplified = [
            {
                "id": item["id"],
                "title": item["title"],
                "subtitle": item["subtitle"],
                "tags": item["tags"],
            }
            for item in candidates[:4]
        ]
        prompt = f"""
四维情境：心情={mood}；正在做={activity}；天气={weather}；时段={moment}。
候选音景：{json.dumps(simplified, ensure_ascii=False)}
请从候选中选一个最适合的 id，写 1 句不超过 55 个汉字的选择理由，
再写 1 句不超过 50 个汉字的温和关怀。不要诊断，不要说教。
只返回 JSON：{{"track_id":"候选id","reason":"...","care_note":"..."}}
""".strip()
        try:
            raw = self._chat(
                "你是克制、温柔的中文情境音乐策展人。严格从给定 candidates 中选 id。",
                prompt,
                temperature=0.5,
                json_mode=True,
            )
        except RuntimeError as exc:
            # Some OpenAI-compatible gateways do not implement response_format.
            if "response_format" in str(exc).lower() or "400" in str(exc):
                raw = self._chat(
                    "你是克制、温柔的中文情境音乐策展人。严格从给定 candidates 中选 id。",
                    prompt,
                    temperature=0.5,
                    json_mode=False,
                )
            else:
                raise
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
        data = json.loads(raw)
        valid_ids = {item["id"] for item in candidates}
        if data.get("track_id") not in valid_ids:
            data["track_id"] = candidates[0]["id"]
        return data

    def weekly_report(self, stats: dict[str, Any]) -> str:
        mood_counts = "，".join(
            f"{mood}{count}次"
            for mood, count in stats["mood_counts"].items()
            if count
        )
        prompt = f"""
请用中文为大学生写一份《情绪与哲思周报》，不要诊断，不要制造焦虑。
本周日期：{stats['start']} 至 {stats['end']}
心情记录次数：{len(stats['moods'])}；有记录天数：{stats['active_days']}
心情分布：{mood_counts or '暂无'}
计划：共 {stats['total_tasks']} 项，完成 {stats['done_tasks']} 项
请写成 4 个短段落，总共约 350-450 汉字：
1. 先观察这一周的情绪地形，不做价值判断；
2. 指出一个资源或微小进步；
3. 用一则契合的哲学提醒（可自行引用，须准确）；
4. 给下周一个非常具体、温柔的小建议。
标题为《情绪与哲思周报》，不要使用列表，不要自称 AI。
""".strip()
        return self._chat(
            "你是熟悉哲学与心理学边界的中文写作者。只做观察和陪伴，不做医疗诊断。",
            prompt,
            temperature=0.72,
            timeout=45,
        )


def local_weekly_report(stats: dict[str, Any]) -> str:
    counts = stats["mood_counts"]
    total = len(stats["moods"])
    start = stats["start"]
    end = stats["end"]
    quote = quote_for_day(end)
    if not total:
        return (
            f"《情绪与哲思周报》\n{start.strftime('%m.%d')}—{end.strftime('%m.%d')}\n\n"
            "这一周还没有留下心情记录。空白不是缺席，它也可以是一种休息。"
            "如果你愿意，下一次只要点一下此刻的感受就够了，不需要解释得很完整。\n\n"
            f"本周推荐给自己的一句话：{quote['text']}——{quote['source']}\n\n"
            "下周的小建议：选一个普通的晚上，为自己记下第一笔情绪。"
        )

    common_mood, common_count = max(counts.items(), key=lambda pair: pair[1])
    completion_rate = round(stats["completion_rate"] * 100)
    changed_to_calm = 0
    by_day: dict[str, list[str]] = {}
    for row in stats["moods"]:
        by_day.setdefault(str(row["local_date"]), []).append(str(row["mood"]))
    for moods in by_day.values():
        if "已老实" in moods[1:] and any(
            m in {"淹没在作业海", "灵魂出窍", "无语"} for m in moods[:-1]
        ):
            changed_to_calm += 1

    terrain = (
        f"这一周，你留下了 {total} 次心情记录，走过 {stats['active_days']} 天。"
        f"出现最多的是「{common_mood}」，共有 {common_count} 次。"
        "情绪并没有按计划排队，它更像天气：有时晴朗，有时云层很低，但都在移动。"
    )
    resource = (
        f"这一周的计划完成了 {stats['done_tasks']} / {stats['total_tasks']} 项，"
        f"完成率 {completion_rate}%。"
    )
    if changed_to_calm:
        resource += (
            f"有 {changed_to_calm} 天，你在高压或低电量之后又回到了“已老实”。"
            "这说明情绪不是一条直线，你也并非一直停在最难的那一格。"
        )
    elif stats["done_tasks"]:
        resource += "完成的数量不是唯一的成绩，愿意把事项写下来，本身就减少了它们在心里占据的模糊空间。"
    else:
        resource += "没有完成也没有关系。先辨认什么在消耗你，比仓促地责怪自己更有用。"

    philosophy = (
        f"本周留一句：{quote['text']}——{quote['source']}。"
        f"{quote['explanation']}"
    )
    if counts.get("淹没在作业海", 0) > counts.get("已老实", 0):
        suggestion = (
            "下周的小建议：在焦虑最强的时候，只做“两分钟版本”的一件事。"
            "比如只打开文档写三行，或者只走到楼下再决定要不要继续。"
        )
    elif counts.get("活人微死", 0) >= 2:
        suggestion = (
            "下周的小建议：把“恢复”当作一项正式计划，而不是完成所有事情后的奖励。"
            "选一天提前结束学习，给睡眠留出真正足够的时间。"
        )
    elif counts.get("灵魂出窍", 0) >= 2:
        suggestion = (
            "下周的小建议：把“恢复”写成一件具体的小事，例如晒太阳十分钟、"
            "给信任的人发一条消息。不要等有动力之后才开始。"
        )
    elif counts.get("摸鱼中", 0) >= 2:
        suggestion = (
            "下周的小建议：给摸鱼设定一个明确的结束点。"
            "休息时尽兴休息，回来时只打开一个任务窗口。"
        )
    elif counts.get("无语", 0) >= 2:
        suggestion = (
            "下周的小建议：在烦躁出现时先离开屏幕两分钟，"
            "再决定要继续、暂停还是换一件事做。"
        )
    else:
        suggestion = (
            "下周的小建议：保留一个没有任务的晚上。"
            "不是奖励，也不是偷懒，而是让注意力有重新长出来的空间。"
        )
    return (
        f"《情绪与哲思周报》\n{start.strftime('%m.%d')}—{end.strftime('%m.%d')}\n\n"
        f"{terrain}\n\n{resource}\n\n{philosophy}\n\n{suggestion}"
    )


def external_music_url(track_id: str) -> str:
    env_key = f"QIXIN_MUSIC_{track_id.upper().replace('-', '_')}_URL"
    return os.getenv(env_key, "").strip()


def ai_context_preview(
    mood: str,
    activity: str,
    weather: str,
    moment: str,
) -> str:
    return (
        f'{{"mood":"{mood}","activity":"{activity}",'
        f'"weather":"{weather}","time":"{moment}"}}'
    )


def week_philosophy_quote(stats: dict[str, Any]) -> dict[str, Any]:
    counts = stats["mood_counts"]
    common = max(counts, key=counts.get) if counts else "已老实"
    common_tag = MOOD_TAG_ALIASES.get(common, common)
    preferred = [quote for quote in QUOTES if common_tag in quote["tags"]]
    if preferred:
        return preferred[stats["start"].toordinal() % len(preferred)]
    return quote_for_day(stats["end"])
