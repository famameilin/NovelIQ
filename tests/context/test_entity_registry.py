import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.context.entity_registry import get_active_entities


class TestEntityRegistry(unittest.TestCase):
    """
    实体注册测试

    修改时间: 2026-03-14
    任务: metrics-repository-refactor
    修改内容: 测试实体上下文查询和提示词格式化（基于 GraphRepository）
    """

    def test_get_active_entities_with_data(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chapter=1,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "走进房间",
                    "emotion": "平静",
                    "emotion_score": 0,
                },
            ),
            SimpleNamespace(
                last_seen_chapter=2,
                name="李四",
                state={
                    "role_function": "配角",
                    "action": "跟随",
                    "emotion": "紧张",
                    "emotion_score": -2,
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chapter_id=5, lookback=10)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "张三")
        self.assertEqual(result[1]["name"], "李四")

    def test_get_active_entities_deduplication(self) -> None:
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chapter=1,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "动作1",
                    "emotion": "情绪1",
                    "emotion_score": 0,
                },
            ),
            SimpleNamespace(
                last_seen_chapter=2,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "动作2",
                    "emotion": "情绪2",
                    "emotion_score": 1,
                },
            ),
            SimpleNamespace(
                last_seen_chapter=3,
                name="李四",
                state={
                    "role_function": "配角",
                    "action": "动作3",
                    "emotion": "情绪3",
                    "emotion_score": 0,
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chapter_id=5, lookback=10)

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
                last_seen_chapter=1,
                name="张三",
                state={
                    "role_function": "主角",
                    "action": "走进房间",
                    "emotion": "平静",
                    "emotion_score": 0,
                },
            ),
            SimpleNamespace(
                last_seen_chapter=2,
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

        result = get_active_entities(mock_repo, run_id="test-run", current_chapter_id=5, lookback=10)

        self.assertEqual([e["name"] for e in result], ["张三"])

    def test_get_active_entities_status_defaults_to_active(self) -> None:
        """2026-08-12 用于验证 state 未写 status 的实体按 active 处理（与 authority 口径一致）"""
        mock_repo = MagicMock()
        mock_repo.fetch_latest_entities.return_value = [
            SimpleNamespace(
                last_seen_chapter=3,
                name="王五",
                state={
                    "role_function": "主角",
                    "action": "登场",
                    "emotion": "平静",
                    "emotion_score": 0,
                },
            ),
        ]

        result = get_active_entities(mock_repo, run_id="test-run", current_chapter_id=5, lookback=10)

        self.assertEqual([e["name"] for e in result], ["王五"])


if __name__ == "__main__":
    unittest.main()
