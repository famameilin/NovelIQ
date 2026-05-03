"""
测试本地数据模型

创建时间: 2025-03-11
任务: 测试数据模型

修改时间: 2026-03-29
任务: refactor-phase1-identity-extraction
修改内容: 移除 relations 字段相关测试
"""

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    DialogueSnapshot,
    ForeshadowingResult,
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
        self.assertIn("is_strong_setup", payload)
        self.assertIn("setup_kind", payload)
        self.assertIn("why_unresolved_now", payload)
        self.assertIn("expected_payoff_family", payload)

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

    def test_positive_foreshadowing_requires_formal_type(self) -> None:
        with self.assertRaises(ValidationError):
            ForeshadowingResult(
                has_foreshadowing=True,
                is_strong_setup=True,
                foreshadowing_type=None,
                anchor_text="玉佩在夜里自行发热。",
                anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
                why_unresolved_now="当前还没有解释它为何会发热。",
                expected_payoff_family="能力触发",
                confidence="high",
            )

    def test_positive_foreshadowing_requires_strong_setup_flag(self) -> None:
        with self.assertRaises(ValidationError):
            ForeshadowingResult(
                has_foreshadowing=True,
                is_strong_setup=False,
                foreshadowing_type="物件",
                setup_kind="异常物件",
                anchor_text="玉佩在夜里自行发热。",
                anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
                why_unresolved_now="当前还没有解释它为何会发热。",
                expected_payoff_family="能力触发",
                confidence="high",
            )

    def test_positive_foreshadowing_requires_setup_kind(self) -> None:
        with self.assertRaises(ValidationError):
            ForeshadowingResult(
                has_foreshadowing=True,
                is_strong_setup=True,
                foreshadowing_type="物件",
                setup_kind=None,
                anchor_text="玉佩在夜里自行发热。",
                anchor_reason="具体钩子：玉佩在夜里自行发热。未闭合原因：当前还没有解释它为何会发热。",
                why_unresolved_now="当前还没有解释它为何会发热。",
                expected_payoff_family="能力触发",
                confidence="high",
            )

    def test_negative_foreshadowing_rejects_strong_setup_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ForeshadowingResult(
                has_foreshadowing=False,
                is_strong_setup=True,
                foreshadowing_type=None,
                setup_kind="异常物件",
                anchor_text="",
                anchor_reason="具体钩子：无。未闭合原因：这里只是在解释为什么不是伏笔。",
                why_unresolved_now="",
                expected_payoff_family="",
                confidence="low",
            )


if __name__ == "__main__":
    unittest.main()
