from __future__ import annotations

import contextlib
import hashlib
import shutil
import tempfile
import unittest
import urllib.error
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from qixin.news import (
    KIND_LECTURE,
    KIND_MENTOR,
    KIND_NOTICE,
    SOURCE_SAMPLE,
    NewsFeed,
    NewsItem,
    NewsService,
    clean_name,
    extract_fields,
    parse_article,
    reminder_items,
    sample_items,
    signup_link,
    signup_opening,
    SIGNUP_TIMEZONE,
)

# 以下两段正文是 2026-11-11 从真实文章抓下来的纯文本（微信 js_content 文本化结果），
# 仅作为离线夹具使用。
LECTURE_TITLE = (
    "人文讲座 | 东南大学经管学院退休教授胡汉辉精彩演讲“领跑数智时代的“领导力””"
)
MENTOR_TITLE = "导师交流 | 第203期如约而至，精研笃实，科创求真！"
MENTOR_URL = "https://mp.weixin.qq.com/s/Jd1yoQqfJjXbclHl3NAaCw"
LECTURE_URL = "https://mp.weixin.qq.com/s/bgPeAF7wGn0_6jnSWxvenA"

LECTURE_TEXT = """\
❖
健雄书院高端人文讲座是健雄书院的品牌活动。该讲座每年邀请校内外知名学者来院与学生进行专题分享交流，做精彩演讲。
健雄书院高端人文讲座（二百二十三）
演讲人：胡汉辉（东南大学经管学院退休教授）
主 题：领跑数智时代的“领导力”
时 间：2026年11月11日（周三）下午16:00-18:00
地 点：九龙湖校区健雄书院报告厅
主 办：东南大学吴健雄学院、东南大学健雄书院
主讲人简介
胡汉辉，东南大学经管学院退休教授，曾获江苏省“百点播火”大学生社会实践优秀指导教师荣誉称号（1987年）；参与指导了东南大学历届“挑战杯”（1989年起）和“国创赛”（2015年起）并多次获特等奖；倡议成立并长期担任“东南大学学生创业协会”（2000年起）和“东南大学创新冬令营”（2010年起）的导师。曾是教育部“《全国普通高校创业教育教学基本要求》起草专家组”成员（2011年）。
推荐理由
机器人的大量使用和数智人的日趋成熟，不仅已对自然人的传统就业岗位形成令人担忧的冲击，而且可能对人类的未来社会演进方式产生尚不确定的影响。报告者将结合自己在东南大学40余年从事创新创业教育改革的探索和指导学生参加创新竞赛和创业实践的经历，向吴健雄学院的同学们介绍以往为自然人所独有的“领导力”的演化，分享和交流有关如何在数智时代生存与发展的思考。
说明
报名讲座的同学注意啦
【备注】
以上报名方式适用于吴院学子。健雄书院所有高端讲座均面向全校开放，欢迎全校师生来健雄书院聆听高端人文讲座。
【报名方式】
吴健雄学院学生登录http://jxsy.seu.edu.cn，该系统用户名和密码与学校信息门户一致，登录后在书院讲堂部分可看到讲座信息，点击报名。此报名将作为人文讲座考勤记录。
【报名时间】
本场讲座将面向吴健雄学院各年级学子开放60个名额，将于11月10日（周二）中午12:30开放报名，请各位同学提前做好准备。
如因各种不可抗拒因素需退选，请于11月11日（周三）中午12:00前完成退选，过时不得退选，否则将视为缺席予以记载。
图文 | 吴健雄学院团委宣传部
一审 | 安照邦
二审 | 高雨馨
三审 | 孙 威
"""

