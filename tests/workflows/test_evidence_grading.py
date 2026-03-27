import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import ExtendedDisambigResult
from src.workflows.annotate_helpers.disambiguation import (
    validate_confidence_with_evidence,
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_CONFIDENCE_MEDIUM,
    DISAMBIG_CONFIDENCE_LOW,
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
            alias_map={"灰衣人": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={"灰衣人": ["前文摘要-弱证据"]},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["灰衣人"], DISAMBIG_CONFIDENCE_MEDIUM)

    def test_strong_evidence_keeps_high(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={"贺重明": ["原文例句", "身份线索"]},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["贺重明"], DISAMBIG_CONFIDENCE_HIGH)

    def test_weak_evidence_prevents_merge_to_existing_character(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"灰衣人": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={"灰衣人": ["前文摘要-弱证据"]},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"])

        self.assertEqual(validated.alias_map["灰衣人"], "灰衣人")
        self.assertEqual(validated.alias_confidence["灰衣人"], DISAMBIG_CONFIDENCE_MEDIUM)

    def test_strong_evidence_allows_merge_to_existing_character(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={"贺重明": ["原文例句", "身份线索"]},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"])

        self.assertEqual(validated.alias_map["贺重明"], "伯安")
        self.assertEqual(validated.alias_confidence["贺重明"], DISAMBIG_CONFIDENCE_HIGH)

    def test_mixed_evidence_keeps_high(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={"贺重明": ["前文摘要-弱证据", "身份线索"]},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["贺重明"], DISAMBIG_CONFIDENCE_HIGH)

    def test_empty_evidence_sources_defaults_to_strong(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"伯安": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            alias_confidence={"伯安": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={},
        )

        validated = validate_confidence_with_evidence(result, [])

        self.assertEqual(validated.alias_confidence["伯安"], DISAMBIG_CONFIDENCE_HIGH)

    def test_self_mapping_not_affected_by_weak_evidence(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"灰衣人": "灰衣人"},
            entity_types={"灰衣人": "character"},
            entity_relations=[],
            alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
            evidence_sources={"灰衣人": ["前文摘要-弱证据"]},
        )

        validated = validate_confidence_with_evidence(result, ["伯安"])

        self.assertEqual(validated.alias_map["灰衣人"], "灰衣人")


if __name__ == "__main__":
    unittest.main()
