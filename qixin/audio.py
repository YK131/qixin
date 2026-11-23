"""本地试听音频：用纯 Python 合成 18 秒、可无缝循环的**音乐**。

旧版的问题很直接：主音色就是棕噪 / 白噪，用户称之为「九龙湖的白噪音」。
这一版把噪声降级成 5% 以下的空气感，真正的声音骨架由四层构成：

1. **和声铺底**（adagio 式长音 pad，慢起慢收）；
2. **分解和弦琶音**（按节拍走动，带重音与轻微人性化时值）；
3. **旋律动机**（每两小节出现一次的短句，重复、变奏、留白）；
4. **轻打击**（kick 用正弦扫频，hi-hat 用高通噪声包络——只做节奏，
   不做主音色）。

最后过两级反馈梳状滤波 + 一级 allpass 的简易混响，再把尾音交叉淡入
开头，保证 SND_LOOP 循环时不爆音。所有 ``method`` 旧名字（``rain`` /
``forest`` / ``room`` / ``library`` / ``sea`` …）都保留，只是内部换成了
音乐化的编配；新增的 ``lofi`` / ``citypop`` / ``chamber`` / ``jazz_club``
/ ``bossa`` / ``guqin`` / ``minimal`` 等同样可以独立生成。

整体在 22.05kHz 单声道 18 秒下生成，单曲目标控制在 8 秒以内。
"""

from __future__ import annotations

import array
import math
import os
import platform
import random
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable

from .db import app_data_dir

SAMPLE_RATE = 22_050
DURATION_SECONDS = 18.0
_TAU = math.tau
_SR = SAMPLE_RATE
_MAX_PEAK = 0.72  # 归一化目标；验收要求峰值 < 0.99，这里留足余量

# ------------------------------------------------------------------ harmony
#
# 和弦以「相对主音的半音偏移」表示，换调只需要改 style["key"]。

_MAJOR = ((0, 4, 7, 11), (-3, 0, 4, 7), (5, 9, 12, 16), (7, 11, 14, 17))
_MINOR = ((0, 3, 7, 10), (-4, 0, 3, 7), (3, 7, 10, 14), (10, 14, 17, 21))
_FOLK = ((0, 4, 7), (-3, 0, 4), (5, 9, 12), (7, 11, 14))
_JAZZ = ((2, 5, 9, 12), (7, 11, 14, 17), (0, 4, 7, 11), (-3, 0, 4, 7))
_CITYPOP = ((5, 9, 12, 16), (-3, 0, 4, 7), (2, 6, 9, 12), (7, 11, 14, 17))
_BOSSA = ((0, 4, 7, 11), (-3, 0, 4, 7), (2, 6, 9, 12), (7, 11, 14, 17))
_PENTA = ((0, 7, 12, 19), (5, 12, 17, 24), (-5, 2, 7, 14), (0, 7, 12, 19))
_POSTROCK = ((0, 4, 7, 12), (-5, -1, 2, 7), (5, 9, 12, 16), (7, 11, 14, 17))

