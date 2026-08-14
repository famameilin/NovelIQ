import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.narrative_metrics import (
    analyze_three_act_structure,
    analyze_three_act_structure_by_position,
    compute_cliffhanger_rate,
    compute_climax_profile_by_position,
    compute_climax_spacing,
    compute_climax_spacing_by_position,
    compute_event_density,
    compute_middle_collapse_index,
    compute_three_act_ratio,
    compute_three_act_ratio_v2,
    find_global_peak,
    find_local_peaks,
    find_local_peaks_by_position,
    find_valley_before_peak,
)


class TestThreeActRatio(unittest.TestCase):
    def test_empty_event_types(self) -> None:
        result = compute_three_act_ratio([])
        self.assertEqual(result["act1_ratio"], 0.0)
        self.assertEqual(result["act2_ratio"], 0.0)
        self.assertEqual(result["act3_ratio"], 0.0)


class TestThreeActRatioV2(unittest.TestCase):
    def test_v2_uses_structural_boundary_instead_of_pre_peak_absolute_valley(self) -> None:
        total = 100
        event_types = ["铺垫"] * total
        cliffhangers = [0] * total
        pivot_moments = [0] * total
        tension_scores = [0.12] * total

        # 前段有偶发尖峰，但不应被误当成最终高潮。
        tension_scores[8] = 0.88

        # 中段进入持续上升，应该被识别为第二幕，而不是被后面的绝对低谷整体吞掉。
        for idx in range(52, 76):
            tension_scores[idx] = 0.18 + ((idx - 52) * 0.01)
            event_types[idx] = "转折" if idx % 3 else "冲突"
            pivot_moments[idx] = 1 if idx % 4 == 0 else 0
            cliffhangers[idx] = 1 if idx % 5 == 0 else 0

        # 峰前人为制造一个绝对低谷，旧算法容易把第一幕拖到这里。
        tension_scores[74] = 0.01
        event_types[74] = "铺垫"
        cliffhangers[74] = 0
        pivot_moments[74] = 0

        # 后段主高潮区。
        for idx in range(80, 96):
            tension_scores[idx] = 0.72 + ((idx - 80) * 0.015)
            event_types[idx] = "冲突"
            cliffhangers[idx] = 1 if idx % 2 == 0 else 0
            pivot_moments[idx] = 1 if idx % 3 == 0 else 0
        tension_scores[90] = 0.99

        diagnostics = analyze_three_act_structure(
            event_types,
            cliffhangers,
            pivot_moments,
            tension_scores,
        )

        self.assertFalse(diagnostics.boundary_fallback_used)
        self.assertGreaterEqual(diagnostics.climax_region_start, 55)
        self.assertGreaterEqual(diagnostics.representative_peak_idx, 80)
        self.assertLessEqual(diagnostics.act1_boundary_idx, 60)
        self.assertGreaterEqual(diagnostics.act1_boundary_idx, 50)

        result = compute_three_act_ratio_v2(
            event_types,
            cliffhangers,
            pivot_moments,
            tension_scores,
        )
        self.assertLess(result["act1_ratio"], 0.6)
        self.assertGreater(result["act2_ratio"], 0.15)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=3)

    def test_v2_falls_back_when_no_legal_structural_boundary_exists(self) -> None:
        event_types = ["铺垫"] * 40
        cliffhangers = [0] * 40
        pivot_moments = [0] * 40
        tension_scores = [0.1 + (idx * 0.01) for idx in range(40)]

        diagnostics = analyze_three_act_structure(
            event_types,
            cliffhangers,
            pivot_moments,
            tension_scores,
        )

        self.assertTrue(diagnostics.boundary_fallback_used)
        self.assertGreaterEqual(diagnostics.act1_boundary_idx, 0)
        self.assertLess(diagnostics.act1_boundary_idx, diagnostics.representative_peak_idx)

    def test_v2_keeps_equal_ratio_for_tiny_input(self) -> None:
        result = compute_three_act_ratio_v2(["铺垫", "冲突"], [0, 1], [0, 0], [0.1, 0.9])
        self.assertAlmostEqual(result["act1_ratio"], 1 / 3, places=4)
        self.assertAlmostEqual(result["act2_ratio"], 1 / 3, places=4)
        self.assertAlmostEqual(result["act3_ratio"], 1 / 3, places=4)


class TestFindGlobalPeak(unittest.TestCase):
    def test_empty_scores(self) -> None:
        result = find_global_peak([])
        self.assertEqual(result, 0)

    def test_single_element(self) -> None:
        result = find_global_peak([0.5])
        self.assertEqual(result, 0)

    def test_peak_at_end(self) -> None:
        result = find_global_peak([0.1, 0.2, 0.3, 0.4, 0.5])
        self.assertEqual(result, 4)

    def test_peak_at_middle(self) -> None:
        result = find_global_peak([0.1, 0.9, 0.2])
        self.assertEqual(result, 1)


