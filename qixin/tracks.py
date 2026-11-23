"""情境歌单曲目数据与四维匹配。

一次推倒重来的原因写在这里，免得以后又走回头路：上一版把「九龙湖的深绿」
「安静得能听见笔尖」当作卖点，标签里全是棕噪 / 白噪。用户的原话是
「九龙湖的白噪音零个人愿意听」——所以这一版**只收真正像音乐的曲目**：
钢琴、指弹、Lo-fi、City Pop、室内乐、爵士、轻电子、民谣、后摇、Bossa
Nova、古风；2026 年又加入了流行、R&B、摇滚与原声，包含周杰伦、方大同、
陶喆、五月天、Beyond、肖邦、久石让等真实作品条目。器乐仍可本地合成
「试听 18 秒」；真实歌曲标记 `platform_only`，点按钮即跳到平台官方
搜索页，完整听感与版权都归平台。

每条曲目除了原有字段，还新增：

``kind``
    曲种，取值见 :data:`KINDS`。匹配时用来做多样性惩罚。
``bpm``
    展示用的整数速度。
``playlists``
    2–3 条平台官方搜索页链接（由 :mod:`qixin.playlists` 构造，不写死歌单 ID）。

匹配仍是四维评分（心情 / 活动 / 天气 / 时段），但排序增加了多样性约束：
前三条不能同 ``kind``、不能同 ``method``，连续两次推荐不会重复同一首
主打曲；每条结果附带一句人话版的 ``match_reason``。
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Iterable

from .playlists import build_playlist_links, platform_names

__all__ = [
    "KINDS",
    "TRACKS",
    "TRACK_BY_ID",
    "recommend_tracks",
    "reset_recent_recommendations",
    "time_bucket",
    "track_reason",
    "weather_group",
]


KINDS = (
    "钢琴",
    "吉他",
    "Lo-fi",
    "City Pop",
    "古典",
    "爵士",
    "轻电子",
    "民谣",
    "后摇",
    "Bossa Nova",
    "古风",
    "流行",
    "R&B",
    "摇滚",
    "原声",
)

#: 天气归一化只认这几个组，界面上的「自动」由 app 先折算成真实天气。
_WEATHER_GROUPS = ("雨", "雪", "晴", "阴", "多云")


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


def weather_group(condition: str) -> str:
    text = str(condition or "")
    for key in _WEATHER_GROUPS:
        if key in text:
            return key
    return "多云"


# ------------------------------------------------------------------ catalog
#
# 数据写成「规格 + 自动补歌单链接」的形式：``playlists`` 由关键词即时构造，
# 这样既不会出现失效的歌单 ID，也不用在数据里手写一长串 percent-encoding。

_SPECS: list[dict[str, Any]] = [
    {
        "id": "keys-window",
        "title": "窗边的第一小节",
        "subtitle": "钢琴独奏 · 分解和弦与一条慢旋律",
        "moods": ["心流在线", "已老实", "精神状态良好", "摸鱼中"],
        "activities": ["写论文", "阅读", "复习考试"],
        "weathers": ["晴", "多云", "阴"],
        "times": ["上午", "下午", "夜晚"],
        "tags": ["钢琴", "分解和弦", "慢板"],
        "color": "#D1A15E",
        "method": "keys",
        "kind": "钢琴",
        "bpm": 80,
        "keywords": ["钢琴独奏 安静", "钢琴 慢板 纯音乐"],
    },
    {
        "id": "guitar-seventh",
        "title": "木吉他的第七格",
        "subtitle": "吉他指弹 · 低音弦上走一条路",
        "moods": ["已老实", "摸鱼中", "活人微死", "灵魂出窍"],
        "activities": ["阅读", "放空", "写论文"],
        "weathers": ["晴", "多云", "阴"],
        "times": ["下午", "夜晚"],
        "tags": ["指弹", "木吉他", "低刺激"],
        "color": "#B88564",
        "method": "guitar_finger",
        "kind": "吉他",
        "bpm": 80,
        "keywords": ["木吉他 指弹", "吉他指弹 纯音乐"],
    },
    {
        "id": "lofi-desk-lamp",
        "title": "台灯下的循环",
        "subtitle": "Lo-fi 学习 · 旧鼓机与电钢琴",
        "moods": ["心流在线", "淹没在作业海", "已老实", "活人微死"],
        "activities": ["写论文", "复习考试", "阅读"],
        "weathers": ["雨", "阴", "多云", "雪"],
        "times": ["上午", "下午", "夜晚", "深夜"],
        "tags": ["Lo-fi", "鼓机", "学习"],
        "color": "#8FA3A0",
        "method": "lofi",
        "kind": "Lo-fi",
        "bpm": 80,
        "keywords": ["Lo-fi 学习", "lofi 专注 背景音乐"],
    },
    {
        "id": "citypop-viaduct",
        "title": "环城高架的霓虹",
        "subtitle": "City Pop 夜行 · 贝斯线把路灯串起来",
        "moods": ["美美得很", "精神状态良好", "摸鱼中", "灵魂出窍"],
        "activities": ["运动", "放空"],
        "weathers": ["晴", "多云", "阴"],
        "times": ["夜晚", "深夜"],
        "tags": ["City Pop", "霓虹", "贝斯"],
        "color": "#727B94",
        "method": "citypop",
        "kind": "City Pop",
        "bpm": 107,
        "keywords": ["City Pop 夜行", "city pop 夜间 驾驶"],
    },
    {
        "id": "chamber-afternoon",
        "title": "弦乐四重奏的下午",
        "subtitle": "古典室内乐 · 慢板与一束斜光",
        "moods": ["已老实", "心流在线", "精神状态良好", "无语"],
        "activities": ["写论文", "阅读", "复习考试"],
        "weathers": ["晴", "阴", "雪"],
        "times": ["下午", "上午"],
        "tags": ["室内乐", "弦乐", "慢板"],
        "color": "#A88D69",
        "method": "chamber",
        "kind": "古典",
        "bpm": 80,
        "keywords": ["古典室内乐", "弦乐四重奏 慢板"],
    },
    {
        "id": "jazz-nine-thirty",
        "title": "九点半的小号",
        "subtitle": "爵士小厅 · 摇摆的鼓刷与低音贝斯",
        "moods": ["摸鱼中", "美美得很", "已老实", "灵魂出窍"],
        "activities": ["阅读", "放空", "写论文"],
        "weathers": ["阴", "雨", "多云", "雪"],
        "times": ["夜晚", "深夜"],
        "tags": ["爵士", "即兴", "小号"],
        "color": "#6F9290",
        "method": "jazz_club",
        "kind": "爵士",
        "bpm": 107,
        "keywords": ["爵士 小厅", "jazz 钢琴 三重奏"],
    },
    {
        "id": "soft-glow",
        "title": "机房外的微光",
        "subtitle": "轻电子氛围 · 长音铺底与缓慢琶音",
        "moods": ["灵魂出窍", "活人微死", "心流在线", "无语"],
        "activities": ["复习考试", "写论文", "放空"],
        "weathers": ["阴", "雨", "雪", "多云"],
        "times": ["深夜", "夜晚"],
        "tags": ["氛围", "合成器", "长音"],
        "color": "#788C9A",
        "method": "soft_pad",
        "kind": "轻电子",
        "bpm": 53,
        "keywords": ["轻电子 氛围", "ambient 电子 纯音乐"],
    },
    {
        "id": "folk-backpack",
        "title": "背包里的旧和弦",
        "subtitle": "民谣 · 三和弦与一条会走路的旋律",
        "moods": ["已老实", "活人微死", "摸鱼中", "灵魂出窍"],
        "activities": ["阅读", "放空", "写论文"],
        "weathers": ["晴", "多云", "阴"],
        "times": ["下午", "夜晚", "清晨"],
        "tags": ["民谣", "叙事", "木吉他"],
        "color": "#C08A6A",
        "method": "folk",
        "kind": "民谣",
        "bpm": 107,
        "keywords": ["民谣 吉他", "民谣 木吉他 弹唱"],
    },
    {
        "id": "postrock-tide",
        "title": "潮水退去之前",
        "subtitle": "后摇 · 一层一层堆起来的吉他",
        "moods": ["淹没在作业海", "无语", "灵魂出窍", "活人微死"],
        "activities": ["运动", "放空", "写论文"],
        "weathers": ["阴", "雨", "雪", "多云"],
        "times": ["下午", "夜晚", "深夜"],
        "tags": ["后摇", "堆叠", "情绪"],
        "color": "#617B68",
        "method": "postrock",
        "kind": "后摇",
        "bpm": 80,
        "keywords": ["后摇 器乐", "post rock 纯音乐"],
    },
    {
        "id": "bossa-balcony",
        "title": "海风晒过阳台",
        "subtitle": "Bossa Nova · 尼龙弦与切分鼓点",
        "moods": ["美美得很", "精神状态良好", "摸鱼中", "已老实"],
        "activities": ["阅读", "放空", "运动"],
        "weathers": ["晴", "多云"],
        "times": ["上午", "下午"],
        "tags": ["Bossa Nova", "尼龙弦", "切分"],
        "color": "#D29B60",
        "method": "bossa",
        "kind": "Bossa Nova",
        "bpm": 107,
        "keywords": ["Bossa Nova", "bossa nova 吉他"],
    },
    {
        "id": "guqin-eaves",
        "title": "檐下雨，古琴三声",
        "subtitle": "古风器乐 · 泛音、留白与雨的气味",
        "moods": ["已老实", "无语", "灵魂出窍", "心流在线"],
        "activities": ["阅读", "写论文", "放空"],
        "weathers": ["雨", "阴", "雪"],
        "times": ["下午", "夜晚", "清晨"],
        "tags": ["古风", "古琴", "留白"],
        "color": "#9A8AA6",
        "method": "guqin",
        "kind": "古风",
        "bpm": 53,
        "keywords": ["古风 器乐", "古琴 纯音乐"],
    },
    {
        "id": "rain-jazz",
        "title": "雨敲在爵士鼓上",
        "subtitle": "雨夜爵士 · 很慢的钢琴与窗外的雨",
        "moods": ["淹没在作业海", "无语", "活人微死", "灵魂出窍"],
        "activities": ["写论文", "阅读", "复习考试"],
        "weathers": ["雨", "阴", "雪"],
        "times": ["夜晚", "深夜"],
        "tags": ["雨夜", "爵士", "钢琴"],
        "color": "#6E8FA3",
        "method": "rain",
        "kind": "爵士",
        "bpm": 80,
        "keywords": ["雨夜 爵士", "爵士 雨声 钢琴"],
    },
    {
        "id": "morning-guitar",
        "title": "早八前的木吉他",
        "subtitle": "晨间木吉他 · 明亮、干净、不催促",
        "moods": ["精神状态良好", "美美得很", "心流在线", "已老实"],
        "activities": ["运动", "复习考试", "阅读"],
        "weathers": ["晴", "多云"],
        "times": ["清晨", "上午"],
        "tags": ["晨间", "木吉他", "明亮"],
        "color": "#C9A86A",
        "method": "morning",
        "kind": "吉他",
        "bpm": 107,
        "keywords": ["晨间 木吉他", "清晨 吉他 轻音乐"],
    },
    {
        "id": "midnight-piano",
        "title": "凌晨两点的琴房",
        "subtitle": "深夜钢琴 · 很轻的触键与很长的不舍",
        "moods": ["灵魂出窍", "活人微死", "无语", "淹没在作业海"],
        "activities": ["写论文", "阅读", "复习考试"],
        "weathers": ["雨", "阴", "雪", "多云"],
        "times": ["深夜", "夜晚"],
        "tags": ["深夜", "钢琴", "安静"],
        "color": "#7C8AA5",
        "method": "night",
        "kind": "钢琴",
        "bpm": 53,
        "keywords": ["深夜 钢琴", "钢琴 助眠 纯音乐"],
    },
    {
        "id": "commute-brisk",
        "title": "地铁口的步子",
        "subtitle": "通勤轻快 · 鼓点替你数着台阶",
        "moods": ["精神状态良好", "美美得很", "摸鱼中", "已老实"],
        "activities": ["运动", "放空", "复习考试"],
        "weathers": ["晴", "多云", "阴"],
        "times": ["清晨", "上午", "下午"],
        "tags": ["通勤", "City Pop", "轻快"],
        "color": "#C97F5E",
        "method": "walk",
        "kind": "City Pop",
        "bpm": 107,
        "keywords": ["通勤 City Pop", "city pop 轻快 节奏"],
    },
    {
        "id": "focus-minimal",
        "title": "一条动机，反复四小节",
        "subtitle": "专注极简 · 一个动机慢慢长大",
        "moods": ["心流在线", "淹没在作业海", "已老实", "摸鱼中"],
        "activities": ["写论文", "复习考试", "阅读"],
        "weathers": ["晴", "阴", "雨", "多云"],
        "times": ["上午", "下午", "深夜"],
        "tags": ["极简", "动机", "专注"],
        "color": "#6C8C7E",
        "method": "minimal",
        "kind": "轻电子",
        "bpm": 80,
        "keywords": ["极简 电子 专注", "minimal 电子 背景"],
    },
    {
        "id": "orchard-bike",
        "title": "橘子汽水与自行车",
        "subtitle": "民谣 · 两条和弦走到黄昏",
        "moods": ["美美得很", "精神状态良好", "摸鱼中", "已老实"],
        "activities": ["运动", "放空", "阅读"],
        "weathers": ["晴", "多云"],
        "times": ["清晨", "上午", "下午"],
        "tags": ["民谣", "黄昏", "轻快"],
        "color": "#B98E5E",
        "method": "folk",
        "kind": "民谣",
        "bpm": 107,
        "keywords": ["民谣 黄昏", "民谣 吉他 轻快"],
    },
    {
        "id": "vintage-bside",
        "title": "旧唱片的 B 面",
        "subtitle": "City Pop · 有点旧、有点甜的合成器",
        "moods": ["美美得很", "摸鱼中", "灵魂出窍", "精神状态良好"],
        "activities": ["放空", "阅读", "运动"],
        "weathers": ["晴", "多云", "阴"],
        "times": ["夜晚", "深夜", "下午"],
        "tags": ["City Pop", "复古", "合成器"],
        "color": "#8B7E9A",
        "method": "citypop",
        "kind": "City Pop",
        "bpm": 107,
        "keywords": ["City Pop 复古", "city pop 合成器"],
    },
    {'id': 'jay-qingtian',
      'title': '晴天',
      'artist': '周杰伦',
      'subtitle': '周杰伦 · 流行 · 2003',
      'moods': ['美美得很', '精神状态良好', '已老实'],
      'activities': ['运动', '放空', '阅读', '写论文'],
      'weathers': ['晴', '多云'],
      'times': ['清晨', '上午', '下午'],
      'tags': ['流行', '周杰伦', '青春'],
      'color': '#C77D8B',
      'method': 'pop_jay',
      'kind': '流行',
      'bpm': 76,
      'keywords': ['周杰伦 晴天', '周杰伦 经典歌曲'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'jay-qilixiang',
      'title': '七里香',
      'artist': '周杰伦',
      'subtitle': '周杰伦 · 流行 · 2004',
      'moods': ['心流在线', '已老实', '摸鱼中', '美美得很'],
      'activities': ['写论文', '阅读', '放空'],
      'weathers': ['晴', '多云', '阴'],
      'times': ['下午', '夜晚'],
      'tags': ['流行', '周杰伦', '夏日'],
      'color': '#B98A6A',
      'method': 'pop_jay',
      'kind': '流行',
      'bpm': 82,
      'keywords': ['周杰伦 七里香', '周杰伦 夏天 歌曲'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'khalil-lovesong',
      'title': 'Love Song',
      'artist': '方大同',
      'subtitle': '方大同 · R&B · 2007',
      'moods': ['美美得很', '心流在线', '已老实'],
      'activities': ['写论文', '阅读', '放空'],
      'weathers': ['晴', '多云', '阴'],
      'times': ['下午', '夜晚'],
      'tags': ['R&B', '方大同', '律动'],
      'color': '#8E7CC3',
      'method': 'rnb_khalil',
      'kind': 'R&B',
      'bpm': 78,
      'keywords': ['方大同 Love Song', '方大同 歌曲'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'khalil-tebie',
      'title': '特别的人',
      'artist': '方大同',
      'subtitle': '方大同 · R&B · 2014',
      'moods': ['美美得很', '已老实', '摸鱼中'],
      'activities': ['阅读', '写论文', '放空'],
      'weathers': ['多云', '阴', '雨'],
      'times': ['夜晚', '下午'],
      'tags': ['R&B', '方大同', '温柔'],
      'color': '#9A86C9',
      'method': 'rnb_khalil',
      'kind': 'R&B',
      'bpm': 72,
      'keywords': ['方大同 特别的人', '方大同 慢歌'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'david-putong',
      'title': '普通朋友',
      'artist': '陶喆',
      'subtitle': '陶喆 · R&B · 1999',
      'moods': ['无语', '已老实', '活人微死'],
      'activities': ['阅读', '写论文'],
      'weathers': ['阴', '雨', '多云'],
      'times': ['夜晚', '深夜'],
      'tags': ['R&B', '陶喆', '慢热'],
      'color': '#7D8FB3',
      'method': 'rnb_david',
      'kind': 'R&B',
      'bpm': 74,
      'keywords': ['陶喆 普通朋友', '陶喆 R&B'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'david-aihenjiandan',
      'title': '爱，很简单',
      'artist': '陶喆',
      'subtitle': '陶喆 · R&B · 2006',
      'moods': ['美美得很', '已老实', '精神状态良好'],
      'activities': ['运动', '放空', '阅读'],
      'weathers': ['晴', '多云'],
      'times': ['下午', '夜晚'],
      'tags': ['R&B', '陶喆', '告白'],
      'color': '#C98E7A',
      'method': 'rnb_david',
      'kind': 'R&B',
      'bpm': 70,
      'keywords': ['陶喆 爱很简单', '陶喆 经典情歌'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'mayday-juejiang',
      'title': '倔强',
      'artist': '五月天',
      'subtitle': '五月天 · 摇滚 · 2004',
      'moods': ['心流在线', '精神状态良好', '淹没在作业海'],
      'activities': ['运动', '复习考试', '写论文'],
      'weathers': ['晴', '多云'],
      'times': ['清晨', '上午'],
      'tags': ['摇滚', '五月天', '热血'],
      'color': '#D06B4F',
      'method': 'rock_mayday',
      'kind': '摇滚',
      'bpm': 92,
      'keywords': ['五月天 倔强', '五月天 摇滚'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'beyond-haikuo',
      'title': '海阔天空',
      'artist': 'Beyond',
      'subtitle': 'Beyond · 摇滚 · 1993',
      'moods': ['心流在线', '精神状态良好', '灵魂出窍'],
      'activities': ['运动', '写论文', '放空'],
      'weathers': ['多云', '阴', '晴'],
      'times': ['上午', '下午', '夜晚'],
      'tags': ['摇滚', 'Beyond', '理想'],
      'color': '#B4553F',
      'method': 'rock_beyond',
      'kind': '摇滚',
      'bpm': 72,
      'keywords': ['Beyond 海阔天空', 'Beyond 经典摇滚'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'pushu-shengru',
      'title': '生如夏花',
      'artist': '朴树',
      'subtitle': '朴树 · 摇滚 · 2003',
      'moods': ['精神状态良好', '美美得很', '心流在线'],
      'activities': ['运动', '放空', '阅读'],
      'weathers': ['晴', '多云'],
      'times': ['清晨', '上午'],
      'tags': ['摇滚', '朴树', '明亮'],
      'color': '#C9825B',
      'method': 'rock_pushu',
      'kind': '摇滚',
      'bpm': 84,
      'keywords': ['朴树 生如夏花', '朴树 摇滚'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'chopin-nocturne',
      'title': '夜曲',
      'artist': '肖邦',
      'subtitle': '肖邦 · 古典 · 1832',
      'moods': ['活人微死', '灵魂出窍', '已老实', '无语'],
      'activities': ['阅读', '写论文', '复习考试'],
      'weathers': ['雨', '雪', '阴'],
      'times': ['夜晚', '深夜'],
      'tags': ['古典', '肖邦', '夜曲'],
      'color': '#8A7BA6',
      'method': 'classical_chopin',
      'kind': '古典',
      'bpm': 66,
      'keywords': ['肖邦 夜曲', '古典钢琴 夜曲'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'beethoven-moonlight',
      'title': '月光奏鸣曲',
      'artist': '贝多芬',
      'subtitle': '贝多芬 · 古典 · 1801',
      'moods': ['灵魂出窍', '活人微死', '无语'],
      'activities': ['阅读', '放空', '写论文'],
      'weathers': ['阴', '雨', '雪'],
      'times': ['深夜', '夜晚'],
      'tags': ['古典', '贝多芬', '静谧'],
      'color': '#7E8CA8',
      'method': 'classical_beethoven',
      'kind': '古典',
      'bpm': 60,
      'keywords': ['贝多芬 月光奏鸣曲', '古典钢琴 奏鸣曲'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'hisaishi-summer',
      'title': 'Summer',
      'artist': '久石让',
      'subtitle': '久石让 · 原声 · 1999',
      'moods': ['美美得很', '心流在线', '精神状态良好'],
      'activities': ['写论文', '阅读', '运动'],
      'weathers': ['晴', '多云'],
      'times': ['上午', '下午'],
      'tags': ['原声', '久石让', '夏日'],
      'color': '#7FA88E',
      'method': 'soundtrack_summer',
      'kind': '原声',
      'bpm': 96,
      'keywords': ['久石让 Summer', '久石让 钢琴'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'sakamoto-mcml',
      'title': 'Merry Christmas Mr. Lawrence',
      'artist': '坂本龙一',
      'subtitle': '坂本龙一 · 原声 · 1983',
      'moods': ['活人微死', '已老实', '灵魂出窍', '无语'],
      'activities': ['阅读', '放空', '写论文'],
      'weathers': ['阴', '雨', '雪'],
      'times': ['夜晚', '深夜'],
      'tags': ['原声', '坂本龙一', '留白'],
      'color': '#6E8C9A',
      'method': 'soundtrack_sakamoto',
      'kind': '原声',
      'bpm': 58,
      'keywords': ['坂本龙一 Merry Christmas', '坂本龙一 钢琴'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'pushu-pingfan',
      'title': '平凡之路',
      'artist': '朴树',
      'subtitle': '朴树 · 民谣 · 2014',
      'moods': ['已老实', '活人微死', '心流在线'],
      'activities': ['复习考试', '写论文', '运动'],
      'weathers': ['多云', '阴'],
      'times': ['下午', '夜晚'],
      'tags': ['民谣', '朴树', '路上'],
      'color': '#A08163',
      'method': 'folk_pushu',
      'kind': '民谣',
      'bpm': 88,
      'keywords': ['朴树 平凡之路', '朴树 民谣'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'eason-haojibujian',
      'title': '好久不见',
      'artist': '陈奕迅',
      'subtitle': '陈奕迅 · 流行 · 2007',
      'moods': ['无语', '已老实', '灵魂出窍'],
      'activities': ['阅读', '放空'],
      'weathers': ['阴', '雨', '多云'],
      'times': ['夜晚', '深夜'],
      'tags': ['流行', '陈奕迅', '想念'],
      'color': '#8C7F92',
      'method': 'pop_eason',
      'kind': '流行',
      'bpm': 62,
      'keywords': ['陈奕迅 好久不见', '陈奕迅 慢歌'],
      'duration': '平台完整版',
      'platform_only': True},
     {'id': 'faye-hongdou',
      'title': '红豆',
      'artist': '王菲',
      'subtitle': '王菲 · 流行 · 1998',
      'moods': ['已老实', '美美得很', '无语'],
      'activities': ['阅读', '放空'],
      'weathers': ['多云', '阴', '雨'],
      'times': ['下午', '夜晚'],
      'tags': ['流行', '王菲', '缱绻'],
      'color': '#B0808F',
      'method': 'pop_faye',
      'kind': '流行',
      'bpm': 72,
      'keywords': ['王菲 红豆', '王菲 经典歌曲'],
      'duration': '平台完整版',
      'platform_only': True},
]


def _materialize(spec: dict[str, Any]) -> dict[str, Any]:
    track = dict(spec)
    keywords = track.pop("keywords")
    if track.get("platform_only"):
        # Real songs win ties against the ambient beds: when a listener taps
        # 「美美得很 · 运动 · 晴」, 周杰伦 should be allowed to show up first.
        track.setdefault("featured", True)
    track["playlists"] = build_playlist_links(str(track["kind"]), keywords)
    track.setdefault("duration", "18 秒无缝循环")
    return track


TRACKS: list[dict[str, Any]] = [_materialize(spec) for spec in _SPECS]
TRACK_BY_ID: dict[str, dict[str, Any]] = {track["id"]: track for track in TRACKS}
_TRACK_ORDER: dict[str, int] = {track["id"]: index for index, track in enumerate(TRACKS)}

#: 曲种 → 一句「为什么是这首」的尾句（页面和 match_reason 共用）。
_KIND_TAILS = {
    "钢琴": "琴音落得很稳",
    "吉他": "指弹不抢你的笔",
    "Lo-fi": "松散鼓点托住专注",
    "City Pop": "贝斯线替你把路照亮",
    "古典": "弦乐把房间撑大",
    "爵士": "小厅的松弛感",
    "轻电子": "脉冲轻轻推着思绪",
    "民谣": "旧和弦陪你做完",
    "后摇": "情绪一层层有出口",
    "Bossa Nova": "切分像海风",
    "古风": "古琴留白，呼吸慢",
    "流行": "旋律一开口就认得",
    "R&B": "转音把情绪托起来",
    "摇滚": "吉他把胸口推开",
    "原声": "像一段电影里的留白",
}

_DEFAULT_TAIL = "适合把注意力收回来"
_DEFAULT_REASON_LIMIT = 28

#: 记录最近几次推荐的主打曲目，连续两次调用不会重复同一首。
_RECENT_TOP: deque[str] = deque(maxlen=3)


def reset_recent_recommendations() -> None:
    """清空「上一首」记忆（测试与切换情境时用）。"""

    _RECENT_TOP.clear()


def _score_track(
    track: dict[str, Any],
    mood: str,
    activity: str,
    weather: str,
    moment: str,
) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    hits: list[str] = []
    if mood in track["moods"]:
        score += 3
        reasons.append(f"接住「{mood}」")
        hits.append("mood")
    if activity in track["activities"]:
        score += 3
        reasons.append(f"适合「{activity}」")
        hits.append("activity")
    if weather in track["weathers"]:
        score += 2
        reasons.append(f"回应「{weather}」")
        hits.append("weather")
    if moment in track["times"]:
        score += 2
        reasons.append(f"贴合「{moment}」")
        hits.append("time")
    return score, reasons, hits


def _match_reason(
    track: dict[str, Any],
    mood: str,
    activity: str,
    weather: str,
    moment: str,
    hits: Iterable[str],
) -> str:
    """一句 ≤28 字的「为什么是这首」。"""

    hit_set = set(hits)
    context: list[str] = []
    if "weather" in hit_set:
        context.append(weather)
    if "time" in hit_set:
        context.append(moment)
    if not context:
        if "activity" in hit_set:
            context.append(activity)
        elif "mood" in hit_set:
            context.append(mood)
    head = "·".join(context) if context else "此刻"

    bpm = track.get("bpm")
    tail = _KIND_TAILS.get(str(track.get("kind", "")), _DEFAULT_TAIL)
    reason = f"{head} · {bpm} BPM，{tail}" if bpm else f"{head}，{tail}"
    if len(reason) > _DEFAULT_REASON_LIMIT:
        # 先收上下文，不砍尾句——尾句才是「说人话」的部分。
        reason = f"{head[:4]} · {bpm} BPM，{tail}" if bpm else f"{head[:4]}，{tail}"
    return reason[:_DEFAULT_REASON_LIMIT]


def _diverse_order(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按分数排序后做多样性挑选，返回新的推荐顺序。

    前三名强制不同 ``kind`` 与不同 ``method``；第一名的挑选还会避开上一次
    的主打，避免连点「生成」时反复听到同一首。约束无法同时满足时逐级放宽，
    因此任何输入都至少能返回完整列表。
    """

    taken: set[int] = set()
    kinds: set[str] = set()
    methods: set[str] = set()
    blocked = set(_RECENT_TOP)
    order: list[dict[str, Any]] = []

    # (要求新的 kind, 要求新的 method, 是否要求避开上一首)
    passes = (
        (True, True, True),
        (True, True, False),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    )
    for slot in range(min(3, len(results))):
        picked: int | None = None
        for need_kind, need_method, avoid_recent in passes:
            if slot > 0 and avoid_recent:
                continue
            for index, item in enumerate(results):
                if index in taken:
                    continue
                if need_kind and item["kind"] in kinds:
                    continue
                if need_method and item["method"] in methods:
                    continue
                if avoid_recent and item["id"] in blocked:
                    continue
                picked = index
                break
            if picked is not None:
                break
        if picked is None:
            break
        item = results[picked]
        taken.add(picked)
        order.append(item)
        kinds.add(str(item["kind"]))
        methods.add(str(item["method"]))

    for index, item in enumerate(results):
        if index not in taken:
            order.append(item)

    if order:
        _RECENT_TOP.append(str(order[0]["id"]))
    return order