# 旋律动机：(起始拍, 相对主音的半音, 时值拍)。每段 8 拍（两小节），
# 重复时靠 velocity / 起始抖动做一点人味，而不是原样循环。
_MOTIF_PIANO = (
    (0.0, 7, 1.5), (1.5, 9, 0.5), (2.0, 11, 1.0), (3.0, 12, 1.0),
    (4.0, 11, 0.5), (4.5, 9, 0.5), (5.0, 7, 1.0), (6.0, 4, 1.0), (7.0, 2, 1.0),
)
_MOTIF_GUITAR = (
    (0.0, 12, 0.75), (0.75, 9, 0.75), (1.5, 7, 0.5), (2.0, 4, 1.0),
    (3.0, 7, 1.0), (4.0, 9, 1.5), (5.5, 12, 0.5), (6.0, 9, 1.0), (7.0, 7, 1.0),
)
_MOTIF_LOFI = (
    (0.0, 7, 0.75), (0.75, 10, 0.75), (1.5, 7, 0.5), (2.0, 5, 1.25),
    (3.5, 4, 0.5), (4.0, 7, 1.0), (5.0, 5, 1.0), (6.0, 4, 2.0),
)
_MOTIF_CITYPOP = (
    (0.0, 12, 0.5), (0.5, 11, 0.5), (1.0, 9, 0.5), (1.5, 7, 0.5),
    (2.0, 9, 1.0), (3.0, 12, 1.0), (4.0, 14, 1.5), (5.5, 12, 0.5),
    (6.0, 9, 1.0), (7.0, 7, 1.0),
)
_MOTIF_CHAMBER = ((0.0, 12, 2.0), (2.0, 7, 1.0), (3.0, 9, 1.0), (4.0, 11, 2.0), (6.0, 9, 2.0))
_MOTIF_JAZZ = (
    (0.0, 10, 0.75), (0.75, 9, 0.75), (1.5, 7, 1.5), (3.0, 4, 1.0),
    (4.0, 7, 0.75), (4.75, 9, 0.75), (5.5, 10, 1.0), (6.5, 12, 1.5),
)
_MOTIF_AMBIENT = ((0.0, 7, 2.0), (2.0, 12, 2.0), (4.0, 9, 2.0), (6.0, 4, 2.0))
_MOTIF_FOLK = (
    (0.0, 7, 1.0), (1.0, 9, 0.5), (1.5, 7, 0.5), (2.0, 4, 1.0),
    (3.0, 2, 1.0), (4.0, 0, 2.0), (6.0, 4, 1.0), (7.0, 2, 1.0),
)
_MOTIF_POSTROCK = ((0.0, 12, 2.0), (2.0, 14, 2.0), (4.0, 16, 2.0), (6.0, 14, 2.0))
_MOTIF_BOSSA = (
    (0.0, 11, 0.5), (0.5, 9, 0.5), (1.0, 7, 0.5), (1.5, 4, 0.5),
    (2.0, 7, 1.0), (3.0, 11, 1.0), (4.0, 12, 1.5), (5.5, 11, 0.5),
    (6.0, 9, 1.0), (7.0, 7, 1.0),
)
_MOTIF_GUQIN = ((0.0, 12, 2.0), (1.5, 7, 1.0), (3.0, 9, 2.5), (5.5, 7, 1.5), (7.0, 0, 1.0))
_MOTIF_MINIMAL = (
    (0.0, 7, 1.0), (1.0, 7, 0.5), (1.5, 12, 0.5), (2.0, 7, 1.0),
    (3.0, 9, 1.0), (4.0, 7, 1.0), (5.0, 4, 1.0), (6.0, 7, 2.0),
)
_MOTIF_NIGHT = ((0.0, 7, 2.0), (2.0, 11, 2.0), (4.0, 9, 1.5), (5.5, 7, 2.5))
_MOTIF_MORNING = (
    (0.0, 12, 0.5), (0.5, 7, 0.5), (1.0, 9, 0.5), (1.5, 12, 0.5),
    (2.0, 14, 1.0), (3.0, 12, 1.0), (4.0, 9, 1.5), (5.5, 7, 0.5),
    (6.0, 9, 1.0), (7.0, 12, 1.0),
)
_MOTIF_RAINJAZZ = (
    (0.0, 3, 1.0), (1.0, 7, 0.5), (1.5, 10, 1.5), (3.0, 7, 1.0),
    (4.0, 5, 1.0), (5.0, 3, 2.0), (7.0, 0, 1.0),
)

# 谐波数量直接决定合成耗时（每个谐波每采样一次 sin），所以克制在 2–4 个：
# 音色仍然分得清，但单曲生成能稳在 8 秒以内。
_TIMBRE_PIANO = (1.0, 0.45, 0.25, 0.12)
_TIMBRE_GUITAR = (1.0, 0.5, 0.26, 0.12)
_TIMBRE_EPIANO = (1.0, 0.26, 0.1)
_TIMBRE_SYNTH = (1.0, 0.48, 0.26, 0.12)
_TIMBRE_STRINGS = (1.0, 0.6, 0.38, 0.22)
_TIMBRE_PAD = (1.0, 0.65, 0.4)
_TIMBRE_GUQIN = (1.0, 0.32, 0.16)
_TIMBRE_BASS = (1.0, 0.28)


def _style(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "bars": 6,
        "key": 60,
        "progression": _MAJOR,
        "pad": 0.0,
        "pad_voices": (0, 1),
        "pad_attack": 0.7,
        "pad_decay": 6.0,
        "pad_release": 0.9,
        "pad_timbre": _TIMBRE_STRINGS,
        "bass": 0.0,
        "bass_beats": ((0.0, 1.0), (2.5, 0.7)),
        "bass_decay": 1.1,
        "arp": 0.0,
        "arp_pattern": (0, 1, 2, 1),
        "arp_step": 0.5,
        "arp_octave": 1,
        "arp_decay": 0.7,
        "arp_length": 1.2,
        "arp_timbre": _TIMBRE_PIANO,
        "strum": False,
        "melody": 0.0,
        "motif": _MOTIF_PIANO,
        "melody_every": 2,
        "melody_octave": 1,
        "melody_decay": 1.6,
        "melody_tail": 0.6,
        "melody_timbre": _TIMBRE_PIANO,
        "kick": 0.0,
        "kick_beats": ((0.0, 1.0), (2.5, 0.65)),
        "hat": 0.0,
        "hat_step": 0.5,
        "swing": 0.0,
        "reverb": 0.22,
        "air": 0.004,
        "rain": 0.0,
        "humanize": 0.005,
    }
    base.update(overrides)
    return base


