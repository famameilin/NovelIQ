"""
实体类型与关系集成测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试从消歧到关系存储的完整流程
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))


class TestExtendedDisambigResultIntegration(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试扩展消歧结果的集成
    """

    def test_full_disambig_result_structure(self) -> None:
        """测试完整消歧结果结构"""
        from src.models.local.disambiguation import ExtendedDisambigResult

        result = ExtendedDisambigResult(
            alias_map={
                "贺重明": "伯安",
                "猴子": "侯飞白",
                "赤甲卫": "赤甲卫",
                "贺家": "贺家",
            },
            entity_types={
                "伯安": "character",
                "侯飞白": "character",
                "赤甲卫": "group",
                "贺家": "organization",
            },
            entity_relations=[
                {"from": "伯安", "to": "贺家", "type": "belongs_to"},
                {"from": "侯飞白", "to": "赤甲卫", "type": "member_of"},
                {"from": "赤甲卫", "to": "贺家", "type": "affiliated_with"},
            ],
        )

        # 验证别名映射
        self.assertEqual(result.alias_map["贺重明"], "伯安")
        self.assertEqual(result.alias_map["猴子"], "侯飞白")
        self.assertEqual(result.alias_map["赤甲卫"], "赤甲卫")  # 群体映射到自身
        self.assertEqual(result.alias_map["贺家"], "贺家")  # 组织映射到自身

        # 验证实体类型
        self.assertEqual(result.entity_types["伯安"], "character")
        self.assertEqual(result.entity_types["侯飞白"], "character")
        self.assertEqual(result.entity_types["赤甲卫"], "group")
        self.assertEqual(result.entity_types["贺家"], "organization")

        # 验证关系
        self.assertEqual(len(result.entity_relations), 3)
        relation_types = {rel["type"] for rel in result.entity_relations}
        self.assertEqual(relation_types, {"belongs_to", "member_of", "affiliated_with"})


class TestEntityRelationStorageIntegration(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试实体关系存储集成
    """

    def test_insert_entity_relation_with_rel_category(self) -> None:
        """测试插入带 rel_category 的关系"""
        from src.storage.repositories.entity.relations import insert_entity_relation

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_session.execute.return_value = mock_result

        # 测试默认 rel_category
        rel_id = insert_entity_relation(
            session=mock_session,
            novel_id="novel_1",
            from_entity=1,
            to_entity=2,
            rel_type="师徒",
        )
        self.assertEqual(rel_id, 1)

        # 测试 hierarchical rel_category
        mock_result.fetchone.return_value = (2,)
        rel_id = insert_entity_relation(
            session=mock_session,
            novel_id="novel_1",
            from_entity=1,
            to_entity=3,
            rel_type="belongs_to",
            rel_category="hierarchical",
        )
        self.assertEqual(rel_id, 2)


class TestGetEntityIdByNameIntegration(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 get_entity_id_by_name 集成
    """

    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_alias")
    def test_find_entity_by_name(self, mock_fetch_alias, mock_fetch_canonical) -> None:
        """测试通过名称查找实体"""
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        # 测试通过规范名找到
        mock_fetch_canonical.return_value = {"entity_id": 1, "canonical": "伯安"}
        mock_fetch_alias.return_value = None

        mock_session = MagicMock()
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "伯安", None)
        self.assertEqual(entity_id, 1)

        # 测试通过别名找到
        mock_fetch_canonical.return_value = None
        mock_fetch_alias.return_value = {"entity_id": 2, "canonical": "贺重明"}

        entity_id = get_entity_id_by_name(mock_session, "novel_1", "重明", None)
        self.assertEqual(entity_id, 2)

        # 测试未找到
        mock_fetch_canonical.return_value = None
        mock_fetch_alias.return_value = None

        entity_id = get_entity_id_by_name(mock_session, "novel_1", "不存在的名字", None)
        self.assertIsNone(entity_id)


if __name__ == "__main__":
    unittest.main()
