"""Merge every ``qixin/data/quotes_*.jsonl`` batch into ``qixin/quotes.py``.

The generated module keeps the hand-written helper functions and re-shuffles the
pool with a fixed seed, so the reading order never restarts from the same line
while staying reproducible between runs.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
DATA = APP / "qixin" / "data"
TARGET = APP / "qixin" / "quotes.py"

REQUIRED = ("id", "text", "source", "concept", "explanation", "tags")
PUNCT = re.compile(r"[\s，。！？；：、“”‘’《》〈〉（）()「」『』—…·,.!?;:\"'\-]+")

HEADER = '''"""典藏语句数据：中外诗句、哲思与西方哲学解读。

数据与读取逻辑分离；本文件由 ``tools/build_quotes.py`` 从
``qixin/data/quotes_*.jsonl`` 生成，运行时不联网。
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any


QUOTES: list[dict[str, Any]] = [
'''

FOOTER = '''
# 固定种子打乱，避免总从同一句开始，同时保证每次运行顺序一致。
random.Random(20261111).shuffle(QUOTES)


def quote_for_day(day: date | None = None) -> dict[str, Any]:
    day = day or date.today()
    return QUOTES[day.toordinal() % len(QUOTES)]


def quote_at(index: int) -> dict[str, Any]:
    return QUOTES[index % len(QUOTES)]


def quote_index(quote: dict[str, Any]) -> int:
    return next((i for i, item in enumerate(QUOTES) if item["id"] == quote["id"]), 0)
'''


def normalize(text: str) -> str:
    return PUNCT.sub("", text).strip().lower()


def main() -> int:
    files = sorted(DATA.glob("quotes_*.jsonl"))
    if not files:
        print("no batch files found")
        return 1
    seen_text: set[str] = set()
    seen_id: set[str] = set()
    rows: list[dict[str, Any]] = []
    skipped = 0
    for path in files:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[warn] {path.name}:{line_number} bad json: {exc}")
                skipped += 1
                continue
            if any(not str(item.get(key, "")).strip() for key in REQUIRED):
                print(f"[warn] {path.name}:{line_number} missing field")
                skipped += 1
                continue
            key = normalize(str(item["text"]))
            if key in seen_text:
                skipped += 1
                continue
            identifier = str(item["id"]).strip()
            if identifier in seen_id:
                suffix = 2
                while f"{identifier}-{suffix}" in seen_id:
                    suffix += 1
                identifier = f"{identifier}-{suffix}"
            seen_text.add(key)
            seen_id.add(identifier)
            tags = [str(tag).strip() for tag in item["tags"] if str(tag).strip()]
            rows.append(
                {
                    "id": identifier,
                    "text": str(item["text"]).strip(),
                    "source": str(item["source"]).strip(),
                    "concept": str(item["concept"]).strip(),
                    "explanation": str(item["explanation"]).strip(),
                    "western": str(item.get("western", "")).strip(),
                    "tags": tags[:5],
                }
            )

    body = []
    for row in rows:
        body.append("    " + json.dumps(row, ensure_ascii=False) + ",\n")
    text = HEADER + "".join(body) + "]" + FOOTER
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"merged {len(files)} files → {len(rows)} quotes "
        f"(skipped {skipped}); with western: {sum(1 for r in rows if r['western'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
