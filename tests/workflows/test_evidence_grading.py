import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import ExtendedDisambigResult, build_evidence_profile
from src.workflows.annotate_helpers.disambiguation import (
    validate_confidence_with_evidence,
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_CONFIDENCE_MEDIUM,
)


class TestValidateConfidenceWithEvidence(unittest.TestCase):
    """
    测试置信度校验逻辑

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: disambiguation-evidence-grading
    说明: 测试证据分级约束规则
    """

    def test_weak_evidence_downgrades_high_to_medium(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"灰衣人": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"灰衣人": build_evidence_profile("【前文总结】灰衣人伯安现身")},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["灰衣人"], DISAMBIG_CONFIDENCE_MEDIUM)

    def test_strong_evidence_keeps_high(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"贺重明": build_evidence_profile("贺重明的真实身份是伯安 | 【身份提示】贺重明其实就是伯安")},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["贺重明"], DISAMBIG_CONFIDENCE_HIGH)

    def test_weak_evidence_prevents_merge_to_existing_character(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"灰衣人": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"灰衣人": build_evidence_profile("【前文总结】灰衣人伯安现身")},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"])

        self.assertEqual(validated.canonical_decisions["灰衣人"], "灰衣人")
        self.assertEqual(validated.alias_confidence["灰衣人"], DISAMBIG_CONFIDENCE_MEDIUM)

    def test_strong_evidence_allows_merge_to_existing_character(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"贺重明": build_evidence_profile("贺重明的真实身份是伯安 | 【身份提示】贺重明其实就是伯安")},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"])

        self.assertEqual(validated.canonical_decisions["贺重明"], "伯安")
        self.assertEqual(validated.alias_confidence["贺重明"], DISAMBIG_CONFIDENCE_HIGH)

    def test_mixed_evidence_keeps_high(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"贺重明": build_evidence_profile("【前文总结】伯安出手 | 【身份提示】贺重明其实就是伯安")},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["贺重明"], DISAMBIG_CONFIDENCE_HIGH)

    def test_empty_context_downgrades_high_to_medium(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"伯安": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"伯安": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"伯安": build_evidence_profile("")},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["伯安"], DISAMBIG_CONFIDENCE_MEDIUM)

    def test_self_mapping_not_affected_by_weak_evidence(self) -> None:
        result = ExtendedDisambigResult(
            canonical_decisions={"灰衣人": "灰衣人"},
            entity_types={"灰衣人": "character"},
            entity_relations=[],
            alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"灰衣人": build_evidence_profile("【前文总结】灰衣人伯安现身")},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"])

        self.assertEqual(validated.canonical_decisions["灰衣人"], "灰衣人")

    def test_strong_unique_marker_promotes_self_mapping_to_existing_character(self) -> None:
        context = (
            "【前文总结】贺伯安为救同伴被火焰吞噬昏迷\n"
            "赵兰英想起贺伯安脊椎处的白金火焰符号，怀里的婴孩脊椎处也有同样印记"
        )
        result = ExtendedDisambigResult(
            canonical_decisions={"婴儿": "婴儿"},
            entity_types={"婴儿": "character"},
            entity_relations=[],
            alias_confidence={"婴儿": DISAMBIG_CONFIDENCE_MEDIUM},
            evidence_profiles={"婴儿": build_evidence_profile(context)},
        )

        validated = validate_confidence_with_evidence(result, ["贺伯安"], {"婴儿": context})

        self.assertEqual(validated.canonical_decisions["婴儿"], "贺伯安")
        self.assertEqual(validated.alias_confidence["婴儿"], DISAMBIG_CONFIDENCE_HIGH)


if __name__ == "__main__":
    unittest.main()
