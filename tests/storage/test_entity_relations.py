"""
实体关系存储单元测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试实体关系存储功能，包括 rel_category 字段
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories.entity.relations import insert_entity_relation


class TestInsertEntityRelation(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 insert_entity_relation 函数的 rel_category 参数
    """

    def test_insert_with_default_rel_category(self) -> None:
        """测试默认 rel_category 为 interpersonal"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_session.execute.return_value = mock_result

        rel_id = insert_entity_relation(
            session=mock_session,
            novel_id="novel_1",
            from_entity=1,
            to_entity=2,
            rel_type="师徒",
        )

        self.assertEqual(rel_id, 1)
        # 验证 execute 被调用
        mock_session.execute.assert_called_once()
        # 获取调用参数
        call_args = mock_session.execute.call_args
        stmt = call_args[0][0]
        # 检查 SQL 语句中包含 rel_category
        self.assertIn("rel_category", str(stmt))

    def test_insert_with_hierarchical_rel_category(self) -> None:
        """测试设置 rel_category 为 hierarchical"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (2,)
        mock_session.execute.return_value = mock_result

        rel_id = insert_entity_relation(
            session=mock_session,
            novel_id="novel_1",
            from_entity=1,
            to_entity=3,
            rel_type="belongs_to",
            rel_category="hierarchical",
        )

        self.assertEqual(rel_id, 2)

    def test_insert_with_all_parameters(self) -> None:
        """测试使用所有参数"""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (3,)
        mock_session.execute.return_value = mock_result

        rel_id = insert_entity_relation(
            session=mock_session,
            novel_id="novel_1",
            from_entity=1,
            to_entity=2,
            rel_type="member_of",
            first_chunk=10,
            tension=0.5,
            rel_category="hierarchical",
            run_id="run_123",
        )

        self.assertEqual(rel_id, 3)
        mock_session.commit.assert_called_once()


class TestGetEntityIdByName(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 get_entity_id_by_name 函数
    """

    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_alias")
    def test_find_by_canonical_name(self, mock_fetch_alias, mock_fetch_canonical) -> None:
        """测试通过规范名找到实体"""
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = {"entity_id": 1, "canonical": "伯安"}
        mock_fetch_alias.return_value = None

        mock_session = MagicMock()
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "伯安", None)

        self.assertEqual(entity_id, 1)
        mock_fetch_canonical.assert_called_once()
        mock_fetch_alias.assert_not_called()

    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_alias")
    def test_find_by_alias_name(self, mock_fetch_alias, mock_fetch_canonical) -> None:
        """测试通过别名找到实体"""
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = None
        mock_fetch_alias.return_value = {"entity_id": 2, "canonical": "贺重明"}

        mock_session = MagicMock()
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "重明", None)

        self.assertEqual(entity_id, 2)
        mock_fetch_canonical.assert_called_once()
        mock_fetch_alias.assert_called_once()

    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_alias")
    def test_entity_not_found(self, mock_fetch_alias, mock_fetch_canonical) -> None:
        """测试实体不存在时返回 None"""
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = None
        mock_fetch_alias.return_value = None

        mock_session = MagicMock()
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "不存在的名字", None)

        self.assertIsNone(entity_id)


if __name__ == "__main__":
    unittest.main()
