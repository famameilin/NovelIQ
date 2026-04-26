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

import runpy
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

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "phase2_strong_foreshadowing_cases.py"
_FIXTURE_DATA = runpy.run_path(str(_FIXTURE_PATH))
PHASE2_STRONG_FORESHADOWING_CASES = _FIXTURE_DATA["PHASE2_STRONG_FORESHADOWING_CASES"]


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

    def test_parse_foreshadowing_with_object_type(self) -> None:
        data = {
            "has_foreshadowing": True,
            "foreshadowing_type": "物件",
            "anchor_text": "玉佩背面刻着一个归字",
            "anchor_reason": "具体钩子：玉佩出现异常纹样。未闭合原因：当前还没有解释玉佩的来历。",
            "confidence": "high",
        }
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertEqual(result.foreshadowing_type, "物件")
        self.assertEqual(result.anchor_text, "玉佩背面刻着一个归字")
        self.assertEqual(result.confidence, "high")

    def test_parse_foreshadowing_with_scene_type(self) -> None:
        data = {
            "has_foreshadowing": True,
            "foreshadowing_type": "场景",
            "anchor_text": "风吹落叶",
            "anchor_reason": "具体钩子：场景里出现反常封锁线索。未闭合原因：当前还没有交代封锁线索会带来什么后果。",
            "confidence": "medium",
        }
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertEqual(result.foreshadowing_type, "场景")
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
            foreshadowing_type="物件",
            anchor_text="some anchor text",
            anchor_reason="具体钩子：异常物件出现。未闭合原因：当前还没有解释它的用途。",
            confidence="low",
        )
        self.assertFalse(validate_foreshadowing_result(result, "some anchor text in context"))

    def test_validate_medium_confidence_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="玉佩背面刻着一个归字",
            anchor_reason="具体钩子：玉佩出现异常纹样。未闭合原因：当前还没有解释玉佩的来历。",
            confidence="medium",
        )
        self.assertFalse(validate_foreshadowing_result(result, "他捡起一块玉佩，玉佩背面刻着一个归字。"))

    def test_validate_empty_anchor_text_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="",
            anchor_reason="具体钩子：异常物件出现。未闭合原因：当前还没有解释它的用途。",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "any text"))

    def test_validate_short_anchor_text_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="ab",
            anchor_reason="具体钩子：异常物件出现。未闭合原因：当前还没有解释它的用途。",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "ab"))

    def test_validate_anchor_text_not_in_chunk_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="玉佩背面刻着归字",
            anchor_reason="具体钩子：玉佩出现异常纹样。未闭合原因：当前还没有解释玉佩的来历。",
            confidence="high",
        )
        chunk_text = "他捡起一块石头，端详片刻后又随手丢开。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_reason_without_required_sections_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="玉佩背面刻着一个归字",
            anchor_reason="玉佩很异常，后面应该会有用。",
            confidence="high",
        )
        chunk_text = "他捡起一块玉佩，玉佩背面刻着一个归字，随手塞进袖中。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_generic_theme_reason_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="场景",
            anchor_text="在中国，任何超脱飞扬的思想都会砰然坠地的，现实的引力太沉重了。",
            anchor_reason="具体钩子：这句话体现主题和时代压力。未闭合原因：后文可能继续展开这种悲剧氛围。",
            confidence="high",
        )
        chunk_text = "在中国，任何超脱飞扬的思想都会砰然坠地的，现实的引力太沉重了。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_everyday_decision_returns_false(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="人物行为",
            anchor_text="她决定明天去镇上卖药。",
            anchor_reason="具体钩子：人物做出明天去镇上卖药的决定。未闭合原因：当前只是提出决定，尚未执行。",
            confidence="high",
        )
        chunk_text = "她决定明天去镇上卖药。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_concrete_future_wording_with_specific_target_returns_true(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="那枚玉佩在阳光下泛着诡异的红光，伯安总觉得它在盯着自己看。",
            anchor_reason=(
                "具体钩子：玉佩出现异常红光并带有主动注视感，显示它不是普通饰物。"
                "未闭合原因：当前只暴露了异常现象，还没有解释玉佩的来历，后续可能揭示其真正用途。"
            ),
            confidence="high",
        )
        chunk_text = "那枚玉佩在阳光下泛着诡异的红光，伯安总觉得它在盯着自己看。"
        self.assertTrue(validate_foreshadowing_result(result, chunk_text))

    def test_validate_anomalous_object_without_legacy_whitelist_keyword_returns_true(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热，表现出非普通饰物特征。未闭合原因：当前只出现异象，还没有解释它为何会发热。",
            confidence="high",
        )
        chunk_text = "那枚玉佩在夜里自行发热。"
        self.assertTrue(validate_foreshadowing_result(result, chunk_text))

    def test_validate_anchor_text_in_chunk_returns_true(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="人物行为",
            anchor_text="人类真正的道德自觉是不可能的，就像他们不可能拔着自己的头发离开大地。要做到这一点，只有借助于人类之外的力量。",
            anchor_reason=(
                "具体钩子：叶文洁把“借助于人类之外的力量”明确设定为解决人类道德困境的出路，"
                "这构成后续重大行动的核心思想钩子。未闭合原因：当前文本只展示她形成这一判断的思想转折，"
                "还没有揭示她会借助什么外部力量，也没有兑现这条判断将引出的后续行动。"
            ),
            confidence="high",
        )
        chunk_text = (
            "也许，人类和邪恶的关系，就是大洋与漂浮于其上的冰山的关系……"
            "人类真正的道德自觉是不可能的，就像他们不可能拔着自己的头发离开大地。"
            "要做到这一点，只有借助于人类之外的力量。"
        )
        self.assertTrue(validate_foreshadowing_result(result, chunk_text))

    def test_real_phase2_regression_cases_follow_strong_setup_gate(self) -> None:
        for case in PHASE2_STRONG_FORESHADOWING_CASES:
            with self.subTest(case_id=case["case_id"]):
                result = ForeshadowingResult(**case["result"])
                self.assertEqual(
                    validate_foreshadowing_result(result, case["chunk_text"]),
                    case["expected_is_strong_setup"],
                )


if __name__ == "__main__":
    unittest.main()