def recommend_tracks(
    mood: str,
    activity: str,
    weather: str,
    moment: str | None = None,
) -> list[dict[str, Any]]:
    """四维评分 + 多样性约束，返回按匹配度排好的全部曲目。

    ``score`` 恒 ≥ 0；``score_percent`` 随返回顺序单调不增；前三条的
    ``kind`` 与 ``method`` 互不相同；结果里带 ``kind`` / ``bpm`` /
    ``playlists`` / ``match_reason``，页面可以直接渲染。
    """

    moment = moment or time_bucket()
    weather = weather_group(weather)

    scored: list[dict[str, Any]] = []
    for track in TRACKS:
        score, reasons, hits = _score_track(track, mood, activity, weather, moment)
        scored.append(
            {
                **track,
                "score": max(0, score),
                "reasons": reasons,
                "match_reason": _match_reason(
                    track, mood, activity, weather, moment, hits
                ),
                "platform_names": platform_names(track),
            }
        )

    scored.sort(
        key=lambda item: (
            -item["score"],
            0 if item.get("featured") else 1,
            _TRACK_ORDER[item["id"]],
        )
    )
    ordered = _diverse_order(scored)

    previous = 100
    for rank, item in enumerate(ordered):
        raw = 62 + item["score"] * 3.3 - min(rank, 3)
        percent = round(min(97, max(55, raw)))
        # 多样性排序可能让后一名分数更高，百分比仍然必须单调不增。
        percent = min(percent, previous)
        item["score_percent"] = percent
        previous = percent
    return ordered


def track_reason(
    mood: str,
    activity: str,
    weather: str,
    moment: str,
    recommendation: dict[str, Any],
) -> str:
    """完整版推荐说明（保留旧接口，页面用短版 ``match_reason``）。"""

    weather = weather_group(weather)
    short = str(recommendation.get("match_reason", "")).strip()
    reasons = recommendation.get("reasons", [])
    base = f"你在{moment}的{weather}里，带着「{mood}」准备{activity}。"
    if short:
        return base + short + "。"
    if reasons:
        return base + "这段声音会" + "、".join(reasons[:3]) + "，不抢走你的注意力。"
    return base + "这段声音足够稳定，让注意力有地方落下来。"
