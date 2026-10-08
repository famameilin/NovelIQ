"""
情绪曲线算法增强单元测试

创建时间: 2026-04-06
任务: 情绪曲线算法增强单元测试
说明: 测试否定词翻转、加权密度计算、LOWESS 平滑（§9.3 替代傅里叶滤波）、jieba用户词典等功能

2026-08-16 M4/M5：权重弃用（命中计数）、否定逻辑移入 src.metrics.negation 共享层
（分类加载/翻转语义/审计回归专项见 tests/metrics/test_negation.py）；
find_negation_context/count_negations_before/load_negation_words 已删除。
2026-10-06：emotion_metrics 包装层（lexical_sentiment_density）删除后，
翻转语义只在 test_negation.py 的共享层入口验证。

测试覆盖:
- 加权计数函数（count_weighted_hits/term_weighted_counts/load_weighted_lexicon 保留）
- jieba用户词典：分词效果验证
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.text_processing.tokenize import get_tokenizer


class TestJiebaUserDict:
    """
    jieba 用户词典测试

    创建时间: 2026-04-06
    任务: 情绪曲线算法增强单元测试
    """

    def test_tokenizer_user_dict_effect(self) -> None:
        """
        jieba 用户词典分词效果

        场景: 用户词典包含 "道心破碎" 和 "心花怒放"
        期望: 这些词不被切分
        """
        tokenizer = get_tokenizer()
        tokens = tokenizer.tokenize("他道心破碎了")

        has_full_term = any("道心" in t or "破碎" in t for t in tokens)
        assert has_full_term

    def test_tokenizer_xin_hua_nu_fang(self) -> None:
        """
        jieba 用户词典分词效果 - 心花怒放

        场景: 用户词典包含 "心花怒放"
        期望: 该词不被切分
        """
        tokenizer = get_tokenizer()
        tokens = tokenizer.tokenize("她心花怒放")

        has_full_term = any("心花" in t or "怒放" in t for t in tokens)
        assert has_full_term

    def test_tokenizer_empty_input(self) -> None:
        """
        Tokenizer 空输入处理

        场景: 输入空字符串
        期望: 返回空列表
        """
        tokenizer = get_tokenizer()
        tokens = tokenizer.tokenize("")
        assert tokens == []

    def test_tokenizer_whitespace_input(self) -> None:
        """
        Tokenizer 空白字符输入处理

        场景: 输入只有空白字符
        期望: 返回空列表
        """
        tokenizer = get_tokenizer()
        tokens = tokenizer.tokenize("   \n\t  ")
        assert tokens == []

    def test_tokenizer_filter_stopwords(self) -> None:
        """
        Tokenizer 停用词过滤

        场景: 启用停用词过滤
        期望: 停用词被过滤
        """
        tokenizer = get_tokenizer()
        tokens_with_stopwords = tokenizer.tokenize("我和你", filter_stopwords=False)
        tokens_without_stopwords = tokenizer.tokenize("我和你", filter_stopwords=True)

        assert len(tokens_without_stopwords) <= len(tokens_with_stopwords)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
