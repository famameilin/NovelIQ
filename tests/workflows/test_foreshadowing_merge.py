"""
创建时间: 2026-03-20
创建者: TraeAI
任务: fix-null-fields-issue - 修复伏笔字段空值问题
说明: 测试伏笔结果合并到 ChunkAnnotation 的逻辑

修改时间: 2026-03-29
修改者: TraeAI
任务: refactor-phase1-identity-extraction
修改内容: 移除 relations、character_appearances、chunk_summary 字段
"""
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    ForeshadowingResult,
)


class TestForeshadowingMerge(unittest.TestCase):
    """测试伏笔结果合并到 ChunkAnnotation 的逻辑"""

    def _create_base_annotation(self) -> ChunkAnnotation:
        """创建基础标注对象"""
        return ChunkAnnotation(
            emotional_valence="positive",
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
                    action="测试行为",
                    action_type="其他",
                    emotion_score="neutral",
                )
            ],
            dialogues=[],
        )

    def test_merge_foreshadowing_with_has_foreshadowing_true(self) -> None:
        """测试合并有伏笔的结果"""
        annotation = self._create_base_annotation()
        foreshadowing = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="物件",
            anchor_text="玉佩背面刻着归字",
            anchor_reason="暗示后文身份揭示",
            confidence="high",
        )

        merged = ChunkAnnotation(
            emotional_valence=annotation.emotional_valence,
            event_type=annotation.event_type,
            pivot_moment=annotation.pivot_moment,
            cliffhanger=annotation.cliffhanger,
            has_foreshadowing=foreshadowing.has_foreshadowing,
            foreshadowing_type=foreshadowing.foreshadowing_type,
            foreshadowing_desc=(
                f"{foreshadowing.anchor_text} - {foreshadowing.anchor_reason}"
                if foreshadowing.has_foreshadowing else ""
            ),
            characters=annotation.characters,
            dialogues=annotation.dialogues,
        )

        self.assertTrue(merged.has_foreshadowing)
        self.assertEqual(merged.foreshadowing_type, "物件")
        self.assertEqual(
            merged.foreshadowing_desc,
            "玉佩背面刻着归字 - 暗示后文身份揭示",
        )

    def test_merge_foreshadowing_with_has_foreshadowing_false(self) -> None:
        """测试合并无伏笔的结果"""
        annotation = self._create_base_annotation()
        foreshadowing = ForeshadowingResult(
            has_foreshadowing=False,
            foreshadowing_type=None,
            anchor_text="",
            anchor_reason="",
            confidence="low",
        )

        merged = ChunkAnnotation(
            emotional_valence=annotation.emotional_valence,
            event_type=annotation.event_type,
            pivot_moment=annotation.pivot_moment,
            cliffhanger=annotation.cliffhanger,
            has_foreshadowing=foreshadowing.has_foreshadowing,
            foreshadowing_type=foreshadowing.foreshadowing_type,
            foreshadowing_desc=(
                f"{foreshadowing.anchor_text} - {foreshadowing.anchor_reason}"
                if foreshadowing.has_foreshadowing else ""
            ),
            characters=annotation.characters,
            dialogues=annotation.dialogues,
        )

        self.assertFalse(merged.has_foreshadowing)
        self.assertIsNone(merged.foreshadowing_type)
        self.assertEqual(merged.foreshadowing_desc, "")

    def test_merge_preserves_other_fields(self) -> None:
        """测试合并保留其他字段"""
        annotation = self._create_base_annotation()
        foreshadowing = ForeshadowingResult(
            has_foreshadowing=True,
            foreshadowing_type="对话",
            anchor_text="测试锚点",
            anchor_reason="测试原因",
            confidence="medium",
        )

        merged = ChunkAnnotation(
            emotional_valence=annotation.emotional_valence,
            event_type=annotation.event_type,
            pivot_moment=annotation.pivot_moment,
            cliffhanger=annotation.cliffhanger,
            has_foreshadowing=foreshadowing.has_foreshadowing,
            foreshadowing_type=foreshadowing.foreshadowing_type,
            foreshadowing_desc=(
                f"{foreshadowing.anchor_text} - {foreshadowing.anchor_reason}"
                if foreshadowing.has_foreshadowing else ""
            ),
            characters=annotation.characters,
            dialogues=annotation.dialogues,
        )

        self.assertEqual(merged.emotional_valence, "positive")
        self.assertEqual(merged.event_type, "铺垫")
        self.assertFalse(merged.pivot_moment)
        self.assertFalse(merged.cliffhanger)
        self.assertEqual(len(merged.characters), 1)
        self.assertEqual(merged.characters[0].name, "张三")


if __name__ == "__main__":
    unittest.main()
