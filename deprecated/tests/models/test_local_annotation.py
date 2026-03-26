import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import LocalConfig
from src.models.local.client import OllamaLocalModelClient, NullLocalModelClient
from src.models.local.parser import make_empty_annotation, try_parse_json
from src.models.local.schema import ChunkAnnotation


class TestAnnotateChunk(unittest.TestCase):
    def test_annotate_chunk_returns_chunk_annotation(self) -> None:
        config = LocalConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "emotional_valence": "negative",
            "event_type": "冲突",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": "null",
            "foreshadowing_desc": "",
            "characters": [{"name": "张三", "role_function": "protagonist", "action": "走", "emotion": "平静", "emotion_score": 0}],
            "relations": [],
            "dialogues": [],
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = OllamaLocalModelClient(config=config, client=mock_client)
        annotation = client.annotate_chunk("测试文本")
        self.assertIsInstance(annotation, ChunkAnnotation)
        self.assertEqual(annotation.emotional_valence, "negative")
        self.assertEqual(annotation.event_type, "冲突")
        self.assertFalse(annotation.pivot_moment)
        self.assertFalse(annotation.cliffhanger)

    def test_annotate_chunk_with_full_schema(self) -> None:
        config = LocalConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "emotional_valence": "positive",
            "event_type": "高潮",
            "pivot_moment": True,
            "cliffhanger": True,
            "has_foreshadowing": True,
            "foreshadowing_type": "causal",
            "foreshadowing_desc": "伏笔描述",
            "characters": [
                {"name": "主角", "role_function": "protagonist", "action": "战斗", "emotion": "兴奋", "emotion_score": 5},
                {"name": "反派", "role_function": "antagonist", "action": "被击败", "emotion": "愤怒", "emotion_score": -4},
            ],
            "relations": [{"from": "主角", "to": "反派", "type": "敌对", "change": "断裂"}],
            "dialogues": [{"speaker": "主角", "tone": "强硬"}],
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = OllamaLocalModelClient(config=config, client=mock_client)
        annotation = client.annotate_chunk("测试文本")
        annotation.validate()
        self.assertEqual(len(annotation.characters), 2)
        self.assertEqual(annotation.characters[0].name, "主角")
        self.assertEqual(annotation.characters[0].emotion_score, 5)
        self.assertEqual(len(annotation.relations), 1)
        self.assertEqual(annotation.relations[0].from_name, "主角")
        self.assertEqual(len(annotation.dialogues), 1)
        self.assertEqual(annotation.dialogues[0].speaker, "主角")

    def test_annotate_chunk_with_prev_summary_passed_to_api(self) -> None:
        config = LocalConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "emotional_valence": "neutral",
            "event_type": "日常",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": "null",
            "foreshadowing_desc": "",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = OllamaLocalModelClient(config=config, client=mock_client)
        client.annotate_chunk("当前文本", prev_summary="前一块摘要")
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        has_summary = any("前文摘要" in m.get("content", "") for m in messages)
        self.assertTrue(has_summary)

    def test_annotate_chunk_with_alias_map_passed_to_api(self) -> None:
        config = LocalConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "emotional_valence": "neutral",
            "event_type": "日常",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": "null",
            "foreshadowing_desc": "",
            "characters": [{"name": "张三", "role_function": "protagonist", "action": "走", "emotion": "平静", "emotion_score": 0}],
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = OllamaLocalModelClient(config=config, client=mock_client)
        alias_map = {"三哥": "张三", "张公子": "张三"}
        client.annotate_chunk("当前文本", alias_map=alias_map)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        has_alias_section = any("人物别名对照表" in m.get("content", "") for m in messages)
        self.assertTrue(has_alias_section)
        user_content = next((m["content"] for m in messages if "人物别名对照表" in m.get("content", "")), "")
        self.assertIn("三哥 → 正式名：张三", user_content)
        self.assertIn("张公子 → 正式名：张三", user_content)

    def test_annotate_chunk_with_alias_map_and_prev_summary(self) -> None:
        config = LocalConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "emotional_valence": "neutral",
            "event_type": "日常",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": "null",
            "foreshadowing_desc": "",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = OllamaLocalModelClient(config=config, client=mock_client)
        alias_map = {"三哥": "张三"}
        client.annotate_chunk("当前文本", prev_summary="前一块摘要", alias_map=alias_map)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_content = next((m["content"] for m in messages if m.get("role") == "user" and "待分析文本" in m.get("content", "")), "")
        self.assertIn("前文摘要", user_content)
        self.assertIn("人物别名对照表", user_content)
        self.assertIn("待分析文本", user_content)

    def test_annotate_chunk_emotion_score_out_of_range_returns_empty(self) -> None:
        config = LocalConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "emotional_valence": "positive",
            "event_type": "日常",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": "null",
            "foreshadowing_desc": "",
            "characters": [{"name": "测试", "role_function": "protagonist", "action": "测试", "emotion": "测试", "emotion_score": 10}],
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        client = OllamaLocalModelClient(config=config, client=mock_client)
        annotation = client.annotate_chunk("测试文本")
        self.assertEqual(annotation.emotional_valence, "neutral")
        self.assertEqual(len(annotation.characters), 0)


