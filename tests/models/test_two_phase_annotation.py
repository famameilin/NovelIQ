"""
创建时间: 2026-03-14
创建者: TraeAI
任务: Chunk 双次调用分析拆分
说明: 测试双次调用相关功能

修改时间: 2026-03-29
修改者: TraeAI
任务: refactor-phase1-identity-extraction
修改内容: 移除 relations 和 character_appearances 相关测试
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.parser import (  # noqa: E402
    build_annotation,
    parse_foreshadowing_result,
    validate_foreshadowing_result,
)
from src.models.local.schema import ForeshadowingResult  # noqa: E402


class TestEmotionalValenceMapping(unittest.TestCase):
    """测试 emotional_valence 五档标准化。"""

    def test_strong_positive_valence_accepted(self) -> None:
        annotation = build_annotation({"emotional_valence": "strong_positive"})
        self.assertEqual(annotation.emotional_valence, "strong_positive")

    def test_mild_positive_valence_accepted(self) -> None:
        annotation = build_annotation({"emotional_valence": "mild_positive"})
        self.assertEqual(annotation.emotional_valence, "mild_positive")

    def test_neutral_valence_accepted(self) -> None:
        annotation = build_annotation({"emotional_valence": "neutral"})
        self.assertEqual(annotation.emotional_valence, "neutral")

    def test_mild_negative_valence_accepted(self) -> None:
        annotation = build_annotation({"emotional_valence": "mild_negative"})
        self.assertEqual(annotation.emotional_valence, "mild_negative")

    def test_strong_negative_valence_accepted(self) -> None:
        annotation = build_annotation({"emotional_valence": "strong_negative"})
        self.assertEqual(annotation.emotional_valence, "strong_negative")

    def test_legacy_positive_defaults_to_neutral(self) -> None:
        annotation = build_annotation({"emotional_valence": "positive"})
        self.assertEqual(annotation.emotional_valence, "neutral")

    def test_legacy_negative_defaults_to_neutral(self) -> None:
        annotation = build_annotation({"emotional_valence": "negative"})
        self.assertEqual(annotation.emotional_valence, "neutral")

    def test_invalid_valence_defaults_to_neutral(self) -> None:
        annotation = build_annotation({"emotional_valence": "invalid_value"})
        self.assertEqual(annotation.emotional_valence, "neutral")


class TestForeshadowingParsing(unittest.TestCase):
    """测试伏笔结果解析。"""

    def test_parse_foreshadowing_with_causal_type(self) -> None:
        data = {
            "has_foreshadowing": True,
            "foreshadowing_type": "causal",
            "anchor_text": "玉佩背面刻着一个归字",
            "anchor_reason": "后文会交代玉佩来历",
            "confidence": "high",
        }
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertEqual(result.foreshadowing_type, "causal")
        self.assertEqual(result.anchor_text, "玉佩背面刻着一个归字")
        self.assertEqual(result.confidence, "high")

    def test_parse_foreshadowing_with_thematic_type(self) -> None:
        data = {
            "has_foreshadowing": True,
            "foreshadowing_type": "thematic",
            "anchor_text": "风吹落叶",
            "anchor_reason": "暗示离别",
            "confidence": "medium",
        }
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertEqual(result.foreshadowing_type, "thematic")
        self.assertEqual(result.confidence, "medium")

    def test_parse_foreshadowing_without_type(self) -> None:
        data = {
            "has_foreshadowing": False,
            "foreshadowing_type": None,
            "anchor_text": "",
            "anchor_reason": "",
            "confidence": "high",
        }
        result = parse_foreshadowing_result(data)
        self.assertFalse(result.has_foreshadowing)
        self.assertIsNone(result.foreshadowing_type)

    def test_parse_foreshadowing_invalid_type_defaults_to_none(self) -> None:
        data = {
            "has_foreshadowing": True,
            "foreshadowing_type": "invalid_type",
            "anchor_text": "some text",
            "anchor_reason": "some reason",
            "confidence": "high",
        }
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertIsNone(result.foreshadowing_type)


class TestForeshadowingValidation(unittest.TestCase):
    """测试伏笔结果验证。"""

    def test_validate_no_foreshadowing_returns_true(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=False,
            foreshadowing_type=None,
            anchor_text="",
            anchor_reason="",
            confidence="high",
        )
        self.assertTrue(validate_foreshadowing_result(result, "any text"))

    def test_validate_low_confidence_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="causal",
            anchor_text="some anchor text",
            anchor_reason="some reason",
            confidence="low",
        )
        self.assertFalse(validate_foreshadowing_result(result, "some anchor text in context"))

    def test_validate_empty_anchor_text_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="causal",
            anchor_text="",
            anchor_reason="some reason",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "any text"))

    def test_validate_short_anchor_text_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="causal",
            anchor_text="ab",
            anchor_reason="some reason",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "ab"))

    def test_validate_anchor_text_not_in_chunk_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="causal",
            anchor_text="玉佩背面刻着归字",
            anchor_reason="伏笔",
            confidence="high",
        )
        chunk_text = "他捡起一块石头，端详片刻后又随手丢开。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_anchor_text_in_chunk_returns_true(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="causal",
            anchor_text="玉佩背面刻着一个归字",
            anchor_reason="伏笔",
            confidence="high",
        )
        chunk_text = "他捡起一块玉佩，玉佩背面刻着一个归字，随手塞进袖中。"
        self.assertTrue(validate_foreshadowing_result(result, chunk_text))


if __name__ == "__main__":
    unittest.main()
