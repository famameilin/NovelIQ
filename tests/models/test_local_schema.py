"""
测试本地数据模型

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试数据模型

修改时间: 2026-03-29
修改者: TraeAI
任务: refactor-phase1-identity-extraction
修改内容: 移除 relations 字段相关测试
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    DialogueSnapshot,
)


class TestLocalSchema(unittest.TestCase):
    def test_schema_to_dict_keys(self) -> None:
        annotation = ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name="张三",
                    role_function="主体",
                    action="走",
                    action_type="移动",
                    emotion_score="neutral",
                )
            ],
            dialogues=[
                DialogueSnapshot(
                    speaker=["张三"],
                )
            ],
        )
        payload = annotation.to_dict()
        self.assertIn("emotional_valence", payload)
        self.assertIn("event_type", payload)
        self.assertIn("characters", payload)
        self.assertIn("dialogues", payload)

    def test_emotion_score_enum(self) -> None:
        annotation = ChunkAnnotation(
            emotional_valence="strong_positive",
            event_type="冲突",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name="张三",
                    role_function="主体",
                    action="战斗",
                    action_type="战斗",
                    emotion_score="strong_positive",
                )
            ],
        )
        self.assertIsNotNone(annotation)


if __name__ == "__main__":
    unittest.main()
