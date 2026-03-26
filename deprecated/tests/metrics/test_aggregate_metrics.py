import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.aggregate_metrics import (
    AggregateResult,
    aggregate_all_metrics,
    compute_antagonist_strength_gap,
    compute_average_clustering,
    compute_character_closeness_centrality,
    compute_character_degree_centrality,
    compute_character_eigenvector_centrality,
    compute_character_function_coverage,
    compute_classical_sentence_ratio,
    compute_cliffhanger_rate,
    compute_climax_spacing,
    compute_clustering_coefficient,
    compute_dialogue_tone_distribution,
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_event_density,
    compute_idiom_density,
    compute_largest_component_size,
    compute_middle_collapse_index,
    compute_number_of_connected_components,
    compute_pivot_moment_density,
    compute_protagonist_betweenness,
    compute_relation_change_frequency,
    compute_relation_network_density,
    compute_three_act_ratio,
)
from src.storage.schema import create_tables


class TestThreeActRatio(unittest.TestCase):
    def test_empty_event_types(self) -> None:
        result = compute_three_act_ratio([])
        self.assertEqual(result["act1_ratio"], 0.0)
        self.assertEqual(result["act2_ratio"], 0.0)
        self.assertEqual(result["act3_ratio"], 0.0)

    def test_single_act(self) -> None:
        result = compute_three_act_ratio(["铺垫", "铺垫", "日常"])
        self.assertGreater(result["act1_ratio"], 0)
        self.assertEqual(result["act2_ratio"], 0.0)
        self.assertEqual(result["act3_ratio"], 0.0)

    def test_mixed_acts(self) -> None:
        result = compute_three_act_ratio(["铺垫", "转折", "高潮"])
        self.assertAlmostEqual(result["act1_ratio"], 1/3, places=6)
        self.assertAlmostEqual(result["act2_ratio"], 1/3, places=6)
        self.assertAlmostEqual(result["act3_ratio"], 1/3, places=6)


class TestClimaxSpacing(unittest.TestCase):
    def test_no_climax(self) -> None:
        result = compute_climax_spacing([1, 2, 3], ["铺垫", "转折", "日常"])
        self.assertEqual(result, 0.0)

    def test_single_climax(self) -> None:
        result = compute_climax_spacing([1, 2, 3], ["铺垫", "高潮", "日常"])
        self.assertEqual(result, 0.0)

    def test_multiple_climaxes(self) -> None:
        result = compute_climax_spacing([1, 5, 10], ["铺垫", "高潮", "高潮"])
        self.assertEqual(result, 5.0)


class TestMiddleCollapseIndex(unittest.TestCase):
    def test_empty_data(self) -> None:
        result = compute_middle_collapse_index([], [])
        self.assertEqual(result, 0.0)

    def test_insufficient_chunks(self) -> None:
        result = compute_middle_collapse_index([1, 2, 3], ["铺垫", "转折", "高潮"])
        self.assertEqual(result, 0.0)

    def test_balanced_structure(self) -> None:
        chunk_ids = list(range(100))
        event_types = ["铺垫"] * 30 + ["转折"] * 40 + ["高潮"] * 30
        result = compute_middle_collapse_index(chunk_ids, event_types)
        self.assertGreater(result, 0.0)


class TestEventDensity(unittest.TestCase):
    def test_empty_event_types(self) -> None:
        result = compute_event_density([])
        for key in ["高潮", "冲突", "转折", "铺垫", "日常"]:
            self.assertEqual(result[key], 0.0)

    def test_event_distribution(self) -> None:
        result = compute_event_density(["高潮", "高潮", "日常", "转折"])
        self.assertAlmostEqual(result["高潮"], 0.5, places=6)
        self.assertAlmostEqual(result["日常"], 0.25, places=6)
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


class TestEmotionRecoverySpeed(unittest.TestCase):
    def test_empty_emotions(self) -> None:
        result = compute_emotion_recovery_speed([])
        self.assertEqual(result, 0.0)

    def test_no_recovery_needed(self) -> None:
        result = compute_emotion_recovery_speed([0.1, 0.1, 0.1])
        self.assertEqual(result, 0.0)

    def test_with_recovery(self) -> None:
        emotions = [0.5, -0.5, -0.3, 0.0, 0.2, 0.5]
        result = compute_emotion_recovery_speed(emotions)
        self.assertGreater(result, 0.0)


