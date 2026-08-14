import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    任务: metrics-repository-refactor
    修改内容: 测试实体上下文查询和提示词格式化（基于 GraphRepository）
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
        mock_repo.fetch_latest_entities.return_value = []

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual(result, [])

    def test_get_active_entities_with_data(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chunk=1,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "走进房间",
                    "emotion": "平静",
                    "emotion_score": 0,
                },
            ),
            SimpleNamespace(
                last_seen_chunk=2,
                name="李四",
                state={
                    "role_function": "配角",
                    "action": "跟随",
                    "emotion": "紧张",
                    "emotion_score": -2,
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "张三")
        self.assertEqual(result[1]["name"], "李四")

    def test_get_active_entities_deduplication(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chunk=1,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "动作1",
                    "emotion": "情绪1",
                    "emotion_score": 0,
                },
            ),
            SimpleNamespace(
                last_seen_chunk=2,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "动作2",
                    "emotion": "情绪2",
                    "emotion_score": 1,
                },
            ),
            SimpleNamespace(
                last_seen_chunk=3,
                name="李四",
                state={
                    "role_function": "配角",
                    "action": "动作3",
                    "emotion": "情绪3",
                    "emotion_score": 0,
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual(len(result), 2)
        names = [e["name"] for e in result]
        self.assertIn("张三", names)
        self.assertIn("李四", names)
        # 2026-08-14 D9：同名实体保留 last_seen_chunk 最新者（动作/情绪取最新行）
        zhang = next(e for e in result if e["name"] == "张三")
        self.assertEqual(zhang["last_action"], "动作2")
        self.assertEqual(zhang["emotion_score"], 1)

    def test_get_active_entities_filters_inactive_status(self) -> None:
        """2026-08-12 用于验证 status 非 active（显式写入 state）的实体被过滤"""
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chunk=1,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "走进房间",
                    "emotion": "平静",
                    "emotion_score": 0,
                },
            ),
            SimpleNamespace(
                last_seen_chunk=2,
                name="李四",
                state={
                    "role_function": "配角",
                    "action": "退场",
                    "emotion": "平静",
                    "emotion_score": 0,
                    "status": "inactive",
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual([e["name"] for e in result], ["张三"])

    def test_get_active_entities_status_defaults_to_active(self) -> None:
        """2026-08-12 用于验证 state 未写 status 的实体按 active 处理（与 authority 口径一致）"""
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chunk=3,
                name="王五",
                state={
                    "role_function": "主角",
                    "action": "登场",
                    "emotion": "平静",
                    "emotion_score": 0,
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chunk_id=5, lookback=10)

        self.assertEqual([e["name"] for e in result], ["王五"])


if __name__ == "__main__":
    unittest.main()