class TestFindValleyBeforePeak(unittest.TestCase):
    def test_peak_at_zero(self) -> None:
        result = find_valley_before_peak([0.9, 0.2, 0.1], 0)
        self.assertEqual(result, 0)

    def test_valley_found(self) -> None:
        result = find_valley_before_peak([0.3, 0.1, 0.9], 2)
        self.assertEqual(result, 1)


class TestFindLocalPeaks(unittest.TestCase):
    def test_empty_scores(self) -> None:
        result = find_local_peaks([], 0)
        self.assertEqual(result, [])

    def test_single_element(self) -> None:
        result = find_local_peaks([0.5], 1)
        self.assertEqual(result, [])

    def test_two_elements(self) -> None:
        result = find_local_peaks([0.1, 0.5], 2)
        self.assertEqual(result, [])

    def test_multiple_peaks_with_min_distance(self) -> None:
        scores = [0.1, 0.5, 0.1, 0.5, 0.1] * 50
        result = find_local_peaks(scores, len(scores))
        self.assertGreater(len(result), 0)


class TestClimaxSpacing(unittest.TestCase):
    def test_no_peaks(self) -> None:
        result = compute_climax_spacing([1, 2, 3], [0.1, 0.2, 0.3])
        self.assertEqual(result, 0.0)

    def test_single_peak(self) -> None:
        result = compute_climax_spacing([1, 2, 3], [0.1, 0.9, 0.2])
        self.assertEqual(result, 0.0)

    def test_multiple_peaks(self) -> None:
        scores = [0.5, 0.9, 0.5, 0.1, 0.9, 0.5, 0.1, 0.9, 0.5] * 10
        chunk_ids = list(range(len(scores)))
        result = compute_climax_spacing(chunk_ids, scores)
        self.assertGreater(result, 0.0)


class TestFindLocalPeaksByPosition(unittest.TestCase):
    """字符坐标版峰值检测（设计 §10）：最小间距按字符位置差，不再按点数。"""

    def test_empty_scores(self) -> None:
        result = find_local_peaks_by_position([], [])
        self.assertEqual(result, [])

    def test_single_element(self) -> None:
        result = find_local_peaks_by_position([0.5], [0.5])
        self.assertEqual(result, [])

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            find_local_peaks_by_position([0.0, 0.5], [0.1])

    def test_non_monotonic_positions_raises(self) -> None:
        with self.assertRaises(ValueError):
            find_local_peaks_by_position([0.0, 0.5, 0.5], [0.1, 0.9, 0.2])

    def test_min_spacing_uses_position_distance_not_point_distance(self) -> None:
        # 三个严格相邻峰（索引 1、3、5）：索引 1 与 3 的位置差仅 0.02 < 0.05，
        # 即使点索引差为 2 也会被合并；索引 5 的位置差 0.57 >= 0.05 保留。
        positions = [0.0, 0.01, 0.02, 0.03, 0.04, 0.60, 0.99]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        result = find_local_peaks_by_position(positions, scores)
        self.assertEqual(result, [1, 5])

    def test_equally_spaced_peaks_all_kept(self) -> None:
        positions = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        result = find_local_peaks_by_position(positions, scores)
        self.assertEqual(result, [1, 3, 5])


class TestComputeClimaxSpacingByPosition(unittest.TestCase):
    """字符坐标版高潮间距：峰值间距 = 字符位置差。"""

    def test_empty_data(self) -> None:
        self.assertEqual(compute_climax_spacing_by_position([], []), 0.0)

    def test_len_mismatch_returns_zero(self) -> None:
        self.assertEqual(compute_climax_spacing_by_position([0.0, 0.5, 1.0], [0.1, 0.9]), 0.0)

    def test_no_peaks(self) -> None:
        self.assertEqual(compute_climax_spacing_by_position([0.0, 0.5, 1.0], [0.1, 0.2, 0.3]), 0.0)

    def test_single_peak(self) -> None:
        self.assertEqual(compute_climax_spacing_by_position([0.0, 0.5, 1.0], [0.1, 0.9, 0.2]), 0.0)

    def test_char_distance_between_peaks(self) -> None:
        # 峰索引 1、3、5：间距 0.15-0.05=0.10 与 0.60-0.15=0.45，平均 0.275。
        positions = [0.0, 0.05, 0.10, 0.15, 0.20, 0.60, 0.99]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        result = compute_climax_spacing_by_position(positions, scores)
        self.assertAlmostEqual(result, 0.275, places=6)


