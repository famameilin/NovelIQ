import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.validator import (
    generate_anonymous_name,
    replace_invalid_names_with_anonymous,
    validate_names_in_sources,
)
from src.models.local.prompts import build_retry_prompt
from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    DialogueSnapshot,
    RelationChangeSnapshot,
)


class TestValidateNamesInSources(unittest.TestCase):
    def test_valid_name_in_text(self) -> None:
        sources = {
            "text": "张三走进房间，看到了李四。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": None,
        }
        invalid = validate_names_in_sources(["张三", "李四"], sources)
        self.assertEqual(invalid, [])

    def test_invalid_name_not_in_sources(self) -> None:
        sources = {
            "text": "张三走进房间。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": None,
        }
        invalid = validate_names_in_sources(["张三", "王五"], sources)
        self.assertEqual(invalid, ["王五"])

    def test_valid_name_in_prev_chunk_text(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_chunk_text": "李四站在门口等待。",
            "active_entities": None,
            "alias_map": None,
        }
        invalid = validate_names_in_sources(["李四"], sources)
        self.assertEqual(invalid, [])

    def test_valid_name_in_active_entities(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_tail_text": None,
            "active_entities": ["张三", "李四"],
            "alias_map": None,
        }
        invalid = validate_names_in_sources(["张三"], sources)
        self.assertEqual(invalid, [])

    def test_valid_name_in_alias_map(self) -> None:
        sources = {
            "text": "猴子走进房间。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": {"猴子": "侯飞白", "算盘": "林立果"},
        }
        invalid = validate_names_in_sources(["侯飞白", "林立果"], sources)
        self.assertEqual(invalid, [])

    def test_all_sources_combined(self) -> None:
        sources = {
            "text": "「张三」看着远方。",
            "prev_chunk_text": "李四已经离开。",
            "active_entities": ["王五"],
            "alias_map": {"猴子": "侯飞白"},
        }
        invalid = validate_names_in_sources(["张三", "李四", "王五", "侯飞白", "赵六"], sources)
        self.assertEqual(invalid, ["赵六"])

    def test_empty_sources(self) -> None:
        sources = {
            "text": "",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": None,
        }
        invalid = validate_names_in_sources(["张三"], sources)
        self.assertEqual(invalid, ["张三"])

    def test_valid_name_in_next_chunk_text(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_chunk_text": None,
            "active_entities": None,
            "alias_map": None,
            "next_chunk_text": "张三站在门口等待。",
        }
        invalid = validate_names_in_sources(["张三"], sources)
        self.assertEqual(invalid, [])

    def test_valid_name_as_substring_of_alias_map_value(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": {"猴子": "侯飞白", "算盘": "林立果"},
        }
        invalid = validate_names_in_sources(["侯飞"], sources)
        self.assertEqual(invalid, [])

    def test_name_not_substring_of_self(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": {"猴子": "侯飞白"},
        }
        invalid = validate_names_in_sources(["侯飞白"], sources)
        self.assertEqual(invalid, [])

    def test_name_is_exact_alias_map_value(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": {"猴子": "侯飞白"},
        }
        invalid = validate_names_in_sources(["侯飞白"], sources)
        self.assertEqual(invalid, [])

    def test_name_not_in_any_source(self) -> None:
        sources = {
            "text": "他继续往前走。",
            "prev_tail_text": None,
            "active_entities": None,
            "alias_map": {"猴子": "侯飞白"},
        }
        invalid = validate_names_in_sources(["王五"], sources)
        self.assertEqual(invalid, ["王五"])


class TestGenerateAnonymousName(unittest.TestCase):
    def test_format(self) -> None:
        name = generate_anonymous_name(1, 0)
        self.assertEqual(name, "匿名_C1_0")

    def test_different_chunk_ids(self) -> None:
        name1 = generate_anonymous_name(1, 0)
        name2 = generate_anonymous_name(2, 0)
        self.assertNotEqual(name1, name2)

    def test_different_indices(self) -> None:
        name1 = generate_anonymous_name(1, 0)
        name2 = generate_anonymous_name(1, 1)
        self.assertNotEqual(name1, name2)


class TestReplaceInvalidNamesWithAnonymous(unittest.TestCase):
    def test_replace_character_name(self) -> None:
        annotation = ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(name="张三", role_function="主体", action="行走", action_type="移动", emotion_score="neutral"),
                CharacterSnapshot(name="李四", role_function="其他", action="站立", action_type="其他", emotion_score="neutral"),
            ],
            relations=[],
            dialogues=[],
        )
        result = replace_invalid_names_with_anonymous(annotation, ["李四"], 1)
        self.assertEqual(result.characters[0].name, "张三")
        self.assertEqual(result.characters[1].name, "匿名_C1_0")

    def test_replace_relation_names(self) -> None:
        annotation = ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[],
            relations=[
                RelationChangeSnapshot(from_name="张三", to_name="李四", type="敌对", change="强化"),
            ],
            dialogues=[],
        )
        result = replace_invalid_names_with_anonymous(annotation, ["张三", "李四"], 2)
        self.assertEqual(result.relations[0].from_name, "匿名_C2_0")
        self.assertEqual(result.relations[0].to_name, "匿名_C2_1")

    def test_replace_dialogue_speaker(self) -> None:
        annotation = ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[],
            relations=[],
            dialogues=[
                DialogueSnapshot(speaker="张三"),
            ],
        )
        result = replace_invalid_names_with_anonymous(annotation, ["张三"], 3)
        self.assertEqual(result.dialogues[0].speaker, "匿名_C3_0")

    def test_same_invalid_name_same_anonymous(self) -> None:
        annotation = ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(name="张三", role_function="主体", action="行走", action_type="移动", emotion_score="neutral"),
            ],
            relations=[
                RelationChangeSnapshot(from_name="张三", to_name="李四", type="敌对", change="强化"),
            ],
            dialogues=[
                DialogueSnapshot(speaker="张三"),
            ],
        )
        result = replace_invalid_names_with_anonymous(annotation, ["张三"], 4)
        self.assertEqual(result.characters[0].name, "匿名_C4_0")
        self.assertEqual(result.relations[0].from_name, "匿名_C4_0")
        self.assertEqual(result.dialogues[0].speaker, "匿名_C4_0")


class TestBuildRetryPrompt(unittest.TestCase):
    def test_format(self) -> None:
        prompt = build_retry_prompt(
            original_user_prompt="请标注以下文本...",
            bad_output='{"characters": [{"name": "张三"}]}',
            invalid_names=["张三", "李四"],
        )
        self.assertIn("请标注以下文本...", prompt)
        self.assertIn("【上次输出有误，请重新标注】", prompt)
        self.assertIn("张三、李四", prompt)
        self.assertIn('{"characters": [{"name": "张三"}]}', prompt)
        self.assertIn("请严格遵守【严格限制】规则", prompt)

    def test_single_invalid_name(self) -> None:
        prompt = build_retry_prompt(
            original_user_prompt="原始 prompt",
            bad_output="错误输出",
            invalid_names=["王五"],
        )
        self.assertIn("王五", prompt)


if __name__ == "__main__":
    unittest.main()
