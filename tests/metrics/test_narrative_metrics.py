import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.narrative_metrics import (
    compute_three_act_ratio,
    compute_three_act_ratio_by_tension,
    compute_climax_spacing,
    compute_middle_collapse_index,
    compute_event_density,
    compute_cliffhanger_rate,
    find_global_peak,
    find_valley_before_peak,
    find_local_peaks,
)


class TestThreeActRatio(unittest.TestCase):
    def test_empty_event_types(self) -> None:
        result = compute_three_act_ratio([])
        self.assertEqual(result["act1_ratio"], 0.0)
        self.assertEqual(result["act2_ratio"], 0.0)
        self.assertEqual(result["act3_ratio"], 0.0)


class TestThreeActRatioByTension(unittest.TestCase):
    def test_empty_tension_scores(self) -> None:
        result = compute_three_act_ratio_by_tension([])
        self.assertEqual(result["act1_ratio"], 0.0)
        self.assertEqual(result["act2_ratio"], 0.0)
        self.assertEqual(result["act3_ratio"], 0.0)

    def test_single_peak_at_end(self) -> None:
        tension_scores = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = compute_three_act_ratio_by_tension(tension_scores)
        self.assertEqual(result["act1_ratio"], 0.0)
        self.assertEqual(result["act2_ratio"], 1.0)
        self.assertEqual(result["act3_ratio"], 0.0)

    def test_peak_at_middle(self) -> None:
        tension_scores = [0.1, 0.2, 0.9, 0.2, 0.1]
        result = compute_three_act_ratio_by_tension(tension_scores)
        total = sum(result.values())
        self.assertAlmostEqual(total, 1.0, places=6)


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