_STYLES: dict[str, dict[str, Any]] = {
    "keys": _style(
        bars=6, key=60, progression=_MAJOR,
        pad=0.03, pad_voices=(0, 2), pad_attack=0.9,
        bass=0.11, arp=0.14, arp_pattern=(0, 1, 2, 3, 2, 1), arp_octave=1,
        arp_decay=0.9, arp_length=1.5,
        melody=0.19, motif=_MOTIF_PIANO, melody_decay=1.8,
        reverb=0.28, air=0.004,
    ),
    "guitar_finger": _style(
        bars=6, key=57, progression=_FOLK,
        bass=0.10, arp=0.16, arp_pattern=(0, 2, 1, 3), arp_octave=1,
        arp_decay=0.9, arp_length=1.0, arp_timbre=_TIMBRE_GUITAR,
        melody=0.15, motif=_MOTIF_GUITAR, melody_timbre=_TIMBRE_GUITAR,
        melody_decay=1.7, reverb=0.22, humanize=0.008,
    ),
    "lofi": _style(
        bars=6, key=60, progression=_MAJOR,
        pad=0.025, pad_voices=(0, 2), pad_attack=0.6,
        bass=0.10, bass_beats=((0.0, 1.0), (2.0, 0.6)),
        arp=0.12, arp_pattern=(0, 2, 1, 2), arp_step=1.0, arp_octave=1,
        arp_decay=0.9, arp_length=1.2, arp_timbre=_TIMBRE_EPIANO,
        melody=0.13, motif=_MOTIF_LOFI, melody_timbre=_TIMBRE_EPIANO,
        melody_decay=1.8, kick=0.13, hat=0.032, swing=0.08,
        reverb=0.2, air=0.008, humanize=0.012,
    ),
    "citypop": _style(
        bars=8, key=62, progression=_CITYPOP,
        pad=0.03, pad_voices=(0, 2), pad_attack=0.5,
        bass=0.13, bass_beats=((0.0, 1.0), (1.5, 0.6), (2.5, 0.9), (3.5, 0.6)),
        arp=0.13, arp_pattern=(0, 2, 1, 3, 2, 1), arp_octave=1,
        arp_decay=0.8, arp_timbre=_TIMBRE_SYNTH,
        melody=0.16, motif=_MOTIF_CITYPOP, melody_timbre=_TIMBRE_SYNTH,
        kick=0.12, hat=0.042, reverb=0.18, humanize=0.006,
    ),
    "chamber": _style(
        bars=6, key=55, progression=_MAJOR,
        pad=0.05, pad_voices=(0, 1, 2), pad_attack=0.6, pad_decay=8.0,
        bass=0.08, bass_beats=((0.0, 1.0), (2.0, 0.7)),
        arp=0.09, arp_pattern=(0, 1, 2, 1, 3, 1), arp_octave=1,
        arp_decay=1.1, arp_length=1.6, arp_timbre=_TIMBRE_STRINGS,
        melody=0.16, motif=_MOTIF_CHAMBER, melody_timbre=_TIMBRE_STRINGS,
        melody_decay=2.0, melody_tail=0.9,
        reverb=0.32, air=0.003, humanize=0.007,
    ),
    "jazz_club": _style(
        bars=8, key=58, progression=_JAZZ,
        pad=0.02, pad_voices=(0, 2), pad_attack=0.5,
        bass=0.11, bass_beats=((0.0, 1.0), (1.0, 0.7), (2.0, 0.9), (3.0, 0.6)),
        arp=0.08, arp_pattern=(0, 1, 2, 3), arp_step=1.0, arp_octave=1,
        arp_decay=0.9, arp_timbre=_TIMBRE_PIANO,
        melody=0.13, motif=_MOTIF_JAZZ, melody_decay=1.4,
        kick=0.05, hat=0.045, swing=0.16, reverb=0.24, humanize=0.012,
    ),
    "soft_pad": _style(
        bars=4, key=55, progression=_MAJOR,
        pad=0.055, pad_voices=(0, 1, 2), pad_attack=1.2, pad_decay=10.0,
        pad_release=1.2, pad_timbre=_TIMBRE_PAD,
        bass=0.05, bass_beats=((0.0, 1.0),),
        arp=0.07, arp_pattern=(0, 1, 2, 3, 2, 1), arp_step=1.0, arp_octave=2,
        arp_decay=1.6, arp_timbre=_TIMBRE_SYNTH,
        melody=0.08, motif=_MOTIF_AMBIENT, melody_every=4,
        melody_timbre=_TIMBRE_PAD, melody_decay=2.6, melody_tail=0.9,
        reverb=0.38, air=0.007, humanize=0.008,
    ),
    "folk": _style(
        bars=8, key=57, progression=_FOLK,
        bass=0.10, arp=0.14, arp_pattern=(0, 1, 2, 3), arp_octave=1,
        arp_decay=0.9, arp_length=1.0, arp_step=1.0,
        arp_timbre=_TIMBRE_GUITAR, strum=True,
        melody=0.15, motif=_MOTIF_FOLK, melody_decay=1.3, melody_tail=0.5,
        melody_timbre=_TIMBRE_GUITAR,
        reverb=0.22, humanize=0.008,
    ),
    "postrock": _style(
        bars=6, key=52, progression=_POSTROCK,
        pad=0.05, pad_voices=(0, 1, 2), pad_attack=0.8, pad_decay=9.0,
        bass=0.10, bass_beats=((0.0, 1.0), (2.0, 0.8)),
        arp=0.10, arp_pattern=(0, 1, 2, 3, 2, 1), arp_octave=1,
        arp_decay=1.2, arp_length=1.5, arp_timbre=_TIMBRE_GUITAR,
        melody=0.14, motif=_MOTIF_POSTROCK, melody_timbre=_TIMBRE_STRINGS,
        melody_decay=2.2, melody_tail=0.9,
        kick=0.07, hat=0.02, hat_step=1.0,
        reverb=0.4, air=0.006, humanize=0.009,
    ),
    "bossa": _style(
        bars=8, key=60, progression=_BOSSA,
        bass=0.11, bass_beats=((0.0, 1.0), (1.5, 0.7), (2.5, 0.8)),
        arp=0.13, arp_pattern=(0, 1, 2, 1), arp_octave=1,
        arp_decay=0.9, arp_length=1.0, arp_timbre=_TIMBRE_GUITAR,
        melody=0.14, motif=_MOTIF_BOSSA, melody_timbre=_TIMBRE_GUITAR,
        kick=0.05, hat=0.03, swing=0.05,
        reverb=0.22, humanize=0.01,
    ),
    "guqin": _style(
        bars=4, key=57, progression=_PENTA,
        pad=0.03, pad_voices=(0, 2), pad_attack=1.4, pad_decay=12.0,
        pad_release=1.4, pad_timbre=_TIMBRE_PAD,
        bass=0.05, bass_beats=((0.0, 1.0),),
        melody=0.20, motif=_MOTIF_GUQIN, melody_every=1,
        melody_timbre=_TIMBRE_GUQIN, melody_decay=2.4, melody_tail=1.0,
        reverb=0.42, air=0.004, humanize=0.014,
    ),
    "rain": _style(
        bars=6, key=56, progression=_JAZZ,
        pad=0.03, pad_voices=(0, 2), pad_attack=0.8,
        bass=0.11, bass_beats=((0.0, 1.0), (1.5, 0.7), (2.5, 0.8)),
        arp=0.07, arp_pattern=(0, 2, 1, 2), arp_step=1.0, arp_octave=1,
        arp_decay=1.1, arp_timbre=_TIMBRE_PIANO,
        melody=0.17, motif=_MOTIF_RAINJAZZ, melody_decay=2.0,
        kick=0.04, hat=0.028, swing=0.14,
        reverb=0.3, rain=0.012, air=0.005, humanize=0.012,
    ),
    "morning": _style(
        bars=8, key=60, progression=_FOLK,
        bass=0.09, arp=0.15, arp_pattern=(0, 1, 2, 3), arp_octave=1,
        arp_decay=0.9, arp_length=1.0, arp_step=1.0,
        arp_timbre=_TIMBRE_GUITAR, strum=True,
        melody=0.16, motif=_MOTIF_MORNING, melody_tail=0.5,
        melody_timbre=_TIMBRE_GUITAR,
        reverb=0.2, humanize=0.006,
    ),
    "night": _style(
        bars=4, key=53, progression=_MINOR,
        pad=0.03, pad_voices=(0, 2), pad_attack=1.2, pad_decay=10.0,
        bass=0.07, bass_beats=((0.0, 1.0),),
        arp=0.09, arp_pattern=(0, 2, 1, 2), arp_step=1.0, arp_octave=1,
        arp_decay=1.3, arp_length=1.6,
        melody=0.16, motif=_MOTIF_NIGHT, melody_every=1,
        melody_decay=2.2, melody_tail=1.0,
        reverb=0.4, air=0.004, humanize=0.01,
    ),
    "walk": _style(
        bars=8, key=60, progression=_CITYPOP,
        pad=0.025, pad_voices=(0, 2), pad_attack=0.4,
        bass=0.13, bass_beats=((0.0, 1.0), (1.5, 0.6), (2.5, 0.9), (3.5, 0.6)),
        arp=0.12, arp_pattern=(0, 2, 1, 3, 2, 1), arp_octave=1,
        arp_decay=0.7, arp_timbre=_TIMBRE_SYNTH,
        melody=0.14, motif=_MOTIF_CITYPOP, melody_timbre=_TIMBRE_SYNTH,
        kick=0.13, hat=0.048,
        reverb=0.16, humanize=0.006,
    ),
    "room": _style(
        bars=4, key=60, progression=_MINOR,
        pad=0.025, pad_voices=(0, 2), pad_attack=1.0,
        bass=0.06, bass_beats=((0.0, 1.0),),
        arp=0.10, arp_pattern=(0, 2, 1, 2), arp_step=1.0, arp_octave=1,
        arp_decay=1.1, arp_length=1.4,
        melody=0.12, motif=_MOTIF_MINIMAL, melody_every=2,
        reverb=0.3, air=0.003, humanize=0.008,
    ),
    "library": _style(
        bars=6, key=60, progression=_MAJOR,
        pad=0.02, pad_voices=(0, 2), pad_attack=0.7,
        bass=0.09, arp=0.10, arp_pattern=(0, 2, 1, 2), arp_step=1.0, arp_octave=1,
        arp_decay=1.0, arp_timbre=_TIMBRE_EPIANO,
        melody=0.11, motif=_MOTIF_LOFI, melody_timbre=_TIMBRE_EPIANO,
        kick=0.07, hat=0.025, swing=0.06,
        reverb=0.22, air=0.008, humanize=0.01,
    ),
    "sea": _style(
        bars=6, key=50, progression=_POSTROCK,
        pad=0.06, pad_voices=(0, 1, 2), pad_attack=1.0, pad_decay=10.0,
        bass=0.09, arp=0.08, arp_pattern=(0, 1, 2, 3, 2, 1), arp_step=0.5,
        arp_decay=1.3, arp_timbre=_TIMBRE_STRINGS,
        melody=0.12, motif=_MOTIF_POSTROCK, melody_timbre=_TIMBRE_STRINGS,
        melody_decay=2.2, melody_tail=1.0,
        reverb=0.42, air=0.008, humanize=0.01,
    ),
    "forest": _style(
        bars=4, key=50, progression=_POSTROCK,
        pad=0.05, pad_voices=(0, 1, 2), pad_attack=1.2, pad_decay=11.0,
        bass=0.08, arp=0.08, arp_pattern=(0, 2, 1, 3), arp_step=0.5,
        arp_decay=1.2, arp_timbre=_TIMBRE_GUITAR,
        melody=0.10, motif=_MOTIF_AMBIENT, melody_timbre=_TIMBRE_GUITAR,
        reverb=0.4, air=0.008, humanize=0.012,
    ),
    "minimal": _style(
        bars=6, key=60, progression=_MAJOR,
        pad=0.03, pad_voices=(0, 2), pad_attack=0.9,
        bass=0.08, bass_beats=((0.0, 1.0), (2.0, 0.6)),
        arp=0.12, arp_pattern=(0, 2, 1, 2), arp_step=1.0, arp_octave=1,
        arp_decay=0.9, arp_timbre=_TIMBRE_SYNTH,
        melody=0.14, motif=_MOTIF_MINIMAL, melody_timbre=_TIMBRE_SYNTH,
        kick=0.05, hat=0.014, hat_step=1.0,
        reverb=0.26, air=0.003, humanize=0.004,
    ),
}