class TestJsonParsing(unittest.TestCase):
    def test_parse_valid_json(self) -> None:
        content = json.dumps({
            "emotional_valence": "neutral",
            "event_type": "日常",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": "null",
            "foreshadowing_desc": "",
        })
        result = try_parse_json(content)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["emotional_valence"], "neutral")

    def test_parse_json_with_markdown_code_block(self) -> None:
        content = """```json
{
    "emotional_valence": "positive",
    "event_type": "高潮",
    "pivot_moment": true,
    "cliffhanger": false,
    "has_foreshadowing": false,
    "foreshadowing_type": "null",
    "foreshadowing_desc": ""
}
```"""
        result = try_parse_json(content)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["emotional_valence"], "positive")

    def test_parse_json_with_trailing_comma(self) -> None:
        content = '{"emotional_valence": "neutral", "event_type": "日常", "pivot_moment": false, "cliffhanger": false, "has_foreshadowing": false, "foreshadowing_type": "null", "foreshadowing_desc": "有描述",}'
        result = try_parse_json(content)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["emotional_valence"], "neutral")

    def test_parse_invalid_json_returns_none(self) -> None:
        content = "这完全不是 JSON"
        result = try_parse_json(content)
        self.assertIsNone(result)

    def test_parse_annotation_invalid_json_returns_empty(self) -> None:
        config = LocalConfig(base_url="http://test:8000/v1", model="test-model")
        mock_client = MagicMock()
        client = OllamaLocalModelClient(config=config, client=mock_client)
        annotation = client._parse_annotation("invalid json content")
        self.assertEqual(annotation.emotional_valence, "neutral")
        self.assertEqual(annotation.event_type, "日常")


class TestMakeEmptyAnnotation(unittest.TestCase):
    def test_make_empty_annotation_returns_valid_annotation(self) -> None:
        annotation = make_empty_annotation()
        self.assertIsInstance(annotation, ChunkAnnotation)
        self.assertEqual(annotation.emotional_valence, "neutral")
        self.assertEqual(annotation.event_type, "日常")
        self.assertFalse(annotation.pivot_moment)
        self.assertFalse(annotation.cliffhanger)
        self.assertFalse(annotation.has_foreshadowing)
        self.assertEqual(annotation.foreshadowing_type, "null")
        self.assertEqual(annotation.foreshadowing_desc, "")
        self.assertEqual(len(annotation.characters), 0)
        self.assertEqual(len(annotation.relations), 0)
        self.assertEqual(len(annotation.dialogues), 0)

    def test_make_empty_annotation_validates(self) -> None:
        annotation = make_empty_annotation()
        annotation.validate()


class TestNullLocalModelClient(unittest.TestCase):
    def test_annotate_chunk_returns_empty_annotation(self) -> None:
        client = NullLocalModelClient()
        annotation = client.annotate_chunk("任意文本")
        self.assertEqual(annotation.emotional_valence, "neutral")
        self.assertEqual(annotation.event_type, "日常")

    def test_disambiguate_characters_returns_identity_map(self) -> None:
        client = NullLocalModelClient()
        candidates = ["张三", "三哥", "张公子"]
        result = client.disambiguate_characters(candidates)
        self.assertEqual(result, {"张三": "张三", "三哥": "三哥", "张公子": "张公子"})

    def test_disambiguate_characters_empty_list(self) -> None:
        client = NullLocalModelClient()
        result = client.disambiguate_characters([])
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
