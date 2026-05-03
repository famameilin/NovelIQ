"""
创建时间: 2026-03-21
任务: refactor-phase3-to-annotation-layer
说明: 测试 Phase3 对话归属判断功能
修改时间: 2026-03-22
任务: code-quality-review
修改内容: 更新测试用例，适配对话归属失败时抛出异常而非返回空字典
修改时间: 2026-03-23
任务: refactor-dialogue-attribution-pipeline
修改内容: 更新测试用例，适配新的返回格式（QuoteCandidate、DialogueRecord）

修改时间: 2026-04-26
任务: phase3-proof-only-fastpath-batch10
修改内容: 补充 proof-only fastpath、并行批次归并与 worker session 隔离的定向回归测试。
"""

import asyncio
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.models.events import StreamEvent
from src.models.local.annotation.context import DialogueAttributionError
from src.models.local.annotation.phase3 import (
    _resolve_phase3_fastpath_candidates,
    attribute_dialogues_with_llm,
    extract_dialogues_from_text,
)
from src.models.local.schema import DialogueAttributionResult, DialogueRecord, DialogueRecordSchema, QuoteCandidate


class _Phase3ParallelTestClient:
    """
    创建时间: 2026-04-26
    任务: phase3-proof-only-fastpath-batch10
    新建原因: 用最小测试替身覆盖 Phase3 并行 worker clone、批次归并与 runtime 落库行为。
    """

    def __init__(
        self,
        task_type: str = "annotation",
        config: object | None = None,
        client: object | None = None,
        analysis_logger: object | None = None,
        token_usage_callback: object | None = None,
        novel_id: str | None = None,
        session: object | None = None,
    ) -> None:
        """
        创建时间: 2026-04-26
        任务: phase3-proof-only-fastpath-batch10
        新建原因: 保持和 AnnotationClient 相同的构造签名，便于 Phase3 真实调用 clone helper。
        """
        self._task_type = task_type
        self._config = config or SimpleNamespace(model="test-model", thinking_enabled=False)
        self._client = client or SimpleNamespace(response_delay_by_first_index={}, completion_order=[])
        self._analysis_logger = analysis_logger
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        self._session = session
        self._emitter = None

    def _is_cloud_api(self) -> bool:
        """测试替身固定走本地 provider 分支。"""
        return False

    async def _call_annotation_api(
        self,
        *,
        messages: list[dict],
        enable_thinking: bool,
        chunk_id: int | None,
        response_model: type[DialogueAttributionResult],
        call_type: str | None,
    ) -> tuple[DialogueAttributionResult, SimpleNamespace]:
        """
        创建时间: 2026-04-26
        任务: phase3-proof-only-fastpath-batch10
        新建原因: 让 Phase3 测试在不接真实模型的前提下，仍然走 execute_phase_call 和 record_model_interaction。
        """
        del enable_thinking, chunk_id, response_model, call_type

        user_prompt = messages[1]["content"]
        indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
        first_index = indices[0]
        response_delay = getattr(self._client, "response_delay_by_first_index", {}).get(first_index, 0.0)
        if response_delay:
            await asyncio.sleep(response_delay)
        completion_order = getattr(self._client, "completion_order", None)
        if completion_order is not None:
            completion_order.append(first_index)

        parsed = DialogueAttributionResult(
            dialogues=[
                DialogueRecordSchema(
                    index=index,
                    is_dialogue=True,
                    speaker=["张三"],
                    tone=None,
                    is_inner_monologue=False,
                    identity_clue=None,
                )
                for index in indices
            ]
        )
        return parsed, SimpleNamespace()

    def _record_estimated_token_usage_from_messages(
        self,
        messages: list[dict],
        content_clean: str,
        phase: str,
        chunk_id: int | None,
        task_type: str | None = None,
    ) -> None:
        """测试替身不需要真实记账，只保留可调用接口。"""
        del messages, content_clean, phase, chunk_id, task_type

    def _record_estimated_token_usage_from_response(
        self,
        messages: list[dict],
        response: object,
        phase: str,
        chunk_id: int | None,
        task_type: str | None = None,
    ) -> None:
        """测试替身不需要真实记账，只保留异常回退接口。"""
        del messages, response, phase, chunk_id, task_type


