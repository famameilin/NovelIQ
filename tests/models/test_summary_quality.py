import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.parser.annotation_builder import (
    _deduplicate_characters,
    _parse_characters,
)
from src.models.local.schema import CharacterSnapshot


class TestCharacterDeduplication(unittest.TestCase):
    """
    测试角色去重逻辑

    创建时间: 2026-03-27
    任务: fix-duplicate-characters-in-chunk
    说明: 测试同一人物重复出现时的去重处理

    修改时间: 2026-03-29
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 validate_summary_quality 相关测试（chunk_summary 已移除）
    """

    def test_no_duplicates_returns_same_list(self) -> None:
        characters = [
            CharacterSnapshot(
                name="伯安", role_function="主体", action="行动", action_type="其他", emotion_score="neutral"
            ),
            CharacterSnapshot(
                name="林立果", role_function="客体", action="被裹挟", action_type="其他", emotion_score="neutral"
            ),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 2)

    def test_duplicate_keeps_higher_priority_role(self) -> None:
        characters = [
            CharacterSnapshot(
                name="伯安", role_function="客体", action="被白芷称为哥哥", action_type="其他", emotion_score="neutral"
            ),
            CharacterSnapshot(
                name="伯安",
                role_function="主体",
                action="决定拜师白芷",
                action_type="其他",
                emotion_score="mild_positive",
            ),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role_function, "主体")
        self.assertEqual(result[0].action, "决定拜师白芷")

    def test_duplicate_same_priority_keeps_first(self) -> None:
        characters = [
            CharacterSnapshot(
                name="伯安", role_function="客体", action="被白芷称为哥哥", action_type="其他", emotion_score="neutral"
            ),
            CharacterSnapshot(
                name="伯安",
                role_function="客体",
                action="决定拜师白芷",
                action_type="其他",
                emotion_score="mild_positive",
            ),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].action, "被白芷称为哥哥")

    def test_multiple_duplicates_all_resolved(self) -> None:
        characters = [
            CharacterSnapshot(
                name="伯安", role_function="客体", action="行为1", action_type="其他", emotion_score="neutral"
            ),
            CharacterSnapshot(
                name="林立果", role_function="主体", action="行为2", action_type="其他", emotion_score="neutral"
            ),
            CharacterSnapshot(
                name="伯安", role_function="主体", action="行为3", action_type="其他", emotion_score="neutral"
            ),
            CharacterSnapshot(
                name="林立果", role_function="客体", action="行为4", action_type="其他", emotion_score="neutral"
            ),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 2)
        for char in result:
            if char.name == "伯安":
                self.assertEqual(char.role_function, "主体")
            elif char.name == "林立果":
                self.assertEqual(char.role_function, "主体")

    def test_empty_list_returns_empty(self) -> None:
        result = _deduplicate_characters([])
        self.assertEqual(len(result), 0)

    def test_parse_characters_deduplicates(self) -> None:
        data = {
            "characters": [
                {"name": "伯安", "role_function": "客体", "action": "行为1", "emotion_score": "neutral"},
                {"name": "伯安", "role_function": "主体", "action": "行为2", "emotion_score": "neutral"},
            ]
        }
        result = _parse_characters(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role_function, "主体")

    def test_role_function_priority_order(self) -> None:
        characters = [
            CharacterSnapshot(name="A", role_function="接收者", action="", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="A", role_function="发送者", action="", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="A", role_function="反对者", action="", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="A", role_function="帮助者", action="", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="A", role_function="客体", action="", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="A", role_function="主体", action="", action_type="其他", emotion_score="neutral"),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role_function, "主体")


if __name__ == "__main__":
    unittest.main()
