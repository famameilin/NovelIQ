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
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.models.local.annotation.context import DialogueAttributionError
from src.models.local.annotation.phase3 import (
    attribute_dialogues_with_llm,
    extract_dialogues_from_text,
)
from src.models.local.schema import DialogueRecord, DialogueRecordSchema, QuoteCandidate


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


class TestAttributeDialoguesWithLLM(unittest.IsolatedAsyncioTestCase):
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

    async def test_empty_dialogues_returns_empty_list(self) -> None:
        """空对话列表返回空列表"""
        mock_client = MagicMock()
        result = await attribute_dialogues_with_llm(mock_client, "text", [], ["张三"])
        self.assertEqual(result, [])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_successful_attribution(self, mock_settings: MagicMock) -> None:
        """成功归属对话"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
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
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
                DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker=["李四"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))
        candidates = [QuoteCandidate(index=1, content="你好"), QuoteCandidate(index=2, content="你好啊")]
        result = await attribute_dialogues_with_llm(mock_annotation_client, "对话文本", candidates, ["张三", "李四"])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].speaker, ["张三"])
        self.assertEqual(result[1].speaker, ["李四"])

    @patch("src.models.local.annotation.phase3.record_model_interaction")
    @patch("src.models.local.annotation.phase3.settings")
    async def test_persists_thinking_from_reasoning_content(
        self,
        mock_settings: MagicMock,
        mock_record_model_interaction: MagicMock,
    ) -> None:
        """Phase3 会把 response 中的 reasoning_content 持久化。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = True
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._extract_reasoning_tokens.return_value = 23
        mock_annotation_client._record_estimated_token_usage_from_messages = MagicMock()
        mock_annotation_client._process_annotation_response.return_value = (
            '{"dialogues": []}',
            "phase3 thinking",
            MagicMock(),
        )
        parsed = MagicMock(dialogues=[], model_dump=MagicMock(return_value={}))
        response = MagicMock()
        response.choices = [
            MagicMock(message=MagicMock(content='{"dialogues": []}', reasoning_content="phase3 thinking"))
        ]
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(parsed, response))
        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            [QuoteCandidate(index=1, content="你好")],
            known_characters=["张三"],
        )
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["thinking_content"], "phase3 thinking")
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["reasoning_tokens"], 23)
        self.assertTrue(mock_record_model_interaction.call_args.kwargs["requested_thinking"])
        mock_annotation_client._record_estimated_token_usage_from_messages.assert_called_once()
        assert mock_annotation_client._record_estimated_token_usage_from_messages.call_args.args[2] == "phase3"

    @patch("src.models.local.annotation.phase3.settings")
    async def test_alias_speaker_normalized_before_known_filter(self, mock_settings: MagicMock) -> None:
        """说话者别名在 known_characters 校验前先归一化"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.runtime.annotation.phase3_max_retries = 3
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
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["猴子"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))
        candidates = [QuoteCandidate(index=1, content="你好")]
        result = await attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            candidates,
            known_characters=["侯飞白"],
            alias_map={"猴子": "侯飞白"},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["侯飞白"])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_batched_dialogues_must_return_global_indices(self, mock_settings: MagicMock) -> None:
        """跨 batch 调用时，模型必须返回候选列表里显示的全局索引。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 5
        mock_settings.runtime.annotation.phase3_max_retries = 3
        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._session = None
        mock_annotation_client._process_annotation_response = MagicMock(return_value=('{"dialogues": []}', None, None))

        async def _call_annotation_api(*args, **kwargs):
            messages = kwargs["messages"]
            user_prompt = messages[1]["content"]
            if '1. content: "对话1"' in user_prompt:
                parsed = MagicMock(
                    dialogues=[
                        DialogueRecordSchema(
                            index=index,
                            is_dialogue=True,
                            speaker=["张三"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                        for index in range(1, 6)
                    ],
                    model_dump=MagicMock(return_value={}),
                )
                return parsed, MagicMock()
            if '6. content: "对话6"' in user_prompt:
                self.assertIn('10. content: "对话10"', user_prompt)
                parsed = MagicMock(
                    dialogues=[
                        DialogueRecordSchema(
                            index=index,
                            is_dialogue=True,
                            speaker=["张三"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                        for index in range(6, 11)
                    ],
                    model_dump=MagicMock(return_value={}),
                )
                return parsed, MagicMock()
            raise AssertionError(f"Unexpected prompt batch: {user_prompt}")

        mock_annotation_client._call_annotation_api = AsyncMock(side_effect=_call_annotation_api)
        candidates = [QuoteCandidate(index=index, content=f"对话{index}") for index in range(1, 11)]
        result = await attribute_dialogues_with_llm(
            mock_annotation_client,
            "测试文本",
            candidates,
            known_characters=["张三"],
        )
        self.assertEqual([record.index for record in result], list(range(1, 11)))
        self.assertTrue(all(record.speaker == ["张三"] for record in result))

    @patch("src.models.local.annotation.phase3.record_model_interaction")
    @patch("src.models.local.annotation.phase3.settings")
    async def test_fallback_client_used_after_primary_retries(
        self,
        mock_settings: MagicMock,
        _mock_record_model_interaction: MagicMock,
    ) -> None:
        """Phase3 主客户端失败后会切到 fallback_client。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.runtime.annotation.phase3_max_retries = 3
        primary_client = MagicMock()
        primary_client._config.model = "primary-model"
        primary_client._config.thinking_enabled = False
        primary_client._is_cloud_api.return_value = False
        primary_client._session = None
        primary_client._process_annotation_response = MagicMock(return_value=('{"dialogues": []}', None, None))
        fallback_client = MagicMock()
        fallback_client._config.model = "fallback-model"
        fallback_client._config.thinking_enabled = False
        fallback_client._is_cloud_api.return_value = True
        fallback_client._session = None
        fallback_client._process_annotation_response = MagicMock(return_value=('{"dialogues": []}', None, None))
        primary_calls = 0
        fallback_calls = 0
        parsed = MagicMock(
            dialogues=[
                DialogueRecordSchema(
                    index=1,
                    is_dialogue=True,
                    speaker=["张三"],
                    tone=None,
                    is_inner_monologue=False,
                )
            ],
            model_dump=MagicMock(return_value={}),
        )
        response = MagicMock()

        async def primary_call(*args, **kwargs):
            nonlocal primary_calls
            primary_calls += 1
            raise ConnectionError("primary failed")

        async def fallback_call(*args, **kwargs):
            nonlocal fallback_calls
            fallback_calls += 1
            return parsed, response

        primary_client._call_annotation_api = AsyncMock(side_effect=primary_call)
        fallback_client._call_annotation_api = AsyncMock(side_effect=fallback_call)
        result = await attribute_dialogues_with_llm(
            primary_client,
            "“你好”",
            [QuoteCandidate(index=1, content="你好")],
            known_characters=["张三"],
            fallback_client=fallback_client,
        )
        self.assertEqual(primary_calls, 3)
        self.assertEqual(fallback_calls, 1)
        self.assertEqual(result[0].speaker, ["张三"])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_fallback_client_failure_raises_dialogue_attribution_error(self, mock_settings: MagicMock) -> None:
        """Phase3 主客户端与兜底客户端都失败时应抛错。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.runtime.annotation.phase3_max_retries = 3
        primary_client = MagicMock()
        primary_client._config.model = "primary-model"
        primary_client._config.thinking_enabled = False
        primary_client._is_cloud_api.return_value = False
        primary_client._process_annotation_response = MagicMock(return_value=('{"dialogues": []}', None, None))
        fallback_client = MagicMock()
        fallback_client._config.model = "fallback-model"
        fallback_client._config.thinking_enabled = False
        fallback_client._is_cloud_api.return_value = True
        fallback_client._process_annotation_response = MagicMock(return_value=('{"dialogues": []}', None, None))
        primary_client._call_annotation_api = AsyncMock(side_effect=ConnectionError("primary failed"))
        fallback_client._call_annotation_api = AsyncMock(side_effect=ConnectionError("fallback failed"))
        with self.assertRaises(DialogueAttributionError):
            await attribute_dialogues_with_llm(
                primary_client,
                "“你好”",
                [QuoteCandidate(index=1, content="你好")],
                known_characters=["张三"],
                fallback_client=fallback_client,
            )
