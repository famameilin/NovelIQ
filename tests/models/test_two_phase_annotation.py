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
from types import SimpleNamespace

from pydantic import ValidationError

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.annotation.phase2 import _validate_phase2_active_setup_link  # noqa: E402
from src.models.local.parser import (  # noqa: E402
    build_annotation,
    parse_foreshadowing_result,
    validate_foreshadowing_result,
)
from src.models.local.schema import ForeshadowingResult  # noqa: E402

_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "phase2_strong_foreshadowing_cases.py"
_FIXTURE_DATA = runpy.run_path(str(_FIXTURE_PATH))
PHASE2_STRONG_FORESHADOWING_CASES = _FIXTURE_DATA["PHASE2_STRONG_FORESHADOWING_CASES"]


def _valid_positive_payload(**overrides):
    """
    构造满足 setup 池新合同的最小正例 payload。

    创建时间: 2026-04-26
    任务: phase2-setup-pool
    新建原因: 多个解析/校验测试仍需要“合法正例基础上再改一个字段”，集中 helper 可以减少样板并避免漏字段。
    """

    payload = {
        "has_foreshadowing": True,
        "is_strong_setup": True,
        "foreshadowing_type": "物件",
        "setup_kind": "异常物件",
        "anchor_text": "那枚玉佩在夜里自行发热。",
        "anchor_reason": (
            "具体钩子：玉佩在夜里自行发热，表现出非普通饰物特征。"
            "未闭合原因：当前只出现异象，还没有解释它为何会发热。"
        ),
        "setup_summary": "玉佩显露异常反应，后续可能揭示其用途或来历",
        "why_unresolved_now": "当前只出现异象，还没有解释它为何会发热。",
        "expected_payoff_family": "能力触发",
        "payoff_likelihood": "high",
        "is_new_setup": True,
        "linked_setup_id": None,
        "setup_status": "open",
        "confidence": "high",
    }
    payload.update(overrides)
    return payload


def _valid_positive_result(**overrides) -> ForeshadowingResult:
    """基于合法正例 payload 构造 Pydantic 结果。"""

    return ForeshadowingResult(**_valid_positive_payload(**overrides))