#: 全部可生成的 method 名称（含为兼容旧缓存保留的 ``forest`` / ``room`` /
#: ``library`` / ``sea``）。测试可以对它逐个生成。
METHODS: tuple[str, ...] = tuple(_STYLES)


# -------------------------------------------------------------------- audio
def _hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((float(midi) - 69.0) / 12.0))


def _add_tone(
    buf: list[float],
    start: float,
    seconds: float,
    freq: float,
    amp: float,
    timbre: tuple[float, ...],
    *,
    attack: float = 0.008,
    decay: float = 1.2,
    release: float = 0.08,
) -> None:
    """把一个带包络的谐波音叠加进 ``buf``（时间单位：秒）。"""

    if amp <= 0.0 or seconds <= 0.0 or freq <= 0.0 or freq >= _SR * 0.45:
        return
    length = int(seconds * _SR)
    offset = int(start * _SR)
    if length <= 0 or offset >= len(buf):
        return
    if offset < 0:
        length += offset
        offset = 0
    if length <= 0:
        return
    length = min(length, len(buf) - offset)

    # 奈奎斯特以上的谐波直接丢掉，避免混叠成刺耳噪声。
    max_harmonic = max(1, int((_SR * 0.45) / freq))
    harmonics = tuple(timbre[:max_harmonic]) or (1.0,)
    count = len(harmonics)
    increments = [_TAU * freq * (index + 1) / _SR for index in range(count)]
    phases = [0.0] * count
    attack_samples = max(1, min(length, int(attack * _SR)))
    release_samples = (
        max(1, min(length, int(release * _SR))) if release > 0 else 0
    )
    # 指数包络改成逐采样相乘：比每采样一次 math.exp 快一个量级。
    decay_step = math.exp(-1.0 / max(1e-4, decay * _SR))
    release_step = 1.0 / release_samples if release_samples else 0.0
    release_start = length - release_samples if release_samples else length
    sin = math.sin
    target = buf
    base = offset
    env = 0.0
    release_gain = 1.0

    for index in range(length):
        if index < attack_samples:
            env = index / attack_samples
        elif index == attack_samples:
            env = 1.0
        else:
            env *= decay_step
        value = 0.0
        for harmonic_index in range(count):
            value += harmonics[harmonic_index] * sin(phases[harmonic_index])
            phases[harmonic_index] += increments[harmonic_index]
        gain = env
        if release_samples and index >= release_start:
            if index == release_start:
                release_gain = 1.0
            gain *= max(0.0, release_gain)
            release_gain -= release_step
        target[base + index] += amp * gain * value


