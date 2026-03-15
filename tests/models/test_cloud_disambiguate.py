import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.cloud.client import ConfiguredCloudModelClient


class TestCloudDisambiguate(unittest.TestCase):
    def test_disambiguate_characters_returns_alias_map(self) -> None:
        config = TaskModelConfig(
            base_url="http://example.com",
            model="gpt-test",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"alias_map": {"三哥": "张三", "张公子": "张三"}}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = ConfiguredCloudModelClient(config=config, client=mock_client)
        candidates = ["张三", "三哥", "张公子"]
        result = client.disambiguate_characters(candidates)
        self.assertIn("三哥", result)
        self.assertEqual(result["三哥"], "张三")

    def test_disambiguate_characters_with_context_sentences(self) -> None:
        config = TaskModelConfig(
            base_url="http://example.com",
            model="gpt-test",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"alias_map": {"猴子": "侯飞白"}}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = ConfiguredCloudModelClient(config=config, client=mock_client)
        candidates = ["侯飞白", "猴子"]
        context_sentences = {"猴子": "猴子笑道：我便是侯飞白。"}
        result = client.disambiguate_characters(candidates, context_sentences=context_sentences)
        self.assertEqual(result["猴子"], "侯飞白")


if __name__ == "__main__":
    unittest.main()
