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
from src.models.local.annotation.evidence_renderer import render_dialogue_attribution_evidence_sections
from src.models.local.annotation.phase3 import (
    attribute_dialogues_with_llm,
    compute_dialogue_lengths_with_llm,
    extract_dialogues_from_text,
)
from src.models.local.schema import DialogueRecord, DialogueRecordSchema, QuoteCandidate
from src.rag.evidence_types import EvidenceBundle, EvidenceItem


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
        mock_annotation_client._process_annotation_response = MagicMock(
            return_value=('{"dialogues": []}', None, None)
        )

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


def _build_phase3_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="灰衣人 -> 白芷",
                metadata={"alias": "灰衣人", "canonical": "白芷"},
            ),
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content="白芷",
                metadata={"name": "白芷", "entity_type": "character"},
            ),
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="白芷",
                metadata={
                    "name": "白芷",
                    "role": "speaker_candidate",
                    "recent_action": "按住剑柄",
                    "recent_emotion": "警惕",
                    "last_seen_chunk": 12,
                },
            ),
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「灰衣人」可能是：白芷",
            ),
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="灰衣人忽然压低声音。",
                metadata={
                    "chunk_id": 5,
                    "similarity": 0.91,
                    "text": "灰衣人忽然压低声音。",
                },
            )
        ],
        requested_names=["灰衣人"],
    )


def _build_phase3_overflow_bundle() -> EvidenceBundle:
    structured = [
        EvidenceItem(
            evidence_type="alias_mapping",
            source="level1",
            content=f"别名{i} -> 人物{i}",
            metadata={"alias": f"别名{i}", "canonical": f"人物{i}"},
        )
        for i in range(1, 4)
    ]
    structured.extend(
        [
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content=f"人物{i}",
                metadata={"name": f"人物{i}", "entity_type": "character"},
            )
            for i in range(1, 4)
        ]
    )
    structured.extend(
        [
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content=f"人物{i}<盟友>人物{i + 1}",
                metadata={
                    "from_name": f"人物{i}",
                    "to_name": f"人物{i + 1}",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            )
            for i in range(1, 4)
        ]
    )

    local = [
        EvidenceItem(
            evidence_type="active_entity",
            source="level2",
            content=f"人物{i}",
            metadata={
                "name": f"人物{i}",
                "role": "speaker_candidate",
                "recent_action": f"动作{i}",
                "recent_emotion": f"情绪{i}",
                "last_seen_chunk": 20 - i,
            },
        )
        for i in range(1, 5)
    ]
    local.extend(
        [
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content=f"「别名{i}」可能是：人物{i}",
            )
            for i in range(1, 4)
        ]
    )

    semantic = [
        EvidenceItem(
            evidence_type="semantic_recall",
            source="level3",
            content=f"人物{i}历史片段：" + ("甲" * 150),
            metadata={
                "chunk_id": i,
                "similarity": 0.9 - i * 0.01,
                "text": f"人物{i}历史片段：" + ("甲" * 150),
            },
        )
        for i in range(1, 4)
    ]

    return EvidenceBundle(
        structured_evidence=structured,
        local_evidence=local,
        semantic_evidence=semantic,
        requested_names=["别名1", "别名2", "别名3"],
    )


def _build_phase3_priority_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="人物一",
                metadata={"name": "人物一"},
            ),
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="人物二",
                metadata={"name": "人物二"},
            ),
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="人物三",
                metadata={"name": "人物三"},
            ),
        ],
        requested_names=["别名一", "别名二", "别名三"],
    )


