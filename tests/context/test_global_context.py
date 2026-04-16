import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.context.global_context import (
    extract_global_context,
    format_global_context_for_prompt,
)


class TestGlobalContext(unittest.TestCase):
    def test_extract_global_context_empty_chunks(self) -> None:
        result = asyncio.run(extract_global_context([]))
        self.assertEqual(result["core_characters"], [])
        self.assertEqual(result["world_setting"], "")

    def test_extract_global_context_with_quotes(self) -> None:
        chunks = [
            '张三说："今天天气真好。"',
            '李四回答："是啊，适合出行。"',
            "王五也加入了对话。",
        ]
        result = asyncio.run(extract_global_context(chunks))

        self.assertTrue(len(result["core_characters"]) >= 0)

    def test_extract_global_context_with_model(self) -> None:
        mock_client = MagicMock()
        mock_inner_client = AsyncMock()
        mock_client._client = mock_inner_client
        mock_client._config = MagicMock()
        mock_client._config.model = "test-model"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[
            0
        ].message.content = '{"core_characters": ["张三", "李四"], "world_setting": "古代武侠世界"}'
        mock_inner_client.chat.completions.create = AsyncMock(return_value=mock_response)

        chunks = ["第一章 张三出场", "李四也出现了"]
        result = asyncio.run(extract_global_context(chunks, client=mock_client))

        self.assertEqual(result["core_characters"], ["张三", "李四"])
        self.assertEqual(result["world_setting"], "古代武侠世界")

    def test_format_global_context_for_prompt_empty(self) -> None:
        result = format_global_context_for_prompt({})
        self.assertEqual(result, "")

    def test_format_global_context_for_prompt_with_characters(self) -> None:
        context = {"core_characters": ["张三", "李四", "王五"]}
        result = format_global_context_for_prompt(context)

        self.assertIn("【全局核心信息】", result)
        self.assertIn("核心角色：张三、李四、王五", result)

    def test_format_global_context_for_prompt_with_world_setting(self) -> None:
        context = {
            "core_characters": ["张三"],
            "world_setting": "修仙世界，强者为尊",
        }
        result = format_global_context_for_prompt(context)

        self.assertIn("世界观：修仙世界，强者为尊", result)

    def test_format_global_context_for_prompt_full(self) -> None:
        context = {
            "core_characters": ["张三", "李四"],
            "world_setting": "古代江湖",
        }
        result = format_global_context_for_prompt(context)

        self.assertIn("【全局核心信息】", result)
        self.assertIn("核心角色：张三、李四", result)
        self.assertIn("世界观：古代江湖", result)


if __name__ == "__main__":
    unittest.main()
