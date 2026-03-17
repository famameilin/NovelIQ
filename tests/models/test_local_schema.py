import sys
from pathlib import Path
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    DialogueSnapshot,
    RelationChangeSnapshot,
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
            relations=[
                RelationChangeSnapshot(
                    from_name="张三",
                    to_name="李四",
                    type="盟友",
                    change="新建",
                )
            ],
            dialogues=[
                DialogueSnapshot(
                    speaker="张三",
                )
            ],
        )
        payload = annotation.to_dict()
        self.assertIn("emotional_valence", payload)
        self.assertIn("event_type", payload)
        self.assertIn("characters", payload)
        self.assertIn("relations", payload)
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
