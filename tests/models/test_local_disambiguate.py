import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.disambiguation import DisambiguationClient
from src.models.local.disambiguation import ExtendedDisambigResult
from src.models.local.schema import DisambiguateResponseModel


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

    def test_disambiguate_characters_returns_merge_target_map(self) -> None:
        client = self._make_client(
            DisambiguateResponseModel(merge_target_map={"三哥": "张三", "张公子": "张三"})
        )

        result = client.disambiguate_characters(["张三", "三哥", "张公子"])

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.merge_target_map["三哥"], "张三")
        self.assertEqual(result.merge_target_map["张公子"], "张三")

    def test_disambiguate_characters_with_context_sentences(self) -> None:
        client = self._make_client(
            DisambiguateResponseModel(merge_target_map={"猴子": "侯飞白"})
        )

        result = client.disambiguate_characters(
            ["侯飞白", "猴子"],
            context_sentences={"猴子": "猴子笑道：我便是侯飞白。"},
        )

        self.assertIsInstance(result, ExtendedDisambigResult)
        self.assertEqual(result.merge_target_map["猴子"], "侯飞白")

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
        self.assertEqual(result.merge_target_map, {})

    def test_disambiguate_characters_with_existing_names(self) -> None:
        client = self._make_client(DisambiguateResponseModel(merge_target_map={}))
        result = client.disambiguate_characters(["张三"], existing_names=["李四", "王五"])
        self.assertIsInstance(result, ExtendedDisambigResult)

    def test_disambiguate_characters_keeps_merge_target_and_common_name_separate(self) -> None:
        client = self._make_client(
            DisambiguateResponseModel(
                merge_target_map={"贺伯安": "伯安"},
                common_name_map={"贺伯安": "贺伯安"},
            )
        )

        result = client.disambiguate_characters(["贺伯安"], existing_names=["伯安"])

        self.assertEqual(result.merge_target_map["贺伯安"], "伯安")
        self.assertEqual(result.common_name_map["贺伯安"], "贺伯安")


if __name__ == "__main__":
    unittest.main()