def _add_kick(buf: list[float], start: float, amp: float) -> None:
    """正弦扫频 kick：只做低频节拍，不是噪声。"""

    if amp <= 0.0:
        return
    length = int(0.26 * _SR)
    offset = int(start * _SR)
    if offset < 0 or offset >= len(buf):
        return
    length = min(length, len(buf) - offset)
    phase = 0.0
    inv_sr = 1.0 / _SR
    for index in range(length):
        t = index * inv_sr
        freq = 46.0 + 92.0 * math.exp(-t * 26.0)
        phase += _TAU * freq / _SR
        env = math.exp(-t * 12.0)
        buf[offset + index] += amp * env * math.sin(phase)


def _add_hat(buf: list[float], start: float, amp: float, rng: random.Random) -> None:
    """hi-hat：高通噪声 + 极快衰减，只提供节奏的「沙」。"""

    if amp <= 0.0:
        return
    length = int(0.055 * _SR)
    offset = int(start * _SR)
    if offset < 0 or offset >= len(buf):
        return
    length = min(length, len(buf) - offset)
    previous = 0.0
    inv_sr = 1.0 / _SR
    for index in range(length):
        white = rng.uniform(-1.0, 1.0)
        high = white - previous
        previous = white
        t = index * inv_sr
        env = math.exp(-t * 70.0)
        buf[offset + index] += amp * env * high


