import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.lexicons.parser import parse_semantic_category_lexicon


class TestParseSemanticCategoryLexicon(unittest.TestCase):
    def setUp(self) -> None:
        self.lexicon_path = str(Path(__file__).resolve().parents[2] / "data" / "lexicons" / "semantic_category.txt")

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


if __name__ == "__main__":
    unittest.main()
