import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))


class TestExtendedDisambigResultIntegration(unittest.TestCase):
    def test_full_disambig_result_structure(self) -> None:
        from src.models.local.disambiguation import ExtendedDisambigResult

        result = ExtendedDisambigResult(
            merge_target_map={
                "AliasA": "CharacterA",
                "AliasB": "CharacterB",
                "GroupA": "GroupA",
                "OrgA": "OrgA",
            },
            entity_types={
                "CharacterA": "character",
                "CharacterB": "character",
                "GroupA": "group",
                "OrgA": "organization",
            },
            entity_relations=[
                {"from": "CharacterA", "to": "OrgA", "type": "belongs_to"},
                {"from": "CharacterB", "to": "GroupA", "type": "member_of"},
                {"from": "GroupA", "to": "OrgA", "type": "affiliated_with"},
            ],
        )

        self.assertEqual(result.merge_target_map["AliasA"], "CharacterA")
        self.assertEqual(result.merge_target_map["AliasB"], "CharacterB")
        self.assertEqual(result.merge_target_map["GroupA"], "GroupA")
        self.assertEqual(result.merge_target_map["OrgA"], "OrgA")

        self.assertEqual(result.entity_types["CharacterA"], "character")
        self.assertEqual(result.entity_types["CharacterB"], "character")
        self.assertEqual(result.entity_types["GroupA"], "group")
        self.assertEqual(result.entity_types["OrgA"], "organization")

        self.assertEqual(len(result.entity_relations), 3)
        relation_types = {rel["type"] for rel in result.entity_relations}
        self.assertEqual(relation_types, {"belongs_to", "member_of", "affiliated_with"})


class TestEntityRelationStorageIntegration(unittest.TestCase):
    def test_insert_entity_relation_with_rel_category(self) -> None:
        from src.storage.repositories.entity.relations import insert_entity_relation

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

        mock_result.fetchone.return_value = (2,)
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


class TestGetEntityIdByNameIntegration(unittest.TestCase):
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_canonical")
    @patch("src.storage.repositories.entity.queries.fetch_entity_by_alias")
    def test_find_entity_by_name(self, mock_fetch_alias, mock_fetch_canonical) -> None:
        from src.storage.repositories.entity.queries import get_entity_id_by_name

        mock_fetch_canonical.return_value = {"entity_id": 1, "canonical": "CharacterA"}
        mock_fetch_alias.return_value = None

        mock_session = MagicMock()
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "CharacterA", None)
        self.assertEqual(entity_id, 1)

        mock_fetch_canonical.return_value = None
        mock_fetch_alias.return_value = {"entity_id": 2, "canonical": "CharacterB"}
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "AliasB", None)
        self.assertEqual(entity_id, 2)

        mock_fetch_canonical.return_value = None
        mock_fetch_alias.return_value = None
        entity_id = get_entity_id_by_name(mock_session, "novel_1", "Missing", None)
        self.assertIsNone(entity_id)


if __name__ == "__main__":
    unittest.main()
