import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.local.unified_client import UnifiedModelClient


class TestLocalDisambiguate(unittest.TestCase):
    def test_disambiguate_characters_returns_alias_map(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"alias_map": {"三哥": "张三", "张公子": "张三"}}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = UnifiedModelClient(task_type="incremental_disambig", config=config, client=mock_client)
        candidates = ["张三", "三哥", "张公子"]
        result = client.disambiguate_characters(candidates)
        self.assertIn("三哥", result)
        self.assertEqual(result["三哥"], "张三")
        self.assertIn("张公子", result)
        self.assertEqual(result["张公子"], "张三")

    def test_disambiguate_characters_with_context_sentences(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"alias_map": {"猴子": "侯飞白"}}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = UnifiedModelClient(task_type="incremental_disambig", config=config, client=mock_client)
        candidates = ["侯飞白", "猴子"]
        context_sentences = {"猴子": "猴子笑道：我便是侯飞白。"}
        result = client.disambiguate_characters(candidates, context_sentences=context_sentences)
        self.assertEqual(result["猴子"], "侯飞白")

    def test_disambiguate_characters_empty_candidates_returns_empty(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        client = UnifiedModelClient(task_type="incremental_disambig", config=config, client=mock_client)
        result = client.disambiguate_characters([])
        self.assertEqual(result, {})

    def test_disambiguate_characters_with_existing_names(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"alias_map": {}}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = UnifiedModelClient(task_type="incremental_disambig", config=config, client=mock_client)
        candidates = ["张三"]
        existing_names = ["李四", "王五"]
        result = client.disambiguate_characters(candidates, existing_names=existing_names)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        has_existing = any("已存在的角色" in m.get("content", "") for m in messages)
        self.assertTrue(has_existing)


if __name__ == "__main__":
    unittest.main()
