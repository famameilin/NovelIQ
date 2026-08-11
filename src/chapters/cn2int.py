"""中文数字转阿拉伯数字（章节编号提取与连续性评分用）"""

from __future__ import annotations

import re

_DIGITS: dict[str, int] = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_UNITS: dict[str, int] = {"十": 10, "百": 100, "千": 1000, "万": 10000}

_CN_NUMERAL_CHARS: set[str] = set(_DIGITS) | set(_UNITS)
_NUM_SEQ_RE = re.compile(r"[零一二三四五六七八九十百千万两〇○\d]+")


def chinese_to_int(text: str) -> int | None:
    """将中文数字转换为整数；包含非数字字符或无法解析时返回 None"""
    if not text or not all(ch in _CN_NUMERAL_CHARS for ch in text):
        return None

    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _DIGITS:
            number = _DIGITS[ch]
        else:
            unit = _UNITS[ch]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
                number = 0
            else:
                section += (number if number else 1) * unit
                number = 0
    return total + section + number


def extract_number(label: str) -> int | None:
    """从标题标签（如「第一章」「卷一」「Chapter 12」）中提取编号"""
    for part in _NUM_SEQ_RE.findall(label):
        if part.isdigit():
            return int(part)
        converted = chinese_to_int(part)
        if converted is not None:
            return converted
    return None
