import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.context.global_context import extract_global_context


class TestGlobalContext(unittest.TestCase):
    def test_extract_global_context_empty_chunks(self) -> None:
        result = asyncio.run(extract_global_context([]))
        self.assertEqual(result["core_characters"], [])
        self.assertEqual(result["world_setting"], "")

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


if __name__ == "__main__":
    unittest.main()
