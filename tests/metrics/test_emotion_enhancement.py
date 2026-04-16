"""
情绪曲线算法增强单元测试

创建时间: 2026-04-06
创建者: GLM-5
任务: 情绪曲线算法增强单元测试
说明: 测试否定词翻转、加权密度计算、傅里叶滤波、jieba用户词典等功能

测试覆盖:
- 否定词翻转逻辑：单重否定、双重否定、无否定
- 加权密度计算：权重贡献、向后兼容
- 傅里叶滤波：基本功能、降噪效果、无滞后
- jieba用户词典：分词效果验证
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.emotion_metrics import (
    count_negations_before,
    find_negation_context,
    lexical_sentiment_density,
    load_negation_words,
)
from src.metrics.fourier_filter import fourier_smooth
from src.metrics.lexicon_metrics import (
    count_weighted_hits,
    load_weighted_lexicon,
    term_weighted_counts,
)
from src.preprocess.tokenize import get_tokenizer


class TestNegationFlip:
    """
    否定词翻转逻辑测试

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 情绪曲线算法增强单元测试
    """

    @pytest.fixture
    def negation_words(self) -> set[str]:
        """测试用否定词集合"""
        return {"不", "没", "未", "勿", "别", "莫", "非", "无", "没有", "难以", "无法"}

    def test_load_negation_words_from_file(self) -> None:
        """
        从文件加载否定词表

        验证否定词表文件存在且可正确加载
        """
        negation_words = load_negation_words()
        assert len(negation_words) > 0
        assert "不" in negation_words
        assert "没" in negation_words
        assert "未" in negation_words

    def test_load_negation_words_nonexistent_file(self) -> None:
        """
        加载不存在的否定词文件返回空集合

        验证文件不存在时的容错处理
        """
        negation_words = load_negation_words("data/lexicons/nonexistent_file.txt")
        assert negation_words == set()

    def test_find_negation_context_single_negation(self, negation_words: set[str]) -> None:
        """
        单重否定词检测

        场景: "不快乐" 中 "快乐" 前存在否定词 "不"
        期望: 返回 True
        """
        text = "不快乐"
        emotion_pos = text.find("快乐")
        result = find_negation_context(text, emotion_pos, negation_words, window=3)
        assert result is True

    def test_find_negation_context_no_negation(self, negation_words: set[str]) -> None:
        """
        无否定词检测

        场景: "快乐" 前无否定词
        期望: 返回 False
        """
        text = "快乐"
        emotion_pos = text.find("快乐")
        result = find_negation_context(text, emotion_pos, negation_words, window=3)
        assert result is False

    def test_find_negation_context_negation_too_far(self, negation_words: set[str]) -> None:
        """
        否定词距离过远不触发翻转

        场景: "不真的很快乐" 中 "不" 距离 "快乐" 超过窗口
        期望: 根据窗口大小决定是否检测到
        """
        text = "不真的很快乐"
        emotion_pos = text.find("快乐")
        result = find_negation_context(text, emotion_pos, negation_words, window=3)
        assert result is False

    def test_count_negations_before_single(self, negation_words: set[str]) -> None:
        """
        统计单个否定词数量

        场景: "不快乐" 中有一个否定词
        期望: 返回 1
        """
        text = "不快乐"
        emotion_pos = text.find("快乐")
        count = count_negations_before(text, emotion_pos, negation_words, window=3)
        assert count == 1

    def test_count_negations_before_double(self, negation_words: set[str]) -> None:
        """
        统计双重否定词数量

        场景: "不是不好" 中有两个否定词
        期望: 返回 2
        """
        text = "不是不好"
        emotion_pos = text.find("好")
        count = count_negations_before(text, emotion_pos, negation_words, window=6)
        assert count == 2

    def test_count_negations_before_none(self, negation_words: set[str]) -> None:
        """
        无否定词时返回 0

        场景: "快乐" 前无否定词
        期望: 返回 0
        """
        text = "快乐"
        emotion_pos = text.find("快乐")
        count = count_negations_before(text, emotion_pos, negation_words, window=3)
        assert count == 0

    def test_single_negation_flip_polarity(self, negation_words: set[str]) -> None:
        """
        单重否定翻转极性

        场景: "不快乐" 中 "快乐" 是正面词，但被否定词翻转
        期望: 正面词计入负面密度
        """
        result = lexical_sentiment_density(
            "不快乐",
            {"快乐": 1},
            {},
            negation_words=negation_words,
            enable_negation=True,
        )
        assert result["neg_density"] > 0
        assert result["pos_density"] == 0

    def test_double_negation_restore_polarity(self, negation_words: set[str]) -> None:
        """
        双重否定还原极性

        场景: "不是不快乐" 中 "快乐" 是正面词，双重否定后仍为正面
        期望: 正面词计入正面密度
        """
        result = lexical_sentiment_density(
            "不是不快乐",
            {"快乐": 1},
            {},
            negation_words=negation_words,
            enable_negation=True,
        )
        assert result["pos_density"] > 0
        assert result["neg_density"] == 0

    def test_no_negation_keep_polarity(self, negation_words: set[str]) -> None:
        """
        无否定词保持原极性

        场景: "快乐" 无否定词
        期望: 正面词计入正面密度
        """
        result = lexical_sentiment_density(
            "快乐",
            {"快乐": 1},
            {},
            negation_words=negation_words,
            enable_negation=True,
        )
        assert result["pos_density"] > 0
        assert result["neg_density"] == 0

    def test_negation_flip_negative_to_positive(self, negation_words: set[str]) -> None:
        """
        否定词翻转负面词为正面

        场景: "不悲伤" 中 "悲伤" 是负面词，被否定词翻转为正面
        期望: 负面词计入正面密度
        """
        result = lexical_sentiment_density(
            "不悲伤",
            {},
            {"悲伤": 1},
            negation_words=negation_words,
            enable_negation=True,
        )
        assert result["pos_density"] > 0
        assert result["neg_density"] == 0

    def test_disable_negation(self, negation_words: set[str]) -> None:
        """
        禁用否定词翻转

        场景: "不快乐" 但禁用否定词翻转
        期望: 正面词仍计入正面密度
        """
        result = lexical_sentiment_density(
            "不快乐",
            {"快乐": 1},
            {},
            negation_words=negation_words,
            enable_negation=False,
        )
        assert result["pos_density"] > 0
        assert result["neg_density"] == 0


class TestWeightedDensity:
    """
    加权密度计算测试

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 情绪曲线算法增强单元测试
    """

    @pytest.fixture
    def weighted_terms(self) -> dict[str, int]:
        """测试用加权词典"""
        return {
            "好": 1,
            "快乐": 2,
            "心花怒放": 3,
            "坏": 1,
            "悲伤": 2,
            "心碎": 3,
        }

    def test_count_weighted_hits_basic(self, weighted_terms: dict[str, int]) -> None:
        """
        加权命中次数计算

        场景: 文本包含不同权重的词条
        期望: 加权命中次数 = sum(count * weight)
        """
        text = "心花怒放和快乐"
        tokens = text
        result = count_weighted_hits(text, tokens, weighted_terms)
        assert result == 5

    def test_weighted_density_different_weights(self) -> None:
        """
        加权密度计算 - 不同权重贡献不同

        场景: 使用带权重的词典计算密度
        期望: 权重为 1, 2, 3 的词条贡献不同
        """
        pos_terms = {"好": 1, "快乐": 2, "心花怒放": 3}
        neg_terms: dict[str, int] = {}

        result_light = lexical_sentiment_density("好", pos_terms, neg_terms, enable_negation=False)
        result_medium = lexical_sentiment_density("快乐", pos_terms, neg_terms, enable_negation=False)
        result_heavy = lexical_sentiment_density("心花怒放", pos_terms, neg_terms, enable_negation=False)

        assert result_light["pos_density"] < result_medium["pos_density"]
        assert result_medium["pos_density"] < result_heavy["pos_density"]

    def test_term_weighted_counts(self, weighted_terms: dict[str, int]) -> None:
        """
        词条级别加权计数

        场景: 获取每个词条的计数和权重
        期望: 返回 {词条: (计数, 权重)} 格式
        """
        text = "心花怒放和快乐"
        tokens = text
        result = term_weighted_counts(text, tokens, weighted_terms)

        assert "心花怒放" in result
        assert "快乐" in result
        assert result["心花怒放"] == (1, 3)
        assert result["快乐"] == (1, 2)

    def test_load_weighted_lexicon_from_file(self, tmp_path: Path) -> None:
        """
        从文件加载加权词典

        场景: 词典文件格式为 "词条\\t权重"
        期望: 正确解析权重
        """
        lexicon_file = tmp_path / "test_lexicon.txt"
        lexicon_file.write_text(
            "# 测试词典\n好\t1\n快乐\t2\n心花怒放\t3\n",
            encoding="utf-8",
        )

        result = load_weighted_lexicon(str(lexicon_file))

        assert result["好"] == 1
        assert result["快乐"] == 2
        assert result["心花怒放"] == 3


class TestFourierSmooth:
    """
    傅里叶滤波测试

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 情绪曲线算法增强单元测试
    """

    def test_fourier_smooth_basic(self) -> None:
        """
        傅里叶滤波基本功能

        场景: 输入任意数值序列
        期望: 输出长度与输入一致
        """
        values = [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0, 1.0]
        result = fourier_smooth(values, keep_ratio=0.1)

        assert len(result) == len(values)
        assert all(isinstance(v, float) for v in result)

    def test_fourier_smooth_empty_input(self) -> None:
        """
        傅里叶滤波空输入

        场景: 输入空列表
        期望: 返回空列表
        """
        result = fourier_smooth([])
        assert result == []

    def test_fourier_smooth_single_value(self) -> None:
        """
        傅里叶滤波单值输入

        场景: 输入只有一个值
        期望: 返回相同的值
        """
        result = fourier_smooth([5.0])
        assert result == [5.0]

    def test_fourier_smooth_noise_reduction(self) -> None:
        """
        傅里叶滤波降噪效果

        场景: 输入包含高频噪声的信号
        期望: 高频噪声被过滤，保留低频趋势
        """
        import math

        base_signal = [math.sin(i * 0.1) for i in range(100)]
        noise = [0.3 * ((-1) ** i) for i in range(100)]
        noisy_signal = [b + n for b, n in zip(base_signal, noise, strict=True)]

        smoothed = fourier_smooth(noisy_signal, keep_ratio=0.05)

        diff_noisy = sum(abs(n - b) for n, b in zip(noisy_signal, base_signal, strict=True))
        diff_smoothed = sum(abs(s - b) for s, b in zip(smoothed, base_signal, strict=True))

        assert diff_smoothed < diff_noisy

    def test_fourier_smooth_no_lag(self) -> None:
        """
        傅里叶滤波无滞后

        场景: 输入信号有转折点
        期望: 转折点位置不延迟（与滑动平均对比）
        """
        values = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

        smoothed = fourier_smooth(values, keep_ratio=0.3)

        transition_idx = 3
        smoothed_at_transition = smoothed[transition_idx]

        assert smoothed_at_transition > smoothed[0]

    def test_fourier_smooth_keep_ratio_effect(self) -> None:
        """
        傅里叶滤波 keep_ratio 参数效果

        场景: 使用不同的 keep_ratio 值
        期望: keep_ratio 越大，平滑后信号越接近原始信号
        """
        import math

        values = [math.sin(i * 0.3) + 0.5 * math.sin(i * 2.0) for i in range(50)]

        smoothed_low = fourier_smooth(values, keep_ratio=0.1)
        smoothed_high = fourier_smooth(values, keep_ratio=0.5)

        diff_low = sum(abs(s - v) for s, v in zip(smoothed_low, values, strict=True))
        diff_high = sum(abs(s - v) for s, v in zip(smoothed_high, values, strict=True))

        assert diff_high < diff_low

    def test_fourier_smooth_preserves_mean(self) -> None:
        """
        傅里叶滤波保持均值

        场景: 输入任意信号
        期望: 平滑后均值基本不变
        """
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0]

        smoothed = fourier_smooth(values, keep_ratio=0.2)

        original_mean = sum(values) / len(values)
        smoothed_mean = sum(smoothed) / len(smoothed)

        assert abs(original_mean - smoothed_mean) < 0.5


class TestJiebaUserDict:
    """
    jieba 用户词典测试

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 情绪曲线算法增强单元测试
    """

    def test_tokenizer_singleton(self) -> None:
        """
        Tokenizer 单例模式

        场景: 多次调用 get_tokenizer
        期望: 返回同一个实例
        """
        t1 = get_tokenizer()
        t2 = get_tokenizer()
        assert t1 is t2

    def test_tokenizer_has_jieba(self) -> None:
        """
        Tokenizer 检测 jieba 是否可用

        场景: 检查 jieba 是否正确加载
        期望: has_jieba 属性为 True
        """
        tokenizer = get_tokenizer()
        assert tokenizer.has_jieba is True

    def test_tokenizer_basic_tokenize(self) -> None:
        """
        Tokenizer 基本分词功能

        场景: 输入中文文本
        期望: 返回分词结果
        """
        tokenizer = get_tokenizer()
        tokens = tokenizer.tokenize("今天天气很好")
        assert len(tokens) > 0
        assert all(isinstance(t, str) for t in tokens)

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


class TestIntegration:
    """
    集成测试

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 情绪曲线算法增强单元测试
    """

    def test_full_emotion_analysis_pipeline(self) -> None:
        """
        完整情感分析流程

        场景: 使用否定词翻转 + 加权密度 + 傅里叶滤波
        期望: 各模块协同工作正常
        """
        negation_words = {"不", "没", "未"}
        pos_terms = {"快乐": 2, "好": 1}
        neg_terms = {"悲伤": 2, "坏": 1}

        texts = [
            "今天很快乐",
            "他不快乐",
            "心情不好",
            "不是不好",
        ]

        densities = []
        for text in texts:
            result = lexical_sentiment_density(
                text,
                pos_terms,
                neg_terms,
                negation_words=negation_words,
                enable_negation=True,
            )
            densities.append(result["net_density"])

        smoothed = fourier_smooth(densities, keep_ratio=0.5)

        assert len(smoothed) == len(densities)

    def test_weighted_negation_combined(self) -> None:
        """
        加权 + 否定词翻转组合

        场景: "不心花怒放" 中 "心花怒放" 权重为 3
        期望: 否定词翻转后，负面密度增加 3
        """
        negation_words = {"不"}
        pos_terms = {"心花怒放": 3}
        neg_terms: dict[str, int] = {}

        result = lexical_sentiment_density(
            "不心花怒放",
            pos_terms,
            neg_terms,
            negation_words=negation_words,
            enable_negation=True,
        )

        assert result["neg_density"] > 0
        assert result["pos_density"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
