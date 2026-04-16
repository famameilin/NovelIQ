import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.disambiguation import DisambiguationClient
from src.models.local.disambiguation import ExtendedDisambigResult
from src.models.local.schema import DisambiguateResponseModel


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


def create_mock_response(response_model: DisambiguateResponseModel):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=response_model.model_dump_json()))]
    return mock_response


class TestLocalDisambiguate(unittest.TestCase):
    def _make_client(self, response_model: DisambiguateResponseModel) -> DisambiguationClient:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        mock_response = create_mock_response(response_model)
        mock_client.chat.completions.create.return_value = mock_response
        return DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )

    @patch("src.models.disambiguation.call_disambiguate_api")
    def test_disambiguate_characters_returns_alias_map(self, mock_api_call: MagicMock) -> None:
        mock_api_call.return_value = DisambiguateResponseModel(
            canonical_decisions={"third_brother": "zhang_san", "young_master_zhang": "zhang_san"}
        )
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

        result = asyncio.run(
            client.disambiguate_characters(_candidates("zhang_san", "third_brother", "young_master_zhang"))
        )

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.canonical_decisions["third_brother"], "zhang_san")
        self.assertEqual(result.canonical_decisions["young_master_zhang"], "zhang_san")

    @patch("src.models.disambiguation.call_disambiguate_api")
    def test_disambiguate_characters_with_context_sentences(self, mock_api_call: MagicMock) -> None:
        mock_api_call.return_value = DisambiguateResponseModel(canonical_decisions={"monkey": "hou_fei_bai"})
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

        result = asyncio.run(
            client.disambiguate_characters(
                _candidates("hou_fei_bai", "monkey"),
                context_sentences={"monkey": "monkey smiled and said he was hou_fei_bai"},
            )
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

        result = asyncio.run(client.disambiguate_characters([]))

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.canonical_decisions, {})

    @patch("src.models.disambiguation.call_disambiguate_api")
    def test_disambiguate_characters_with_existing_names(self, mock_api_call: MagicMock) -> None:
        mock_api_call.return_value = DisambiguateResponseModel(canonical_decisions={})
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
        result = asyncio.run(
            client.disambiguate_characters(_candidates("zhang_san"), existing_names=["li_si", "wang_wu"])
        )
        self.assertIsInstance(result, ExtendedDisambigResult)


if __name__ == "__main__":
    unittest.main()
