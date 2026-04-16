import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.style_metrics import (
    parse_semantic_category_lexicon,
    semantic_category_densities,
)


class TestParseSemanticCategoryLexicon(unittest.TestCase):
    def setUp(self) -> None:
        self.lexicon_path = str(Path(__file__).resolve().parents[2] / "data" / "lexicons" / "semantic_category.txt")

    def test_parse_returns_dict(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIsInstance(result, dict)

    def test_parse_has_ten_categories(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        expected_keys = {
            "combat",
            "body",
            "relation",
            "faction",
            "command",
            "action",
            "psychology",
            "measure",
            "emotion",
            "color",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_parse_combat_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("combat", result)
        self.assertIn("长剑", result["combat"])
        self.assertIn("宝剑", result["combat"])
        self.assertIn("神功", result["combat"])

    def test_parse_body_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("body", result)
        self.assertIn("头颅", result["body"])
        self.assertIn("心脏", result["body"])

    def test_parse_relation_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("relation", result)
        self.assertIn("父亲", result["relation"])
        self.assertIn("师父", result["relation"])

    def test_parse_faction_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("faction", result)
        self.assertIn("宗门", result["faction"])
        self.assertIn("门派", result["faction"])

    def test_parse_command_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("command", result)
        self.assertIn("命令", result["command"])
        self.assertIn("吩咐", result["command"])

    def test_parse_action_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("action", result)
        self.assertIn("行走", result["action"])
        self.assertIn("奔跑", result["action"])

    def test_parse_psychology_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("psychology", result)
        self.assertIn("思考", result["psychology"])
        self.assertIn("领悟", result["psychology"])

    def test_parse_measure_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("measure", result)
        self.assertIn("巨大", result["measure"])
        self.assertIn("微小", result["measure"])

    def test_parse_emotion_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("emotion", result)
        self.assertIn("欢喜", result["emotion"])
        self.assertIn("愤怒", result["emotion"])

    def test_parse_color_category(self) -> None:
        result = parse_semantic_category_lexicon(self.lexicon_path)
        self.assertIn("color", result)
        self.assertIn("红色", result["color"])
        self.assertIn("金色", result["color"])


class TestSemanticCategoryDensities(unittest.TestCase):
    def test_empty_text(self) -> None:
        category_terms = {"combat": ["长剑", "宝剑"], "body": ["头颅"]}
        result = semantic_category_densities("", category_terms)
        self.assertEqual(result["combat"], 0.0)
        self.assertEqual(result["body"], 0.0)

    def test_single_category_hit(self) -> None:
        category_terms = {"combat": ["长剑", "宝剑"], "body": ["头颅"]}
        text = "他手持长剑"
        result = semantic_category_densities(text, category_terms)
        self.assertGreater(result["combat"], 0.0)
        self.assertEqual(result["body"], 0.0)

    def test_multiple_categories_hit(self) -> None:
        category_terms = {
            "combat": ["长剑", "宝剑"],
            "body": ["头颅", "心脏"],
            "relation": ["父亲", "师父"],
        }
        text = "他手持长剑刺向敌人的心脏"
        result = semantic_category_densities(text, category_terms)
        self.assertGreater(result["combat"], 0.0)
        self.assertGreater(result["body"], 0.0)
        self.assertEqual(result["relation"], 0.0)

    def test_density_calculation(self) -> None:
        category_terms = {"combat": ["剑"]}
        text = "剑剑剑"
        result = semantic_category_densities(text, category_terms)
        self.assertAlmostEqual(result["combat"], 1.0, places=2)

    def test_empty_category_terms(self) -> None:
        category_terms = {"combat": [], "body": ["头颅"]}
        text = "他手持长剑"
        result = semantic_category_densities(text, category_terms)
        self.assertEqual(result["combat"], 0.0)

    def test_all_ten_categories(self) -> None:
        category_terms = {
            "combat": ["长剑"],
            "body": ["头颅"],
            "relation": ["父亲"],
            "faction": ["宗门"],
            "command": ["命令"],
            "action": ["行走"],
            "psychology": ["思考"],
            "measure": ["巨大"],
            "emotion": ["欢喜"],
            "color": ["红色"],
        }
        text = "长剑头颅父亲宗门命令行走思考巨大欢喜红色"
        result = semantic_category_densities(text, category_terms)
        for key in category_terms.keys():
            self.assertIn(key, result)
            self.assertGreaterEqual(result[key], 0.0)

    def test_with_real_lexicon(self) -> None:
        lexicon_path = str(Path(__file__).resolve().parents[2] / "data" / "lexicons" / "semantic_category.txt")
        category_terms = parse_semantic_category_lexicon(lexicon_path)
        text = "他手持长剑，修炼神功，心中思考着父亲的教诲。"
        result = semantic_category_densities(text, category_terms)
        self.assertIn("combat", result)
        self.assertIn("psychology", result)
        self.assertIn("relation", result)
        self.assertGreater(result["combat"], 0.0)


if __name__ == "__main__":
    unittest.main()
