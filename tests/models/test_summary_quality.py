import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.parser.annotation_builder import (
    validate_summary_quality,
    _SUMMARY_MIN_LENGTH,
    _SUMMARY_MAX_LENGTH,
    _deduplicate_characters,
    _parse_characters,
)
from src.models.local.schema import CharacterSnapshot


class TestCharacterDeduplication(unittest.TestCase):
    """
    测试角色去重逻辑

    创建时间: 2026-03-27
    创建者: TraeAI
    任务: fix-duplicate-characters-in-chunk
    说明: 测试同一人物重复出现时的去重处理
    """

    def test_no_duplicates_returns_same_list(self) -> None:
        characters = [
            CharacterSnapshot(name="伯安", role_function="主体", action="行动", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="林立果", role_function="客体", action="被裹挟", action_type="其他", emotion_score="neutral"),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 2)

    def test_duplicate_keeps_higher_priority_role(self) -> None:
        characters = [
            CharacterSnapshot(name="伯安", role_function="客体", action="被白芷称为哥哥", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="伯安", role_function="主体", action="决定拜师白芷", action_type="其他", emotion_score="mild_positive"),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].role_function, "主体")
        self.assertEqual(result[0].action, "决定拜师白芷")

    def test_duplicate_same_priority_keeps_first(self) -> None:
        characters = [
            CharacterSnapshot(name="伯安", role_function="客体", action="被白芷称为哥哥", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="伯安", role_function="客体", action="决定拜师白芷", action_type="其他", emotion_score="mild_positive"),
        ]
        result = _deduplicate_characters(characters)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].action, "被白芷称为哥哥")

    def test_multiple_duplicates_all_resolved(self) -> None:
        characters = [
            CharacterSnapshot(name="伯安", role_function="客体", action="行为1", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="林立果", role_function="主体", action="行为2", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="伯安", role_function="主体", action="行为3", action_type="其他", emotion_score="neutral"),
            CharacterSnapshot(name="林立果", role_function="客体", action="行为4", action_type="其他", emotion_score="neutral"),
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


class TestSummaryQualityValidation(unittest.TestCase):
    """
    测试摘要质量校验

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: disambiguation-evidence-grading
    说明: 测试摘要长度和名字粘连检测
    """

    def test_valid_summary_passes(self) -> None:
        summary = "伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生，但眼神锐利。"
        passed, issues = validate_summary_quality(summary)

        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)

    def test_short_summary_fails(self) -> None:
        summary = "伯安看灰衣人。"
        passed, issues = validate_summary_quality(summary)

        self.assertFalse(passed)
        self.assertTrue(any("过短" in issue for issue in issues))

    def test_long_summary_fails(self) -> None:
        summary = "伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生，但眼神中却透露出一股锐利的光芒，让人不敢小觑。" * 2
        passed, issues = validate_summary_quality(summary)

        self.assertFalse(passed)
        self.assertTrue(any("过长" in issue for issue in issues))

    def test_name_adhesion_detected(self) -> None:
        summary = "灰衣人伯安近看觉得对方身形单薄，似乎是个文弱书生。"
        passed, issues = validate_summary_quality(summary)

        self.assertFalse(passed)
        self.assertTrue(any("粘连" in issue for issue in issues))

    def test_empty_summary_passes(self) -> None:
        summary = ""
        passed, issues = validate_summary_quality(summary)

        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)

    def test_min_length_boundary(self) -> None:
        summary = "伯安近看灰衣人，觉得对方身形单薄，似书生。"
        if len(summary) >= _SUMMARY_MIN_LENGTH:
            passed, issues = validate_summary_quality(summary)
            self.assertTrue(passed or not any("过短" in issue for issue in issues))

    def test_max_length_boundary(self) -> None:
        summary = "伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生。"
        if len(summary) <= _SUMMARY_MAX_LENGTH:
            passed, issues = validate_summary_quality(summary)
            self.assertTrue(passed or not any("过长" in issue for issue in issues))

    def test_good_writing_style_passes(self) -> None:
        summary = "灰衣人前来应聘教习，伯安因此留意对方，发现其身形单薄，似书生。"
        passed, issues = validate_summary_quality(summary)

        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)


if __name__ == "__main__":
    unittest.main()
