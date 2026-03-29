import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories.entity.relations import insert_entity_relation


class TestInsertEntityRelation(unittest.TestCase):
    def test_insert_with_default_rel_category(self) -> None:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1,)
        mock_session.execute.return_value = mock_result

        rel_id = insert_entity_relation(
            session=mock_session,
            novel_id="novel_1",
            from_entity=1,
            to_entity=2,
            rel_type="mentor",
            run_id="run_123",
        )

        self.assertEqual(rel_id, 1)
        mock_session.execute.assert_called_once()
        stmt = mock_session.execute.call_args[0][0]
        self.assertIn("rel_category", str(stmt))

    def test_insert_with_hierarchical_rel_category(self) -> None:
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
            run_id="run_123",
            rel_category="hierarchical",
        )

        self.assertEqual(rel_id, 2)

    def test_insert_with_all_parameters(self) -> None:
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
            run_id="run_123",
            first_chunk=10,
            tension=0.5,
            rel_category="hierarchical",
        )

        self.assertEqual(rel_id, 3)
        mock_session.commit.assert_called_once()


class TestGetEntityIdByName(unittest.TestCase):
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    def test_find_by_canonical_name(self, mock_fetch_canonical) -> None:
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = {"entity_id": 1, "canonical": "A"}

        mock_session = MagicMock()
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "A", None)

        self.assertEqual(entity_id, 1)
        mock_fetch_canonical.assert_called_once()
        mock_session.execute.assert_not_called()

    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    def test_find_by_alias_name(self, mock_fetch_canonical) -> None:
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = None
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (2,)

        entity_id = get_entity_id_by_name(mock_session, "novel_1", "alias_b", None)

        self.assertEqual(entity_id, 2)
        mock_fetch_canonical.assert_called_once()
        mock_session.execute.assert_called_once()

    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    def test_entity_not_found(self, mock_fetch_canonical) -> None:
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = None
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None

        entity_id = get_entity_id_by_name(mock_session, "novel_1", "missing", None)

        self.assertIsNone(entity_id)



if __name__ == "__main__":
    unittest.main()
