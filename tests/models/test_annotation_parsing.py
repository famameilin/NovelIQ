import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.local.unified_client import UnifiedModelClient
from src.models.local.parser import make_empty_annotation, try_parse_json
from src.models.local.schema import ChunkAnnotation, ForeshadowingResult


def create_mock_stream_response(content: str):
    """
    创建模拟的流式 API 响应生成器

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: 适配流式输出模式
    """
    # 将内容分成多个 chunk 模拟流式输出
    chunk_size = 50
    for i in range(0, len(content), chunk_size):
        chunk_content = content[i:i+chunk_size]
        delta = MagicMock()
        delta.content = chunk_content
        delta.reasoning_content = None
        
        choice = MagicMock()
        choice.delta = delta
        
        chunk = MagicMock()
        chunk.choices = [choice]
        
        yield chunk


def _create_foreshadowing_result() -> ForeshadowingResult:
    return ForeshadowingResult(
        has_foreshadowing=False,
        foreshadowing_type=None,
        anchor_text="",
        anchor_reason="",
        confidence="high",
    )


class TestAnnotateChunk(unittest.TestCase):
    @patch("src.models.local.annotation_client.settings")
    def test_annotate_chunk_returns_chunk_annotation(self, mock_settings: MagicMock) -> None:
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖，适配新的响应格式
        """
        # 禁用 two-phase annotation
        mock_settings.analysis.two_phase_annotation.enabled = False
        
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        content = json.dumps({
            "emotional_valence": "negative",
            "event_type": "冲突",
            "pivot_moment": False,
            "cliffhanger": False,
            "has_foreshadowing": False,
            "foreshadowing_type": None,
            "foreshadowing_desc": "",
            "characters": [{"name": "张三", "role_function": "主体", "action": "走", "action_type": "移动", "emotion_score": "neutral"}],
            "relations": [],
            "dialogues": [],
        })
        mock_client.chat.completions.create.return_value = create_mock_stream_response(content)

        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        annotation = client.annotate_chunk("张三走在路上")
        self.assertIsInstance(annotation, ChunkAnnotation)
        self.assertEqual(annotation.emotional_valence, "negative")
        self.assertEqual(annotation.event_type, "冲突")
        self.assertFalse(annotation.pivot_moment)
        self.assertFalse(annotation.cliffhanger)

    @patch("src.models.local.annotation_client.settings")
    def test_annotate_chunk_with_full_schema(self, mock_settings: MagicMock) -> None:
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖，适配新的响应格式
        """
        # 禁用 two-phase annotation
        mock_settings.analysis.two_phase_annotation.enabled = False
        
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        content = json.dumps({
            "emotional_valence": "strong_positive",
            "event_type": "转折",
            "pivot_moment": True,
            "cliffhanger": True,
            "has_foreshadowing": True,
            "foreshadowing_type": "causal",
            "foreshadowing_desc": "伏笔描述",
            "characters": [
                {"name": "张三", "role_function": "主体", "action": "战斗", "action_type": "战斗", "emotion_score": "strong_positive"},
                {"name": "李四", "role_function": "反对者", "action": "被击败", "action_type": "战斗", "emotion_score": "strong_negative"},
            ],
            "relations": [{"from": "张三", "to": "李四", "type": "敌对", "change": "断裂"}],
            "dialogues": [{"speaker": "张三"}],
        })
        mock_client.chat.completions.create.return_value = create_mock_stream_response(content)

        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        annotation = client.annotate_chunk("张三与李四展开激战")
        self.assertEqual(len(annotation.characters), 2)
        self.assertEqual(annotation.characters[0].name, "张三")
        self.assertEqual(annotation.characters[0].emotion_score, "strong_positive")
        self.assertEqual(len(annotation.relations), 1)
        self.assertEqual(annotation.relations[0].from_name, "张三")
        self.assertEqual(len(annotation.dialogues), 1)
        self.assertEqual(annotation.dialogues[0].speaker, "张三")


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
        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
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
