"""中文数字转换单元测试"""

from __future__ import annotations

import pytest

from src.chapters.cn2int import chinese_to_int, extract_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一", 1),
        ("二", 2),
        ("两", 2),
        ("三", 3),
        ("九", 9),
        ("十", 10),
        ("十一", 11),
        ("二十", 20),
        ("二十一", 21),
        ("一百", 100),
        ("一百零一", 101),
        ("一百二十三", 123),
        ("一千零一", 1001),
        ("一万零一", 10001),
        ("零", 0),
        ("〇", 0),
        ("○", 0),
        ("二百五十", 250),
        ("十二", 12),
        # 万 组合与独立出现
        ("万", 10000),
        ("十万", 100000),
        ("两万", 20000),
        ("二十万", 200000),
        ("十二万三千", 123000),
        ("一万二千五", 12500),
        # 〇/○ 复合位：零 之后的末位数字按显式个位处理
        ("一百〇五", 105),
        ("一百○一", 101),
        ("一千〇二", 1002),
        ("一万〇一", 10001),
        ("一万零五", 10005),
        # 零位链：〇 占位抬升左侧数字位权（一〇八 = 108）
        ("一〇八", 108),
        ("一〇〇八", 1008),
        ("一〇二三", 1023),
        ("二〇二四", 2024),
        ("二〇二三", 2023),
        ("一千〇二三", 1023),
        ("一千〇十", 1010),
        ("三百〇五", 305),
        ("〇五", 5),
        # 隐含十位/百位/千位（口语省略）
        ("二百五", 250),
        ("三百六", 360),
        ("一千二", 1200),
        ("一万二", 12000),
        ("三百零五", 305),
        # 2026-08-13 P1 修复：万 前的零位链低位块不再丢失
        ("一百零五万", 1050000),
        ("一〇八万", 1080000),
        ("一〇〇八万", 10080000),
        ("一千零一万", 10010000),
        ("三百二十一万四千五百六十七", 3214567),
        # 2026-08-13 新增「亿」级单位支持
        ("一亿", 100000000),
        ("一亿零五万", 100050000),
        ("一万亿", 1000000000000),
        ("一万万", 100000000),
        ("二十亿零三万", 2000030000),
    ],
)
def test_chinese_to_int(text: str, expected: int) -> None:
    assert chinese_to_int(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "abc", "一a二", "三章", "第章", "abc一"],
)
def test_chinese_to_int_invalid(text: str) -> None:
    assert chinese_to_int(text) is None


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("第一章", 1),
        ("第12章", 12),
        ("第0章", 0),
        ("第一百二十三章", 123),
        ("卷一", 1),
        ("第三部", 3),
        ("Chapter 12", 12),
        ("Unit 5", 5),
        ("Part 2", 2),
        ("Volume 3", 3),
        ("第一章之番外", 1),
    ],
)
def test_extract_number(label: str, expected: int) -> None:
    assert extract_number(label) == expected


def test_extract_number_no_number() -> None:
    assert extract_number("番外") is None
    assert extract_number("序言") is None