MENTOR_TEXT = """\
活动介绍
“健雄书院导师交流时间”是吴健雄学院拔尖创新人才培养模式的改革新举措。健雄书院每周安排数位导师与学生亲切交流。交流的重点包括：专业方向选择、人生职业规划、如何让大学生活有意义等。交流活动共有4种形式：专业宣讲会、走进实验室、专业方向交流专场、常规场次。机会难得，欢迎大家踊跃参与。
“健雄书院导师交流时间”安排
常规场次
王艺炜
东南大学信息科学与工程学院教授，研究方向为海洋信息处理和人工智能。本科毕业于东南大学，其后在香港科技大学获得MPhil学位，在新加坡国立大学获得Ph.D.学位。毕业后曾先后在美国亚马逊公司（西雅图）担任应用科学家，加州大学洛杉矶分校担任博士后研究员，加州大学默塞德分校担任助理教授（tenure-track）。发表60篇CCF-A类会议和期刊论文，累计被引用5000余次。所在团队主要研究能够通过多模态数据理解物理世界的通用人工智能技术，以及使用人工智能技术赋能水下信息感知。
吴 俊
东南大学电子科学与工程学院教授、博士研究生导师。曾赴加州大学洛杉矶分校（UCLA）及新加坡国立大学（NUS）从事科研工作，入选东南大学青年特聘教授、至善青年学者计划A层次（首批），柔性集成器件与智能人机系统江苏省高校重点实验室主任，东大-瑞声智能传感器卓越工程师技术中心负责人，东南大学柔性集成器件与系统微专业负责人。主持多项国家级重点课题及产学研项目。近5年在Science advances、Nature Communications、Advanced materials等国内外重要期刊发表SCI 收录论文50余篇，同时申报或授权了多项发明专利，转让多项。担任Research、JMM等多个学术期刊的特刊编辑，担任AI sensors等多个学术会议分会主席。多次荣获挑战杯、互联网+等赛事国家级荣誉。
包贤强
东南大学计算机科学与工程学院教授、博士生导师，国家高层次青年人才，德国洪堡学者。研究方向包括医疗机器人、磁控机器人、具身智能、人工智能交叉等。以第一/共一在Nature、Science Advances、IEEE Transactions系列(包括TRO、TMECH、TIE等)期刊或会议上发表研究论文20余篇，其中1篇论文被遴选为Science Advances封面文章。作为科研骨干研发的血管介入手术机器人，完成了人体临床实验和动物实验，目前已实现技术转化，获得了三类医疗器械许可证，并实现了销售。以科研骨干参与开发的超声胎儿检测机器人，目前已成立初创公司来推进产业化。申请欧盟专利1项，授权中国发明专利15项。获得IEEE ICMA国际会议自动化最佳论文奖、MARSS国际会议最佳大会论文奖提名奖、自动化学会科技进步奖二等奖等。研究获多个官方及权威平台报道，包括学术期刊《Science》官方账号介绍，德国联邦研究、技术与航天部官方平台报道等。
韩金广
东南大学网络空间安全学院教授、博士生导师、密码科学与技术系主任。2013年博士毕业于澳大利亚卧龙岗大学，研究方向包括密码学、隐私保护、访问控制、云计算和区块链安全。发表学术论文80余篇，主持国家自然科学基金项目、江苏省自然科学基金项目。中国密码学会区块链专委会委员、中国密码学会大数据与人工智能安全专委会委员、中国网络空间安全学会应用密码工程专委会委员。
闫 浩
东南大学集成电路学院副教授、博士生导师，国家集成电路设计自动化技术创新中心项目负责人。研究时序分析等智能化数字电路设计方法学。近年来主持国家自然科学基金面上、国家重点研发计划、省重点研发等项目。在IEEE/ACM DAC、TCAD等EDA领域发表论文50余篇，获2021 ASP-DAC 最佳论文提名、2022 ISCICT 最佳论文。牵头制定工信部行业标准1项。担任2023年和2024年 IEEE ISEDA TPC主席，2025年中国研究生创“芯”大赛EDA精英挑战赛技术委员会副主任。
孙振华
东南大学吴健雄学院2005级校友，电路与系统硕士，高级工程师。南京砺行微电子科技有限公司总经理、执行董事。担任东南大学集成电路校友会第一届秘书长、江北新区人才协会副秘书长、三江学院产业创新学院副院长。创业期间，入选“创新型企业家培育计划”、“创业南京”高层次创业人才引进计划、“南京江北新区十大杰出青年”等项目。
马 强
光学专业理学博士，本科毕业于南京航空航天大学，硕士、博士阶段均就读于华东师范大学，现任职于东南大学实验室与设备管理处，主要负责校级公共平台建设工作。
贺子桐
东南大学经济管理学院2026级会计学硕士研究生，本科期间作为多个项目的商业模式主统筹，助力项目斩获第十九届“挑战杯”全国大学生课外学术科技作品竞赛“人工智能+” 专项赛国特、中国国际大学生创新大赛（2024）产业命题赛道国金等省级国家级奖项7项，获“东南大学2026届本科优秀毕业生”称号。
Tips：请同学们合理选择预约场次，避免时间冲突。
说明
报名的同学注意啦
【报名方式】
登录http://jxsy.seu.edu.cn，该系统用户名和密码与学校信息门户一致。登录后，在导师制部分选择批次“健雄书院导师交流时间第203期”，查看报名信息并完成报名。此报名将作为导师交流考勤记录。完成导师交流后，在反馈栏提交反馈表。
【报名时间】
本期导师交流将于11月6日（周五）中午12:30开放报名，请各位同学提前做好准备。请注意，如有特殊原因，请于报名截止前退选；逾期不再受理。
主办 | 东南大学吴健雄学院
东南大学健雄书院
"""

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _make_writable_dir(base: Path | None) -> Path | None:
    """建一个真正可写的临时目录。

    沙箱下 tempfile.mkdtemp 生成的 0700 目录可能不继承写权限，
    因此先用普通 mkdir 建唯一目录，再退到 mkdtemp，都失败则返回 None。
    """
    root = None
    try:
        if base is not None:
            base.mkdir(parents=True, exist_ok=True)
        root = base if base is not None else Path(tempfile.gettempdir())
    except OSError:
        return None

    for factory in ("plain", "mkdtemp"):
        directory = None
        try:
            if factory == "plain":
                directory = root / f"qixin-news-{uuid.uuid4().hex[:10]}"
                directory.mkdir()
            else:
                directory = Path(tempfile.mkdtemp(prefix="qixin-news-", dir=str(root)))
            probe = directory / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return directory
        except OSError:
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
    return None


