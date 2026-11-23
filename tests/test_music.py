"""情境歌单模块的离线验收测试。

运行方式（与仓库其它测试一致）::

    python run_all_tests.py

单独运行本文件也可以，但 DSH 沙箱下 ``tempfile.mkdtemp()`` 创建的 0o700
目录不可写，所以这里不用 ``tempfile``，而是把临时文件放进项目内的
``.testtmp/``（与 ``run_all_tests.py`` 的包装 runner 同一思路，注释见
``_scratch_dir``）。GUI 几何自检会真的创建 ``QixinApp``（窗口 withdraw），
并在结束时恢复字号，避免影响其它测试。
"""

from __future__ import annotations

import array
import math
import shutil
import time
import unittest
import uuid
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from qixin import audio, playlists, tracks
from qixin.tracks import KINDS, TRACKS, recommend_tracks, reset_recent_recommendations

#: 验收要求的 12 组「心情 × 活动 × 天气 × 时段」。
COMBINATIONS = (
    ("已老实", "写论文", "晴", "下午"),
    ("淹没在作业海", "复习考试", "雨", "深夜"),
    ("美美得很", "运动", "多云", "清晨"),
    ("灵魂出窍", "放空", "阴", "夜晚"),
    ("无语", "阅读", "雪", "上午"),
    ("心流在线", "写论文", "雨", "下午"),
    ("活人微死", "阅读", "多云", "深夜"),
    ("摸鱼中", "放空", "晴", "夜晚"),
    ("精神状态良好", "运动", "阴", "上午"),
    ("已老实", "复习考试", "雨", "清晨"),
    ("美美得很", "阅读", "雪", "下午"),
    ("无语", "写论文", "多云", "夜晚"),
)

_APP_ROOT = Path(__file__).resolve().parents[1]
_SCRATCH_ROOT = _APP_ROOT / ".testtmp"


