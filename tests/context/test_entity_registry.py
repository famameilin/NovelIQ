import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.context.entity_registry import (
    format_entities_for_prompt,
    get_active_entities,
)


class TestEntityRegistry(unittest.TestCase):
    """
    实体注册测试

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 更新测试用例以使用 EntityRepository 接口
    """

    def test_format_entities_for_prompt_empty(self) -> None:
        result = format_entities_for_prompt([])
        self.assertEqual(result, "")

    def test_format_entities_for_prompt_single_entity(self) -> None:
        entities = [
            {
                "name": "张三",
                "role": "主角",
                "last_action": "走进房间",
                "last_emotion": "平静",
                "emotion_score": 0,
            }
        ]
        result = format_entities_for_prompt(entities)

        self.assertIn("【近期活跃角色】", result)
        self.assertIn("张三（主角）", result)
        self.assertIn("走进房间", result)
        self.assertIn("平静", result)

    def test_format_entities_for_prompt_multiple_entities(self) -> None:
        entities = [
            {
                "name": "张三",
                "role": "主角",
                "last_action": "拔剑",
                "last_emotion": "愤怒",
                "emotion_score": 5,
            },
            {
                "name": "李四",
                "role": "配角",
                "last_action": "后退",
                "last_emotion": "恐惧",
                "emotion_score": -3,
            },
        ]
        result = format_entities_for_prompt(entities)

        self.assertIn("张三（主角）：拔剑；愤怒（5）", result)
        self.assertIn("李四（配角）：后退；恐惧（-3）", result)

    def test_get_active_entities_empty(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_active_entities.return_value = []

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual(result, [])

    def test_get_active_entities_with_data(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_active_entities.return_value = [
            (1, "张三", "主角", "走进房间", "平静", 0),
            (2, "李四", "配角", "跟随", "紧张", -2),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "张三")
        self.assertEqual(result[1]["name"], "李四")

    def test_get_active_entities_deduplication(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_active_entities.return_value = [
            (1, "张三", "主角", "动作1", "情绪1", 0),
            (2, "张三", "主角", "动作2", "情绪2", 1),
            (3, "李四", "配角", "动作3", "情绪3", 0),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual(len(result), 2)
        names = [e["name"] for e in result]
        self.assertIn("张三", names)
        self.assertIn("李四", names)


if __name__ == "__main__":
    unittest.main()