class TestExtractDialoguesFromText(unittest.TestCase):
    """
    创建时间: 2026-03-21
    任务: refactor-phase3-to-annotation-layer
    说明: 测试对话提取功能
    修改时间: 2026-03-23
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配 QuoteCandidate 返回格式
    修改时间: 2026-03-23
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
    任务: refactor-phase3-to-annotation-layer
    说明: 测试 LLM 对话归属判断功能
    修改时间: 2026-03-23
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配 DialogueRecord 返回格式

    修改时间: 2026-04-26
    任务: phase3-proof-only-fastpath-batch10
    修改内容: 增补 fastpath 命中/拒绝、混合索引与并行 worker session 隔离测试。
    """

    def test_fastpath_hits_prefix_speech_pattern(self) -> None:
        """proof-only fastpath 命中 `张三说：“……”`。"""
        text = "张三说：“你好。”"
        candidates = extract_dialogues_from_text(text)

        fastpath_records, llm_candidates, hit_types, reject_reasons = _resolve_phase3_fastpath_candidates(
            text,
            candidates,
            known_characters=["张三"],
            alias_map=None,
        )

        self.assertEqual(len(fastpath_records), 1)
        self.assertEqual(fastpath_records[0].index, 1)
        self.assertEqual(fastpath_records[0].speaker, ["张三"])
        self.assertTrue(fastpath_records[0].is_dialogue)
        self.assertEqual(dict(hit_types), {"prefix_speech_verb": 1})
        self.assertEqual(dict(reject_reasons), {})
        self.assertEqual(llm_candidates, [])

    def test_fastpath_hits_suffix_speech_pattern(self) -> None:
        """proof-only fastpath 命中 `“……”张三说道。`。"""
        text = "“你好。”张三说道。"
        candidates = extract_dialogues_from_text(text)

        fastpath_records, llm_candidates, hit_types, reject_reasons = _resolve_phase3_fastpath_candidates(
            text,
            candidates,
            known_characters=["张三"],
            alias_map=None,
        )

        self.assertEqual(len(fastpath_records), 1)
        self.assertEqual(fastpath_records[0].index, 1)
        self.assertEqual(fastpath_records[0].speaker, ["张三"])
        self.assertEqual(dict(hit_types), {"suffix_speech_verb": 1})
        self.assertEqual(dict(reject_reasons), {})
        self.assertEqual(llm_candidates, [])

    def test_fastpath_keeps_strict_single_speaker_with_addressee_tail_or_modifier(self) -> None:
        """引号内称呼对象、句尾叙述和安全修饰语不应破坏已严格证明的 speaker。"""
        scenarios = [
            ("张三说：“李四快跑！”", ["张三", "李四"], "prefix_speech_verb", ["张三"]),
            ("张三说：“走吧。”他转身离开。", ["张三"], "prefix_speech_verb", ["张三"]),
            ("猴子兴奋地喊道：“快跑！”", ["猴子"], "prefix_speech_verb", ["猴子"]),
        ]

        for text, known_characters, hit_type, expected_speaker in scenarios:
            with self.subTest(text=text):
                candidates = extract_dialogues_from_text(text)
                fastpath_records, llm_candidates, hit_types, reject_reasons = _resolve_phase3_fastpath_candidates(
                    text,
                    candidates,
                    known_characters=known_characters,
                    alias_map=None,
                )

                self.assertEqual(len(fastpath_records), 1)
                self.assertEqual(fastpath_records[0].speaker, expected_speaker)
                self.assertEqual(dict(hit_types), {hit_type: 1})
                self.assertEqual(dict(reject_reasons), {})
                self.assertEqual(llm_candidates, [])

    def test_fastpath_rejects_complex_or_ambiguous_speakers(self) -> None:
        """proof-only fastpath 会把复杂句、多人竞争和代词场景退回 LLM。"""
        scenarios = [
            ("张三对李四说：“你好。”", ["张三", "李四"], "multiple_names"),
            ("张三和李四说：“一起上。”", ["张三", "李四"], "multiple_names"),
            ("他说：“你好。”", ["张三"], "pronoun_context"),
            ("李四向张三说道：“你好。”", ["张三"], "no_strict_match"),
        ]

        for text, known_characters, reject_reason in scenarios:
            with self.subTest(text=text, reject_reason=reject_reason):
                candidates = extract_dialogues_from_text(text)
                fastpath_records, llm_candidates, _hit_types, reject_reasons = _resolve_phase3_fastpath_candidates(
                    text,
                    candidates,
                    known_characters=known_characters,
                    alias_map=None,
                )

                self.assertEqual(fastpath_records, [])
                self.assertEqual([candidate.index for candidate in llm_candidates], [1])
                self.assertEqual(reject_reasons[reject_reason], 1)

    @patch("src.models.local.annotation.phase3.settings")
    async def test_fastpath_only_path_skips_llm_and_still_runs_alias_normalization(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """全量 fastpath 命中时不走 LLM，但仍会经过 post-process 做别名归一化。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 10
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 3

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._call_annotation_api = AsyncMock()

        result = await attribute_dialogues_with_llm(
            mock_annotation_client,
            "猴子说：“你好。”",
            [QuoteCandidate(index=1, content="你好。")],
            known_characters=["侯飞白"],
            alias_map={"猴子": "侯飞白"},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["侯飞白"])
        mock_annotation_client._call_annotation_api.assert_not_awaited()

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
        mock_settings.thinking.phase3_batch_parallelism = 1
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

    @patch("src.models.local.annotation.runtime.record_model_interaction")
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
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 3
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
        mock_settings.thinking.phase3_batch_parallelism = 1
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
        mock_settings.thinking.phase3_batch_parallelism = 1
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

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_mixed_fastpath_and_llm_keep_global_indices(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """部分候选走 fastpath、部分走 LLM 时，LLM 仍消费原始全局 index。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 10
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 3

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            user_prompt = spec.messages[1]["content"]
            self.assertIn('2. content: "第二句。"', user_prompt)
            self.assertNotIn('1. content: "第一句。"', user_prompt)
            return SimpleNamespace(
                parsed=DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=2,
                            is_dialogue=True,
                            speaker=["李四"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                    ]
                )
            )

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        text = "张三说：“第一句。”\n“第二句。”"
        candidates = extract_dialogues_from_text(text)

        result = await attribute_dialogues_with_llm(
            mock_client,
            text,
            candidates,
            known_characters=["张三", "李四"],
        )

        self.assertEqual(mock_execute_phase_call.await_count, 1)
        self.assertEqual([record.index for record in result], [1, 2])
        self.assertEqual(result[0].speaker, ["张三"])
        self.assertEqual(result[1].speaker, ["李四"])

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_batch_validation_rejects_cross_batch_indices_before_merge(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """每个 batch 都应先按自己的候选集合校验，避免跨 batch index 污染混进最终结果。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 2
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 1

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            user_prompt = spec.messages[1]["content"]
            if '1. content: "甲。"' in user_prompt:
                return SimpleNamespace(
                    parsed=DialogueAttributionResult(
                        dialogues=[
                            DialogueRecordSchema(
                                index=3,
                                is_dialogue=True,
                                speaker=["张三"],
                                tone=None,
                                is_inner_monologue=False,
                                identity_clue=None,
                            )
                        ]
                    )
                )
            return SimpleNamespace(
                parsed=DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=3,
                            is_dialogue=True,
                            speaker=["李四"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        ),
                        DialogueRecordSchema(
                            index=4,
                            is_dialogue=True,
                            speaker=["王五"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        ),
                    ]
                )
            )

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        text = "“甲。”\n“乙。”\n“丙。”\n“丁。”"
        candidates = extract_dialogues_from_text(text)

        result = await attribute_dialogues_with_llm(
            mock_client,
            text,
            candidates,
            known_characters=["张三"],
        )

        self.assertEqual([(record.index, record.speaker) for record in result], [(3, ["李四"]), (4, ["王五"])])

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_attempt_number_tracks_real_retry_attempts_instead_of_batch_index(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """Phase3 应把真实 retry attempt 写进 runtime spec，而不是批次序号。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 2
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 2

        attempts_by_first_index: dict[int, list[int]] = {}
        call_count_by_first_index: dict[int, int] = {}

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            user_prompt = spec.messages[1]["content"]
            indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
            first_index = indices[0]
            attempts_by_first_index.setdefault(first_index, []).append(spec.attempt_number)
            call_count_by_first_index[first_index] = call_count_by_first_index.get(first_index, 0) + 1
            if first_index == 3 and call_count_by_first_index[first_index] == 1:
                raise ConnectionError("retry me once")
            return SimpleNamespace(
                parsed=DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=index,
                            is_dialogue=True,
                            speaker=["张三"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                        for index in indices
                    ]
                )
            )

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        text = "“甲。”\n“乙。”\n“丙。”"
        candidates = extract_dialogues_from_text(text)

        result = await attribute_dialogues_with_llm(
            mock_client,
            text,
            candidates,
            known_characters=["张三"],
        )

        self.assertEqual([record.index for record in result], [1, 2, 3])
        self.assertEqual(attempts_by_first_index[1], [1])
        self.assertEqual(attempts_by_first_index[3], [1, 2])

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_parallel_batches_respect_configured_concurrency_limit(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """受控并行应把同时运行的 batch 数限制在 `phase3_batch_parallelism` 以内。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 2
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 3
        current_concurrency = 0
        max_concurrency = 0

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            nonlocal current_concurrency, max_concurrency
            user_prompt = spec.messages[1]["content"]
            indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
            current_concurrency += 1
            max_concurrency = max(max_concurrency, current_concurrency)
            try:
                await asyncio.sleep(0.03)
                return SimpleNamespace(
                    parsed=DialogueAttributionResult(
                        dialogues=[
                            DialogueRecordSchema(
                                index=index,
                                is_dialogue=True,
                                speaker=["张三"],
                                tone=None,
                                is_inner_monologue=False,
                                identity_clue=None,
                            )
                            for index in indices
                        ]
                    )
                )
            finally:
                current_concurrency -= 1

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        text = "“甲。”\n“乙。”\n“丙。”\n“丁。”\n“戊。”\n“己。”"
        candidates = extract_dialogues_from_text(text)

        result = await attribute_dialogues_with_llm(
            mock_client,
            text,
            candidates,
            known_characters=["张三"],
        )

        self.assertEqual([record.index for record in result], [1, 2, 3, 4, 5, 6])
        self.assertEqual(mock_execute_phase_call.await_count, 3)
        self.assertEqual(max_concurrency, 2)

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_parallel_batches_cancel_siblings_after_first_failure(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """任一 batch 失败后，应取消其余已启动 sibling batch，避免继续消耗 token 和落审计。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 2
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 1
        started_batches: list[int] = []
        completed_batches: list[int] = []

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            user_prompt = spec.messages[1]["content"]
            indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
            first_index = indices[0]
            started_batches.append(first_index)
            if first_index == 1:
                await asyncio.sleep(0.01)
                raise ConnectionError("batch one failed")
            await asyncio.sleep(0.05)
            completed_batches.append(first_index)
            return SimpleNamespace(
                parsed=DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=index,
                            is_dialogue=True,
                            speaker=["张三"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                        for index in indices
                    ]
                )
            )

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        text = "“甲。”\n“乙。”\n“丙。”\n“丁。”"
        candidates = extract_dialogues_from_text(text)

        with self.assertRaises(DialogueAttributionError):
            await attribute_dialogues_with_llm(
                mock_client,
                text,
                candidates,
                known_characters=["张三"],
            )

        await asyncio.sleep(0.08)
        self.assertEqual(set(started_batches), {1, 3})
        self.assertEqual(completed_batches, [])

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_metadata_request_keeps_fastpath_speaker_and_metadata(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """请求 metadata 时，fastpath 仍应保留 speaker 权威，并通过轻量 batch 补充元数据。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 10
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 1

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            user_prompt = spec.messages[1]["content"]
            self.assertIn("张三", user_prompt)
            self.assertNotIn("张三、李四", user_prompt)
            return SimpleNamespace(
                parsed=DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=1,
                            is_dialogue=True,
                            speaker=["李四"],
                            tone="温和",
                            is_inner_monologue=False,
                            identity_clue="张三自称名为白芷",
                        )
                    ]
                )
            )

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        result = await attribute_dialogues_with_llm(
            mock_client,
            "张三说：“我叫白芷。”",
            [QuoteCandidate(index=1, content="我叫白芷。")],
            known_characters=["张三", "李四"],
            require_tones=True,
            require_identity_clues=True,
        )

        self.assertEqual(mock_execute_phase_call.await_count, 1)
        self.assertEqual(result[0].speaker, ["张三"])
        self.assertEqual(result[0].tone, "温和")
        self.assertEqual(result[0].identity_clue, "张三自称名为白芷")

    @patch("src.models.local.annotation.phase3.execute_phase_call", new_callable=AsyncMock)
    @patch("src.models.local.annotation.phase3.settings")
    async def test_parallel_batches_merge_back_in_global_index_order(
        self,
        mock_settings: MagicMock,
        mock_execute_phase_call: AsyncMock,
    ) -> None:
        """并行 batch 即使乱序完成，最终结果仍按原始 index 稳定归并。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 2
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 3
        completion_order: list[int] = []

        async def _fake_execute_phase_call(
            _client: _Phase3ParallelTestClient,
            spec: object,
        ) -> SimpleNamespace:
            user_prompt = spec.messages[1]["content"]
            indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
            if indices[0] == 1:
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.01)
            completion_order.append(indices[0])
            return SimpleNamespace(
                parsed=DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=index,
                            is_dialogue=True,
                            speaker=["张三"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                        for index in indices
                    ]
                )
            )

        mock_execute_phase_call.side_effect = _fake_execute_phase_call
        mock_client = _Phase3ParallelTestClient()
        text = "“甲。”\n“乙。”\n“丙。”\n“丁。”"
        candidates = extract_dialogues_from_text(text)

        result = await attribute_dialogues_with_llm(
            mock_client,
            text,
            candidates,
            known_characters=["张三"],
        )

        self.assertEqual(completion_order, [3, 1])
        self.assertEqual([record.index for record in result], [1, 2, 3, 4])
        self.assertTrue(all(record.speaker == ["张三"] for record in result))

    @patch("src.models.local.annotation.runtime.record_model_interaction")
    @patch("src.models.local.annotation.phase3.settings")
    async def test_parallel_workers_do_not_share_parent_session(
        self,
        mock_settings: MagicMock,
        mock_record_model_interaction: MagicMock,
    ) -> None:
        """并行 worker 写 interaction 时不会把父 client 的 session 透传下去。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 1
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 1

        shared_transport = SimpleNamespace(response_delay_by_first_index={}, completion_order=[])
        parent_session = object()
        mock_client = _Phase3ParallelTestClient(client=shared_transport, session=parent_session)
        text = "“甲。”\n“乙。”"
        candidates = extract_dialogues_from_text(text)

        result = await attribute_dialogues_with_llm(
            mock_client,
            text,
            candidates,
            known_characters=["张三"],
        )

        self.assertEqual([record.index for record in result], [1, 2])
        self.assertEqual(mock_record_model_interaction.call_count, 2)
        self.assertTrue(all(call.kwargs["session"] is None for call in mock_record_model_interaction.call_args_list))
        self.assertIs(mock_client._session, parent_session)

    @patch("src.models.local.annotation.runtime.record_model_interaction")
    @patch("src.models.local.annotation.phase3.settings")
    async def test_parallel_workers_emit_distinct_stream_ids(
        self,
        mock_settings: MagicMock,
        mock_record_model_interaction: MagicMock,
    ) -> None:
        """并行 worker 的 output/thinking 事件应带独立 stream_id，且不复用父 emitter 包装。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 1
        mock_settings.thinking.phase3_batch_parallelism = 2
        mock_settings.runtime.annotation.phase3_max_retries = 1

        emitted_events: list[StreamEvent] = []
        worker_emitter_ids: list[int] = []

        async def _capture_emitter(event: StreamEvent) -> None:
            emitted_events.append(event)

        async def _patched_call_annotation_api(
            self: _Phase3ParallelTestClient,
            *,
            messages: list[dict],
            enable_thinking: bool,
            chunk_id: int | None,
            response_model: type[DialogueAttributionResult],
            call_type: str | None,
        ) -> tuple[DialogueAttributionResult, SimpleNamespace]:
            del enable_thinking, response_model, call_type
            worker_emitter_ids.append(id(self._emitter))
            user_prompt = messages[1]["content"]
            indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
            first_index = indices[0]

            await self._emitter(
                StreamEvent(
                    action="progress",
                    stage="annotate",
                    sub_stage="phase3",
                    chunk_id=chunk_id,
                    message=f"batch-{first_index}-progress",
                )
            )
            await self._emitter(
                StreamEvent(
                    action="output",
                    stage="annotate",
                    sub_stage="phase3",
                    chunk_id=chunk_id,
                    content=f"output-{first_index}",
                )
            )
            await self._emitter(
                StreamEvent(
                    action="thinking",
                    stage="annotate",
                    sub_stage="phase3",
                    chunk_id=chunk_id,
                    content=f"thinking-{first_index}",
                )
            )
            return (
                DialogueAttributionResult(
                    dialogues=[
                        DialogueRecordSchema(
                            index=index,
                            is_dialogue=True,
                            speaker=["张三"],
                            tone=None,
                            is_inner_monologue=False,
                            identity_clue=None,
                        )
                        for index in indices
                    ]
                ),
                SimpleNamespace(),
            )

        mock_client = _Phase3ParallelTestClient(session=object())
        mock_client._emitter = _capture_emitter
        text = "“甲。”\n“乙。”"
        candidates = extract_dialogues_from_text(text)

        with patch.object(_Phase3ParallelTestClient, "_call_annotation_api", new=_patched_call_annotation_api):
            result = await attribute_dialogues_with_llm(
                mock_client,
                text,
                candidates,
                known_characters=["张三"],
            )

        self.assertEqual([record.index for record in result], [1, 2])
        self.assertEqual(mock_record_model_interaction.call_count, 2)
        self.assertTrue(all(emitter_id != id(_capture_emitter) for emitter_id in worker_emitter_ids))

        progress_events = [event for event in emitted_events if event.action == "progress"]
        output_events = [event for event in emitted_events if event.action == "output"]
        thinking_events = [event for event in emitted_events if event.action == "thinking"]

        self.assertTrue(all(event.stream_id is None for event in progress_events))
        self.assertEqual(len({event.stream_id for event in output_events}), 2)
        self.assertEqual(
            {event.stream_id for event in output_events},
            {event.stream_id for event in thinking_events},
        )
        self.assertTrue(all(event.stream_id for event in output_events + thinking_events))

    @patch("src.models.local.annotation.runtime.record_model_interaction")
    @patch("src.models.local.annotation.phase3.settings")
    async def test_fallback_client_used_after_primary_retries(
        self,
        mock_settings: MagicMock,
        mock_record_model_interaction: MagicMock,
    ) -> None:
        """Phase3 主客户端失败后会切到 fallback_client。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
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
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["attempt_number"], 4)

    @patch("src.models.local.annotation.runtime.record_model_interaction")
    @patch("src.models.local.annotation.phase3.settings")
    async def test_fallback_worker_does_not_share_fallback_parent_session(
        self,
        mock_settings: MagicMock,
        mock_record_model_interaction: MagicMock,
    ) -> None:
        """fallback worker 写 interaction 时也不应透传 fallback 父 client 的 session。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 1

        primary_session = object()
        fallback_session = object()
        primary_client = _Phase3ParallelTestClient(
            config=SimpleNamespace(model="primary-model", thinking_enabled=False),
            client=SimpleNamespace(),
            session=primary_session,
        )
        fallback_client = _Phase3ParallelTestClient(
            config=SimpleNamespace(model="fallback-model", thinking_enabled=False),
            client=SimpleNamespace(),
            session=fallback_session,
        )

        async def _patched_call_annotation_api(
            self: _Phase3ParallelTestClient,
            *,
            messages: list[dict],
            enable_thinking: bool,
            chunk_id: int | None,
            response_model: type[DialogueAttributionResult],
            call_type: str | None,
        ) -> tuple[DialogueAttributionResult, SimpleNamespace]:
            del enable_thinking, chunk_id, response_model, call_type
            if self._config.model == "primary-model":
                raise ConnectionError("primary failed")

            user_prompt = messages[1]["content"]
            indices = [int(match) for match in re.findall(r"(\d+)\. content:", user_prompt)]
            parsed = DialogueAttributionResult(
                dialogues=[
                    DialogueRecordSchema(
                        index=index,
                        is_dialogue=True,
                        speaker=["张三"],
                        tone=None,
                        is_inner_monologue=False,
                        identity_clue=None,
                    )
                    for index in indices
                ]
            )
            return parsed, SimpleNamespace()

        with patch.object(_Phase3ParallelTestClient, "_call_annotation_api", new=_patched_call_annotation_api):
            result = await attribute_dialogues_with_llm(
                primary_client,
                "“你好”",
                [QuoteCandidate(index=1, content="你好")],
                known_characters=["张三"],
                fallback_client=fallback_client,
            )

        self.assertEqual(result[0].speaker, ["张三"])
        self.assertEqual(mock_record_model_interaction.call_count, 1)
        self.assertIs(mock_record_model_interaction.call_args.kwargs["session"], None)
        self.assertIs(primary_client._session, primary_session)
        self.assertIs(fallback_client._session, fallback_session)

    @patch("src.models.local.annotation.phase3.settings")
    async def test_fallback_client_failure_raises_dialogue_attribution_error(self, mock_settings: MagicMock) -> None:
        """Phase3 主客户端与兜底客户端都失败时应抛错。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
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
