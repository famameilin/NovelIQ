import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.context.rolling_memory import (
    get_prev_tail_text,
    get_next_text,
    format_rolling_memory_for_prompt,
)


class TestRollingMemory(unittest.TestCase):
    """
    滚动记忆测试

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 更新测试用例以使用 ChunkRepository 接口
    """

    def test_get_prev_tail_text_first_chunk(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_prev_chunk_text.return_value = None
        result = get_prev_tail_text(mock_repo, run_id="test-run", chunk_id=0, tail_chars=200)
        self.assertIsNone(result)

    def test_get_prev_tail_text_no_previous_chunk(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_prev_chunk_text.return_value = None

        result = get_prev_tail_text(mock_repo, run_id="test-run", chunk_id=5, tail_chars=200)
        self.assertIsNone(result)

    def test_get_prev_tail_text_short_text(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_prev_chunk_text.return_value = "短文本内容"

        result = get_prev_tail_text(mock_repo, run_id="test-run", chunk_id=1, tail_chars=200)
        self.assertEqual(result, "短文本内容")

    def test_get_prev_tail_text_long_text(self) -> None:
        """
        测试长文本

        修改时间: 2026-03-13
        修改者: TraeAI
        任务: refactor-core-data-layer-functions
        修改原因: get_prev_tail_text 已被修改为返回完整的上一个 chunk 文本，
                 而不是只返回末尾部分。此测试验证函数返回完整文本。
        """
        mock_repo = MagicMock()
        long_text = "a" * 500
        mock_repo.fetch_prev_chunk_text.return_value = long_text

        result = get_prev_tail_text(mock_repo, run_id="test-run", chunk_id=1, tail_chars=200)
        self.assertEqual(len(result), 500)
        self.assertEqual(result, long_text)

    def test_get_prev_tail_text_custom_tail_chars(self) -> None:
        """
        测试自定义尾部字符数

        修改时间: 2026-03-13
        修改者: TraeAI
        任务: refactor-core-data-layer-functions
        修改原因: get_prev_tail_text 已被修改为返回完整的上一个 chunk 文本，
                 而不是只返回末尾部分。tail_chars 参数已不再用于截断文本。
                 此测试验证函数返回完整文本。
        """
        mock_repo = MagicMock()
        text = "这是一段测试文本，用于测试尾部文本提取功能。"
        mock_repo.fetch_prev_chunk_text.return_value = text

        result = get_prev_tail_text(mock_repo, run_id="test-run", chunk_id=1, tail_chars=10)
        self.assertEqual(result, text)

    def test_get_next_text(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_next_chunk_text.return_value = "下一个chunk的内容"

        result = get_next_text(mock_repo, run_id="test-run", chunk_id=1)
        self.assertEqual(result, "下一个chunk的内容")

    def test_get_next_text_no_next_chunk(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_next_chunk_text.return_value = None

        result = get_next_text(mock_repo, run_id="test-run", chunk_id=100)
        self.assertIsNone(result)

    def test_format_rolling_memory_empty(self) -> None:
        result = format_rolling_memory_for_prompt(None, None)
        self.assertEqual(result, "")

    def test_format_rolling_memory_only_tail_text(self) -> None:
        result = format_rolling_memory_for_prompt("前文尾部内容", None)
        self.assertIn("<Previous_Context>", result)
        self.assertIn("前文尾部内容", result)
        self.assertIn("</Previous_Context>", result)
        self.assertNotIn("<Active_Entities>", result)

    def test_format_rolling_memory_only_entities(self) -> None:
        result = format_rolling_memory_for_prompt(None, "【近期活跃角色】\n- 张三")
        self.assertNotIn("<Previous_Context>", result)
        self.assertIn("<Active_Entities>", result)
        self.assertIn("【近期活跃角色】", result)
        self.assertIn("</Active_Entities>", result)

    def test_format_rolling_memory_both(self) -> None:
        result = format_rolling_memory_for_prompt("前文尾部", "活跃角色信息")

        self.assertIn("<Previous_Context>", result)
        self.assertIn("前文尾部", result)
        self.assertIn("</Previous_Context>", result)
        self.assertIn("<Active_Entities>", result)
        self.assertIn("活跃角色信息", result)
        self.assertIn("</Active_Entities>", result)

        parts = result.split("\n\n")
        self.assertEqual(len(parts), 2)


if __name__ == "__main__":
    unittest.main()
