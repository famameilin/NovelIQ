"""
消歧扩展功能单元测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试消歧阶段的entity_types和entity_relations解析
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import ExtendedDisambigResult, build_extended_result_from_response
from src.models.local.schema import DisambiguateResponseModel, HierarchicalRelation


class TestExtendedDisambigResult(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 ExtendedDisambigResult 数据类
    """

    def test_basic_creation(self) -> None:
        """测试基本创建"""
        result = ExtendedDisambigResult(
            alias_map={"贺重明": "伯安"},
            entity_types={"伯安": "character", "赤甲卫": "group"},
            entity_relations=[{"from": "伯安", "to": "贺家", "type": "belongs_to"}],
        )
        self.assertEqual(result.alias_map["贺重明"], "伯安")
        self.assertEqual(result.entity_types["伯安"], "character")
        self.assertEqual(len(result.entity_relations), 1)

    def test_empty_creation(self) -> None:
        """测试空数据创建"""
        result = ExtendedDisambigResult(
            alias_map={},
            entity_types={},
            entity_relations=[],
        )
        self.assertEqual(len(result.alias_map), 0)
        self.assertEqual(len(result.entity_types), 0)
        self.assertEqual(len(result.entity_relations), 0)


class TestBuildExtendedResultFromResponse(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 build_extended_result_from_response 函数
    """

    def test_basic_parsing(self) -> None:
        """测试基本解析"""
        response = DisambiguateResponseModel(
            alias_map={"贺重明": "伯安", "赤甲卫": "赤甲卫"},
            entity_types={"伯安": "character", "赤甲卫": "group", "贺家": "organization"},
            entity_relations=[
                HierarchicalRelation(**{"from": "伯安", "to": "贺家", "type": "belongs_to"}),
            ],
        )
        candidates = ["贺重明", "赤甲卫", "贺家"]

        result = build_extended_result_from_response(response, candidates)

        self.assertEqual(result.alias_map["贺重明"], "伯安")
        self.assertEqual(result.alias_map["赤甲卫"], "赤甲卫")  # 群体映射到自身
        self.assertEqual(result.entity_types["伯安"], "character")
        self.assertEqual(result.entity_types["赤甲卫"], "group")
        self.assertEqual(result.entity_types["贺家"], "organization")
        self.assertEqual(len(result.entity_relations), 1)
        self.assertEqual(result.entity_relations[0]["from"], "伯安")
        self.assertEqual(result.entity_relations[0]["to"], "贺家")
        self.assertEqual(result.entity_relations[0]["type"], "belongs_to")

    def test_group_organization_self_mapping(self) -> None:
        """测试群体/组织名称映射到自身"""
        response = DisambiguateResponseModel(
            alias_map={"赤甲卫": "赤甲卫", "贺家": "贺家"},
            entity_types={"赤甲卫": "group", "贺家": "organization"},
            entity_relations=[],
        )
        candidates = ["赤甲卫", "贺家"]

        result = build_extended_result_from_response(response, candidates)

        # 群体和组织应该映射到自身
        self.assertEqual(result.alias_map["赤甲卫"], "赤甲卫")
        self.assertEqual(result.alias_map["贺家"], "贺家")

    def test_multiple_relations(self) -> None:
        """测试多个关系解析"""
        response = DisambiguateResponseModel(
            alias_map={"伯安": "伯安", "张三": "张三", "赤甲卫": "赤甲卫", "贺家": "贺家"},
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
        candidates = ["伯安", "张三", "赤甲卫", "贺家"]

        result = build_extended_result_from_response(response, candidates)

        self.assertEqual(len(result.entity_relations), 3)
        relation_types = {rel["type"] for rel in result.entity_relations}
        self.assertEqual(relation_types, {"belongs_to", "member_of", "affiliated_with"})

    def test_missing_candidates_in_response(self) -> None:
        """测试响应中缺少某些候选名时的处理"""
        response = DisambiguateResponseModel(
            alias_map={"贺重明": "伯安"},
            entity_types={"伯安": "character"},
            entity_relations=[],
        )
        candidates = ["贺重明", "白芷"]  # 白芷不在响应中

        result = build_extended_result_from_response(response, candidates)

        # 缺少的候选名应该映射到自身
        self.assertEqual(result.alias_map["贺重明"], "伯安")
        self.assertEqual(result.alias_map["白芷"], "白芷")


class TestHierarchicalRelationModel(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 HierarchicalRelation 模型
    """

    def test_relation_creation(self) -> None:
        """测试关系创建"""
        rel = HierarchicalRelation(
            **{"from": "伯安", "to": "贺家", "type": "belongs_to"},
        )
        self.assertEqual(rel.from_entity, "伯安")
        self.assertEqual(rel.to_entity, "贺家")
        self.assertEqual(rel.type, "belongs_to")

    def test_all_relation_types(self) -> None:
        """测试所有关系类型"""
        types = ["belongs_to", "member_of", "leader_of", "affiliated_with"]
        for rel_type in types:
            rel = HierarchicalRelation(
                **{"from": "A", "to": "B", "type": rel_type},
            )
            self.assertEqual(rel.type, rel_type)


if __name__ == "__main__":
    unittest.main()
