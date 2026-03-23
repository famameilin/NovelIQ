"""
创建时间: 2026-03-21
创建者: TraeAI
任务: refactor-phase3-to-annotation-layer
说明: 测试 Phase3 对话归属判断功能

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容: 更新测试用例，适配对话归属失败时抛出异常而非返回空字典

修改时间: 2026-03-23
修改者: TraeAI
任务: refactor-dialogue-attribution-pipeline
修改内容: 更新测试用例，适配新的返回格式（QuoteCandidate、DialogueRecord）
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
from src.models.local.schema import DialogueRecord, QuoteCandidate


class TestExtractDialoguesFromText(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试对话提取功能

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配 QuoteCandidate 返回格式

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix-phase3-validation
    修改内容: 使用正确的 Unicode 引号字符 (U+201C/U+201D)
    """

    def test_extract_single_dialogue(self) -> None:
        """提取单个对话 - 使用中文双引号 U+201C/U+201D"""
        text = "他说：\u201c你好啊。\u201d"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], QuoteCandidate)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].content, "你好啊。")

    def test_extract_multiple_dialogues(self) -> None:
        """提取多个对话 - 使用中文双引号"""
        text = "\u201c第一个对话。\u201d他说道。\u201c第二个对话。\u201d她回答。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].content, "第一个对话。")
        self.assertEqual(result[1].index, 2)
        self.assertEqual(result[1].content, "第二个对话。")

    def test_extract_dialogue_with_empty_content_skipped(self) -> None:
        """空对话内容被跳过，索引保持原始位置"""
        text = "\u201c\u201d他说道。\u201c有内容\u201d她回答。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index, 2)
        self.assertEqual(result[0].content, "有内容")

    def test_extract_no_dialogues(self) -> None:
        """没有对话时返回空列表"""
        text = "这是一段没有对话的文本。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 0)

    def test_extract_dialogue_with_whitespace(self) -> None:
        """对话内容前后空白被去除 - 使用英文双引号"""
        text = '"  有空白的内容  "'
        result = extract_dialogues_from_text(text)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].content, "有空白的内容")


class TestAttributeDialoguesWithLLM(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试 LLM 对话归属判断功能

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配 DialogueRecord 返回格式
    """

    def test_empty_dialogues_returns_empty_list(self) -> None:
        """空对话列表返回空列表"""
        mock_client = MagicMock()
        result = attribute_dialogues_with_llm(mock_client, "text", [], ["张三"])
        self.assertEqual(result, [])

    @patch("src.models.local.annotation.phase3.settings")
    def test_successful_attribution(self, mock_settings: MagicMock) -> None:
        """成功归属对话"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_client = MagicMock()
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_annotation_client._call_api_stream.return_value = MagicMock()
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
                DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker="李四"),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api.return_value = (mock_response, "{}")
        mock_client._annotation_client = mock_annotation_client

        candidates = [QuoteCandidate(index=1, content="你好"), QuoteCandidate(index=2, content="你好啊")]
        result = attribute_dialogues_with_llm(mock_client, "对话文本", candidates, ["张三", "李四"])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].speaker, "张三")
        self.assertEqual(result[1].speaker, "李四")

    @patch("src.models.local.annotation.phase3.settings")
    def test_exception_raises_dialogue_attribution_error(self, mock_settings: MagicMock) -> None:
        """异常时抛出 ValueError（model 未配置）"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_client = MagicMock()
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = None
        mock_client._annotation_client = mock_annotation_client

        candidates = [QuoteCandidate(index=1, content="你好")]

        with self.assertRaises(ValueError):
            attribute_dialogues_with_llm(mock_client, "对话文本", candidates, ["张三"])

    @patch("src.models.local.annotation.phase3.settings")
    def test_alias_speaker_normalized_before_known_filter(self, mock_settings: MagicMock) -> None:
        """说话者别名在 known_characters 校验前先归一化"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_client = MagicMock()
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_annotation_client._call_api_stream.return_value = MagicMock()
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="猴子"),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api.return_value = (mock_response, "{}")
        mock_client._annotation_client = mock_annotation_client

        candidates = [QuoteCandidate(index=1, content="你好")]
        result = attribute_dialogues_with_llm(
            mock_client,
            "对话文本",
            candidates,
            known_characters=["侯飞白"],
            alias_map={"猴子": "侯飞白"},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "侯飞白")


class TestComputeDialogueLengthsWithLLM(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试计算对话长度功能

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配新的返回格式
    """

    def test_empty_text_returns_empty_dict(self) -> None:
        """空文本返回空字典"""
        mock_client = MagicMock()
        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, "")
        self.assertEqual(speaker_lengths, {})
        self.assertEqual(attribution, {})
        self.assertEqual(dialogues, [])

    def test_no_dialogues_returns_empty_dict(self) -> None:
        """没有对话返回空字典"""
        mock_client = MagicMock()
        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, "没有对话的文本")
        self.assertEqual(speaker_lengths, {})
        self.assertEqual(attribution, {})
        self.assertEqual(dialogues, [])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_compute_lengths_with_attribution(self, mock_attribute: MagicMock) -> None:
        """根据归属结果计算对话长度 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
            DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker="李四"),
            DialogueRecord(index=3, content="再见", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。\u201c再见\u201d他说。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertIsInstance(speaker_lengths, dict)
        self.assertEqual(speaker_lengths.get("张三", 0), 4)
        self.assertEqual(speaker_lengths.get("李四", 0), 3)
        self.assertIsInstance(attribution, dict)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_unknown_speaker_not_counted(self, mock_attribute: MagicMock) -> None:
        """未知说话者的对话不计入 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
            DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker="王五"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(speaker_lengths.get("张三", 0), 2)
        self.assertNotIn("李四", speaker_lengths)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_non_dialogue_filtered(self, mock_attribute: MagicMock) -> None:
        """非对话内容被过滤 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="精打细算", is_dialogue=False, speaker=None),
            DialogueRecord(index=2, content="你好", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c精打细算\u201d的折扇。\u201c你好\u201d他说道。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(len(dialogues), 1)
        self.assertEqual(speaker_lengths.get("张三", 0), 2)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_source_content_preferred_over_model_content(self, mock_attribute: MagicMock) -> None:
        """长度统计优先使用原文提取内容，避免模型改写影响"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好你好你好", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(speaker_lengths.get("张三", 0), 2)
        self.assertEqual(dialogues, [(1, "你好")])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_duplicate_index_counted_once(self, mock_attribute: MagicMock) -> None:
        """重复 index 只计一次，避免长度膨胀"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(speaker_lengths.get("张三", 0), 2)
        self.assertEqual(attribution, {1: "张三"})
        self.assertEqual(dialogues, [(1, "你好")])


if __name__ == "__main__":
    unittest.main()
