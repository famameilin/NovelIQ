"""
创建时间: 2026-03-21
创建者: TraeAI
任务: refactor-phase3-to-annotation-layer
说明: 测试 Phase3 对话归属判断功能

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容: 更新测试用例，适配对话归属失败时抛出异常而非返回空字典
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.annotation.phase3 import (
    extract_dialogues_from_text,
    attribute_dialogues_with_llm,
    compute_dialogue_lengths_with_llm,
)


class TestExtractDialoguesFromText(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试对话提取功能
    """

    def test_extract_single_dialogue(self) -> None:
        """提取单个对话"""
        text = '他说："你好啊。"'
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], (1, "你好啊。"))

    def test_extract_multiple_dialogues(self) -> None:
        """提取多个对话"""
        text = '"第一个对话。"他说道。"第二个对话。"她回答。'
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], (1, "第一个对话。"))
        self.assertEqual(result[1], (2, "第二个对话。"))

    def test_extract_dialogue_with_empty_content_skipped(self) -> None:
        """空对话内容被跳过，索引保持原始位置"""
        text = '""他说道。"有内容"她回答。'
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], (2, "有内容"))

    def test_extract_no_dialogues(self) -> None:
        """没有对话时返回空列表"""
        text = "这是一段没有对话的文本。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 0)

    def test_extract_dialogue_with_whitespace(self) -> None:
        """对话内容前后空白被去除"""
        text = '"  有空白的内容  "'
        result = extract_dialogues_from_text(text)
        self.assertEqual(result[0], (1, "有空白的内容"))


class TestAttributeDialoguesWithLLM(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试 LLM 对话归属判断功能
    """

    def test_empty_dialogues_returns_empty_dict(self) -> None:
        """空对话列表返回空字典"""
        mock_client = MagicMock()
        result = attribute_dialogues_with_llm(mock_client, "text", [], ["张三"])
        self.assertEqual(result, {})

    @patch("src.models.local.annotation.phase3.settings")
    def test_successful_attribution(self, mock_settings: MagicMock) -> None:
        """成功归属对话"""
        mock_settings.prompts.dialogue_attribution_system = "system"
        mock_settings.prompts.dialogue_attribution_user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_client = MagicMock()
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_annotation_client._call_api_stream.return_value = MagicMock()
        mock_annotation_client._parse_structured_response.return_value = MagicMock(
            dialogues=[
                MagicMock(index=1, speaker="张三"),
                MagicMock(index=2, speaker="李四"),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_client._annotation_client = mock_annotation_client

        dialogues = [(1, "你好"), (2, "你好啊")]
        result = attribute_dialogues_with_llm(mock_client, "对话文本", dialogues, ["张三", "李四"])

        self.assertEqual(result, {1: "张三", 2: "李四"})

    @patch("src.models.local.annotation.phase3.settings")
    def test_exception_raises_dialogue_attribution_error(self, mock_settings: MagicMock) -> None:
        """异常时抛出 DialogueAttributionError"""
        mock_settings.prompts.dialogue_attribution_system = "system"
        mock_settings.prompts.dialogue_attribution_user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_client = MagicMock()
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = None
        mock_client._annotation_client = mock_annotation_client

        dialogues = [(1, "你好")]

        from src.models.local.annotation.context import DialogueAttributionError
        with self.assertRaises(DialogueAttributionError):
            attribute_dialogues_with_llm(mock_client, "对话文本", dialogues, ["张三"])


class TestComputeDialogueLengthsWithLLM(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试计算对话长度功能
    """

    def test_empty_text_returns_zeros(self) -> None:
        """空文本返回全零列表"""
        mock_client = MagicMock()
        result = compute_dialogue_lengths_with_llm(mock_client, "", ["张三", "李四"])
        self.assertEqual(result, [0, 0])

    def test_empty_speakers_returns_empty_list(self) -> None:
        """空说话者列表返回空列表"""
        mock_client = MagicMock()
        result = compute_dialogue_lengths_with_llm(mock_client, "文本", [])
        self.assertEqual(result, [])

    def test_no_dialogues_returns_zeros(self) -> None:
        """没有对话返回全零列表"""
        mock_client = MagicMock()
        result = compute_dialogue_lengths_with_llm(mock_client, "没有对话的文本", ["张三"])
        self.assertEqual(result, [0])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_compute_lengths_with_attribution(self, mock_attribute: MagicMock) -> None:
        """根据归属结果计算对话长度"""
        mock_attribute.return_value = {1: "张三", 2: "李四", 3: "张三"}

        mock_client = MagicMock()
        text = '"你好"他说道。"你好啊"她回答。"再见"他说。'
        speakers = ["张三", "李四"]

        result = compute_dialogue_lengths_with_llm(mock_client, text, speakers)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 4)
        self.assertEqual(result[1], 3)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_unknown_speaker_not_counted(self, mock_attribute: MagicMock) -> None:
        """未知说话者的对话不计入"""
        mock_attribute.return_value = {1: "张三", 2: "王五"}

        mock_client = MagicMock()
        text = '"你好"他说道。"你好啊"她回答。'
        speakers = ["张三", "李四"]

        result = compute_dialogue_lengths_with_llm(mock_client, text, speakers)

        self.assertEqual(result[0], 2)
        self.assertEqual(result[1], 0)


if __name__ == "__main__":
    unittest.main()