@contextlib.contextmanager
def temp_cache_dir():
    """项目内 .tmp 优先，退回系统临时目录；不改变测试语义。"""
    directory = _make_writable_dir(PROJECT_ROOT / ".tmp") or _make_writable_dir(None)
    if directory is None:  # pragma: no cover - 极端环境
        raise unittest.SkipTest("当前环境没有可写的临时目录")
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class ReminderExpiryTests(unittest.TestCase):
    def test_suggests_opening_and_prefers_registration_link(self) -> None:
        item = parse_article(
            "导师交流",
            "报名截止时间：11月21日18:00\n【报名方式】\n"
            "登录 https://jxsy.seu.edu.cn/?event=21 完成报名。\n"
            "将于11月20日下午4:30开放报名。",
            url="https://wjx.seu.edu.cn/news/21",
            published="2026-11-18",
        )
        self.assertEqual(signup_opening(item), datetime(2026, 11, 20, 16, 30, tzinfo=SIGNUP_TIMEZONE))
        self.assertEqual(item.signup_url, "https://jxsy.seu.edu.cn/?event=21")
        self.assertEqual(signup_link("javascript:openSignup()"), "")

    def test_cutoff_or_date_alone_does_not_suggest_opening(self) -> None:
        for text in ("报名截止时间：11月21日18:00", "11月21日开放报名"):
            with self.subTest(text=text):
                item = parse_article("导师交流", text, published="2026-11-18")
                self.assertIsNone(signup_opening(item))

    def test_explicit_cutoff_keeps_open_signups_visible_until_the_deadline(self) -> None:
        item = parse_article(
            "人文讲座", "【报名时间】\n11月17日 12:30开放报名。\n"
            "报名截止时间：11月18日 18:00\n活动时间：11月19日 17:00",
            published="2026-11-16",
        )
        feed = NewsFeed(items=[item])
        self.assertEqual(reminder_items(feed, datetime(2026, 11, 18, 17, 59)), [item])
        self.assertEqual(reminder_items(feed, datetime(2026, 11, 18, 10, tzinfo=timezone.utc)), [])
        self.assertEqual(feed.items, [item])

    def test_expiry_for_event_time_registration_range_and_opening_only(self) -> None:
        lecture = parse_article(LECTURE_TITLE, LECTURE_TEXT, published="2026-11-09")
        ranged = parse_article(
            "导师交流", "报名时间：11月10日 12:30 至 11日 15:00",
            published="2026-11-09",
        )
        opening_only = parse_article(
            "导师交流", "【报名时间】\n2026年11月11日（周三）12:30开放报名。",
            published="2026-11-09",
        )
        feed = NewsFeed(items=[lecture, ranged, opening_only])
        self.assertEqual(reminder_items(feed, datetime(2026, 11, 11, 14, 59)), feed.items)
        self.assertEqual(reminder_items(feed, datetime(2026, 11, 11, 15)), [lecture, opening_only])
        self.assertEqual(reminder_items(feed, datetime(2026, 11, 11, 16)), [opening_only])
        self.assertEqual(reminder_items(feed, datetime(2026, 11, 12)), [])


class LectureArticleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.item = parse_article(
            LECTURE_TITLE, LECTURE_TEXT, url=LECTURE_URL, published="2026-11-09"
        )

    def test_kind_and_reminder_flag(self) -> None:
        self.assertEqual(self.item.kind, KIND_LECTURE)
        self.assertTrue(self.item.needs_reminder)

    def test_speaker_field(self) -> None:
        self.assertEqual(self.item.speakers, ["胡汉辉"])
        self.assertIn("教授", self.item.speaker_detail)

    def test_topic_when_place(self) -> None:
        self.assertIn("领导力", self.item.topic)
        self.assertIn("2026年11月11日", self.item.when_text)
        self.assertIn("16:00-18:00", self.item.when_text)
        self.assertIn("九龙湖", self.item.place)

    def test_signup_and_seats(self) -> None:
        self.assertIn("12:30", self.item.signup_text)
        self.assertIn("11月10日", self.item.signup_text)
        self.assertIn("60", self.item.seats)

    def test_published_source_and_summary(self) -> None:
        self.assertEqual(self.item.published, "2026-11-09")
        self.assertEqual(self.item.source, "微信公众号")
        self.assertTrue(60 <= len(self.item.summary) <= 90, self.item.summary)


class MentorArticleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.item = parse_article(
            MENTOR_TITLE, MENTOR_TEXT, url=MENTOR_URL, published="2026-11-06"
        )

    def test_kind_and_reminder_flag(self) -> None:
        self.assertEqual(self.item.kind, KIND_MENTOR)
        self.assertTrue(self.item.needs_reminder)

    def test_multiple_speakers_are_found(self) -> None:
        for name in ("王艺炜", "吴俊", "包贤强", "韩金广", "闫浩"):
            self.assertIn(name, self.item.speakers, f"缺少导师 {name}")

    def test_noise_lines_are_not_speakers(self) -> None:
        for noise in ("常规场次", "活动介绍", "说明", "报名方式", "主办"):
            self.assertNotIn(noise, self.item.speakers)

    def test_speaker_detail_and_signup(self) -> None:
        self.assertIn("信息科学与工程学院", self.item.speaker_detail)
        self.assertIn("12:30", self.item.signup_text)
        self.assertIn("11月6日", self.item.signup_text)

    def test_missing_when_and_place_stay_empty(self) -> None:
        # 每场的时间/地点可能只存在于图片或表格里，宁可为空也不编造。
        self.assertEqual(self.item.when_text, "")
        self.assertEqual(self.item.place, "")


class NameCleaningTests(unittest.TestCase):
    def test_spaced_two_char_names_are_merged(self) -> None:
        self.assertEqual(clean_name("吴 俊"), "吴俊")
        self.assertEqual(clean_name("闫　浩"), "闫浩")
        self.assertEqual(clean_name("马  强"), "马强")
        self.assertEqual(clean_name(" 孙 威 "), "孙威")

    def test_normal_names_are_untouched(self) -> None:
        self.assertEqual(clean_name("王艺炜"), "王艺炜")
        self.assertEqual(clean_name("包贤强"), "包贤强")

    def test_spaced_names_survive_in_article(self) -> None:
        item = parse_article(
            "导师交流 | 小样本",
            "常规场次\n吴 俊\n东南大学电子科学与工程学院教授，研究方向为柔性器件。\n"
            "闫 浩\n东南大学集成电路学院副教授，研究方向为时序分析。\n",
        )
        self.assertEqual(item.speakers, ["吴俊", "闫浩"])
        self.assertTrue(item.needs_reminder)


class ClassificationTests(unittest.TestCase):
    def test_title_keywords_decide_kind(self) -> None:
        self.assertEqual(parse_article("人文讲座 | 某场讲座", "").kind, KIND_LECTURE)
        self.assertEqual(parse_article("导师交流 | 第203期", "").kind, KIND_MENTOR)
        self.assertEqual(parse_article("关于2027年部分节假日安排的通知", "").kind, KIND_NOTICE)

    def test_body_keywords_decide_kind(self) -> None:
        self.assertEqual(parse_article("活动预告", "本周人文讲座安排如下").kind, KIND_LECTURE)
        self.assertEqual(parse_article("活动预告", "本期导师交流开始报名").kind, KIND_MENTOR)

    def test_notice_never_needs_reminder(self) -> None:
        item = parse_article("关于2027年校院级SRTP项目立项评审相关工作的通知", "")
        self.assertEqual(item.kind, KIND_NOTICE)
        self.assertFalse(item.needs_reminder)


