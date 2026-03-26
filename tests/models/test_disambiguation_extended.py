import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import ExtendedDisambigResult, build_extended_result_from_response
from src.models.local.schema import DisambiguateResponseModel, HierarchicalRelation


class TestExtendedDisambigResult(unittest.TestCase):
    def test_basic_creation(self) -> None:
        result = ExtendedDisambigResult(
            merge_target_map={"贺重明": "伯安"},
            common_name_map={"贺重明": "贺重明"},
            entity_types={"伯安": "character", "赤甲卫": "group"},
            entity_relations=[{"from": "伯安", "to": "贺家", "type": "belongs_to"}],
        )

        self.assertEqual(result.merge_target_map["贺重明"], "伯安")
        self.assertEqual(result.common_name_map["贺重明"], "贺重明")
        self.assertEqual(result.entity_types["伯安"], "character")
        self.assertEqual(len(result.entity_relations), 1)

    def test_empty_creation(self) -> None:
        result = ExtendedDisambigResult(
            merge_target_map={},
            entity_types={},
            entity_relations=[],
        )

        self.assertEqual(result.merge_target_map, {})
        self.assertEqual(result.entity_types, {})
        self.assertEqual(result.entity_relations, [])

    def test_evidence_sources_field(self) -> None:
        result = ExtendedDisambigResult(
            merge_target_map={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            evidence_sources={"贺重明": ["原文例句", "身份线索"]},
        )

        self.assertEqual(result.evidence_sources["贺重明"], ["原文例句", "身份线索"])


class TestBuildExtendedResultFromResponse(unittest.TestCase):
    def test_basic_parsing(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={"贺重明": "伯安", "赤甲卫": "赤甲卫"},
            common_name_map={"贺重明": "伯安", "赤甲卫": "赤甲卫"},
            entity_types={"伯安": "character", "赤甲卫": "group", "贺家": "organization"},
            entity_relations=[
                HierarchicalRelation(**{"from": "伯安", "to": "贺家", "type": "belongs_to"}),
            ],
        )

        result = build_extended_result_from_response(response, ["贺重明", "赤甲卫", "贺家"])

        self.assertEqual(result.merge_target_map["贺重明"], "伯安")
        self.assertEqual(result.common_name_map["贺重明"], "贺重明")
        self.assertEqual(result.merge_target_map["赤甲卫"], "赤甲卫")
        self.assertEqual(result.entity_types["赤甲卫"], "group")
        self.assertEqual(result.entity_types["贺家"], "organization")
        self.assertEqual(result.entity_relations[0]["type"], "belongs_to")

    def test_group_and_org_self_mapping(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={"赤甲卫": "赤甲卫", "贺家": "贺家"},
            common_name_map={"赤甲卫": "赤甲卫", "贺家": "贺家"},
            entity_types={"赤甲卫": "group", "贺家": "organization"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, ["赤甲卫", "贺家"])

        self.assertEqual(result.merge_target_map["赤甲卫"], "赤甲卫")
        self.assertEqual(result.merge_target_map["贺家"], "贺家")

    def test_multiple_relations(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={
                "伯安": "伯安",
                "张三": "张三",
                "赤甲卫": "赤甲卫",
                "贺家": "贺家",
            },
            common_name_map={
                "伯安": "伯安",
                "张三": "张三",
                "赤甲卫": "赤甲卫",
                "贺家": "贺家",
            },
            entity_types={
                "伯安": "character",
                "张三": "character",
                "赤甲卫": "group",
                "贺家": "organization",
            },
            entity_relations=[
                HierarchicalRelation(**{"from": "伯安", "to": "贺家", "type": "belongs_to"}),
                HierarchicalRelation(**{"from": "张三", "to": "赤甲卫", "type": "member_of"}),
                HierarchicalRelation(**{"from": "赤甲卫", "to": "贺家", "type": "affiliated_with"}),
            ],
        )

        result = build_extended_result_from_response(response, ["伯安", "张三", "赤甲卫", "贺家"])

        self.assertEqual(len(result.entity_relations), 3)
        self.assertEqual(
            {rel["type"] for rel in result.entity_relations},
            {"belongs_to", "member_of", "affiliated_with"},
        )

    def test_missing_candidates_default_to_self(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={"贺重明": "伯安"},
            common_name_map={"贺重明": "贺重明"},
            entity_types={"伯安": "character"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, ["贺重明", "白芷"])

        self.assertEqual(result.merge_target_map["贺重明"], "伯安")
        self.assertEqual(result.merge_target_map["白芷"], "白芷")
        self.assertEqual(result.common_name_map["贺重明"], "贺重明")
        self.assertEqual(result.common_name_map["白芷"], "白芷")

    def test_common_name_map_does_not_fall_back_to_existing_merge_target(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={"贺伯安": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, ["贺伯安"])

        self.assertEqual(result.merge_target_map["贺伯安"], "伯安")
        self.assertEqual(result.common_name_map["贺伯安"], "贺伯安")

    def test_evidence_sources_extraction(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={"贺重明": "伯安", "灰衣人": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
            evidence_sources={
                "贺重明": ["原文例句", "身份线索"],
                "灰衣人": ["前文摘要-弱证据"],
            },
        )

        result = build_extended_result_from_response(response, ["贺重明", "灰衣人"])

        self.assertEqual(result.evidence_sources["贺重明"], ["原文例句", "身份线索"])
        self.assertEqual(result.evidence_sources["灰衣人"], ["前文摘要-弱证据"])

    def test_evidence_sources_default_to_original_text(self) -> None:
        response = DisambiguateResponseModel(
            merge_target_map={"伯安": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
        )

        result = build_extended_result_from_response(response, ["伯安"])

        self.assertEqual(result.evidence_sources["伯安"], ["原文例句"])


class TestHierarchicalRelationModel(unittest.TestCase):
    def test_relation_creation(self) -> None:
        rel = HierarchicalRelation(**{"from": "伯安", "to": "贺家", "type": "belongs_to"})
        self.assertEqual(rel.from_entity, "伯安")
        self.assertEqual(rel.to_entity, "贺家")
        self.assertEqual(rel.type, "belongs_to")

    def test_all_relation_types(self) -> None:
        for rel_type in ["belongs_to", "member_of", "leader_of", "affiliated_with"]:
            rel = HierarchicalRelation(**{"from": "A", "to": "B", "type": rel_type})
            self.assertEqual(rel.type, rel_type)


if __name__ == "__main__":
    unittest.main()
