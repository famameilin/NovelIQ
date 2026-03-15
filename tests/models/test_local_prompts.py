import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.local.unified_client import UnifiedModelClient


class TestLocalPrompts(unittest.TestCase):
    def test_annotate_chunk_includes_system_prompt(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"emotional_valence": "neutral", "event_type": "日常", "pivot_moment": false, "cliffhanger": false, "has_foreshadowing": false, "foreshadowing_type": null, "foreshadowing_desc": ""}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        client.annotate_chunk("测试文本")
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_messages = [m for m in messages if m.get("role") == "system"]
        self.assertGreater(len(system_messages), 0)
        self.assertIn("叙事结构分析助手", system_messages[0].get("content", ""))

    def test_annotate_chunk_includes_few_shot_examples(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"emotional_valence": "neutral", "event_type": "日常", "pivot_moment": false, "cliffhanger": false, "has_foreshadowing": false, "foreshadowing_type": null, "foreshadowing_desc": ""}'
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        client.annotate_chunk("测试文本")
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_messages = [m for m in messages if m.get("role") == "user"]
        self.assertGreater(len(user_messages), 1)

    def test_disambiguate_characters_includes_system_prompt(self) -> None:
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
        client.disambiguate_characters(["张三"])
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_messages = [m for m in messages if m.get("role") == "system"]
        self.assertGreater(len(system_messages), 0)
        self.assertIn("人名消歧系统", system_messages[0].get("content", ""))


if __name__ == "__main__":
    unittest.main()
