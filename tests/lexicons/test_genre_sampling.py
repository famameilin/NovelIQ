"""段落分层抽样测试（设计《章节粒度分析指标重设计》§11.2）"""

from __future__ import annotations

import pytest

from src.lexicons.genre_detector_sampling import sample_paragraphs_by_char_position


def _paragraphs(specs: list[tuple[int, int, int, int, int]]) -> list[tuple[int, int, int, int, int]]:
    """(paragraph_id, global_start_char, global_end_char, char_count, token_count)"""
    return list(specs)


class TestSampleParagraphsByCharPosition:
    def test_empty_input(self) -> None:
        result = sample_paragraphs_by_char_position([])
        assert result.paragraph_ids == []
        assert result.coverage_char_ratio == 0.0
        assert result.coverage_token_ratio == 0.0
        assert result.layer_count == 0

    def test_short_text_returns_all_paragraphs(self) -> None:
        paragraphs = _paragraphs(
            [
                (0, 0, 100, 100, 10),
                (1, 100, 300, 200, 20),
                (2, 300, 350, 50, 5),
            ]
        )
        result = sample_paragraphs_by_char_position(paragraphs)
        assert result.paragraph_ids == [0, 1, 2]
        assert result.coverage_char_ratio == pytest.approx(1.0)
        assert result.coverage_token_ratio == pytest.approx(1.0)
        # 短篇也按公式报告层数（min_samples 兜底）
        assert result.layer_count == 10

    def test_short_text_at_min_samples_boundary(self) -> None:
        """total == min_samples 时仍返回全部段落"""
        paragraphs = _paragraphs(
            [(i, i * 100, (i + 1) * 100, 100, 10) for i in range(10)]
        )
        result = sample_paragraphs_by_char_position(paragraphs, min_samples=10)
        assert result.paragraph_ids == list(range(10))
        assert result.coverage_char_ratio == pytest.approx(1.0)

    def test_short_text_zero_tokens(self) -> None:
        """token 总数为 0 时 token 覆盖比例为 0.0（避免除零）"""
        paragraphs = _paragraphs(
            [
                (0, 0, 100, 100, 0),
                (1, 100, 200, 100, 0),
                (2, 200, 300, 100, 0),
            ]
        )
        result = sample_paragraphs_by_char_position(paragraphs)
        assert result.paragraph_ids == [0, 1, 2]
        assert result.coverage_char_ratio == pytest.approx(1.0)
        assert result.coverage_token_ratio == 0.0

    def test_layered_selection_unequal_lengths(self) -> None:
        """
        不等长段落：每层选字符中点最接近层中点的段落，空层跳过。
        11 段（坐标总长 2200 字符，10 层，每层 220）：
        - 层 3 [660,880) 与层 7 [1540,1760) 无 global_start 落入，跳过
        - 段 4（1000-1300，中点 1150）在层 4 [880,1100) 输给段 3（950，距层中点 990 更近）
        - 段 8（1900-2000）在层 8 输给段 7（1850）；段 10（2100-2200）在层 9 输给段 9（2050）
        """
        paragraphs = _paragraphs(
            [
                (0, 0, 400, 400, 40),
                (1, 400, 500, 100, 10),
                (2, 500, 900, 400, 40),
                (3, 900, 1000, 100, 10),
                (4, 1000, 1300, 300, 30),
                (5, 1300, 1400, 100, 10),
                (6, 1400, 1800, 400, 40),
                (7, 1800, 1900, 100, 10),
                (8, 1900, 2000, 100, 10),
                (9, 2000, 2100, 100, 10),
                (10, 2100, 2200, 100, 10),
            ]
        )
        result = sample_paragraphs_by_char_position(paragraphs)
        assert result.layer_count == 10
        assert result.paragraph_ids == [0, 1, 2, 3, 5, 6, 7, 9]
        # 抽样字符 1700 / 2200，token 170 / 220
        assert result.coverage_char_ratio == pytest.approx(1700 / 2200)
        assert result.coverage_token_ratio == pytest.approx(170 / 220)

    def test_layered_selection_skips_empty_layers(self) -> None:
        """
        中间 500-1000 字符区间无段落：对应层（3/4/5）跳过，
        覆盖比例以段落实际字符总和为分母（1100，非坐标跨度 1600）
        """
        paragraphs = _paragraphs(
            [
                (0, 0, 100, 100, 10),
                (1, 100, 200, 100, 10),
                (2, 200, 300, 100, 10),
                (3, 300, 400, 100, 10),
                (4, 400, 500, 100, 10),
                (5, 1000, 1100, 100, 10),
                (6, 1100, 1200, 100, 10),
                (7, 1200, 1300, 100, 10),
                (8, 1300, 1400, 100, 10),
                (9, 1400, 1500, 100, 10),
                (10, 1500, 1600, 100, 10),
            ]
        )
        result = sample_paragraphs_by_char_position(paragraphs)
        assert result.layer_count == 10
        assert result.paragraph_ids == [0, 2, 4, 5, 7, 8, 10]
        assert result.coverage_char_ratio == pytest.approx(700 / 1100)
        assert result.coverage_token_ratio == pytest.approx(70 / 110)

    def test_token_budget_truncates_later_layers(self) -> None:
        """
        每段 token=5，预算 12：累计 5→10→15 超过预算后停止后续层，
        选中 [0, 2, 3]（层 0/1/2），层 3 起不再抽样
        """
        paragraphs = _paragraphs(
            [(i, i * 100, (i + 1) * 100, 100, 5) for i in range(12)]
        )
        result = sample_paragraphs_by_char_position(
            paragraphs, sample_ratio=0.1, min_samples=10, token_budget=12
        )
        assert result.paragraph_ids == [0, 2, 3]
        assert result.coverage_char_ratio == pytest.approx(300 / 1200)
        assert result.coverage_token_ratio == pytest.approx(15 / 60)

    def test_token_budget_not_exceeded_keeps_all_layers(self) -> None:
        paragraphs = _paragraphs(
            [(i, i * 100, (i + 1) * 100, 100, 5) for i in range(12)]
        )
        result = sample_paragraphs_by_char_position(
            paragraphs, sample_ratio=0.1, min_samples=10, token_budget=1000
        )
        # 等长 12 段 × 10 层：段 1/7 的中点在层内竞争中落选
        assert result.paragraph_ids == [0, 2, 3, 4, 5, 6, 8, 9, 10, 11]
        assert result.coverage_char_ratio == pytest.approx(1000 / 1200)

    def test_layer_count_scales_with_sample_ratio(self) -> None:
        paragraphs = _paragraphs(
            [(i, i * 100, (i + 1) * 100, 100, 5) for i in range(100)]
        )
        result = sample_paragraphs_by_char_position(
            paragraphs, sample_ratio=0.5, min_samples=10
        )
        # int(100 * 0.5) = 50 层
        assert result.layer_count == 50
        assert len(result.paragraph_ids) == 50
