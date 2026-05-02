"""
类型检测模块测试

创建时间: 2026-04-06
创建者: GLM-5
任务: 多类型加权混合词表方案
"""

from src.lexicons.genre_detector import (
    detect_genre_weighted,
    get_weighted_lexicon_config,
)


class TestDetectGenreWeighted:
    """多类型加权检测测试"""

    def test_empty_chunk_texts(self):
        """空 chunk 列表返回 general 类型"""
        result = detect_genre_weighted([])
        assert result.genre_weights == [("general", 1.0)]
        assert result.sample_count == 0

    def test_single_chunk_xianxia(self):
        """单个修仙 chunk 检测"""
        chunk_texts = [
            (1, "剑气纵横三万里，一剑光寒十九洲。修仙者渡劫飞升，金丹元婴化神。"),
        ]
        result = detect_genre_weighted(chunk_texts)
        assert len(result.genre_weights) >= 1
        assert result.sample_count == 1
        assert "xianxia" in [g for g, _ in result.genre_weights]

    def test_single_chunk_fantasy(self):
        """
        创建时间: 2026-05-02
        任务: diagnosis-genre-hints-and-fantasy-label
        新建原因: 正式题材集合新增 `玄幻` 后，底层 detector 至少应能识别典型玄幻强指示词，
                  不再只能把这类文本硬塞回仙侠或都市。
        """
        chunk_texts = [
            (1, "少年体内血脉封印松动，异火与灵兽共鸣，阵法试炼随之开启。"),
        ]
        result = detect_genre_weighted(chunk_texts)
        assert len(result.genre_weights) >= 1
        assert result.sample_count == 1
        assert "fantasy" in [g for g, _ in result.genre_weights]

    def test_single_chunk_urban(self):
        """单个都市 chunk 检测"""
        chunk_texts = [
            (1, "他在职场打拼多年，终于升职加薪。老板和同事都对他刮目相看。"),
        ]
        result = detect_genre_weighted(chunk_texts)
        assert len(result.genre_weights) >= 1
        assert result.sample_count == 1

    def test_multiple_chunks_sampling(self):
        """多个 chunk 均匀采样"""
        chunk_texts = [(i, f"第{i}章内容，剑气修仙境界提升。") for i in range(100)]
        result = detect_genre_weighted(chunk_texts, sample_ratio=0.1)
        assert result.sample_count >= 3
        assert result.sample_count <= 10

    def test_min_samples_constraint(self):
        """最少采样数约束"""
        chunk_texts = [(i, f"第{i}章内容。") for i in range(5)]
        result = detect_genre_weighted(chunk_texts, sample_ratio=0.1, min_samples=10)
        assert result.sample_count >= 10 or result.sample_count == len(chunk_texts)

    def test_large_novel_sampling(self):
        """长篇小说采样测试"""
        chunk_texts = [(i, f"第{i}章内容，剑气修仙境界提升。") for i in range(500)]
        result = detect_genre_weighted(chunk_texts, sample_ratio=0.1)
        assert result.sample_count == 50

    def test_weights_sum_to_one(self):
        """权重归一化后和为 1"""
        chunk_texts = [
            (1, "剑气修仙境界提升。"),
            (2, "职场升职加薪。"),
            (3, "权谋阴谋夺权篡位。"),
        ]
        result = detect_genre_weighted(chunk_texts)
        total_weight = sum(w for _, w in result.genre_weights)
        assert abs(total_weight - 1.0) < 0.001

    def test_weights_accumulate_to_one(self):
        """权重累加到 1.0 后停止"""
        chunk_texts = [(i, f"第{i}章内容，剑气修仙境界提升。") for i in range(50)]
        result = detect_genre_weighted(chunk_texts)
        accumulated = 0.0
        for _, w in result.genre_weights:
            accumulated += w
        assert accumulated >= 1.0 or len(result.genre_weights) == 1


class TestGetWeightedLexiconConfig:
    """加权词表配置测试"""

    def test_single_genre(self):
        """单个类型配置"""
        genre_weights = [("xianxia", 1.0)]
        config = get_weighted_lexicon_config(genre_weights)
        assert len(config) == 1
        assert config[0][0] == "xianxia"
        assert config[0][2] == 1.0

    def test_multiple_genres(self):
        """多个类型配置"""
        genre_weights = [("xianxia", 0.7), ("urban", 0.3)]
        config = get_weighted_lexicon_config(genre_weights)
        assert len(config) == 2
        assert config[0][0] == "xianxia"
        assert config[0][2] == 0.7
        assert config[1][0] == "urban"
        assert config[1][2] == 0.3

    def test_general_genre(self):
        """general 类型配置"""
        genre_weights = [("general", 1.0)]
        config = get_weighted_lexicon_config(genre_weights)
        assert len(config) == 1
        assert config[0][0] == "general"
