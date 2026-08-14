"""
段落曲线计算测试（设计 §5.5 / §9）

覆盖：密度分子/分母计算、token_count=0 → None（§15.2）、position 字符中点/
总字符数（§9.1）、平滑映射回全量（含 None 点）、对齐缺失段落跳过、
settings 默认参数生效、total_chars<=0 时 position 全 0
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from src.config import settings
from src.workflows.paragraph_curves import compute_paragraph_curves


def _paragraph(
    paragraph_id: int,
    *,
    global_start_char: int,
    global_end_char: int,
    char_count: int,
    token_count: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        paragraph_id=paragraph_id,
        global_start_char=global_start_char,
        global_end_char=global_end_char,
        char_count=char_count,
        token_count=token_count,
    )


def _metric(
    paragraph_id: int,
    *,
    positive_weight_sum: float,
    negative_weight_sum: float,
    token_count: int,
    surface_tension: float | None = 0.5,
) -> SimpleNamespace:
    return SimpleNamespace(
        paragraph_id=paragraph_id,
        positive_weight_sum=positive_weight_sum,
        negative_weight_sum=negative_weight_sum,
        token_count=token_count,
        surface_tension=surface_tension,
    )


class TestComputeParagraphCurves:
    def test_density_and_position_calculation(self) -> None:
        """密度 = 分子/分母；position = 段落字符中点/全书字符数（§9.1）"""
        paragraphs = [
            _paragraph(0, global_start_char=0, global_end_char=10, char_count=10, token_count=5),
            _paragraph(1, global_start_char=10, global_end_char=30, char_count=20, token_count=10),
        ]
        metric_rows = [
            _metric(0, positive_weight_sum=2.0, negative_weight_sum=1.0, token_count=5, surface_tension=0.5),
            _metric(1, positive_weight_sum=4.0, negative_weight_sum=4.0, token_count=10, surface_tension=0.7),
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=30)

        assert [row.paragraph_id for row in rows] == [0, 1]
        # pos/neg/net 密度
        assert rows[0].pos_density == pytest.approx(0.4)
        assert rows[0].neg_density == pytest.approx(0.2)
        assert rows[0].net_density == pytest.approx(0.2)
        assert rows[1].pos_density == pytest.approx(0.4)
        assert rows[1].neg_density == pytest.approx(0.4)
        assert rows[1].net_density == pytest.approx(0.0)
        # surface_tension 直接取自指标行
        assert rows[0].surface_tension == 0.5
        assert rows[1].surface_tension == 0.7

    def test_token_count_zero_yields_none_densities(self) -> None:
        """token_count == 0 时密度为 None，不伪造（§15.2）"""
        paragraphs = [
            _paragraph(0, global_start_char=0, global_end_char=10, char_count=10, token_count=0),
            _paragraph(1, global_start_char=10, global_end_char=20, char_count=10, token_count=4),
        ]
        metric_rows = [
            _metric(0, positive_weight_sum=1.0, negative_weight_sum=0.0, token_count=0),
            _metric(1, positive_weight_sum=2.0, negative_weight_sum=1.0, token_count=4),
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=20)

        assert rows[0].pos_density is None
        assert rows[0].neg_density is None
        assert rows[0].net_density is None
        assert rows[0].smoothed_net_density is None
        assert rows[1].pos_density == pytest.approx(0.5)
        assert rows[1].net_density == pytest.approx(0.25)

    def test_position_midpoint_over_total_chars(self) -> None:
        """
        position = ((global_start + global_end) / 2) / total_chars（§9.1）

        用 net_density 编码 position 本身：密度随位置线性变化时，
        LOWESS 平滑精确恢复该线性关系，间接验证坐标计算
        """
        paragraph_count = 10
        paragraphs = [
            _paragraph(
                i,
                global_start_char=i * 100,
                global_end_char=(i + 1) * 100,
                char_count=100,
                token_count=10,
            )
            for i in range(paragraph_count)
        ]
        expected_positions = [
            (i * 100 + (i + 1) * 100) / 2 / 1000 for i in range(paragraph_count)
        ]
        metric_rows = [
            _metric(
                i,
                positive_weight_sum=10.0 * expected_positions[i],
                negative_weight_sum=0.0,
                token_count=10,
            )
            for i in range(paragraph_count)
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=1000)

        for i, row in enumerate(rows):
            assert row.smoothed_net_density == pytest.approx(expected_positions[i], abs=1e-6)

    def test_smoothing_maps_back_to_full_with_none_points(self) -> None:
        """
        平滑映射回全量：net_density 非 None 的点被平滑，
        None 点（token_count=0）的平滑值保持 None；平滑值有限
        """
        paragraph_count = 12
        paragraphs = [
            _paragraph(
                i,
                global_start_char=i * 50,
                global_end_char=(i + 1) * 50,
                char_count=50,
                token_count=0 if i == 5 else 10,
            )
            for i in range(paragraph_count)
        ]
        metric_rows = [
            _metric(
                i,
                positive_weight_sum=5.0,
                negative_weight_sum=5.0,
                token_count=0 if i == 5 else 10,
                surface_tension=0.5,
            )
            for i in range(paragraph_count)
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=600)

        assert len(rows) == paragraph_count
        # 非 None 点被平滑且有限
        for i, row in enumerate(rows):
            if i == 5:
                assert row.net_density is None
                assert row.smoothed_net_density is None
            else:
                assert row.net_density == pytest.approx(0.0)
                assert row.smoothed_net_density is not None
                assert math.isfinite(row.smoothed_net_density)
            assert row.smoothed_surface_tension is not None

    def test_smoothing_recovers_linear_trend(self) -> None:
        """足够点数（>= min_points）时，线性净密度趋势被 LOWESS 平滑恢复"""
        paragraph_count = 20
        paragraphs = [
            _paragraph(
                i,
                global_start_char=i * 50,
                global_end_char=(i + 1) * 50,
                char_count=50,
                token_count=10,
            )
            for i in range(paragraph_count)
        ]
        metric_rows = [
            _metric(
                i,
                positive_weight_sum=10.0 + i,
                negative_weight_sum=10.0 - i,
                token_count=10,
                surface_tension=0.5,
            )
            for i in range(paragraph_count)
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=1000)

        # net_density = (10+i - (10-i))/10 = 0.2i，线性；平滑后应恢复该趋势
        for i, row in enumerate(rows):
            assert row.smoothed_net_density == pytest.approx(0.2 * i, abs=1e-6)

    def test_missing_side_paragraphs_are_skipped(self) -> None:
        """缺任一侧的段落跳过：指标缺失的段落、无段落的指标行都被忽略"""
        paragraphs = [
            _paragraph(0, global_start_char=0, global_end_char=10, char_count=10, token_count=5),
            _paragraph(1, global_start_char=10, global_end_char=20, char_count=10, token_count=5),
            _paragraph(2, global_start_char=20, global_end_char=30, char_count=10, token_count=5),
        ]
        metric_rows = [
            _metric(0, positive_weight_sum=1.0, negative_weight_sum=0.0, token_count=5),
            # paragraph 1 缺指标行 → 跳过
            _metric(2, positive_weight_sum=1.0, negative_weight_sum=0.0, token_count=5),
            # 无对应段落的指标行 → 忽略
            _metric(99, positive_weight_sum=9.0, negative_weight_sum=0.0, token_count=5),
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=30)

        assert [row.paragraph_id for row in rows] == [0, 2]

    def test_total_chars_non_positive_gives_zero_positions(self) -> None:
        """total_chars <= 0 时 position 全 0（x 退化，仍不产生 NaN）"""
        paragraphs = [
            _paragraph(i, global_start_char=i * 10, global_end_char=(i + 1) * 10, char_count=10, token_count=10)
            for i in range(10)
        ]
        metric_rows = [
            _metric(i, positive_weight_sum=5.0, negative_weight_sum=4.0, token_count=10)
            for i in range(10)
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=0)

        assert len(rows) == 10
        assert all(row.smoothed_net_density is not None for row in rows)
        assert all(row.net_density == pytest.approx(0.1) for row in rows)

    def test_settings_defaults_take_effect(self, monkeypatch) -> None:
        """
        bandwidth/min_points 为 None 时取 settings.metrics.lowess_*：
        将 lowess_min_points 调大后，n < min_points 应返回原始曲线
        """
        monkeypatch.setattr(settings.metrics, "lowess_min_points", 100)
        monkeypatch.setattr(settings.metrics, "lowess_bandwidth", 0.5)

        paragraphs = [
            _paragraph(i, global_start_char=i * 10, global_end_char=(i + 1) * 10, char_count=10, token_count=10)
            for i in range(10)
        ]
        metric_rows = [
            _metric(i, positive_weight_sum=5.0 + i, negative_weight_sum=4.0, token_count=10)
            for i in range(10)
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=100)

        # n=10 < lowess_min_points=100 → 平滑返回原始值
        for _i, row in enumerate(rows):
            assert row.smoothed_net_density == pytest.approx(row.net_density)
            assert row.smoothed_surface_tension == pytest.approx(row.surface_tension)

    def test_surface_tension_none_points_stay_none(self) -> None:
        """surface_tension 为 None 的段落：平滑值保持 None，其余被平滑"""
        paragraphs = [
            _paragraph(i, global_start_char=i * 10, global_end_char=(i + 1) * 10, char_count=10, token_count=10)
            for i in range(8)
        ]
        metric_rows = [
            _metric(i, positive_weight_sum=1.0, negative_weight_sum=0.0, token_count=10, surface_tension=None)
            if i == 3
            else _metric(i, positive_weight_sum=1.0, negative_weight_sum=0.0, token_count=10, surface_tension=0.5)
            for i in range(8)
        ]

        rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=80)

        assert rows[3].surface_tension is None
        assert rows[3].smoothed_surface_tension is None
        assert rows[0].smoothed_surface_tension == pytest.approx(0.5)

    def test_custom_weights_parameter(self) -> None:
        """显式 weights 参数生效：与 char_count 默认权重结果一致（等权场景）"""
        paragraphs = [
            _paragraph(i, global_start_char=i * 10, global_end_char=(i + 1) * 10, char_count=10, token_count=10)
            for i in range(10)
        ]
        metric_rows = [
            _metric(i, positive_weight_sum=5.0, negative_weight_sum=4.0, token_count=10)
            for i in range(10)
        ]

        default_rows = compute_paragraph_curves(paragraphs, metric_rows, total_chars=100)
        custom_rows = compute_paragraph_curves(
            paragraphs,
            metric_rows,
            total_chars=100,
            weights=[10.0] * 10,
        )

        assert [row.smoothed_net_density for row in custom_rows] == pytest.approx(
            [row.smoothed_net_density for row in default_rows]
        )

    def test_weights_length_mismatch_raises(self) -> None:
        paragraphs = [
            _paragraph(0, global_start_char=0, global_end_char=10, char_count=10, token_count=5)
        ]
        metric_rows = [_metric(0, positive_weight_sum=1.0, negative_weight_sum=0.0, token_count=5)]

        with pytest.raises(ValueError):
            compute_paragraph_curves(paragraphs, metric_rows, total_chars=10, weights=[1.0, 2.0])