class FieldExtractionTests(unittest.TestCase):
    def test_extract_fields_returns_stable_keys(self) -> None:
        fields = extract_fields(LECTURE_TEXT)
        self.assertEqual(
            set(fields),
            {"speakers", "speaker_detail", "topic", "when", "place", "signup", "seats"},
        )
        self.assertEqual(fields["speakers"], "胡汉辉")
        self.assertIn("12:30", fields["signup"])
        self.assertIn("60", fields["seats"])

    def test_extract_fields_tolerates_empty_text(self) -> None:
        fields = extract_fields("")
        self.assertEqual(
            set(fields),
            {"speakers", "speaker_detail", "topic", "when", "place", "signup", "seats"},
        )
        self.assertTrue(all(value == "" for value in fields.values()))

    def test_key_is_url_sha1_prefix(self) -> None:
        expected = hashlib.sha1(LECTURE_URL.encode("utf-8")).hexdigest()[:16]
        self.assertEqual(parse_article("标题", "", url=LECTURE_URL).key, expected)
        self.assertEqual(
            parse_article("标题", "", url=LECTURE_URL).key,
            parse_article("另一个标题", "正文", url=LECTURE_URL).key,
        )
        self.assertNotEqual(
            parse_article("标题", "", url=LECTURE_URL).key,
            parse_article("标题", "", url=MENTOR_URL).key,
        )


class OfflineFetchTests(unittest.TestCase):
    def test_fetch_without_network_returns_samples(self) -> None:
        with temp_cache_dir() as cache_dir:
            service = NewsService(cache_dir=cache_dir)
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                feed = service.fetch()
        self.assertIsInstance(feed, NewsFeed)
        self.assertTrue(feed.items, "兜底示例不应为空")
        self.assertFalse(feed.live)
        self.assertTrue(feed.error)
        self.assertTrue(feed.fetched_at)
        self.assertEqual(len(feed.items), 2)
        self.assertTrue(all(item.source == SOURCE_SAMPLE for item in feed.items))
        self.assertTrue(all(item.needs_reminder for item in feed.items))
        self.assertTrue(any(item.kind == KIND_LECTURE for item in feed.items))
        self.assertTrue(any(item.kind == KIND_MENTOR for item in feed.items))

    def test_fetch_never_raises_on_broken_network(self) -> None:
        with temp_cache_dir() as cache_dir:
            service = NewsService(cache_dir=cache_dir)
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=RuntimeError("boom"),
            ):
                feed = service.fetch(limit=4)
        self.assertTrue(feed.items)
        self.assertFalse(feed.live)

    def test_cache_is_reused_unless_forced(self) -> None:
        with temp_cache_dir() as cache_dir:
            service = NewsService(cache_dir=cache_dir)
            cached_item = parse_article(LECTURE_TITLE, LECTURE_TEXT, url=LECTURE_URL)
            service._write_cache(
                NewsFeed(
                    items=[cached_item],
                    fetched_at=datetime.now().isoformat(timespec="seconds"),
                    live=True,
                    source_note="已从学院官网同步 1 条",
                )
            )
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                fresh = service.fetch()
                forced = service.fetch(force=True)
        self.assertTrue(fresh.live)
        self.assertEqual(len(fresh.items), 1)
        self.assertEqual(fresh.items[0].key, cached_item.key)
        self.assertEqual(fresh.source_note, "已从学院官网同步 1 条")
        # force=True 会绕过新鲜缓存，网络失败后退回旧缓存并标记离线
        self.assertFalse(forced.live)
        self.assertTrue(forced.error)
        self.assertEqual(forced.items[0].key, cached_item.key)

    def test_sample_items_are_marked(self) -> None:
        items = sample_items()
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertIsInstance(item, NewsItem)
            self.assertEqual(item.source, SOURCE_SAMPLE)
            self.assertIn("示例", item.title)
            self.assertTrue(item.summary)


if __name__ == "__main__":
    unittest.main()
