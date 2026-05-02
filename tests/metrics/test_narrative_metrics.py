import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.narrative_metrics import (
    analyze_three_act_structure,
    compute_cliffhanger_rate,
    compute_climax_spacing,
    compute_event_density,
    compute_middle_collapse_index,
    compute_three_act_ratio,
    compute_three_act_ratio_v2,
    find_global_peak,
    find_local_peaks,
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
