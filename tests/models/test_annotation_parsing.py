import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.annotation import AnnotationClient
from src.models.local.parser import make_empty_annotation, try_parse_json
from src.models.local.schema import ChunkAnnotation


class TestJsonParsing(unittest.TestCase):
    def test_parse_valid_json(self) -> None:
        content = json.dumps({
            "emotional_valence": "neutral",
            "event_type": "铺垫",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": None,
            "foreshadowing_desc": "",
        })
        result = try_parse_json(content)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["emotional_valence"], "neutral")

    def test_parse_json_with_markdown_code_block(self) -> None:
        content = """```json
{
    "emotional_valence": "strong_positive",
    "event_type": "转折",
    "pivot_moment": true,
    "cliffhanger": false,
    "has_foreshadowing": false,
    "foreshadowing_type": null,
    "foreshadowing_desc": ""
}
```"""
        result = try_parse_json(content)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["emotional_valence"], "strong_positive")

    def test_parse_json_with_trailing_comma(self) -> None:
        content = '{"emotional_valence": "neutral", "event_type": "铺垫", "pivot_moment": false, "cliffhanger": false, "has_foreshadowing": false, "foreshadowing_type": null, "foreshadowing_desc": "有描述",}'
        result = try_parse_json(content)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["emotional_valence"], "neutral")

    def test_parse_invalid_json_returns_none(self) -> None:
        content = "这完全不是 JSON"
        result = try_parse_json(content)
        self.assertIsNone(result)

    def test_parse_annotation_invalid_json_returns_empty(self) -> None:
        config = TaskModelConfig(base_url="http://test:8000/v1", model="test-model")
        mock_client = MagicMock()
        client = AnnotationClient(task_type="annotation", config=config, client=mock_client)
        annotation = client._parse_annotation("invalid json content")
        self.assertEqual(annotation.emotional_valence, "neutral")
        self.assertEqual(annotation.event_type, "铺垫")


class TestMakeEmptyAnnotation(unittest.TestCase):
    def test_make_empty_annotation_returns_valid_annotation(self) -> None:
        annotation = make_empty_annotation()
        self.assertIsInstance(annotation, ChunkAnnotation)
        self.assertEqual(annotation.emotional_valence, "neutral")
        self.assertEqual(annotation.event_type, "铺垫")
        self.assertFalse(annotation.pivot_moment)
        self.assertFalse(annotation.cliffhanger)
        self.assertFalse(annotation.has_foreshadowing)
        self.assertIsNone(annotation.foreshadowing_type)
        self.assertEqual(annotation.foreshadowing_desc, "")
        self.assertEqual(len(annotation.characters), 0)
        self.assertEqual(len(annotation.relations), 0)
        self.assertEqual(len(annotation.dialogues), 0)

    def test_make_empty_annotation_validates(self) -> None:
        annotation = make_empty_annotation()
        self.assertIsInstance(annotation, ChunkAnnotation)


if __name__ == "__main__":
    unittest.main()
