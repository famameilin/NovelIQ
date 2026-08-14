import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.character_metrics import (
    compute_antagonist_strength_gap,
    compute_average_clustering,
    compute_character_closeness_centrality,
    compute_character_degree_centrality,
    compute_character_eigenvector_centrality,
    compute_character_function_coverage,
    compute_clustering_coefficient,
    compute_greimas_coverage,
    compute_largest_component_size,
    compute_number_of_connected_components,
    compute_protagonist_betweenness,
    compute_relation_change_frequency,
    compute_relation_network_density,
)


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
        self.assertEqual(result, 0.0)

    def test_multiple_relations(self) -> None:
        result = compute_relation_network_density([("A", "B"), ("A", "C")])
        self.assertEqual(result, 1.0)

    def test_density_includes_isolated_nodes_when_node_names_are_provided(self) -> None:
        result = compute_relation_network_density(
            [("A", "B"), ("B", "C"), ("A", "B")],
            node_names=["A", "B", "C", "D"],
        )
        self.assertAlmostEqual(result, 4 / 6, places=6)


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
        for func in ["主体", "客体", "发送者", "接收者", "帮助者", "反对者", "其他"]:
            self.assertEqual(result[func], 0.0)

    def test_role_distribution(self) -> None:
        result = compute_character_function_coverage(["主体", "反对者", "帮助者"])
        self.assertAlmostEqual(result["主体"], 1 / 3, places=6)
        self.assertAlmostEqual(result["反对者"], 1 / 3, places=6)
        self.assertAlmostEqual(result["帮助者"], 1 / 3, places=6)


class TestGreimasCoverage(unittest.TestCase):
    def test_empty_roles(self) -> None:
        result = compute_greimas_coverage([])
        self.assertEqual(result, 0.0)

    def test_partial_coverage(self) -> None:
        result = compute_greimas_coverage(["主体", "反对者", "帮助者"])
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_full_coverage(self) -> None:
        result = compute_greimas_coverage(["主体", "客体", "发送者", "接收者", "帮助者", "反对者"])
        self.assertEqual(result, 1.0)


class TestAntagonistStrengthGap(unittest.TestCase):
    def test_empty_characters(self) -> None:
        result = compute_antagonist_strength_gap([])
        self.assertEqual(result, 0.0)

    def test_no_protagonist(self) -> None:
        result = compute_antagonist_strength_gap([("反派", "反对者", 5)])
        self.assertEqual(result, 0.0)

    def test_with_both_roles(self) -> None:
        characters = [
            ("主角", "主体", 4),
            ("反派", "反对者", 3),
        ]
        result = compute_antagonist_strength_gap(characters)
        self.assertEqual(result, 1.0)


class TestRelationChangeFrequency(unittest.TestCase):
    """2026-08-14 修复（§19.10）：change_rate 分母从章节数改为全书总字数（每万字频率）。"""

    def test_empty_relations(self) -> None:
        result = compute_relation_change_frequency([], 10000)
        self.assertEqual(result["total_changes"], 0.0)
        self.assertEqual(result["change_rate"], 0.0)
        self.assertEqual(result["新建_rate"], 0.0)
        self.assertEqual(result["强化_rate"], 0.0)
        self.assertEqual(result["弱化_rate"], 0.0)
        self.assertEqual(result["断裂_rate"], 0.0)

    def test_change_rate_per_10k_chars(self) -> None:
        relations = [
            ("A", "B", "盟友", "强化"),
            ("A", "C", "敌对", "新建"),
            ("A", "D", "敌对", "新建"),
        ]
        result = compute_relation_change_frequency(relations, 10000)
        self.assertEqual(result["total_changes"], 3.0)
        self.assertEqual(result["change_rate"], 3.0)

    def test_change_rate_zero_chars_returns_zero(self) -> None:
        result = compute_relation_change_frequency([("A", "B", "盟友", "强化")], 0)
        self.assertEqual(result["total_changes"], 0.0)
        self.assertEqual(result["change_rate"], 0.0)

    def test_change_frequency(self) -> None:
        relations = [
            ("A", "B", "盟友", "强化"),
            ("A", "C", "敌对", "新建"),
        ]
        result = compute_relation_change_frequency(relations, 10000)
        self.assertEqual(result["total_changes"], 2.0)
        self.assertEqual(result["change_rate"], 2.0)

    def test_change_frequency_english_change_kind(self) -> None:
        """2026-08-13 修复 P1：数据源 change_kind 是英文枚举（assert/reinforce/...），
        此前用中文键计数导致四个 *_rate 恒为 0。"""
        relations = [
            ("A", "B", "盟友", "assert"),
            ("A", "B", "盟友", "reinforce"),
            ("A", "B", "盟友", "weaken"),
            ("A", "C", "敌对", "assert"),
            ("A", "D", "敌对", "break"),
            ("A", "D", "敌对", "retract"),
        ]
        result = compute_relation_change_frequency(relations, 20000)
        self.assertEqual(result["total_changes"], 6.0)
        self.assertEqual(result["change_rate"], 3.0)
        self.assertEqual(result["新建_rate"], 2 / 6)
        self.assertEqual(result["强化_rate"], 1 / 6)
        self.assertEqual(result["弱化_rate"], 1 / 6)
        self.assertEqual(result["断裂_rate"], 2 / 6)

    def test_change_frequency_refine_and_supersede_not_counted_in_rates(self) -> None:
        """refine/supersede（类型修正/替换）不归入四类变化率，仅计入总量。"""
        relations = [
            ("A", "B", "盟友", "refine"),
            ("A", "B", "盟友", "supersede"),
            ("A", "B", "盟友", "assert"),
        ]
        result = compute_relation_change_frequency(relations, 10000)
        self.assertEqual(result["total_changes"], 3.0)
        self.assertEqual(result["change_rate"], 3.0)
        self.assertEqual(result["新建_rate"], 1 / 3)
        self.assertEqual(result["强化_rate"], 0.0)
        self.assertEqual(result["弱化_rate"], 0.0)
        self.assertEqual(result["断裂_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
