import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.disambiguation import DisambiguationClient
from src.models.local.disambiguation import ExtendedDisambigResult
from src.models.local.schema import DisambiguateResponseModel


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


def create_mock_stream_response(content: str):
    chunk_size = 50
    for i in range(0, len(content), chunk_size):
        chunk_content = content[i : i + chunk_size]
        delta = MagicMock()
        delta.content = chunk_content
        delta.reasoning_content = None

        choice = MagicMock()
        choice.delta = delta

        chunk = MagicMock()
        chunk.choices = [choice]

        yield chunk


class TestLocalDisambiguate(unittest.TestCase):
    def _make_client(self, response_model: DisambiguateResponseModel) -> DisambiguationClient:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = create_mock_stream_response(
            response_model.model_dump_json()
        )
        return DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )

    def test_disambiguate_characters_returns_alias_map(self) -> None:
        client = self._make_client(
            DisambiguateResponseModel(canonical_decisions={"third_brother": "zhang_san", "young_master_zhang": "zhang_san"})
        )

        result = client.disambiguate_characters(_candidates("zhang_san", "third_brother", "young_master_zhang"))

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.canonical_decisions["third_brother"], "zhang_san")
        self.assertEqual(result.canonical_decisions["young_master_zhang"], "zhang_san")

    def test_disambiguate_characters_with_context_sentences(self) -> None:
        client = self._make_client(
            DisambiguateResponseModel(canonical_decisions={"monkey": "hou_fei_bai"})
        )

        result = client.disambiguate_characters(
            _candidates("hou_fei_bai", "monkey"),
            context_sentences={"monkey": "monkey smiled and said he was hou_fei_bai"},
        )

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.canonical_decisions["monkey"], "hou_fei_bai")

    def test_disambiguate_characters_empty_candidates_returns_empty(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        client = DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=MagicMock(),
        )

        result = client.disambiguate_characters([])

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.canonical_decisions, {})

    def test_disambiguate_characters_with_existing_names(self) -> None:
        client = self._make_client(DisambiguateResponseModel(canonical_decisions={}))
        result = client.disambiguate_characters(_candidates("zhang_san"), existing_names=["li_si", "wang_wu"])
        self.assertIsInstance(result, ExtendedDisambigResult)


if __name__ == "__main__":
    unittest.main()
