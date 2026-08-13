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
_UNITS: dict[str, int] = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}

_CN_NUMERAL_CHARS: set[str] = set(_DIGITS) | set(_UNITS)
_NUM_SEQ_RE = re.compile(r"[零一二三四五六七八九十百千万两〇○\d]+")


def _block_value(block: list[int]) -> int:
    """把零位链低位块转成数值（〇/零 只占位）：[0, 5] → 5、[0, 0, 8] → 8"""
    value = 0
    for digit in block:
        value = value * 10 + digit
    return value


def chinese_to_int(text: str) -> int | None:
    """将中文数字转换为整数；包含非数字字符或无法解析时返回 None"""
    if not text or not all(ch in _CN_NUMERAL_CHARS for ch in text):
        return None

    total = 0
    section = 0
    number = 0
    number_scale = 1
    block: list[int] = []
    last_unit = 1
    for ch in text:
        if ch in _DIGITS:
            digit = _DIGITS[ch]
            if digit == 0:
                # 2026-08-13 P1-4 零位链修复：零/〇/○ 是占位符而非可覆盖数字，
                # 落入低位块并抬高左侧悬空数字的位权（一〇八 = 1×100 + 8）
                block.append(0)
                number_scale *= 10
                continue
            if block:
                # 零链后的数字：留在低位块中（〇二三 → 23，块长决定左侧位权）
                block.append(digit)
                number_scale *= 10
                continue
            number = digit
        else:
            unit = _UNITS[ch]
            if unit >= 10000:
                # 2026-08-13 P1 修复：万/亿分支此前只取 (section + number)，
                # 丢弃了零位链低位块（一百零五万 → 1,000,000 应为 1,050,000）
                # 也未用 number_scale 抬高悬空数字（一〇八万 → 10,000 应为 1,080,000）。
                # 级单位按 last_unit 区分三种语义：
                #   更高一级单位后出现（亿…万）：低位组独立落账（一亿零五万 = 1亿 + 5万）
                #   同级连用（万万 = 亿）：叠加放大
                #   常规（万/亿 前无级单位）：当前组 × 级单位
                block_value = _block_value(block) if block else 0
                scaled_number = number * number_scale if number_scale > 1 else number
                if last_unit > unit:
                    # 更高一级单位后出现万/亿（一亿零五万）：先把高一级 section 落账，
                    # 低位组只由块/数字构成（不含已落账的 section，否则会重复放大）
                    total += section
                    low_base = block_value + scaled_number
                    section = (low_base if low_base else 1) * unit
                elif last_unit == unit:
                    # 同级级单位连用（万万 = 亿）：叠加放大
                    section = (section if section else 1) * unit
                else:
                    # 常规：当前组（section + 低位块 + 缩放数字）× 级单位
                    base = section + block_value + scaled_number
                    section = (base if base else 1) * unit
                number = 0
                number_scale = 1
                block = []
                last_unit = unit
            elif block:
                # 低位块遇单位：块值 × 单位（零占位自动落位，如 一千零十 = 1010）
                block_value = _block_value(block)
                section += (block_value if block_value else 1) * unit
                block = []
                last_unit = unit
            else:
                section += (number if number else 1) * unit
                number = 0
                last_unit = unit
    if block:
        section += _block_value(block)
    if number:
        if number_scale > 1:
            # 零位链把悬空数字抬到对应位（一〇八 → 1×100）
            section += number * number_scale
        elif last_unit > 10:
            # 隐含十位/百位/千位：二百五 = 250、一千二 = 1200、一万二 = 12000
            section += number * (last_unit // 10)
        else:
            section += number
    return total + section


def extract_number(label: str) -> int | None:
    """从标题标签（如「第一章」「卷一」「Chapter 12」）中提取编号"""
    for part in _NUM_SEQ_RE.findall(label):
        if part.isdigit():
            return int(part)
        converted = chinese_to_int(part)
        if converted is not None:
            return converted
    return None
