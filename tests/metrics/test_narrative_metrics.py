"""叙事结构指标：归一化字符进度轴。"""

from __future__ import annotations

import unittest

from src.metrics.narrative_metrics import (
    analyze_three_act_structure,
    compute_cliffhanger_rate,
    compute_climax_profile,
    compute_climax_spacing,
    compute_event_density,
    compute_middle_collapse_index,
    compute_three_act_ratio,
    compute_three_act_ratio_v2,
    find_global_peak,
    find_local_peaks,
    find_valley_before_peak,
)


def _linspace(n: int) -> list[float]:
    if n <= 1:
        return [0.0] * n
    return [i / (n - 1) for i in range(n)]


class TestThreeActRatio(unittest.TestCase):
    def test_empty_event_types(self) -> None:
        result = compute_three_act_ratio([])
        self.assertEqual(result["act1_ratio"], 0.0)


class TestFindLocalPeaks(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(find_local_peaks([], []), [])

    def test_too_short(self) -> None:
        self.assertEqual(find_local_peaks([0.5], [0.5]), [])

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            find_local_peaks([0.0, 0.5], [0.1])

    def test_min_spacing_uses_progress(self) -> None:
        positions = [0.0, 0.01, 0.02, 0.03, 0.04, 0.60, 0.99]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        self.assertEqual(find_local_peaks(positions, scores), [1, 5])

    def test_equally_spaced_peaks(self) -> None:
        positions = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        self.assertEqual(find_local_peaks(positions, scores), [1, 3, 5])


class TestClimaxSpacing(unittest.TestCase):
    def test_no_peaks(self) -> None:
        self.assertIsNone(compute_climax_spacing([0.0, 0.5, 1.0], [0.1, 0.2, 0.3]))

    def test_single_peak(self) -> None:
        self.assertIsNone(compute_climax_spacing([0.0, 0.5, 1.0], [0.1, 0.9, 0.2]))

    def test_progress_distance(self) -> None:
        positions = [0.0, 0.05, 0.10, 0.15, 0.20, 0.60, 0.99]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        result = compute_climax_spacing(positions, scores)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result, 0.275, places=6)


class TestClimaxProfile(unittest.TestCase):
    def test_empty(self) -> None:
        result = compute_climax_profile([], [])
        self.assertEqual(result["climax_count"], 0)
        self.assertIsNone(result["dominant_climax_pos"])

    def test_positions_are_progress(self) -> None:
        positions = [0.0, 0.05, 0.10, 0.15, 0.20, 0.60, 0.99]
        scores = [0.1, 0.9, 0.3, 0.8, 0.2, 0.9, 0.1]
        result = compute_climax_profile(positions, scores)
        self.assertEqual(result["climax_positions"], [0.05, 0.15, 0.6])
        self.assertEqual(result["dominant_climax_pos"], 0.05)


class TestMiddleCollapse(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertIsNone(compute_middle_collapse_index([], []))

    def test_insufficient(self) -> None:
        self.assertIsNone(compute_middle_collapse_index([0.0, 0.5, 1.0], [0.1, 0.2, 0.3]))

    def test_balanced(self) -> None:
        n = 100
        positions = _linspace(n)
        scores = [0.3] * 30 + [0.2] * 40 + [0.3] * 30
        result = compute_middle_collapse_index(positions, scores)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreater(result, 0.0)


class TestThreeActStructure(unittest.TestCase):
    def test_v2_progress_axis(self) -> None:
        total = 100
        positions = _linspace(total)
        event_types = ["铺垫"] * total
        cliffhangers = [0] * total
        pivot_moments = [0] * total
        tension_scores = [0.12] * total
        for idx in range(52, 76):
            tension_scores[idx] = 0.18 + ((idx - 52) * 0.01)
            event_types[idx] = "冲突"
            pivot_moments[idx] = 1
        diagnostics = analyze_three_act_structure(
            positions, event_types, cliffhangers, pivot_moments, tension_scores
        )
        ratios = diagnostics.ratio_dict()
        self.assertAlmostEqual(sum(ratios.values()), 1.0, places=3)
        ratios_v2 = compute_three_act_ratio_v2(
            positions, event_types, cliffhangers, pivot_moments, tension_scores
        )
        self.assertEqual(ratios_v2, ratios)

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            analyze_three_act_structure(
                [0.0, 0.5, 1.0], ["铺垫"] * 3, [0] * 3, [0] * 3, [0.1, 0.2]
            )


class TestEventDensityAndCliffhanger(unittest.TestCase):
    def test_event_density(self) -> None:
        result = compute_event_density(["冲突", "冲突", "铺垫", "转折"])
        self.assertAlmostEqual(result["冲突"], 0.5, places=6)

    def test_cliffhanger(self) -> None:
        self.assertEqual(compute_cliffhanger_rate([1, 0, 1, 0]), 0.5)


class TestHelpers(unittest.TestCase):
    def test_global_peak(self) -> None:
        self.assertEqual(find_global_peak([0.1, 0.9, 0.2]), 1)

    def test_valley(self) -> None:
        self.assertEqual(find_valley_before_peak([0.5, 0.1, 0.9], 2), 1)


if __name__ == "__main__":
    unittest.main()
