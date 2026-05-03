"""
lexicon_density 边界测试

修改时间: 2026-04-06
任务: 移除向后兼容代码
修改内容: 更新测试以适配新的 lexicon_density 签名（需要 text 参数）
"""

from src.metrics.style_metrics import lexicon_density


def test_mixed_lexicon_density_is_capped_at_one() -> None:
    text = "天地玄黄"
    tokens = ["天地玄黄"]
    terms = ["天地", "玄黄"]

    density = lexicon_density(tokens, terms, text=text)

    assert density == 1.0


def test_token_lexicon_density_is_capped_at_one() -> None:
    text = "甲"
    tokens = ["甲"]
    terms = ["甲", "乙"]

    density = lexicon_density(tokens, terms, text=text)

    assert density == 1.0
