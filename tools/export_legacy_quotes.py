"""把现有典藏导出成 JSONL，并补齐「西方视角」解读。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from qixin.quotes import QUOTES  # noqa: E402

WESTERN = {
    "wang-mian-plum": "斯宾诺莎说，荣誉与恐惧都依赖他人的眼光；把评价权收回自己，才谈得上自由。",
    "wang-wan-sunrise": "赫拉克利特强调流变：新的一天不是旧日的延续，而是在旧日里就已经开始。",
    "thoreau-deliberate": "梭罗与爱默生都相信，生活需要被有意识地选择；不选择，也是默认了别人替你选。",
    "mencius-mind": "笛卡尔以「我思」为起点；孟子更早把「思」看作心自身的能力，而非外来的恩赐。",
    "liu-yuxi-new-trees": "尼采的「生成」拒绝把失败当作终局；病树旁边，春天照样按自己的节律发生。",
    "zhuangzi-finite-life": "海德格尔把「有限」看作意义的条件：正因为会结束，选择才有重量。",
    "epictetus-first-principle": "亚里士多德认为德性来自习惯；爱比克泰德补上一句：先定方向，习惯才不至于空转。",
    "plato-good-life": "苏格拉底在《克里同篇》里宁可受罚也不逃走：活得好，优先于仅仅活着。",
    "socrates-know-yourself": "福柯把「认识自己」读成一种实践：不是发现一个固定的我，而是持续地照看自己。",
    "rilke-future": "柏格森说时间是创造性的绵延；未来不是等待发生的日程，而是正在改写你的力量。",
    "zhongyong-learning": "杜威的「做中学」与「笃行」同调：知识若停在概念里，就没有真正完成。",
    "tagore-stars": "斯多葛提醒人区分可控与不可控：太阳已经落下，星星仍在你能抬头的地方。",
    "heraclitus-river": "赫拉克利特的流变论是西方过程思想的源头；同一性在时间中始终是个近似值。",
    "qu-yuan-long-way": "加缪笔下的西西弗明知徒劳仍推石上山；求索的价值不在终点，而在拒绝停下。",
    "su-shi-orange-season": "尼采的「 Amor fati 」：不是忍受季节，而是在橙黄橘绿里认出此刻的成熟。",
    "heraclitus-character": "亚里士多德说德性是习惯的产物；赫拉克利特更早把性格与命运系在同一根绳上。",
    "pascal-reed": "帕斯卡在《思想录》里把人的伟大放在思想：脆弱与尊严，是同一件事的两面。",
    "nietzsche-why": "尼采追问的不是「怎样活」，而是「为何活」；有了理由，承受才有形状。",
    "camus-summer": "加缪在《西西弗神话》里拒绝自杀与希望两端；不可战胜的夏天，是对荒诞的温柔反抗。",
    "montaigne-what-know": "蒙田的怀疑不是虚无，而是苏格拉底式的自知无知：先承认边界，才可能不狂妄。",
    "socrates-examined": "苏格拉底把哲学生活当作每日的自我盘问；未经审视，等于把人生交给了默认设置。",
    "zhuangzi-white-horse": "塞涅卡谈生命的长度不在年岁而在使用；白驹过隙，是提醒而非恐吓。",
    "laozi-first-step": "亚里士多德认为行动先于德性；千里之行，是把「成为」拆成今天这一步。",
    "xunzi-steps": "休谟说习惯是人生最大的向导；跬步之所以有效，是因为它把意志变成了惯性。",
    "rilke-questions": "克尔凯郭尔主张在不确定中决断；里尔克更缓一些：先与问题同住，别急着要答案。",
    "laozi-small": "维特根斯坦说解决之道常在于把大问题拆成可处理的小问题；细节是入口，不是琐碎。",
    "su-shi-no-weather": "斯多葛的「无动于衷」并非麻木，而是风雨过后不再额外给自己加戏。",
    "analects-harmony": "罗尔斯的「理性多元」与「和而不同」相通：分歧不必被消除，只需被妥善安放。",
    "su-shi-mountain": "胡塞尔的现象学要求「回到事情本身」；走出山里，是为了看见自己一直带着的视角。",
    "gong-zizhen-fallen-flower": "黑格尔的「扬弃」：结束不是消失，而是被保存进下一个阶段。",
    "bai-juyi-warm-wine": "亚里士多德把友谊看作德性生活的必需品；一杯酒，是把关系从日程里捞出来。",
    "laozi-water": "斯多葛的「顺应自然」与水的智慧相邻：不与世界硬碰，才留得住自己的力量。",
    "analects-learn-think": "康德区分感性与知性；只学不思是材料堆积，只思不学是空中楼阁。",
    "su-shi-young-again": "尼采的「永恒轮回」逼问：若人生再来一次，你是否愿意？苏轼答得更轻：水还能向西。",
    "lu-you-practice": "杜威的实用主义与「躬行」一致：真理要在做里被检验，而不只是在说里被相信。",
    "marcus-obstacle": "马可·奥勒留把障碍纳入德性的练习；斯多葛的训练，是把阻力转成材料。",
    "su-shi-home": "海德格尔说「栖居」不是地址，而是与世界相处的方式；心安处，才是可居之处。",
    "su-shi-light-joy": "伊壁鸠鲁的快乐是清淡的：不追刺激，只求不被多余的欲望打扰。",
    "tao-chrysanthemum": "海德格尔引用荷尔德林谈「栖居」；采菊与见山，是同一件事的两面——在场。",
    "du-fu-summit": "尼采的「远视」需要攀登；视野不是天赋，而是走到更高处换来的。",
    "tao-yuanming-morning": "塞涅卡说我们并非时间太少，而是浪费太多；「难再晨」是对注意力的提醒。",
    "epictetus-control": "爱比克泰德的控制二分法是斯多葛的入口；把力气放在自己能做的那一栏。",
    "zhuangzi-fish": "维特根斯坦说「我的语言的界限即世界的界限」；你不是鱼，正因你有一套自己的语法。",
    "xin-qiji-green-hills": "斯宾诺莎的必然性：青山遮不住东流，不是因为乐观，而是因为规律不因情绪改道。",
    "analects-winter-pine": "亚里士多德认为德性在困境中才显形；岁寒，是一场不设预告的考试。",
    "zhuangzi-summer-insect": "康德区分经验的条件与经验的边界；夏虫的局限，是它从未拥有过另一种经验。",
    "wang-wei-clouds": "海德格尔的「泰然任之」：不强求结果，让事物按其本己的方式出现。",
    "aristotle-happiness": "亚里士多德把幸福看作「合乎德性的实现活动」；它不是状态，而是持续做的事。",
    "wang-yangming-unity": "杜威反对知与行的割裂；王阳明更彻底：知而不行，只是未知。",
    "tao-yuanming-waves": "斯多葛的「顺应自然」与「不喜亦不惧」同调：情绪不必被消灭，只需不再主宰。",
    "kierkegaard-backward": "克尔凯郭尔说「生活只能倒着理解，却必须正着过」；这句话本身就是他的方法论。",
    "wang-bo-ambition": "尼采的「权力意志」不是压倒他人，而是在逆境中仍能自我提升。",
    "lu-you-path": "库恩的范式转换：不是路消失了，而是你换了一个看路的框架。",
    "laozi-contentment": "伊壁鸠鲁把知足视为最大的财富；边界清楚，欲望才不至于无限膨胀。",
    "heidegger-poetic": "海德格尔借荷尔德林说，人应当「诗意地栖居」；诗意不是装饰，而是与世界相处的尺度。",
    "mencius-cultivate": "亚里士多德区分实践与制作：穷达不同，做人的尺度却可以一致。",
    "analects-self-reliance": "斯多葛把注意力收回自身；求诸己，是唯一不会落空的方向。",
    "su-shi-rain": "爱比克泰德说困扰人的是判断而非事情；雨声照旧，脚步可以自己定。",
    "wang-bo-friend": "亚里士多德把友谊分为三类；真正的朋友，是即便远隔也能共享同一种善。",
    "wang-anshi-high-view": "培根说知识即力量；站得高不是傲慢，而是减少被浮云误导的概率。",
    "montaigne-life": "蒙田的随笔就是「属于自己」的练习；不表演，不辩解，只如实地写。",
    "su-shi-traveler": "海德格尔的「在世存在」本就是一种旅途；旅人视角，让得失都轻一点。",
    "bai-juyi-temple-flower": "莱布尼茨的「前定和谐」各有节律；山寺的桃花，只是还没到它的四月。",
    "analects-knowing": "苏格拉底的自知无知与「知之为知之」同源：诚实是知识的起点。",
    "zhang-jiuling-orchid": "康德的无利害关怀：美不依赖被观看，草木的价值也不靠折取来证明。",
    "zhu-xi-spring-water": "杜威说经验需要不断更新；源头活水，是给心智留一条输入的通道。",
    "liu-yuxi-autumn": "尼采说视角决定世界的样子；晴空一鹤，是心情先把天推高了。",
    "du-fu-rain": "培根谈「润物无声」式的影响；真正改变人的，往往是不被察觉的日常。",
    "kierkegaard-anxiety": "克尔凯郭尔把焦虑看作「自由的眩晕」；它提醒你，可能性正在你面前打开。",
    "pascal-heart": "帕斯卡区分「几何精神」与「细腻精神」；有些真，只能被感受而不能被证明。",
    "great-learning-still": "斯多葛的「专注当下」与「知止」相通：先划定边界，安静才有落点。",
    "li-bai-wind": "斯宾诺莎的必然与自由并不矛盾；承认风浪，才谈得上挂帆。",
    "laozi-fortune": "黑格尔的辩证法：祸福互为条件，否定性本身推动着下一步。",
    "zhongyong-balance": "亚里士多德的中道不是折中，而是恰如其分；张弛之间，是分寸感。",
    "zheng-xie-bamboo": "斯多葛的「韧性」来自判断的稳定；风从四面来，根却不必移动。",
    "spinoza-understand": "斯宾诺莎的这句本身就是方法论：理解先于评判，情绪才有被安放的位置。",
    "zhouyi-self-strength": "尼采的「自我超越」与「自强不息」相通；不是胜过别人，而是不断越过旧的自己。",
    "yang-wanli-lotus": "杜威看重「萌芽状态」的经验；尖尖角之所以重要，是因为它指向尚未展开的可能。",
    "liu-yuxi-sunset": "塞涅卡说生命的价值不在长度；桑榆虽晚，霞光仍可满天。",
    "seneca-life-length": "塞涅卡在《论生命之短暂》里说，我们并非时间太少，而是把时间花在了不属于自己的事上。",
}


def main() -> None:
    rows = []
    missing = []
    for quote in QUOTES:
        western = WESTERN.get(quote["id"], "").strip()
        if not western:
            missing.append(quote["id"])
        rows.append(
            {
                "id": quote["id"],
                "text": quote["text"],
                "source": quote["source"],
                "concept": quote["concept"],
                "explanation": quote["explanation"],
                "western": western,
                "tags": list(quote.get("tags", [])),
            }
        )
    target = APP / "qixin" / "data" / "quotes_legacy.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} legacy rows; missing western: {len(missing)} {missing[:5]}")


if __name__ == "__main__":
    main()