def _add_air(buf: list[float], amount: float, rng: random.Random) -> None:
    """极轻的高频空气感：< 1% 幅度，只为去掉「数字静音」的死寂。"""

    if amount <= 0.0:
        return
    low = 0.0
    for index in range(len(buf)):
        white = rng.uniform(-1.0, 1.0)
        low = 0.995 * low + 0.005 * white
        buf[index] += amount * (white - low)


def _add_rain(buf: list[float], amount: float, rng: random.Random) -> None:
    """雨声只做背景纹理：带通噪声 + 缓慢起伏，始终低于主音色。"""

    if amount <= 0.0:
        return
    low = 0.0
    band = 0.0
    for index in range(len(buf)):
        white = rng.uniform(-1.0, 1.0)
        low = 0.99 * low + 0.01 * white
        band = 0.86 * band + 0.14 * (white - low)
        swell = 0.65 + 0.35 * math.sin(_TAU * 0.09 * index / _SR)
        buf[index] += amount * band * swell


def _apply_reverb(buf: list[float], wet: float) -> None:
    """两级反馈梳状滤波 + 一级 allpass，得到简单但自然的房间尾音。"""

    if wet <= 0.0:
        return
    length = len(buf)
    wet_signal = [0.0] * length
    for delay_ms, feedback in ((67.0, 0.40), (89.0, 0.34)):
        delay = max(1, int(_SR * delay_ms / 1000.0))
        line = [0.0] * delay
        cursor = 0
        for index in range(length):
            value = buf[index] + feedback * line[cursor]
            line[cursor] = value
            wet_signal[index] += value
            cursor += 1
            if cursor == delay:
                cursor = 0

    delay = max(1, int(_SR * 0.012))
    line = [0.0] * delay
    cursor = 0
    gain = 0.5
    for index in range(length):
        delayed = line[cursor]
        feed = wet_signal[index] * 0.5
        value = -gain * feed + delayed
        line[cursor] = feed + gain * value
        wet_signal[index] = value
        cursor += 1
        if cursor == delay:
            cursor = 0

    for index in range(length):
        buf[index] += wet * wet_signal[index]


