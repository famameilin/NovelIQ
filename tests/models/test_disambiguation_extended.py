import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import (
    EvidenceProfile,
    ExtendedDisambigResult,
    build_extended_result_from_response,
)
from src.models.local.schema import DisambiguateResponseModel, HierarchicalRelation


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


class TestExtendedDisambigResult(unittest.TestCase):
    def test_basic_creation(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"he_zhong_ming": "bo_an"},
            entity_types={"bo_an": "character", "red_guard": "group"},
            entity_relations=[{"from": "bo_an", "to": "he_family", "type": "belongs_to"}],
        )

        self.assertEqual(result.alias_map["he_zhong_ming"], "bo_an")
        self.assertEqual(result.entity_types["bo_an"], "character")
        self.assertEqual(len(result.entity_relations), 1)

    def test_empty_creation(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={},
            entity_types={},
            entity_relations=[],
        )

        self.assertEqual(result.alias_map, {})
        self.assertEqual(result.entity_types, {})
        self.assertEqual(result.entity_relations, [])

    def test_evidence_profiles_field(self) -> None:
        result = ExtendedDisambigResult(
            alias_map={"he_zhong_ming": "bo_an"},
            entity_types={"bo_an": "character"},
            entity_relations=[],
            evidence_profiles={
                "he_zhong_ming": EvidenceProfile(
                    has_original_sentence=True,
                    has_identity_clue=True,
                    has_summary=False,
                    strong_signals=["identity_reveal"],
                    strength="strong",
                )
            },
        )

        self.assertEqual(result.evidence_profiles["he_zhong_ming"].strength, "strong")


class TestBuildExtendedResultFromResponse(unittest.TestCase):
    def test_basic_parsing(self) -> None:
        response = DisambiguateResponseModel(
            alias_map={"he_zhong_ming": "bo_an", "red_guard": "red_guard"},
            entity_types={"bo_an": "character", "red_guard": "group", "he_family": "organization"},
            entity_relations=[
                HierarchicalRelation(**{"from": "bo_an", "to": "he_family", "type": "belongs_to"}),
            ],
        )

        result = build_extended_result_from_response(response, _candidates("he_zhong_ming", "red_guard", "he_family"))

        self.assertEqual(result.alias_map["he_zhong_ming"], "bo_an")
        self.assertEqual(result.alias_map["red_guard"], "red_guard")
        self.assertEqual(result.entity_types["red_guard"], "group")
        self.assertEqual(result.entity_types["he_family"], "organization")
        self.assertEqual(result.entity_relations[0]["type"], "belongs_to")

    def test_group_and_org_self_mapping(self) -> None:
        response = DisambiguateResponseModel(
            alias_map={"red_guard": "red_guard", "he_family": "he_family"},
            entity_types={"red_guard": "group", "he_family": "organization"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, _candidates("red_guard", "he_family"))

        self.assertEqual(result.alias_map["red_guard"], "red_guard")
        self.assertEqual(result.alias_map["he_family"], "he_family")

    def test_multiple_relations(self) -> None:
        response = DisambiguateResponseModel(
            alias_map={
                "bo_an": "bo_an",
                "zhang_san": "zhang_san",
                "red_guard": "red_guard",
                "he_family": "he_family",
            },
            entity_types={
                "bo_an": "character",
                "zhang_san": "character",
                "red_guard": "group",
                "he_family": "organization",
            },
            entity_relations=[
                HierarchicalRelation(**{"from": "bo_an", "to": "he_family", "type": "belongs_to"}),
                HierarchicalRelation(**{"from": "zhang_san", "to": "red_guard", "type": "member_of"}),
                HierarchicalRelation(**{"from": "red_guard", "to": "he_family", "type": "affiliated_with"}),
            ],
        )

        result = build_extended_result_from_response(response, _candidates("bo_an", "zhang_san", "red_guard", "he_family"))

        self.assertEqual(len(result.entity_relations), 3)
        self.assertEqual(
            {rel["type"] for rel in result.entity_relations},
            {"belongs_to", "member_of", "affiliated_with"},
        )

    def test_missing_candidates_default_to_self(self) -> None:
        response = DisambiguateResponseModel(
            alias_map={"he_zhong_ming": "bo_an"},
            entity_types={"bo_an": "character"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, _candidates("he_zhong_ming", "bai_zhi"))

        self.assertEqual(result.alias_map["he_zhong_ming"], "bo_an")
        self.assertEqual(result.alias_map["bai_zhi"], "bai_zhi")

    def test_evidence_profiles_are_derived_from_context(self) -> None:
        response = DisambiguateResponseModel(
            alias_map={"he_zhong_ming": "bo_an", "gray_man": "bo_an"},
            entity_types={"bo_an": "character"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(
            response,
            _candidates("he_zhong_ming", "gray_man"),
            {
                "he_zhong_ming": "贺重明的真实身份是伯安 | 【身份提示】贺重明其实就是伯安",
                "gray_man": "【前文总结】灰衣人伯安现身",
            },
        )

        self.assertEqual(result.evidence_profiles["he_zhong_ming"].strength, "strong")
        self.assertEqual(result.evidence_profiles["gray_man"].strength, "weak")

    def test_missing_context_produces_weak_evidence_profile(self) -> None:
        response = DisambiguateResponseModel(
            alias_map={"bo_an": "bo_an"},
            entity_types={"bo_an": "character"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, _candidates("bo_an"))

        self.assertEqual(result.evidence_profiles["bo_an"].strength, "weak")


class TestHierarchicalRelationModel(unittest.TestCase):
    def test_relation_creation(self) -> None:
        rel = HierarchicalRelation(**{"from": "bo_an", "to": "he_family", "type": "belongs_to"})
        self.assertEqual(rel.from_entity, "bo_an")
        self.assertEqual(rel.to_entity, "he_family")
        self.assertEqual(rel.type, "belongs_to")

    def test_all_relation_types(self) -> None:
        for rel_type in ["belongs_to", "member_of", "leader_of", "affiliated_with"]:
            rel = HierarchicalRelation(**{"from": "A", "to": "B", "type": rel_type})
            self.assertEqual(rel.type, rel_type)


if __name__ == "__main__":
    unittest.main()
