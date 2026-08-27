"""
段落表层张力测试（设计《章节粒度分析指标重设计》§9.2）

覆盖：分量公式（每百字口径）、MAD 稳健标准化与 clip 边界（手工核算）、
常量序列全 0、加权 z（默认/自定义/缺失键/权重和为 0）、
sigmoid 特殊值与单调性、空输入、端到端流水线。
"""

from __future__ import annotations

import math

import pytest

from src.config import settings
from src.metrics.paragraph_metrics import ParagraphMetricCounts
from src.metrics.paragraph_surface_tension import (
    robust_standardize_components,
    surface_tension_components,
    surface_tension_sigmoid,
    surface_tension_z_value,
)

# 手工核算基准（test_robust_standardize_manual_mad）：
# fight 值 [0,1,2,3,10]，median=2.0，MAD=1.0，z=(v-2)/(1.4826*1)
MAD_SCALE = 1.4826


def _make_counts(**overrides: object) -> ParagraphMetricCounts:
    """构造全零 ParagraphMetricCounts 并覆盖指定字段"""
    return ParagraphMetricCounts(
        token_count=overrides.get("token_count", 0),  # type: ignore[arg-type]
        char_count=overrides.get("char_count", 0),  # type: ignore[arg-type]
        sentence_count=overrides.get("sentence_count", 0),  # type: ignore[arg-type]
        sentence_char_sum=overrides.get("sentence_char_sum", 0.0),  # type: ignore[arg-type]
        sentence_char_sum_sq=overrides.get("sentence_char_sum_sq", 0.0),  # type: ignore[arg-type]
        positive_weight_sum=overrides.get("positive_weight_sum", 0.0),  # type: ignore[arg-type]
        negative_weight_sum=overrides.get("negative_weight_sum", 0.0),  # type: ignore[arg-type]
        fight_weight_sum=overrides.get("fight_weight_sum", 0.0),  # type: ignore[arg-type]
        exclaim_count=overrides.get("exclaim_count", 0),  # type: ignore[arg-type]
        question_count=overrides.get("question_count", 0),  # type: ignore[arg-type]
        pause_count=overrides.get("pause_count", 0),  # type: ignore[arg-type]
        dialogue_char_count=overrides.get("dialogue_char_count", 0),  # type: ignore[arg-type]
        sensory_hit_count=overrides.get("sensory_hit_count", 0),  # type: ignore[arg-type]
        imagery_hit_count=overrides.get("imagery_hit_count", 0),  # type: ignore[arg-type]
        metaphor_sentence_count=overrides.get("metaphor_sentence_count", 0),  # type: ignore[arg-type]
        function_word_counts=overrides.get("function_word_counts", {}),  # type: ignore[arg-type]
        semantic_category_counts=overrides.get("semantic_category_counts", {}),  # type: ignore[arg-type]
    )


def _constant_components() -> dict[str, float]:
    # 注意：不含 fight 键，避免 **others 覆盖各段落独立的 fight 值
    return {"exclaim": 1.0, "question": 1.0, "dialogue": 0.5, "pause": 2.0}


class TestSurfaceTensionComponents:
    def test_formula(self) -> None:
        """分量公式：战斗词命中率、感叹/问号/停顿每百字频率、对话占比"""
        counts = _make_counts(
            token_count=10,
            char_count=100,
            fight_weight_sum=5.0,
            exclaim_count=3,
            question_count=2,
            dialogue_char_count=40,
            pause_count=5,
        )
        assert surface_tension_components(counts) == {
            "fight": 0.5,
            "exclaim": 3.0,
            "question": 2.0,
            "dialogue": 0.4,
            "pause": 5.0,
        }

    def test_zero_counts_guarded(self) -> None:
        """全零计数：分母按 1 保护，分量全 0"""
        assert surface_tension_components(_make_counts()) == {
            "fight": 0.0,
            "exclaim": 0.0,
            "question": 0.0,
            "dialogue": 0.0,
            "pause": 0.0,
        }

    def test_per_hundred_chars_scale(self) -> None:
        """每百字口径：char_count=50 时感叹号 1 个折算为 2.0"""
        counts = _make_counts(char_count=50, exclaim_count=1, question_count=1, pause_count=1)
        components = surface_tension_components(counts)
        assert components["exclaim"] == pytest.approx(2.0)
        assert components["question"] == pytest.approx(2.0)
        assert components["pause"] == pytest.approx(2.0)