class TestComputeClimaxProfileByPosition(unittest.TestCase):
    """字符坐标版高潮剖面：climax_positions 直接使用真实字符位置。"""

    def test_empty_scores(self) -> None:
        result = compute_climax_profile_by_position([], [])
        self.assertEqual(result["climax_count"], 0)
        self.assertEqual(result["climax_positions"], [])
        self.assertEqual(result["climax_heights"], [])
        self.assertIsNone(result["peak_escalation"])
        self.assertIsNone(result["dominant_climax_pos"])

    def test_positions_are_real_char_positions(self) -> None:
        # 若按旧口径 p/total 估算，峰值位置应为 [1/7, 3/7, 5/7]；
        # 字符坐标版必须返回真实字符位置 [0.2, 0.3, 0.9]。
        positions = [0.0, 0.2, 0.25, 0.3, 0.7, 0.9, 1.0]
        scores = [0.1, 0.9, 0.2, 0.8, 0.2, 0.9, 0.1]
        result = compute_climax_profile_by_position(positions, scores)
        self.assertEqual(result["climax_count"], 3)
        self.assertEqual(result["climax_positions"], [0.2, 0.3, 0.9])
        self.assertEqual(result["climax_heights"], [1.0, 0.889, 1.0])
        self.assertEqual(result["peak_escalation"], "flat")
        self.assertEqual(result["dominant_climax_pos"], 0.2)


class TestAnalyzeThreeActStructureByPosition(unittest.TestCase):
    """字符坐标版三幕结构：窗口按字符区间、比例按字符位置。"""

    @staticmethod
    def _build_v2_scenario() -> tuple[list[str], list[int], list[int], list[float]]:
        """复用旧 v2 回归场景：前段偶发尖峰 + 中段持续上升 + 后段主高潮区。"""
        total = 100
        event_types = ["铺垫"] * total
        cliffhangers = [0] * total
        pivot_moments = [0] * total
        tension_scores = [0.12] * total

        tension_scores[8] = 0.88

        for idx in range(52, 76):
            tension_scores[idx] = 0.18 + ((idx - 52) * 0.01)
            event_types[idx] = "转折" if idx % 3 else "冲突"
            pivot_moments[idx] = 1 if idx % 4 == 0 else 0
            cliffhangers[idx] = 1 if idx % 5 == 0 else 0

        tension_scores[74] = 0.01
        event_types[74] = "铺垫"
        cliffhangers[74] = 0
        pivot_moments[74] = 0

        for idx in range(80, 96):
            tension_scores[idx] = 0.72 + ((idx - 80) * 0.015)
            event_types[idx] = "冲突"
            cliffhangers[idx] = 1 if idx % 2 == 0 else 0
            pivot_moments[idx] = 1 if idx % 3 == 0 else 0
        tension_scores[90] = 0.99
        return event_types, cliffhangers, pivot_moments, tension_scores

    def test_empty_inputs_zero_result(self) -> None:
        diagnostics = analyze_three_act_structure_by_position([], [], [], [], [])
        self.assertEqual(diagnostics.act1_ratio, 0.0)
        self.assertTrue(diagnostics.boundary_fallback_used)

    def test_tiny_input_equal_third(self) -> None:
        diagnostics = analyze_three_act_structure_by_position(
            [0.0, 1.0],
            ["铺垫", "冲突"],
            [0, 1],
            [0, 0],
            [0.1, 0.9],
        )
        self.assertAlmostEqual(diagnostics.act1_ratio, 1 / 3, places=4)
        self.assertAlmostEqual(diagnostics.act2_ratio, 1 / 3, places=4)
        self.assertAlmostEqual(diagnostics.act3_ratio, 1 / 3, places=4)

    def test_zero_span_falls_back_to_equal_third(self) -> None:
        # 单点输入字符跨度为零：等分兜底。
        diagnostics = analyze_three_act_structure_by_position(
            [0.5], ["冲突"], [0], [0], [0.9]
        )
        self.assertAlmostEqual(diagnostics.act1_ratio, 1 / 3, places=4)
        self.assertTrue(diagnostics.boundary_fallback_used)

    def test_equal_positions_match_point_index_behavior(self) -> None:
        event_types, cliffhangers, pivot_moments, tension_scores = self._build_v2_scenario()
        positions = [i / 99 for i in range(100)]
        diagnostics = analyze_three_act_structure_by_position(
            positions, event_types, cliffhangers, pivot_moments, tension_scores
        )
        self.assertFalse(diagnostics.boundary_fallback_used)
        self.assertGreaterEqual(diagnostics.climax_region_start, 55)
        self.assertGreaterEqual(diagnostics.representative_peak_idx, 80)
        self.assertLessEqual(diagnostics.act1_boundary_idx, 60)
        self.assertGreaterEqual(diagnostics.act1_boundary_idx, 50)

    def test_ratio_uses_char_position_not_index(self) -> None:
        event_types, cliffhangers, pivot_moments, tension_scores = self._build_v2_scenario()
        # 二次压缩前段：边界索引 80 对应字符位置 (80/99)^2 ≈ 0.653，
        # 若按索引比例则会是 0.8 —— 比例必须与字符位置一致。
        positions = [(i / 99) ** 2 for i in range(100)]
        diagnostics = analyze_three_act_structure_by_position(
            positions, event_types, cliffhangers, pivot_moments, tension_scores
        )
        span = positions[-1] - positions[0]
        expected_act1 = (positions[diagnostics.act1_boundary_idx] - positions[0]) / span
        expected_act2 = (
            positions[diagnostics.representative_peak_idx]
            - positions[diagnostics.act1_boundary_idx]
        ) / span
        expected_act3 = (positions[-1] - positions[diagnostics.representative_peak_idx]) / span
        self.assertAlmostEqual(diagnostics.act1_ratio, expected_act1, places=4)
        self.assertAlmostEqual(diagnostics.act2_ratio, expected_act2, places=4)
        self.assertAlmostEqual(diagnostics.act3_ratio, expected_act3, places=4)
        self.assertAlmostEqual(sum(diagnostics.ratio_dict().values()), 1.0, places=4)
        self.assertLess(diagnostics.act1_ratio, 0.7)

    def test_climax_window_uses_char_span_not_point_count(self) -> None:
        # 前 60 个点压缩在 [0, 0.5]，后 40 个点铺在 [0.5, 1.0]；
        # 张力/冲突簇放在索引 55-59（字符位置 < 0.5）。
        total = 100
        positions = [0.0]
        for i in range(1, total):
            positions.append(positions[-1] + (0.5 / 59 if i < 60 else 0.5 / 40))
        event_types = ["铺垫"] * total
        cliffhangers = [0] * total
        pivot_moments = [0] * total
        tension_scores = [0.1] * total
        for i in range(55, 60):
            tension_scores[i] = 0.9
            event_types[i] = "冲突"
            cliffhangers[i] = 1

        diagnostics = analyze_three_act_structure_by_position(
            positions, event_types, cliffhangers, pivot_moments, tension_scores
        )
        # 字符坐标版扫描范围为后 45% 字符跨度（位置 >= 0.55），
        # 索引 55-59 的位置均 < 0.5 不在扫描范围内 → 高潮区起点落在后段；
        # 点索引版（旧实现）该场景高潮区起点为 55。
        self.assertGreaterEqual(diagnostics.climax_region_start, 60)
        self.assertGreaterEqual(positions[diagnostics.climax_region_start], 0.55)

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            analyze_three_act_structure_by_position(
                [0.0, 0.5, 1.0], ["铺垫"] * 3, [0] * 3, [0] * 3, [0.1, 0.2]
            )


