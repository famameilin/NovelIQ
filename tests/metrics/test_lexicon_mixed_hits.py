"""
phrase 模式匹配测试

修改时间: 2026-04-06
修改者: GLM-5
任务: 移除向后兼容代码
修改内容: 移除对 count_token_hits 的引用，仅使用 count_mixed_hits
"""
from src.metrics.lexicon_metrics import count_mixed_hits


def test_mixed_hits_detects_phrase_substring_when_token_miss() -> None:
    text = "青衫剑客踏月而来"
    tokens = ["青衫", "剑客", "踏月", "而来"]

    assert count_mixed_hits(text, tokens, ["青衫剑客"]) == 1


def test_mixed_hits_detects_multi_word_phrase() -> None:
    text = "the golden core remains stable"
    tokens = ["the", "golden", "core", "remains", "stable"]

    assert count_mixed_hits(text, tokens, ["golden core"]) == 1


def test_mixed_hits_prefers_longest_non_overlapping_phrase_matches() -> None:
    text = "渡劫飞升"
    tokens = ["渡劫飞升"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "渡劫飞升"])

    assert hits == 1


def test_mixed_hits_counts_each_non_overlapping_span_once() -> None:
    text = "渡劫飞升渡劫"
    tokens = ["渡劫飞升", "渡劫"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "渡劫飞升"])

    assert hits == 2


def test_mixed_hits_deduplicates_phrase_and_component_token_matches() -> None:
    text = "渡劫飞升"
    tokens = ["渡劫", "飞升"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "飞升", "渡劫飞升"])

    assert hits == 1