class TestRobustStandardize:
    def test_manual_mad_and_clip_upper(self) -> None:
        """5 段落手工核算：median=2.0、MAD=1.0，z 值 + clip 上界"""
        others = _constant_components()
        component_lists = [{"fight": value, **others} for value in (0.0, 1.0, 2.0, 3.0, 10.0)]
        result = robust_standardize_components(component_lists)

        assert result[0]["fight"] == pytest.approx(-2.0 / MAD_SCALE, abs=1e-4)
        assert result[1]["fight"] == pytest.approx(-1.0 / MAD_SCALE, abs=1e-4)
        assert result[2]["fight"] == pytest.approx(0.0, abs=1e-9)
        assert result[3]["fight"] == pytest.approx(1.0 / MAD_SCALE, abs=1e-4)
        assert result[4]["fight"] == 3.0  # (10-2)/1.4826≈5.4 被 clip 到 3

        # 常量分量（其余键全部相同）→ z 全 0
        for item in result:
            assert item["exclaim"] == pytest.approx(0.0, abs=1e-9)
            assert item["question"] == pytest.approx(0.0, abs=1e-9)
            assert item["dialogue"] == pytest.approx(0.0, abs=1e-9)
            assert item["pause"] == pytest.approx(0.0, abs=1e-9)

    def test_clip_lower_bound(self) -> None:
        """下界 clip：负向离群值 (v-median)/1.4826 ≈ -7.4 被 clip 到 -3"""
        others = _constant_components()
        component_lists = [{"fight": value, **others} for value in (0.0, 1.0, 2.0, 3.0, -10.0)]
        result = robust_standardize_components(component_lists)
        assert result[4]["fight"] == -3.0
        assert result[2]["fight"] == pytest.approx((2.0 - 1.0) / MAD_SCALE, abs=1e-4)

    def test_constant_sequence_all_zero(self) -> None:
        """全常量序列（MAD=0）：所有 z 为 0，不除零"""
        component_lists = [_constant_components() for _ in range(3)]
        result = robust_standardize_components(component_lists)
        expected = {
            "exclaim": 0.0,
            "question": 0.0,
            "dialogue": 0.0,
            "pause": 0.0,
        }
        assert result == [expected for _ in range(3)]

    def test_empty_input(self) -> None:
        """空输入返回空列表"""
        assert robust_standardize_components([]) == []

    def test_heterogeneous_keys_union(self) -> None:
        """键不同的输入：按并集处理，缺失键按 0"""
        result = robust_standardize_components([{"fight": 1.0}, {"fight": 1.0, "exclaim": 0.0}])
        assert result == [{"fight": 0.0, "exclaim": 0.0}, {"fight": 0.0, "exclaim": 0.0}]


class TestSurfaceTensionZValue:
    def test_default_weights_equal(self) -> None:
        """默认等权（settings.metrics.surface_tension_weights）：全 1 的 z 分量为 1.0"""
        z = surface_tension_z_value({"fight": 1.0, "exclaim": 1.0, "question": 1.0, "dialogue": 1.0, "pause": 1.0})
        assert z == pytest.approx(1.0)

    def test_custom_weights(self) -> None:
        """自定义权重加权平均"""
        z = surface_tension_z_value({"fight": 1.0, "exclaim": 3.0}, weights={"fight": 0.5, "exclaim": 0.5})
        assert z == pytest.approx(2.0)

    def test_missing_keys_zero(self) -> None:
        """缺失分量键按 0 处理：只有 fight 时按配置权重折算"""
        weights = settings.metrics.surface_tension_weights
        z = surface_tension_z_value({"fight": 1.0})
        expected = weights.get("fight", 0.0) / sum(weights.values())
        assert z == pytest.approx(expected)

    def test_zero_weight_sum_guarded(self) -> None:
        """权重和为 0 时防御返回 0，不抛除零异常"""
        assert surface_tension_z_value({"fight": 1.0}, weights={"other": 0.0}) == 0.0


class TestSurfaceTensionSigmoid:
    def test_special_values(self) -> None:
        assert surface_tension_sigmoid(0.0) == pytest.approx(0.5)
        assert surface_tension_sigmoid(1.0) == pytest.approx(1.0 / (1.0 + math.exp(-1.0)))
        assert surface_tension_sigmoid(3.0) == pytest.approx(0.9525741268224334, abs=1e-9)

    def test_monotonic_and_range(self) -> None:
        assert surface_tension_sigmoid(-3.0) < surface_tension_sigmoid(0.0) < surface_tension_sigmoid(3.0)
        # 100 在 float64 下 sigmoid 恰好舍入为 1.0，用 10 验证严格小于 1
        assert 0.0 < surface_tension_sigmoid(-10.0) < surface_tension_sigmoid(10.0) < 1.0


class TestPipeline:
    def test_components_to_tension(self) -> None:
        """端到端：分量 → 稳健标准化 → 加权 z → sigmoid，输出在 (0, 1)"""
        counts_list = [
            _make_counts(token_count=10, char_count=100, fight_weight_sum=1.0),
            _make_counts(
                token_count=10,
                char_count=100,
                fight_weight_sum=2.0,
                exclaim_count=5,
                question_count=2,
                dialogue_char_count=30,
                pause_count=4,
            ),
            _make_counts(token_count=10, char_count=100, fight_weight_sum=3.0, exclaim_count=1),
            _make_counts(
                token_count=10,
                char_count=100,
                fight_weight_sum=4.0,
                exclaim_count=2,
                question_count=3,
                dialogue_char_count=20,
                pause_count=3,
            ),
            _make_counts(
                token_count=10,
                char_count=100,
                fight_weight_sum=5.0,
                exclaim_count=8,
                question_count=4,
                dialogue_char_count=50,
                pause_count=6,
            ),
        ]
        components = [surface_tension_components(counts) for counts in counts_list]
        z_components = robust_standardize_components(components)
        z_values = [surface_tension_z_value(zc) for zc in z_components]
        tensions = [surface_tension_sigmoid(z) for z in z_values]

        assert len(z_components) == len(counts_list)
        assert all(-3.0 <= z <= 3.0 for z in z_values)
        assert all(0.0 < tension < 1.0 for tension in tensions)
        # 强度排序与战斗词命中率单调一致（其余分量 run 内对称）
        assert tensions[-1] > tensions[0]
