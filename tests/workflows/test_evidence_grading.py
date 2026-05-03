import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import ExtendedDisambigResult, build_evidence_profile
from src.workflows.annotate_helpers.disambiguation import (
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_CONFIDENCE_MEDIUM,
    validate_confidence_with_evidence,
)


class TestValidateConfidenceWithEvidence(unittest.TestCase):
    """
    测试置信度校验逻辑

    创建时间: 2026-03-26
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
            evidence_profiles={
                "贺重明": build_evidence_profile("贺重明的真实身份是伯安 | 【身份提示】贺重明其实就是伯安")
            },
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
            evidence_profiles={
                "贺重明": build_evidence_profile("贺重明的真实身份是伯安 | 【身份提示】贺重明其实就是伯安")
            },
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
            evidence_profiles={
                "贺重明": build_evidence_profile("【前文总结】伯安出手 | 【身份提示】贺重明其实就是伯安")
            },
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

    def test_kinship_identity_does_not_override_self_mapping(self) -> None:
        context = "【身份线索】白芷的哥哥是贺铮"
        result = ExtendedDisambigResult(
            canonical_decisions={"白芷": "白芷"},
            entity_types={"白芷": "character"},
            entity_relations=[],
            alias_confidence={"白芷": DISAMBIG_CONFIDENCE_MEDIUM},
            evidence_profiles={"白芷": build_evidence_profile(context)},
        )

        validated = validate_confidence_with_evidence(result, ["贺铮"], {"白芷": context})

        self.assertEqual(validated.canonical_decisions["白芷"], "白芷")

    def test_protected_candidate_without_strong_evidence_cannot_merge(self) -> None:
        """
        创建时间: 2026-04-20
        任务: enforce-protected-disambig-gate
        说明: 受保护候选即便被模型判成 merge，如果只有一般上下文而无强证据，后端也必须打回自映射。
        """
        context = "【受保护-默认不合并】侍卫一路跟在伯安身侧，替他牵马开路"
        result = ExtendedDisambigResult(
            canonical_decisions={"侍卫": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"侍卫": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"侍卫": build_evidence_profile(context)},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"], {"侍卫": context})

        self.assertEqual(validated.canonical_decisions["侍卫"], "侍卫")
        self.assertEqual(validated.alias_confidence["侍卫"], DISAMBIG_CONFIDENCE_MEDIUM)

    def test_protected_candidate_with_naming_scene_can_merge(self) -> None:
        """
        创建时间: 2026-04-20
        任务: enforce-protected-disambig-gate
        说明: 受保护候选若出现“本名/人称”这类命名场景，应保留强证据合并通道。
        """
        context = "【受保护-默认不合并】【命名场景】此女本名柳婉儿，人称柳妹妹"
        result = ExtendedDisambigResult(
            canonical_decisions={"丫鬟": "柳婉儿"},
            entity_types={"柳婉儿": "character"},
            entity_relations=[],
            alias_confidence={"丫鬟": DISAMBIG_CONFIDENCE_HIGH},
            evidence_profiles={"丫鬟": build_evidence_profile(context)},
        )

        validated = validate_confidence_with_evidence(result, ["柳婉儿"], {"丫鬟": context})

        self.assertEqual(validated.canonical_decisions["丫鬟"], "柳婉儿")
        self.assertEqual(validated.alias_confidence["丫鬟"], DISAMBIG_CONFIDENCE_HIGH)


if __name__ == "__main__":
    unittest.main()