class TestMiddleCollapseIndex(unittest.TestCase):
    def test_empty_data(self) -> None:
        result = compute_middle_collapse_index([], [])
        self.assertEqual(result, 0.0)

    def test_insufficient_chunks(self) -> None:
        result = compute_middle_collapse_index([1, 2, 3], [0.1, 0.2, 0.3])
        self.assertEqual(result, 0.0)

    def test_balanced_structure(self) -> None:
        chunk_ids = list(range(100))
        tension_scores = [0.3] * 30 + [0.2] * 40 + [0.3] * 30
        result = compute_middle_collapse_index(chunk_ids, tension_scores)
        self.assertGreater(result, 0.0)


class TestEventDensity(unittest.TestCase):
    def test_empty_event_types(self) -> None:
        result = compute_event_density([])
        for key in ["冲突", "铺垫", "转折"]:
            self.assertEqual(result[key], 0.0)

    def test_event_distribution(self) -> None:
        result = compute_event_density(["冲突", "冲突", "铺垫", "转折"])
        self.assertAlmostEqual(result["冲突"], 0.5, places=6)
        self.assertAlmostEqual(result["铺垫"], 0.25, places=6)
        self.assertAlmostEqual(result["转折"], 0.25, places=6)


class TestCliffhangerRate(unittest.TestCase):
    def test_empty_cliffhangers(self) -> None:
        result = compute_cliffhanger_rate([])
        self.assertEqual(result, 0.0)

    def test_all_cliffhangers(self) -> None:
        result = compute_cliffhanger_rate([1, 1, 1])
        self.assertEqual(result, 1.0)

    def test_partial_cliffhangers(self) -> None:
        result = compute_cliffhanger_rate([1, 0, 1, 0])
        self.assertEqual(result, 0.5)


if __name__ == "__main__":
    unittest.main()