def _crossfade_loop(samples: array.array) -> array.array:
    """把尾音交叉淡入开头，SND_LOOP 循环时不会「咔」一下。"""

    count = len(samples)
    fade_count = int(_SR * 0.42)
    if count <= fade_count * 2:
        return samples
    looped = array.array("f", samples[: count - fade_count])
    for index in range(fade_count):
        amount = index / max(1, fade_count - 1)
        looped[index] = (
            samples[index] * amount + samples[count - fade_count + index] * (1 - amount)
        )
    return looped


def _generate_ambient(method: str, seed: str) -> array.array:
    """按 ``method`` 编配并渲染一段 18 秒循环（确定性，可离线生成）。"""

    style = _STYLES.get(method) or _STYLES["keys"]
    rng = random.Random(f"{method}|{seed}")
    count = int(_SR * DURATION_SECONDS)
    buffer = [0.0] * count

    bars = max(1, int(style["bars"]))
    bar_seconds = DURATION_SECONDS / bars
    beat = bar_seconds / 4.0
    key = int(style["key"])
    progression = style["progression"]
    swing = float(style["swing"]) * beat
    humanize = float(style["humanize"])

    def when(base: float, jitter: float | None = None) -> float:
        spread = humanize if jitter is None else jitter
        return base + (rng.uniform(-spread, spread) if spread else 0.0)

    for bar in range(bars):
        chord = progression[bar % len(progression)]
        bar_start = bar * bar_seconds

        if style["pad"] > 0:
            for voice in style["pad_voices"]:
                midi = key + chord[voice % len(chord)]
                _add_tone(
                    buffer,
                    bar_start,
                    bar_seconds + float(style["pad_release"]),
                    _hz(midi),
                    float(style["pad"]),
                    style["pad_timbre"],
                    attack=float(style["pad_attack"]),
                    decay=float(style["pad_decay"]),
                    release=float(style["pad_release"]),
                )

        if style["bass"] > 0:
            for offset_beats, velocity in style["bass_beats"]:
                midi = key - 12 + chord[0]
                _add_tone(
                    buffer,
                    when(bar_start + offset_beats * beat),
                    beat * 1.6,
                    _hz(midi),
                    float(style["bass"]) * float(velocity),
                    _TIMBRE_BASS,
                    attack=0.012,
                    decay=float(style["bass_decay"]),
                    release=0.12,
                )

        if style["arp"] > 0:
            pattern = style["arp_pattern"]
            step = float(style["arp_step"])
            notes_per_bar = max(1, int(round(4.0 / step)))
            arp_octave = 12 * int(style["arp_octave"])
            for step_index in range(notes_per_bar):
                degree = pattern[step_index % len(pattern)]
                midi = key + arp_octave + chord[degree % len(chord)]
                shift = swing if (step_index % 2) else 0.0
                start = when(bar_start + step_index * step * beat + shift)
                accent = 1.0 if step_index % 4 == 0 else 0.74
                amp = float(style["arp"]) * accent * rng.uniform(0.88, 1.08)
                _add_tone(
                    buffer,
                    start,
                    float(style["arp_length"]),
                    _hz(midi),
                    amp,
                    style["arp_timbre"],
                    attack=0.008,
                    decay=float(style["arp_decay"]),
                    release=0.1,
                )
                if style["strum"]:
                    # 木吉他扫弦：只补两个和弦音，间隔 18ms，别把 CPU 扫穿。
                    root_index = degree % len(chord)
                    extras = [
                        extra
                        for extra_index, extra in enumerate(chord)
                        if extra_index != root_index
                    ][:2]
                    for order, extra in enumerate(extras, start=1):
                        _add_tone(
                            buffer,
                            start + 0.018 * order,
                            float(style["arp_length"]) * 0.85,
                            _hz(key + arp_octave - 12 + extra),
                            amp * 0.45,
                            style["arp_timbre"],
                            attack=0.01,
                            decay=float(style["arp_decay"]),
                            release=0.1,
                        )

        if style["melody"] > 0 and bar % max(1, int(style["melody_every"])) == 0:
            octave = 12 * int(style["melody_octave"])
            for offset_beats, degree, beats in style["motif"]:
                if rng.random() < 0.04:  # 偶尔留白，别像打字机
                    continue
                midi = key + octave + degree
                start = when(bar_start + offset_beats * beat)
                amp = float(style["melody"]) * rng.uniform(0.82, 1.12)
                _add_tone(
                    buffer,
                    start,
                    beats * beat + float(style["melody_tail"]),
                    _hz(midi),
                    amp,
                    style["melody_timbre"],
                    attack=0.01,
                    decay=float(style["melody_decay"]),
                    release=0.14,
                )

        if style["kick"] > 0:
            for offset_beats, velocity in style["kick_beats"]:
                _add_kick(
                    buffer,
                    when(bar_start + offset_beats * beat, 0.004),
                    float(style["kick"]) * float(velocity),
                )

        if style["hat"] > 0:
            hat_step = float(style["hat_step"])
            hat_count = max(1, int(round(4.0 / hat_step)))
            for step_index in range(hat_count):
                shift = swing if (step_index % 2) else 0.0
                start = bar_start + step_index * hat_step * beat + shift
                amp = float(style["hat"]) * (0.9 if step_index % 2 == 0 else 0.55)
                _add_hat(buffer, when(start, 0.003), amp, rng)

    _add_air(buffer, float(style["air"]), rng)
    _add_rain(buffer, float(style["rain"]), rng)
    _apply_reverb(buffer, float(style["reverb"]))

    # 去直流 + 归一化；留 0.72 峰值余量，避免 int16 转换削顶。
    mean = sum(buffer) / count
    peak = 0.0
    for value in buffer:
        peak = max(peak, abs(value - mean))
    gain = (_MAX_PEAK / peak) if peak > 0 else 0.0
    samples = array.array("f", ((value - mean) * gain for value in buffer))
    return _crossfade_loop(samples)


