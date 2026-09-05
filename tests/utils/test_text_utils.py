"""2026-09-04 用于验证通配符词项匹配谓词与 SQL LIKE 口径一致"""

from src.utils.text_utils import like_pattern, term_matches


def test_term_matches_plain_substring_case_insensitive() -> None:
    """2026-09-04 用于验证无通配符词项等价于大小写不敏感子串包含"""
    assert term_matches("顾霜", "顾霜持剑现身")
    assert term_matches("sword", "顾霜持 Sword 现身")
    assert not term_matches("顾霜", "伯安进入山门")


def test_term_matches_percent_wildcard() -> None:
    """2026-09-04 用于验证 % 匹配任意长度（含零长度）"""
    assert term_matches("偷%鸡", "伯安提议偷赤羽炽尾鸡")
    assert term_matches("偷%", "伯安提议偷灵兽")
    assert term_matches("%密谋%", "伯安与发小在假山密谋偷灵兽")
    assert not term_matches("偷%鸡", "伯安与发小在假山密谋")


def test_term_matches_underscore_wildcard() -> None:
    """2026-09-04 用于验证 _ 恰好匹配单个字符"""
    assert term_matches("赤羽_尾鸡", "赤羽炽尾鸡")
    assert not term_matches("赤羽_尾鸡", "赤羽炽炽尾鸡")
    assert not term_matches("赤羽_尾鸡", "赤羽尾鸡")


def test_term_matches_empty_term_never_hits() -> None:
    """2026-09-04 用于验证空词项不产生全表命中"""
    assert not term_matches("", "任意文本")


def test_like_pattern_wraps_term_with_substring_wildcards() -> None:
    """2026-09-04 用于验证词项被包成子串 LIKE 模式且内部通配符原样保留"""
    assert like_pattern("伯安") == "%伯安%"
    assert like_pattern("偷%") == "%偷%%"
