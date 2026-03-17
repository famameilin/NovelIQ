import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.local.unified_client import UnifiedModelClient
from src.models.local.schema import DisambiguateResponseModel


def create_mock_stream_response(content: str):
    """
    创建模拟的流式 API 响应生成器

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: 适配流式输出模式
    """
    # 将内容分成多个 chunk 模拟流式输出
    chunk_size = 50
    for i in range(0, len(content), chunk_size):
        chunk_content = content[i:i+chunk_size]
        delta = MagicMock()
        delta.content = chunk_content
        delta.reasoning_content = None
        
        choice = MagicMock()
        choice.delta = delta
        
        chunk = MagicMock()
        chunk.choices = [choice]
        
        yield chunk


class TestLocalDisambiguate(unittest.TestCase):
    def test_disambiguate_characters_returns_alias_map(self) -> None:
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖，适配新的响应格式
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        disambiguate_result = DisambiguateResponseModel(alias_map={"三哥": "张三", "张公子": "张三"})
        mock_client.chat.completions.create.return_value = create_mock_stream_response(disambiguate_result.model_dump_json())

        client = UnifiedModelClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )
        candidates = ["张三", "三哥", "张公子"]
        result = client.disambiguate_characters(candidates)
        self.assertIn("三哥", result)
        self.assertEqual(result["三哥"], "张三")
        self.assertIn("张公子", result)
        self.assertEqual(result["张公子"], "张三")

    def test_disambiguate_characters_with_context_sentences(self) -> None:
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖，适配新的响应格式
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        disambiguate_result = DisambiguateResponseModel(alias_map={"猴子": "侯飞白"})
        mock_client.chat.completions.create.return_value = create_mock_stream_response(disambiguate_result.model_dump_json())

        client = UnifiedModelClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )
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
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖，适配新的响应格式
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        disambiguate_result = DisambiguateResponseModel(alias_map={})
        mock_client.chat.completions.create.return_value = create_mock_stream_response(disambiguate_result.model_dump_json())

        client = UnifiedModelClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )

        candidates = ["张三"]
        existing_names = ["李四", "王五"]
        result = client.disambiguate_characters(candidates, existing_names=existing_names)


if __name__ == "__main__":
    unittest.main()