def _malformed_positive_result(**overrides) -> ForeshadowingResult:
    """为 validator 测试构造绕过 schema 的脏 positive 结果。"""

    return ForeshadowingResult.model_construct(**_valid_positive_payload(**overrides))


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
        data = _valid_positive_payload(
            foreshadowing_type="物件",
            setup_kind="异常物件",
            anchor_text="玉佩背面刻着一个归字",
            anchor_reason="具体钩子：玉佩出现异常纹样。未闭合原因：当前还没有解释玉佩的来历。",
            setup_summary="玉佩背面归字暗示其真实来历仍待揭示",
            why_unresolved_now="当前还没有解释玉佩的来历。",
            expected_payoff_family="身份揭示",
            confidence="high",
        )
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertTrue(result.is_strong_setup)
        self.assertEqual(result.foreshadowing_type, "物件")
        self.assertEqual(result.setup_kind, "异常物件")
        self.assertEqual(result.anchor_text, "玉佩背面刻着一个归字")
        self.assertEqual(result.why_unresolved_now, "当前还没有解释玉佩的来历。")
        self.assertEqual(result.expected_payoff_family, "身份揭示")
        self.assertEqual(result.confidence, "high")

    def test_parse_foreshadowing_with_scene_type(self) -> None:
        data = _valid_positive_payload(
            foreshadowing_type="场景",
            setup_kind="因果引线",
            anchor_text="风吹落叶",
            anchor_reason="具体钩子：场景里出现反常封锁线索。未闭合原因：当前还没有交代封锁线索会带来什么后果。",
            setup_summary="反常封锁线索出现，后续可能触发规则兑现",
            why_unresolved_now="当前还没有交代封锁线索会带来什么后果。",
            expected_payoff_family="规则兑现",
            confidence="medium",
        )
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertTrue(result.is_strong_setup)
        self.assertEqual(result.foreshadowing_type, "场景")
        self.assertEqual(result.setup_kind, "因果引线")
        self.assertEqual(result.confidence, "medium")

    def test_parse_foreshadowing_without_type(self) -> None:
        data = {
            "has_foreshadowing": False,
            "is_strong_setup": False,
            "foreshadowing_type": None,
            "anchor_text": "",
            "anchor_reason": "",
            "confidence": "high",
        }
        result = parse_foreshadowing_result(data)
        self.assertFalse(result.has_foreshadowing)
        self.assertFalse(result.is_strong_setup)
        self.assertIsNone(result.foreshadowing_type)

    def test_parse_foreshadowing_invalid_confidence_defaults_to_low(self) -> None:
        data = _valid_positive_payload(
            foreshadowing_type="物件",
            setup_kind="异常物件",
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
            why_unresolved_now="当前还没有解释它为何会发热。",
            expected_payoff_family="能力触发",
            confidence="INVALID",
        )
        result = parse_foreshadowing_result(data)
        self.assertEqual(result.confidence, "low")

    def test_parse_foreshadowing_missing_confidence_defaults_to_low(self) -> None:
        data = _valid_positive_payload(
            foreshadowing_type="物件",
            setup_kind="异常物件",
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
            why_unresolved_now="当前还没有解释它为何会发热。",
            expected_payoff_family="能力触发",
        )
        data.pop("confidence", None)
        result = parse_foreshadowing_result(data)
        self.assertEqual(result.confidence, "low")

    def test_parse_foreshadowing_string_false_bools_stay_negative(self) -> None:
        """测试字符串 false 不会再被误判成强伏笔正例。"""
        data = {
            "has_foreshadowing": "false",
            "is_strong_setup": "false",
            "foreshadowing_type": None,
            "setup_kind": None,
            "anchor_text": "",
            "anchor_reason": "",
            "why_unresolved_now": "",
            "expected_payoff_family": "",
            "confidence": "low",
        }
        result = parse_foreshadowing_result(data)
        self.assertFalse(result.has_foreshadowing)
        self.assertFalse(result.is_strong_setup)
        self.assertIsNone(result.foreshadowing_type)
        self.assertIsNone(result.setup_kind)

    def test_parse_foreshadowing_string_true_bools_stay_positive(self) -> None:
        """测试字符串 true 仍能被归一化成合法强伏笔正例。"""
        data = _valid_positive_payload(
            has_foreshadowing="true",
            is_strong_setup="true",
            foreshadowing_type="物件",
            setup_kind="异常物件",
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
            why_unresolved_now="当前还没有解释它为何会发热。",
            expected_payoff_family="能力触发",
            confidence="high",
        )
        result = parse_foreshadowing_result(data)
        self.assertTrue(result.has_foreshadowing)
        self.assertTrue(result.is_strong_setup)
        self.assertEqual(result.foreshadowing_type, "物件")
        self.assertEqual(result.setup_kind, "异常物件")

    def test_parse_foreshadowing_invalid_boolean_string_raises_value_error(self) -> None:
        """测试未知布尔字符串不会被静默吞掉。"""
        data = {
            "has_foreshadowing": "maybe",
            "is_strong_setup": False,
            "foreshadowing_type": None,
            "setup_kind": None,
            "anchor_text": "",
            "anchor_reason": "",
            "why_unresolved_now": "",
            "expected_payoff_family": "",
            "confidence": "low",
        }
        with self.assertRaises(ValueError):
            parse_foreshadowing_result(data)

    def test_parse_foreshadowing_invalid_type_raises_validation_error(self) -> None:
        data = _valid_positive_payload(
            foreshadowing_type="invalid_type",
            anchor_text="some text",
            anchor_reason="some reason",
            confidence="high",
        )
        with self.assertRaises(ValidationError):
            parse_foreshadowing_result(data)

    def test_parse_positive_with_low_payoff_likelihood_raises_validation_error(self) -> None:
        data = _valid_positive_payload(payoff_likelihood="low")

        with self.assertRaises(ValidationError):
            parse_foreshadowing_result(data)

    def test_parse_high_confidence_medium_payoff_likelihood_stays_positive(self) -> None:
        """
        创建时间: 2026-04-29
        任务: foreshadow-expectation-v2
        新建原因: `confidence` 与 `payoff_likelihood` 已拆开，high confidence + medium payoff 应保留为合法入池正例。
        """

        data = _valid_positive_payload(payoff_likelihood="medium", confidence="high")

        result = parse_foreshadowing_result(data)

        self.assertTrue(result.has_foreshadowing)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.payoff_likelihood, "medium")