class TestPhase3EvidenceIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_attribute_dialogues_with_llm_appends_shared_evidence_blocks(self) -> None:
        bundle = _build_phase3_bundle()

        with patch("src.models.local.annotation.phase3.settings") as mock_settings:
            mock_settings.prompts.phase3.system = "system"
            mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
            mock_settings.thinking.phase3_candidates_per_batch = 8

            mock_annotation_client = MagicMock()
            mock_annotation_client._config.model = "test-model"
            mock_annotation_client._config.thinking_enabled = False
            mock_annotation_client._is_cloud_api.return_value = False
            mock_response = MagicMock(dialogues=[], model_dump=MagicMock(return_value={}))
            mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

            await attribute_dialogues_with_llm(
                mock_annotation_client,
                "“你终于来了。”",
                [QuoteCandidate(index=1, content="你终于来了。")],
                known_characters=["白芷"],
                evidence_bundle=bundle,
            )

        user_prompt = mock_annotation_client._call_annotation_api.await_args.kwargs["messages"][-1]["content"]
        self.assertIn("【近期活跃角色】", user_prompt)
        self.assertIn("<Narrative_Evidence_Level1>", user_prompt)
        self.assertIn("<Disambig_Candidates>", user_prompt)
        self.assertIn("<Vector_Evidence>", user_prompt)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_compute_dialogue_lengths_passes_evidence_bundle_to_phase3(self, mock_attribute: MagicMock) -> None:
        bundle = _build_phase3_bundle()
        mock_attribute.return_value = []

        mock_client = MagicMock()
        await compute_dialogue_lengths_with_llm(
            mock_client,
            "“你好”他说道。",
            evidence_bundle=bundle,
        )

        self.assertIs(mock_attribute.await_args.kwargs["evidence_bundle"], bundle)

    @patch("src.models.local.annotation.phase3.settings")
    async def test_attribute_dialogues_with_llm_prioritizes_batch_relevant_candidates(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Phase3 会优先保留当前 batch 真正提到的候选名，而不是机械截前两条。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._is_cloud_api.return_value = False
        mock_response = MagicMock(dialogues=[], model_dump=MagicMock(return_value={}))
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "“别名三，你终于开口了。”",
            [QuoteCandidate(index=1, content="别名三，你终于开口了。")],
            known_characters=["人物一", "人物二", "人物三"],
            evidence_bundle=_build_phase3_priority_bundle(),
        )

        user_prompt = mock_annotation_client._call_annotation_api.await_args.kwargs["messages"][-1]["content"]
        self.assertIn("「别名三」可能是：人物一、人物二、人物三", user_prompt)
        self.assertLess(
            user_prompt.index("「别名三」可能是：人物一、人物二、人物三"),
            user_prompt.index("「别名一」可能是：人物一、人物二、人物三"),
        )


class TestRenderDialogueAttributionEvidenceSections(unittest.TestCase):
    """测试 Phase3 renderer 的 alias_map 和 active_entities 逻辑"""

    def _call(self, bundle=None, alias_map=None, active_entities=None):
        return render_dialogue_attribution_evidence_sections(
            bundle,
            alias_map=alias_map,
            active_entities=active_entities,
        )

    def test_both_none_returns_empty(self) -> None:
        """evidence_bundle=None 且 active_entities=None 时返回 []"""
        result = self._call()
        self.assertEqual(result, [])

    def test_alias_map_none_includes_level1_aliases(self) -> None:
        """alias_map=None 时 include_level1_alias_mappings=True，prompt 包含 Level1 别名裁决"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, alias_map=None)
        # 应包含 Level1 别名映射行
        self.assertTrue(any("已确认别名：灰衣人" in s for s in result))

    def test_alias_map_provided_excludes_level1_aliases(self) -> None:
        """alias_map 非 None 时 include_level1_alias_mappings=False，不注入 Level1 别名裁决"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, alias_map={"猴子": "侯飞白"})
        # disambig_context 是合并块（Level1 事实 + Level2 候选 + Level3 向量），
        # include_level1_alias_mappings=False 只是不包含别名映射行，
        # 但仍会包含 disambig candidates。因此检查“已确认别名：灰衣人”不在结果中。
        self.assertTrue(all("已确认别名：灰衣人" not in s for s in result))
        # 但 active_entities 仍应存在
        self.assertTrue(any("【近期活跃角色】" in s for s in result))

    def test_active_entities_override_bundle(self) -> None:
        """active_entities 非 None 时优先使用传入值，而非 bundle 中的值"""
        bundle = _build_phase3_bundle()
        custom_entities = "【近期活跃角色】自定义实体"
        result = self._call(bundle=bundle, active_entities=custom_entities)
        self.assertIn(custom_entities, result)

    def test_explicit_active_entities_string_is_trimmed_by_phase3_policy(self) -> None:
        """真实入口传入的 active_entities 字符串也要经过 Phase3 裁剪。"""
        custom_entities = "\n".join(
            [
                "【近期活跃角色】",
                "- 角色一（speaker_candidate）：动作一 [chunk=1]",
                "- 角色二（speaker_candidate）：动作二 [chunk=2]",
                "- 角色三（speaker_candidate）：动作三 [chunk=3]",
                "- 角色四（speaker_candidate）：动作四 [chunk=4]",
            ]
        )

        result = self._call(bundle=_build_phase3_bundle(), active_entities=custom_entities)
        active_section = next(section for section in result if "【近期活跃角色】" in section)

        self.assertEqual(sum(1 for line in active_section.splitlines() if line.startswith("- ")), 3)
        self.assertNotIn("角色四", active_section)

    def test_active_entities_without_bundle(self) -> None:
        """evidence_bundle=None 但 active_entities 非 None 时，只返回 active_entities"""
        custom_entities = "【近期活跃角色】仅 fallback"
        result = self._call(bundle=None, active_entities=custom_entities)
        self.assertEqual(result, [custom_entities])

    def test_explicit_empty_alias_map_still_suppresses_level1_alias_lines(self) -> None:
        """显式 alias_map={} 时仍视为调用方已决议，不再反向注入 Level1 alias。"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, alias_map={})
        self.assertTrue(all("已确认别名：灰衣人" not in s for s in result))

    def test_explicit_empty_active_entities_suppresses_bundle_fallback(self) -> None:
        """显式传入空字符串时，不回退 bundle active_entities，也不插入空白区段。"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, active_entities="")
        self.assertTrue(all("【近期活跃角色】" not in s for s in result))

    def test_phase3_sections_trim_overlong_shared_evidence_context(self) -> None:
        """Phase3 task renderer 会裁剪过长的共享 evidence，避免 prompt 继续膨胀。"""
        result = self._call(bundle=_build_phase3_overflow_bundle())

        active_section = next(section for section in result if "【近期活跃角色】" in section)
        level1_section = next(section for section in result if "<Narrative_Evidence_Level1>" in section)
        disambig_section = next(section for section in result if "<Disambig_Candidates>" in section)
        vector_section = next(section for section in result if "<Vector_Evidence>" in section)

        self.assertEqual(sum(1 for line in active_section.splitlines() if line.startswith("- ")), 3)
        self.assertEqual(sum(1 for line in level1_section.splitlines() if line.startswith("- ")), 6)
        self.assertEqual(sum(1 for line in disambig_section.splitlines() if line.startswith("「")), 2)
        self.assertEqual(vector_section.count("[Chunk "), 2)
        self.assertNotIn("[Chunk 3]", vector_section)
        self.assertIn("...", vector_section)
        self.assertNotIn("人物1历史片段：" + ("甲" * 150), vector_section)