class TestEmotionPolarityDistribution(unittest.TestCase):
    def test_empty_valences(self) -> None:
        result = compute_emotion_polarity_distribution([])
        self.assertEqual(result["positive_ratio"], 0.0)
        self.assertEqual(result["negative_ratio"], 0.0)
        self.assertEqual(result["neutral_ratio"], 0.0)

    def test_polarity_distribution(self) -> None:
        result = compute_emotion_polarity_distribution(["positive", "negative", "neutral"])
        self.assertAlmostEqual(result["positive_ratio"], 1/3, places=6)
        self.assertAlmostEqual(result["negative_ratio"], 1/3, places=6)
        self.assertAlmostEqual(result["neutral_ratio"], 1/3, places=6)


class TestPivotMomentDensity(unittest.TestCase):
    def test_empty_pivot_moments(self) -> None:
        result = compute_pivot_moment_density([])
        self.assertEqual(result, 0.0)

    def test_all_pivots(self) -> None:
        result = compute_pivot_moment_density([1, 1, 1])
        self.assertEqual(result, 1.0)

    def test_partial_pivots(self) -> None:
        result = compute_pivot_moment_density([1, 0, 1, 0, 0])
        self.assertEqual(result, 0.4)


class TestCharacterDegreeCentrality(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_character_degree_centrality([])
        self.assertEqual(result, {})

    def test_single_relation(self) -> None:
        result = compute_character_degree_centrality([("A", "B")])
        self.assertEqual(result["A"], 1.0)
        self.assertEqual(result["B"], 1.0)

    def test_multiple_relations(self) -> None:
        result = compute_character_degree_centrality([("A", "B"), ("A", "C"), ("B", "C")])
        self.assertEqual(result["A"], 1.0)
        self.assertGreater(result["B"], 0.0)
        self.assertGreater(result["C"], 0.0)


class TestRelationNetworkDensity(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_relation_network_density([])
        self.assertEqual(result, 0.0)

    def test_single_relation(self) -> None:
        result = compute_relation_network_density([("A", "B")])
        self.assertEqual(result, 1.0)

    def test_multiple_relations(self) -> None:
        result = compute_relation_network_density([("A", "B"), ("A", "C")])
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)


class TestProtagonistBetweenness(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_protagonist_betweenness([], "主角")
        self.assertEqual(result, 0.0)

    def test_protagonist_not_in_network(self) -> None:
        result = compute_protagonist_betweenness([("A", "B")], "主角")
        self.assertEqual(result, 0.0)

    def test_protagonist_as_bridge(self) -> None:
        relations = [("主角", "A"), ("主角", "B"), ("A", "B")]
        result = compute_protagonist_betweenness(relations, "主角")
        self.assertGreaterEqual(result, 0.0)


class TestCharacterClosenessCentrality(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_character_closeness_centrality([])
        self.assertEqual(result, {})

    def test_single_relation(self) -> None:
        result = compute_character_closeness_centrality([("A", "B")])
        self.assertEqual(result["A"], 1.0)
        self.assertEqual(result["B"], 1.0)

    def test_triangle_graph(self) -> None:
        result = compute_character_closeness_centrality([("A", "B"), ("B", "C"), ("A", "C")])
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertIn("C", result)


class TestCharacterEigenvectorCentrality(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_character_eigenvector_centrality([])
        self.assertEqual(result, {})

    def test_single_relation(self) -> None:
        result = compute_character_eigenvector_centrality([("A", "B")])
        self.assertIn("A", result)
        self.assertIn("B", result)


class TestClusteringCoefficient(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_clustering_coefficient([])
        self.assertEqual(result, {})

    def test_triangle_graph(self) -> None:
        result = compute_clustering_coefficient([("A", "B"), ("B", "C"), ("A", "C")])
        self.assertEqual(result["A"], 1.0)
        self.assertEqual(result["B"], 1.0)
        self.assertEqual(result["C"], 1.0)


class TestAverageClustering(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_average_clustering([])
        self.assertEqual(result, 0.0)

    def test_triangle_graph(self) -> None:
        result = compute_average_clustering([("A", "B"), ("B", "C"), ("A", "C")])
        self.assertEqual(result, 1.0)


class TestConnectedComponents(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_number_of_connected_components([])
        self.assertEqual(result, 0)

    def test_single_component(self) -> None:
        result = compute_number_of_connected_components([("A", "B"), ("B", "C")])
        self.assertEqual(result, 1)

    def test_multiple_components(self) -> None:
        result = compute_number_of_connected_components([("A", "B"), ("C", "D")])
        self.assertEqual(result, 2)


class TestLargestComponentSize(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_largest_component_size([])
        self.assertEqual(result, 0)

    def test_single_component(self) -> None:
        result = compute_largest_component_size([("A", "B"), ("B", "C")])
        self.assertEqual(result, 3)

    def test_multiple_components(self) -> None:
        result = compute_largest_component_size([("A", "B"), ("C", "D"), ("D", "E")])
        self.assertEqual(result, 3)


class TestCharacterFunctionCoverage(unittest.TestCase):
    def test_empty_roles(self) -> None:
        result = compute_character_function_coverage([])
        for func in ["protagonist", "antagonist", "helper", "mentor", "other"]:
            self.assertEqual(result[func], 0.0)

    def test_role_distribution(self) -> None:
        result = compute_character_function_coverage(["protagonist", "antagonist", "helper"])
        self.assertAlmostEqual(result["protagonist"], 1/3, places=6)
        self.assertAlmostEqual(result["antagonist"], 1/3, places=6)
        self.assertAlmostEqual(result["helper"], 1/3, places=6)


class TestAntagonistStrengthGap(unittest.TestCase):
    def test_empty_characters(self) -> None:
        result = compute_antagonist_strength_gap([])
        self.assertEqual(result, 0.0)

    def test_no_protagonist(self) -> None:
        result = compute_antagonist_strength_gap([("反派", "antagonist", 5)])
        self.assertEqual(result, 0.0)

    def test_with_both_roles(self) -> None:
        characters = [
            ("主角", "protagonist", 4),
            ("反派", "antagonist", 3),
        ]
        result = compute_antagonist_strength_gap(characters)
        self.assertEqual(result, 1.0)


class TestRelationChangeFrequency(unittest.TestCase):
    def test_empty_relations(self) -> None:
        result = compute_relation_change_frequency([], 10)
        self.assertEqual(result["total_changes"], 0.0)
        self.assertEqual(result["change_rate"], 0.0)

    def test_change_frequency(self) -> None:
        relations = [
            ("A", "B", "盟友", "强化"),
            ("A", "C", "敌对", "新建"),
        ]
        result = compute_relation_change_frequency(relations, 10)
        self.assertEqual(result["total_changes"], 2.0)
        self.assertEqual(result["change_rate"], 0.2)


class TestDialogueToneDistribution(unittest.TestCase):
    def test_empty_tones(self) -> None:
        result = compute_dialogue_tone_distribution([])
        self.assertEqual(result, {})

    def test_tone_distribution(self) -> None:
        result = compute_dialogue_tone_distribution(["强硬", "温和", "强硬"])
        self.assertAlmostEqual(result["强硬"], 2/3, places=6)
        self.assertAlmostEqual(result["温和"], 1/3, places=6)


class TestIdiomDensity(unittest.TestCase):
    def test_empty_texts(self) -> None:
        result = compute_idiom_density([])
        self.assertEqual(result, 0.0)

    def test_with_idioms(self) -> None:
        result = compute_idiom_density(["一心一意", "三心二意"])
        self.assertGreater(result, 0.0)


class TestClassicalSentenceRatio(unittest.TestCase):
    def test_empty_texts(self) -> None:
        result = compute_classical_sentence_ratio([])
        self.assertEqual(result, 0.0)

    def test_with_classical_sentences(self) -> None:
        result = compute_classical_sentence_ratio(["此乃天意也。", "岂不美哉？"])
        self.assertGreater(result, 0.0)

    def test_modern_sentences(self) -> None:
        result = compute_classical_sentence_ratio(["这是现代汉语。", "今天天气很好。"])
        self.assertEqual(result, 0.0)


class TestAggregateAllMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = Path(self.temp_file.name)
        self.conn = sqlite3.connect(self.db_path)
        create_tables(self.conn)
        self._populate_test_data()

    def tearDown(self) -> None:
        self.conn.close()
        try:
            self.db_path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def _populate_test_data(self) -> None:
        self.conn.execute("INSERT INTO chunks (chunk_id, text) VALUES (0, '测试文本一心一意')")
        self.conn.execute("INSERT INTO chunks (chunk_id, text) VALUES (1, '此乃天意也。')")
        self.conn.execute("INSERT INTO chunk_annotation (chunk_id, event_type, cliffhanger, pivot_moment, emotional_valence) VALUES (0, '铺垫', 1, 0, 'positive')")
        self.conn.execute("INSERT INTO chunk_annotation (chunk_id, event_type, cliffhanger, pivot_moment, emotional_valence) VALUES (1, '高潮', 0, 1, 'negative')")
        self.conn.execute("INSERT INTO chunk_characters (chunk_id, name, role_function, emotion_score) VALUES (0, '主角', 'protagonist', 5)")
        self.conn.execute("INSERT INTO chunk_characters (chunk_id, name, role_function, emotion_score) VALUES (0, '反派', 'antagonist', -3)")
        self.conn.execute("INSERT INTO chunk_relations (chunk_id, from_char, to_char, type, change) VALUES (0, '主角', '反派', '敌对', '强化')")
        self.conn.execute("INSERT INTO chunk_dialogues (chunk_id, speaker, tone) VALUES (0, '主角', '强硬')")
        self.conn.execute("INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density) VALUES (0, 0.1, 0.05, 0.05, 0.05)")
        self.conn.execute("INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density) VALUES (1, 0.02, 0.1, -0.08, -0.06)")
        self.conn.commit()

    def test_aggregate_returns_result(self) -> None:
        result = aggregate_all_metrics(self.conn)
        self.assertIsInstance(result, AggregateResult)
        self.assertIsInstance(result.narrative_structure, dict)
        self.assertIsInstance(result.emotion_curve, dict)
        self.assertIsInstance(result.character_relations, dict)
        self.assertIsInstance(result.language_style, dict)
        self.assertIsInstance(result.traditional_culture, dict)

    def test_aggregate_narrative_structure(self) -> None:
        result = aggregate_all_metrics(self.conn)
        self.assertIn("act1_ratio", result.narrative_structure)
        self.assertIn("act2_ratio", result.narrative_structure)
        self.assertIn("act3_ratio", result.narrative_structure)
        self.assertIn("climax_spacing", result.narrative_structure)
        self.assertIn("middle_collapse_index", result.narrative_structure)
        self.assertIn("cliffhanger_rate", result.narrative_structure)

    def test_aggregate_emotion_curve(self) -> None:
        result = aggregate_all_metrics(self.conn)
        self.assertIn("emotion_recovery_speed", result.emotion_curve)
        self.assertIn("pivot_moment_density", result.emotion_curve)
        self.assertIn("positive_ratio", result.emotion_curve)

    def test_aggregate_character_relations(self) -> None:
        result = aggregate_all_metrics(self.conn)
        self.assertIn("network_density", result.character_relations)
        self.assertIn("antagonist_strength_gap", result.character_relations)
        self.assertIn("total_changes", result.character_relations)
        self.assertIn("average_clustering", result.character_relations)
        self.assertIn("num_connected_components", result.character_relations)

    def test_aggregate_language_style(self) -> None:
        result = aggregate_all_metrics(self.conn)
        self.assertIn("强硬", result.language_style)

    def test_aggregate_traditional_culture(self) -> None:
        result = aggregate_all_metrics(self.conn)
        self.assertIn("idiom_density", result.traditional_culture)
        self.assertIn("classical_sentence_ratio", result.traditional_culture)


if __name__ == "__main__":
    unittest.main()