class TestForeshadowingValidation(unittest.TestCase):
    """测试伏笔结果验证。"""

    def test_validate_no_foreshadowing_returns_true(self) -> None:
        result = ForeshadowingResult(
            has_foreshadowing=False,
            is_strong_setup=False,
            foreshadowing_type=None,
            anchor_text="",
            anchor_reason="",
            confidence="high",
        )
        self.assertTrue(validate_foreshadowing_result(result, "any text"))

    def test_validate_negative_with_stale_strong_setup_fields_returns_false(self) -> None:
        result = ForeshadowingResult.model_construct(
            has_foreshadowing=False,
            is_strong_setup=True,
            foreshadowing_type=None,
            setup_kind="异常物件",
            anchor_text="",
            anchor_reason="具体钩子：无。未闭合原因：这里只是在解释为什么不是伏笔。",
            why_unresolved_now="",
            expected_payoff_family="",
            confidence="low",
        )
        self.assertFalse(validate_foreshadowing_result(result, "any text"))

    def test_validate_low_confidence_returns_false(self) -> None:
        result = _valid_positive_result(
            anchor_text="some anchor text",
            anchor_reason="具体钩子：异常物件出现。未闭合原因：当前还没有解释它的用途。",
            setup_summary="异常物件出现但用途仍未解释",
            why_unresolved_now="当前还没有解释它的用途。",
            expected_payoff_family="能力触发",
            confidence="low",
        )
        self.assertFalse(validate_foreshadowing_result(result, "some anchor text in context"))

    def test_validate_medium_confidence_returns_false(self) -> None:
        result = _valid_positive_result(
            anchor_text="玉佩背面刻着一个归字",
            anchor_reason="具体钩子：玉佩出现异常纹样。未闭合原因：当前还没有解释玉佩的来历。",
            setup_summary="玉佩归字暗示其来历待揭示",
            why_unresolved_now="当前还没有解释玉佩的来历。",
            expected_payoff_family="身份揭示",
            confidence="medium",
        )
        self.assertFalse(validate_foreshadowing_result(result, "他捡起一块玉佩，玉佩背面刻着一个归字。"))

    def test_validate_positive_without_type_returns_false(self) -> None:
        result = ForeshadowingResult.model_construct(
            has_foreshadowing=True,
            is_strong_setup=True,
            foreshadowing_type=None,
            setup_kind="异常物件",
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热，表现出非普通饰物特征。未闭合原因：当前只出现异象，还没有解释它为何会发热。",
            why_unresolved_now="当前只出现异象，还没有解释它为何会发热。",
            expected_payoff_family="能力触发",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "那枚玉佩在夜里自行发热。"))

    def test_validate_positive_without_structured_fields_returns_false(self) -> None:
        result = ForeshadowingResult.model_construct(
            has_foreshadowing=True,
            is_strong_setup=False,
            foreshadowing_type="物件",
            setup_kind=None,
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热，表现出非普通饰物特征。未闭合原因：当前只出现异象，还没有解释它为何会发热。",
            why_unresolved_now="",
            expected_payoff_family="",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "那枚玉佩在夜里自行发热。"))

    def test_validate_positive_with_low_payoff_likelihood_returns_false(self) -> None:
        result = _malformed_positive_result(payoff_likelihood="low")

        self.assertFalse(validate_foreshadowing_result(result, "那枚玉佩在夜里自行发热。"))

    def test_validate_high_confidence_medium_payoff_likelihood_returns_true(self) -> None:
        """
        创建时间: 2026-04-29
        任务: foreshadow-expectation-v2
        新建原因: medium payoff 现在表示回收路径不够稳，但只要 confidence=high 且钩子具体，仍应允许进入强 setup 池。
        """

        result = _valid_positive_result(payoff_likelihood="medium", confidence="high")

        self.assertTrue(validate_foreshadowing_result(result, "那枚玉佩在夜里自行发热。"))

    def test_validate_punishment_special_treatment_description_returns_false(self) -> None:
        """
        创建时间: 2026-04-29
        任务: foreshadow-expectation-v2
        新建原因: 处罚规格/特殊待遇描写不应因看起来“特殊”就进入强 setup 池污染 expectation 分母。
        """

        result = _valid_positive_result(
            setup_kind="异常物件",
            anchor_text="钢筋高帽和铁门牌子",
            anchor_reason=(
                "具体钩子：钢筋高帽和铁门牌子构成异常特殊待遇。"
                "未闭合原因：当前还没有解释这种处罚规格会怎样影响他的后续命运。"
            ),
            setup_summary="钢筋高帽和铁门牌子暗示他遭受特殊待遇",
            why_unresolved_now="当前还没有解释这种处罚规格会怎样影响他的后续命运。",
            expected_payoff_family="命运变差",
        )

        self.assertFalse(validate_foreshadowing_result(result, "他被迫戴上钢筋高帽和铁门牌子。"))

    def test_validate_chunk_223_transition_reveal_teaser_new_setup_returns_false(self) -> None:
        """
        创建时间: 2026-04-29
        任务: foreshadow-expectation-v2
        新建原因: 临近揭示前的“接下来展示/揭示真相”类过渡预告不应单独新建 high thread。
        """

        result = _valid_positive_result(
            foreshadowing_type="对话",
            setup_kind="明确承诺",
            anchor_text="接下来会展示截获的信息，揭示三体文明的真相。",
            anchor_reason=(
                "具体钩子：文本承诺接下来会展示截获的信息并揭示三体文明真相。"
                "未闭合原因：当前还没有展示截获信息，也没有揭示三体文明真相。"
            ),
            setup_summary="接下来展示截获信息并揭示三体文明真相",
            why_unresolved_now="当前还没有展示截获信息，也没有揭示三体文明真相。",
            expected_payoff_family="其他",
            is_new_setup=True,
            linked_setup_id=None,
            setup_status="open",
        )

        self.assertFalse(validate_foreshadowing_result(result, "接下来会展示截获的信息，揭示三体文明的真相。"))

    def test_validate_transition_reveal_teaser_linked_thread_can_pass(self) -> None:
        """
        创建时间: 2026-04-29
        任务: foreshadow-expectation-v2
        新建原因: 过渡预告只禁止单独开新 thread；如果明确强化已有 setup，仍应允许 ledger 记录推进。
        """

        result = _valid_positive_result(
            foreshadowing_type="对话",
            setup_kind="明确承诺",
            anchor_text="接下来会展示截获的信息，揭示三体文明的真相。",
            anchor_reason=(
                "具体钩子：文本承诺接下来会展示截获的信息并揭示三体文明真相。"
                "未闭合原因：当前还没有展示截获信息，也没有揭示三体文明真相。"
            ),
            setup_summary="接下来展示截获信息并揭示三体文明真相",
            why_unresolved_now="当前还没有展示截获信息，也没有揭示三体文明真相。",
            expected_payoff_family="其他",
            is_new_setup=False,
            linked_setup_id="setup-223",
            setup_status="reinforced",
        )

        self.assertTrue(validate_foreshadowing_result(result, "接下来会展示截获的信息，揭示三体文明的真相。"))

    def test_validate_empty_anchor_text_returns_false(self) -> None:
        result = _malformed_positive_result(
            anchor_text="",
            anchor_reason="具体钩子：异常物件出现。未闭合原因：当前还没有解释它的用途。",
            setup_summary="异常物件出现但用途仍未解释",
            why_unresolved_now="当前还没有解释它的用途。",
            expected_payoff_family="能力触发",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "any text"))

    def test_validate_short_anchor_text_returns_false(self) -> None:
        result = _malformed_positive_result(
            anchor_text="ab",
            anchor_reason="具体钩子：异常物件出现。未闭合原因：当前还没有解释它的用途。",
            setup_summary="异常物件出现但用途仍未解释",
            why_unresolved_now="当前还没有解释它的用途。",
            expected_payoff_family="能力触发",
            confidence="high",
        )
        self.assertFalse(validate_foreshadowing_result(result, "ab"))

    def test_validate_anchor_text_not_in_chunk_returns_false(self) -> None:
        result = _valid_positive_result(
            anchor_text="玉佩背面刻着归字",
            anchor_reason="具体钩子：玉佩出现异常纹样。未闭合原因：当前还没有解释玉佩的来历。",
            setup_summary="玉佩归字暗示其来历待揭示",
            why_unresolved_now="当前还没有解释玉佩的来历。",
            expected_payoff_family="身份揭示",
            confidence="high",
        )
        chunk_text = "他捡起一块石头，端详片刻后又随手丢开。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_reason_without_required_sections_returns_false(self) -> None:
        result = _valid_positive_result(
            anchor_text="玉佩背面刻着一个归字",
            anchor_reason="玉佩很异常，后面应该会有用。",
            setup_summary="玉佩归字暗示其来历待揭示",
            why_unresolved_now="当前还没有解释玉佩的来历。",
            expected_payoff_family="身份揭示",
            confidence="high",
        )
        chunk_text = "他捡起一块玉佩，玉佩背面刻着一个归字，随手塞进袖中。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_generic_theme_reason_returns_false(self) -> None:
        result = _valid_positive_result(
            foreshadowing_type="场景",
            setup_kind="其他",
            anchor_text="在中国，任何超脱飞扬的思想都会砰然坠地的，现实的引力太沉重了。",
            anchor_reason="具体钩子：这句话体现主题和时代压力。未闭合原因：后文可能继续展开这种悲剧氛围。",
            setup_summary="时代现实会压垮超脱思想",
            why_unresolved_now="后文可能继续展开这种悲剧氛围。",
            expected_payoff_family="主题展开",
            confidence="high",
        )
        chunk_text = "在中国，任何超脱飞扬的思想都会砰然坠地的，现实的引力太沉重了。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_everyday_decision_returns_false(self) -> None:
        result = _valid_positive_result(
            foreshadowing_type="人物行为",
            setup_kind="其他",
            anchor_text="她决定明天去镇上卖药。",
            anchor_reason="具体钩子：人物做出明天去镇上卖药的决定。未闭合原因：当前只是提出决定，尚未执行。",
            setup_summary="她决定明天去镇上卖药",
            why_unresolved_now="当前只是提出决定，尚未执行。",
            expected_payoff_family="重大行动",
            confidence="high",
        )
        chunk_text = "她决定明天去镇上卖药。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_formal_setup_kind_still_requires_concrete_signal(self) -> None:
        result = _valid_positive_result(
            foreshadowing_type="人物行为",
            setup_kind="明确承诺",
            anchor_text="她决定明天去镇上卖药。",
            anchor_reason="具体钩子：人物决定明天去镇上卖药。未闭合原因：当前只是提出决定，尚未执行。",
            setup_summary="她决定明天去镇上卖药",
            why_unresolved_now="当前只是提出决定，尚未执行。",
            expected_payoff_family="重大行动",
            confidence="high",
        )
        chunk_text = "她决定明天去镇上卖药。"
        self.assertFalse(validate_foreshadowing_result(result, chunk_text))

    def test_validate_concrete_future_wording_with_specific_target_returns_true(self) -> None:
        result = _valid_positive_result(
            anchor_text="那枚玉佩在阳光下泛着诡异的红光，伯安总觉得它在盯着自己看。",
            anchor_reason=(
                "具体钩子：玉佩出现异常红光并带有主动注视感，显示它不是普通饰物。"
                "未闭合原因：当前只暴露了异常现象，还没有解释玉佩的来历，后续可能揭示其真正用途。"
            ),
            setup_summary="玉佩出现异常红光并带有注视感，后续可能揭示其能力或来历",
            why_unresolved_now="当前只暴露了异常现象，还没有解释玉佩的来历，后续可能揭示其真正用途。",
            expected_payoff_family="能力触发",
            confidence="high",
        )
        chunk_text = "那枚玉佩在阳光下泛着诡异的红光，伯安总觉得它在盯着自己看。"
        self.assertTrue(validate_foreshadowing_result(result, chunk_text))

    def test_validate_anomalous_object_without_legacy_whitelist_keyword_returns_true(self) -> None:
        result = _valid_positive_result(
            anchor_text="那枚玉佩在夜里自行发热。",
            anchor_reason="具体钩子：玉佩在夜里自行发热，表现出非普通饰物特征。未闭合原因：当前只出现异象，还没有解释它为何会发热。",
            why_unresolved_now="当前只出现异象，还没有解释它为何会发热。",
            expected_payoff_family="能力触发",
            confidence="high",
        )
        chunk_text = "那枚玉佩在夜里自行发热。"
        self.assertTrue(validate_foreshadowing_result(result, chunk_text))

    def test_validate_anchor_text_in_chunk_returns_true(self) -> None:
        result = _valid_positive_result(
            foreshadowing_type="人物行为",
            setup_kind="因果引线",
            anchor_text="人类真正的道德自觉是不可能的，就像他们不可能拔着自己的头发离开大地。要做到这一点，只有借助于人类之外的力量。",
            anchor_reason=(
                "具体钩子：叶文洁把“借助于人类之外的力量”明确设定为解决人类道德困境的出路，"
                "这构成后续重大行动的核心思想钩子。未闭合原因：当前文本只展示她形成这一判断的思想转折，"
                "还没有揭示她会借助什么外部力量，也没有兑现这条判断将引出的后续行动。"
            ),
            setup_summary="叶文洁认定必须借助人类之外的力量改变人类道德困境",
            why_unresolved_now="当前文本只展示她形成这一判断的思想转折，还没有揭示她会借助什么外部力量，也没有兑现这条判断将引出的后续行动。",
            expected_payoff_family="重大行动",
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
                if case["expected_is_strong_setup"]:
                    result = ForeshadowingResult(**case["result"])
                else:
                    # 中文注释：这些样例代表“旧 prompt/旧模型可能给出的脏 positive 输出”，
                    # 现在真实热路径会在结构化校验阶段前置拒绝；这里仍保留 model_construct，
                    # 继续覆盖 projector/validator 的兜底拒绝语义。
                    result = ForeshadowingResult.model_construct(**case["result"])
                self.assertEqual(
                    validate_foreshadowing_result(result, case["chunk_text"]),
                    case["expected_is_strong_setup"],
                )


class TestPhase2SetupPoolLinkValidation(unittest.TestCase):
    """测试 Phase2 setup 池链接校验。"""

    def test_validate_phase2_active_setup_link_rejects_mismatched_visible_thread(self) -> None:
        result = _valid_positive_result(
            is_new_setup=False,
            linked_setup_id="setup-1",
            setup_status="reinforced",
            setup_summary="玉佩出现异常红光，后续可能揭示其能力或来历",
            setup_kind="异常物件",
            expected_payoff_family="能力触发",
        )
        active_setup_pool = [
            SimpleNamespace(
                setup_id="setup-1",
                setup_summary="铜铃在雨夜自行作响，后续可能暴露禁制规则",
                setup_kind="异常规则",
                expected_payoff_family="规则兑现",
            )
        ]

        with self.assertRaises(ValueError):
            _validate_phase2_active_setup_link(result, active_setup_pool)

    def test_validate_phase2_active_setup_link_accepts_matching_visible_thread(self) -> None:
        result = _valid_positive_result(
            is_new_setup=False,
            linked_setup_id="setup-1",
            setup_status="reinforced",
            setup_summary="玉佩出现异常红光，后续可能揭示其能力或来历",
            setup_kind="异常物件",
            expected_payoff_family="能力触发",
        )
        active_setup_pool = [
            SimpleNamespace(
                setup_id="setup-1",
                setup_summary="玉佩出现异常红光，后续可能揭示其能力或来历。",
                setup_kind="异常物件",
                expected_payoff_family="能力触发",
            )
        ]

        _validate_phase2_active_setup_link(result, active_setup_pool)


if __name__ == "__main__":
    unittest.main()