def _scratch_dir(name: str) -> Path:
    """在项目内建一个可写目录（沙箱对系统 tempfile 目录有权限限制）。"""

    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = _SCRATCH_ROOT / f"{name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quiet_remove(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_recent_recommendations()

    def test_catalog_has_at_least_sixteen_music_tracks(self) -> None:
        self.assertGreaterEqual(len(TRACKS), 16)
        ids = [track["id"] for track in TRACKS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(tracks.TRACK_BY_ID), set(ids))
        self.assertEqual(len(KINDS), len(set(KINDS)))

    def test_no_noise_is_used_as_the_headline(self) -> None:
        banned = ("白噪", "棕噪", "噪声", "噪音")
        for track in TRACKS:
            for field in ("title", "subtitle"):
                text = str(track[field])
                self.assertFalse(
                    any(word in text for word in banned),
                    f"{track['id']} 的 {field} 仍在卖噪声：{text}",
                )
            head = str(track["tags"][0]) if track["tags"] else ""
            self.assertFalse(
                any(word in head for word in banned),
                f"{track['id']} 的首标签不能是噪声：{head}",
            )

    def test_every_track_keeps_the_original_fields(self) -> None:
        required = (
            "id",
            "title",
            "subtitle",
            "moods",
            "activities",
            "weathers",
            "times",
            "tags",
            "color",
            "method",
            "duration",
            "kind",
            "playlists",
        )
        for track in TRACKS:
            for field in required:
                self.assertIn(field, track, f"{track['id']} 缺字段 {field}")
            self.assertIn(track["kind"], KINDS, track["id"])
            self.assertIsInstance(track["bpm"], int)
            self.assertTrue(40 <= track["bpm"] <= 180, track["id"])
            self.assertTrue(track["moods"], track["id"])
            self.assertTrue(track["activities"], track["id"])
            self.assertTrue(track["weathers"], track["id"])
            self.assertTrue(track["times"], track["id"])
            self.assertGreaterEqual(len(track["tags"]), 3, track["id"])

    def test_kinds_cover_the_required_spread(self) -> None:
        present = {track["kind"] for track in TRACKS}
        for kind in ("钢琴", "吉他", "Lo-fi", "City Pop", "古典", "爵士", "轻电子", "民谣", "后摇", "Bossa Nova", "古风"):
            self.assertIn(kind, present, f"缺少曲种 {kind}")

    def test_playlists_are_official_search_links(self) -> None:
        for track in TRACKS:
            links = track["playlists"]
            self.assertGreaterEqual(len(links), 2, track["id"])
            self.assertLessEqual(len(links), 3, track["id"])
            platforms = {link["platform"] for link in links}
            self.assertEqual(platforms, {"网易云音乐", "QQ音乐"}, track["id"])
            for link in links:
                url = link["url"]
                self.assertTrue(url.startswith("https://"), url)
                self.assertTrue(url.isascii(), f"URL 必须已经 percent-encode：{url}")
                self.assertNotIn(" ", url)
                self.assertTrue(playlists.is_official_url(url), url)
                parsed = urlparse(url)
                self.assertIn(parsed.hostname, playlists.ALLOWED_HOSTS)
                if parsed.hostname == "music.163.com":
                    fragment = parsed.fragment
                    query = fragment.split("?", 1)[1] if "?" in fragment else ""
                    self.assertIn("type=1000", query, url)
                    self.assertTrue(parse_qs(query).get("s"), url)
                else:
                    query = parsed.query
                    self.assertIn("t=song", query, url)
                    self.assertTrue(parse_qs(query).get("w"), url)
                self.assertTrue(link["label"].strip(), track["id"])

    def test_search_url_rejects_unknown_platforms_and_blank_keywords(self) -> None:
        with self.assertRaises(ValueError):
            playlists.search_url("某不存在的平台", "钢琴")
        with self.assertRaises(ValueError):
            playlists.search_url(playlists.PLATFORM_NETEASE, "   ")
        with self.assertRaises(ValueError):
            playlists.build_playlist_links("钢琴", ["<keyword>"])

    def test_mood_links_carry_mood_and_activity(self) -> None:
        links = playlists.mood_links("已老实", "写论文")
        self.assertEqual(len(links), 2)
        self.assertEqual({link["platform"] for link in links}, {"网易云音乐", "QQ音乐"})
        for link in links:
            self.assertTrue(playlists.is_official_url(link["url"]))
            self.assertTrue(link["url"].isascii())
        keyword = playlists.mood_keyword("已老实", "写论文")
        self.assertIn("已老实", keyword)
        self.assertIn("写论文", keyword)

    def test_open_playlist_uses_the_official_search_page(self) -> None:
        from unittest import mock

        from qixin import pages_music

        opened: list[str] = []
        with mock.patch(
            "qixin.playlists.webbrowser.open",
            side_effect=lambda url: opened.append(url) or True,
        ):
            pages_music._open_track_playlist(object(), TRACKS[0])
        self.assertEqual(opened, [TRACKS[0]["playlists"][0]["url"]])
        self.assertTrue(playlists.is_official_url(opened[0]))

        with mock.patch("qixin.playlists.webbrowser.open") as browser:
            self.assertFalse(playlists.open_url("https://example.com/not-official"))
            browser.assert_not_called()


class RecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_recent_recommendations()

    def tearDown(self) -> None:
        reset_recent_recommendations()

    def test_all_combinations_return_diverse_top_three(self) -> None:
        for mood, activity, weather, moment in COMBINATIONS:
            with self.subTest(mood=mood, activity=activity, weather=weather, moment=moment):
                results = recommend_tracks(mood, activity, weather, moment)
                self.assertGreaterEqual(len(results), 3)
                self.assertEqual(len(results), len(TRACKS))
                top = results[:3]
                self.assertEqual(len({item["kind"] for item in top}), 3)
                self.assertEqual(len({item["method"] for item in top}), 3)
                for item in results:
                    self.assertGreaterEqual(item["score"], 0)
                    self.assertIn(item["kind"], KINDS)
                    self.assertIn("bpm", item)
                    self.assertTrue(item["playlists"])
                    reason = str(item["match_reason"])
                    self.assertTrue(reason.strip())
                    self.assertLessEqual(len(reason), 28, reason)
                percents = [item["score_percent"] for item in results]
                for earlier, later in zip(percents, percents[1:]):
                    self.assertGreaterEqual(earlier, later)

    def test_fallback_handles_unknown_inputs(self) -> None:
        for mood, activity, weather, moment in (
            ("未知心情", "躺着", "沙尘", "凌晨"),
            ("", "", "", ""),
            ("已老实", "写论文", "雪", "中午"),
        ):
            with self.subTest(mood=mood, activity=activity):
                results = recommend_tracks(mood, activity, weather, moment)
                self.assertGreaterEqual(len(results), 3)
                self.assertTrue(all(item["score"] >= 0 for item in results))
                self.assertTrue(all(item["score_percent"] >= 55 for item in results))

    def test_consecutive_recommendations_rotate_the_headline(self) -> None:
        baseline = recommend_tracks("已老实", "写论文", "晴", "下午")
        self.assertTrue(baseline)
        heads = [baseline[0]["id"]]
        for _ in range(2):
            heads.append(recommend_tracks("已老实", "写论文", "晴", "下午")[0]["id"])
        self.assertEqual(len(set(heads)), len(heads), heads)

    def test_match_reason_is_short_human_sentence(self) -> None:
        results = recommend_tracks("淹没在作业海", "复习考试", "雨", "深夜")
        reason = results[0]["match_reason"]
        self.assertLessEqual(len(reason), 28)
        self.assertNotIn("\n", reason)
        self.assertTrue(any(token in reason for token in ("深夜", "雨", "BPM", "复习考试")))

    def test_results_expose_page_ready_fields(self) -> None:
        result = recommend_tracks("美美得很", "运动", "晴", "下午")[0]
        self.assertTrue(result["platform_names"])
        self.assertTrue(
            all({"platform", "label", "url"} <= set(link) for link in result["playlists"])
        )
        self.assertIsInstance(result["score_percent"], int)


class AudioTests(unittest.TestCase):
    def test_every_method_generates_listenable_audio(self) -> None:
        room = _scratch_dir("music-audio")
        try:
            for method in audio.METHODS:
                with self.subTest(method=method):
                    started = time.perf_counter()
                    samples = audio._generate_ambient(method, f"probe-{method}")
                    elapsed = time.perf_counter() - started
                    self.assertLess(elapsed, 8.0, f"{method} 生成耗时 {elapsed:.2f}s")

                    self.assertGreater(len(samples), 300_000)
                    self.assertTrue(
                        all(math.isfinite(value) for value in samples),
                        f"{method} 出现 NaN/Inf",
                    )
                    peak = audio.peak_of(samples)
                    self.assertLess(peak, 0.99, f"{method} 峰值 {peak:.3f} 会削顶")
                    self.assertGreater(peak, 0.30, f"{method} 几乎没有声音")

                    path = room / f"{method}.wav"
                    audio.write_wav(path, samples)
                    self.assertGreater(path.stat().st_size, 100_000)
                    with wave.open(str(path), "rb") as handle:
                        self.assertEqual(handle.getnchannels(), 1)
                        self.assertEqual(handle.getframerate(), audio.SAMPLE_RATE)
                        pcm = array.array("h")
                        pcm.frombytes(handle.readframes(handle.getnframes()))
                    wav_peak = max(abs(value) for value in pcm) / 32767
                    self.assertLess(wav_peak, 0.99, f"{method} WAV 峰值 {wav_peak:.3f}")
        finally:
            _quiet_remove(room)

    def test_unknown_method_falls_back_instead_of_crashing(self) -> None:
        samples = audio._generate_ambient("no_such_method", "fallback")
        self.assertGreater(len(samples), 300_000)
        self.assertLess(audio.peak_of(samples), 0.99)

    def test_player_cache_reuses_generated_file(self) -> None:
        room = _scratch_dir("music-cache")
        try:
            player = audio.AmbientPlayer(room / "cache")
            track = {"id": "cache-probe", "method": "keys", "title": "cache"}
            first = player.ensure_track(track)
            mtime = first.stat().st_mtime_ns
            second = player.ensure_track(track)
            self.assertEqual(first, second)
            self.assertEqual(mtime, second.stat().st_mtime_ns)
            self.assertGreater(second.stat().st_size, 100_000)
        finally:
            _quiet_remove(room)


# --------------------------------------------------------------- geometry

_REQUIRED_TEXT = ("不想选？按此刻心情直接开歌单", "打开歌单", "BPM", "匹配理由")