class TestComputeDialogueLengthsWithLLM(unittest.IsolatedAsyncioTestCase):
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

    async def test_empty_text_returns_empty_result(self) -> None:
        """空文本返回空结果对象"""
        mock_client = MagicMock()
        result = await compute_dialogue_lengths_with_llm(mock_client, "")
        self.assertEqual(result.speaker_lengths, {})
        self.assertEqual(result.canonical_attribution, {})
        self.assertEqual(result.dialogues, [])

    async def test_no_dialogues_returns_empty_result(self) -> None:
        """没有对话返回空结果对象"""
        mock_client = MagicMock()
        result = await compute_dialogue_lengths_with_llm(mock_client, "没有对话的文本")
        self.assertEqual(result.speaker_lengths, {})
        self.assertEqual(result.canonical_attribution, {})
        self.assertEqual(result.dialogues, [])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_compute_lengths_with_attribution(self, mock_attribute: MagicMock) -> None:
        """根据归属结果计算对话长度 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker=["李四"]),
            DialogueRecord(index=3, content="再见", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。\u201c再见\u201d他说。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertIsInstance(result.speaker_lengths, dict)
        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好") + len("再见"))
        self.assertEqual(result.speaker_lengths.get("李四", 0), len("你好啊"))
        self.assertEqual(result.canonical_attribution, {1: ["张三"], 2: ["李四"], 3: ["张三"]})
        self.assertEqual(result.dialogues, [(1, "你好"), (2, "你好啊"), (3, "再见")])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_unknown_speaker_kept_and_counted(self, mock_settings: MagicMock) -> None:
        """未知说话者会被保留并计入长度，交由下游继续判断。

        此测试走端到端真实分支：传入 known_characters，mock API 返回不在已知列表中的 speaker，
        验证 _post_process_validation 不丢弃未知 speaker，且长度统计正确。
        """
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
                DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker=["王五"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。"

        result = await compute_dialogue_lengths_with_llm(
            mock_annotation_client,
            text,
            known_characters=["张三"],
        )

        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.speaker_lengths.get("王五", 0), len("你好啊"))
        self.assertEqual(result.canonical_attribution, {1: ["张三"], 2: ["王五"]})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_non_dialogue_filtered(self, mock_attribute: MagicMock) -> None:
        """非对话内容被过滤 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="精打细算", is_dialogue=False, speaker=None),
            DialogueRecord(index=2, content="你好", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c精打细算\u201d的折扇。\u201c你好\u201d他说道。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(len(result.dialogues), 1)
        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.canonical_attribution, {2: ["张三"]})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_source_content_preferred_over_model_content(self, mock_attribute: MagicMock) -> None:
        """长度统计优先使用原文提取内容，避免模型改写影响"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好你好你好", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.dialogues, [(1, "你好")])
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_duplicate_index_counted_once(self, mock_attribute: MagicMock) -> None:
        """重复 index 只计一次，避免长度膨胀"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})
        self.assertEqual(result.dialogues, [(1, "你好")])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_return_tones_when_requested(self, mock_attribute: MagicMock) -> None:
        """显式请求时返回对话语气。"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"], tone="强硬"),
        ]

        mock_client = MagicMock()
        text = '"你好"他说道。'

        result = await compute_dialogue_lengths_with_llm(
            mock_client,
            text,
            return_tones=True,
        )

        self.assertEqual(result.speaker_lengths.get("张三", 0), len(result.dialogues[0][1]))
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})
        self.assertEqual(result.dialogues[0][0], 1)
        self.assertEqual(result.dialogue_tones, {1: "强硬"})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_return_identity_clues_when_requested(self, mock_attribute: MagicMock) -> None:
        """显式请求时返回身份线索。"""
        mock_attribute.return_value = [
            DialogueRecord(
                index=1,
                content="你好",
                is_dialogue=True,
                speaker=["张三"],
                identity_clue="声音低沉的中年男子",
            ),
        ]

        mock_client = MagicMock()
        text = '"你好"他说道。'

        result = await compute_dialogue_lengths_with_llm(
            mock_client,
            text,
            return_identity_clues=True,
        )

        self.assertEqual(result.speaker_lengths.get("张三", 0), len(result.dialogues[0][1]))
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})
        self.assertEqual(result.dialogue_identity_clues, {1: "声音低沉的中年男子"})

    @patch("src.models.local.annotation.phase3.settings")
    async def test_thinking_enabled_false_is_passed_to_api(self, mock_settings: MagicMock) -> None:
        """验证 thinking_enabled=False 时 enable_thinking=False 被传递给 API 调用。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            [QuoteCandidate(index=1, content="你好")],
            known_characters=["张三"],
        )

        call_kwargs = mock_annotation_client._call_annotation_api.await_args.kwargs
        self.assertFalse(call_kwargs["enable_thinking"])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_thinking_enabled_true_is_passed_to_api(self, mock_settings: MagicMock) -> None:
        """验证 thinking_enabled=True 时 enable_thinking=True 被传递给 API 调用。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = True
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            [QuoteCandidate(index=1, content="你好")],
            known_characters=["张三"],
        )

        call_kwargs = mock_annotation_client._call_annotation_api.await_args.kwargs
        self.assertTrue(call_kwargs["enable_thinking"])


class TestPostProcessValidationFix(unittest.TestCase):
    """测试 _post_process_validation：别名归一化 + 保留 LLM speaker 判断"""

    def _call_validation(
        self,
        records: list[DialogueRecord],
        known_characters: list[str] | None = None,
        alias_map: dict[str, str] | None = None,
    ) -> list[DialogueRecord]:
        from src.models.local.annotation.phase3 import _post_process_validation

        candidates = [QuoteCandidate(index=r.index, content=r.content or "") for r in records]
        return _post_process_validation(records, candidates, known_characters, alias_map, chunk_id=1)

    def test_speaker_in_known_set_passes_through(self) -> None:
        """speaker 在 known_set 中时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["白芷"]),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["白芷"])

    def test_unknown_speaker_kept(self) -> None:
        """speaker 不在 known_set 中时保留 LLM 原始判断，不丢弃不修正"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["新角色"]),
        ]
        result = self._call_validation(records, known_characters=["伯安"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["新角色"])

    def test_alias_normalized(self) -> None:
        """别名归一化"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["猴子"]),
        ]
        result = self._call_validation(records, known_characters=["侯飞白"], alias_map={"猴子": "侯飞白"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["侯飞白"])

    def test_no_known_characters_passes_through(self) -> None:
        """无 known_characters 时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["白芷"]),
        ]
        result = self._call_validation(records, known_characters=None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["白芷"])

    def test_identity_clue_preserved(self) -> None:
        """identity_clue 作为元数据保留，不参与 speaker 修正"""
        records = [
            DialogueRecord(
                index=1,
                content="我叫白芷。",
                is_dialogue=True,
                speaker=["白芷"],
                identity_clue="白芷自称名为白芷",
            ),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["白芷"])
        self.assertEqual(result[0].identity_clue, "白芷自称名为白芷")

    def test_null_speaker_passes_through(self) -> None:
        """speaker 为 null 时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=None),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].speaker)

    def test_invalid_index_skipped(self) -> None:
        """无效 index 的记录被跳过"""
        from src.models.local.annotation.phase3 import _post_process_validation

        records = [
            DialogueRecord(index=99, content="你好", is_dialogue=True, speaker=["白芷"]),
        ]
        candidates = [QuoteCandidate(index=1, content="你好")]
        result = _post_process_validation(records, candidates, ["白芷"], None, chunk_id=1)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