def write_wav(path: Path, samples: array.array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array.array(
        "h",
        (int(max(-1.0, min(1.0, sample)) * 32767) for sample in samples),
    )
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".wav", delete=False) as temporary:
        temp_path = Path(temporary.name)
    try:
        with wave.open(str(temp_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm.tobytes())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)



def peak_of(samples: array.array) -> float:
    """生成/测试共用的峰值检查。"""

    return max((abs(value) for value in samples), default=0.0)


class AmbientPlayer:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else app_data_dir() / "ambient"
        self._lock = threading.Lock()
        self._generation = 0
        self._process: subprocess.Popen[bytes] | None = None
        self.current_track_id: str | None = None
        self.playing = False

    def path_for(self, track: dict[str, Any]) -> Path:
        # 版本后缀：合成器换过，旧缓存不该再被当成新音色播放。
        return self.cache_dir / f"{track['id']}-v2.wav"

    def ensure_track(self, track: dict[str, Any]) -> Path:
        path = self.path_for(track)
        if path.exists() and path.stat().st_size > 100_000:
            return path
        samples = _generate_ambient(str(track["method"]), str(track["id"]))
        write_wav(path, samples)
        return path

    def play_async(
        self,
        track: dict[str, Any],
        on_ready: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        track_id = str(track["id"])
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._stop_locked()
            self.current_track_id = track_id

        def worker() -> None:
            try:
                path = self.ensure_track(track)
                with self._lock:
                    if generation != self._generation:
                        return
                    self._start_playback(path)
                    self.playing = True
            except Exception as exc:
                with self._lock:
                    if generation != self._generation:
                        return
                    self._stop_locked()
                if on_error:
                    on_error(str(exc))
                return
            if on_ready:
                on_ready(track_id)

        threading.Thread(target=worker, daemon=True).start()

    def _start_playback(self, path: Path) -> None:
        system = platform.system()
        if system == "Windows":
            import winsound

            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
            return
        if system == "Darwin":
            self._process = subprocess.Popen(["afplay", str(path)])
            return
        self._process = subprocess.Popen(["aplay", "-q", str(path)])

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self._stop_locked()

    def _stop_locked(self) -> None:
        if platform.system() == "Windows":
            try:
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        if self._process is not None:
            try:
                self._process.terminate()
            except OSError:
                pass
            self._process = None
        self.playing = False
        self.current_track_id = None