def collect_geometry_report(scales: tuple[float, ...] = (0.95, 1.2, 1.45)) -> list[dict]:
    """渲染歌单页并返回每一档字号下的几何检查结果。

    ``check_music.py`` 直接复用这个函数，测试与手动自检不会出现两套口径。
    """

    from qixin.db import Store
    from qixin.theme import FONT_BOOST, set_font_scale
    from qixin.ui import QixinApp

    reports: list[dict] = []
    room = _scratch_dir("music-geometry")
    store = Store(room / "geometry.db", demo=True)
    app = QixinApp(store, demo=True)
    app.root.withdraw()
    try:
        for scale in scales:
            set_font_scale(scale)
            app.font_scale = scale
            app.meter.invalidate()
            app.show_page("music")
            app.root.update_idletasks()
            app.root.update()

            canvas = app.page_canvas
            bounds = canvas.bbox("all") or (0, 0, 0, 0)
            page_width = round(app.page_w * app.ui_scale)
            content_height = round(app._page_content_height * app.ui_scale)
            texts: list[tuple[tuple[int, int, int, int], str]] = []
            for item in canvas.find_all():
                if canvas.type(item) != "text":
                    continue
                box = canvas.bbox(item)
                if box:
                    texts.append((box, canvas.itemcget(item, "text")))

            overlaps: list[tuple[str, str]] = []
            for first in range(len(texts)):
                for second in range(first + 1, len(texts)):
                    left, right = texts[first][0], texts[second][0]
                    if (
                        min(left[2], right[2]) - max(left[0], right[0]) > 3
                        and min(left[3], right[3]) - max(left[1], right[1]) > 3
                    ):
                        overlaps.append((texts[first][1][:18], texts[second][1][:18]))

            labels = [text for _box, text in texts]
            joined = "\n".join(labels)
            reports.append(
                {
                    "scale": scale,
                    "bounds": bounds,
                    "page_width": page_width,
                    "content_height": content_height,
                    "overflow_x": bounds[2] > page_width + 2 or bounds[0] < -2,
                    "overflow_y": bounds[3] > content_height + 2,
                    "overlaps": overlaps,
                    "text_count": len(texts),
                    "has_quick_row": _REQUIRED_TEXT[0] in joined,
                    "has_open_playlist": any("打开歌单" in text for text in labels),
                    "has_bpm": any("BPM" in text for text in labels),
                    "has_reason": any("匹配理由" in text for text in labels),
                    "has_kind_badge": any(text.strip() in KINDS for text in labels),
                    "playlist_buttons": bool(canvas.find_withtag("music_playlist_0")),
                    "quick_buttons": bool(canvas.find_withtag("quick_playlist_0"))
                    and bool(canvas.find_withtag("quick_playlist_1")),
                }
            )
    finally:
        app._on_close()
        set_font_scale(FONT_BOOST)
        # ``_on_close`` 已经关闭 Store；这里只清理临时目录。
        _quiet_remove(room)
    return reports


class GeometryTests(unittest.TestCase):
    def test_music_page_fits_three_font_scales(self) -> None:
        reports = collect_geometry_report((0.95, 1.2, 1.45))
        self.assertEqual(len(reports), 3)
        for report in reports:
            scale = report["scale"]
            with self.subTest(scale=scale):
                self.assertFalse(report["overflow_x"], f"{scale}: 横向溢出 {report['bounds']}")
                self.assertFalse(report["overflow_y"], f"{scale}: 纵向溢出 {report['bounds']}")
                self.assertEqual(report["overlaps"], [], f"{scale}: 文字重叠")
                self.assertTrue(report["has_quick_row"], f"{scale}: 缺少快捷歌单行")
                self.assertTrue(report["has_open_playlist"], f"{scale}: 缺少打开歌单按钮")
                self.assertTrue(report["playlist_buttons"], f"{scale}: 卡片缺歌单按钮")
                self.assertTrue(report["quick_buttons"], f"{scale}: 缺两个平台快捷按钮")
                self.assertTrue(report["has_bpm"], f"{scale}: 缺少 BPM")
                self.assertTrue(report["has_reason"], f"{scale}: 缺少匹配理由")
                self.assertTrue(report["has_kind_badge"], f"{scale}: 缺少曲种徽章")
                self.assertGreater(report["text_count"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
