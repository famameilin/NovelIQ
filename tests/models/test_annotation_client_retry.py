"""
Phase1/Phase2 独立重试机制测试

创建时间: 2026-03-14
任务: Phase1/Phase2独立重试机制

修改时间: 2026-03-18
任务: code-quality-refactor - Task 9 拆分annotation_client
修改内容: 更新测试以调用子模块函数
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import settings
from src.models.local.annotation import Phase1MaxRetriesExceededError, Phase2MaxRetriesExceededError
from src.models.local.annotation.multi_phase import annotate_chunk_multi_phase
from src.models.local.annotation.phase1 import annotate_chunk_phase1
from src.models.local.annotation.phase2 import annotate_chunk_phase2
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation, ForeshadowingResult
from src.rag import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)


def create_mock_annotation(character_names: list[str] | None = None) -> ChunkAnnotation:
    characters = (
        [
            CharacterSnapshot(
                name=name,
                role_function="主体",
                action="观察",
                action_type="其他",
                emotion_score="neutral",
            )
            for name in character_names
        ]
        if character_names
        else []
    )
    return ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        characters=characters,
        relations=[],
        dialogues=[],
        character_appearances=[],
        chunk_summary="测试摘要",
    )


def create_mock_foreshadowing() -> ForeshadowingResult:
    return ForeshadowingResult(
        has_foreshadowing=True,
        is_strong_setup=True,
        foreshadowing_type="其他",
        setup_kind="其他",
        anchor_text="测试锚点文本",
        anchor_reason="测试锚点原因",
        setup_summary="测试锚点对应的 setup thread 仍待后续兑现",
        why_unresolved_now="当前只是给出测试锚点，还没有兑现这个测试钩子。",
        expected_payoff_family="其他",
        payoff_likelihood="high",
        is_new_setup=True,
        linked_setup_id=None,
        setup_status="open",
        confidence="high",
    )


def create_phase4_evidence_bundle() -> EvidenceBundle:
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
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content="白芷<盟友>侯飞白",
                metadata={
                    "from_name": "白芷",
                    "to_name": "侯飞白",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            ),
            EvidenceItem(
                evidence_type="entity_type",
                source="level1",
                content="白芷:character",
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
                    "role": "主体",
                    "recent_action": "试探侯飞白",
                    "recent_emotion": "警惕",
                    "last_seen_chunk": 18,
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
                content="灰衣人曾在旧宅与侯飞白短暂结盟。",
                metadata={
                    "chunk_id": 9,
                    "similarity": 0.93,
                    "text": "灰衣人曾在旧宅与侯飞白短暂结盟。",
                },
            )
        ],
        requested_names=["灰衣人"],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷", entity_type="character")],
            confirmed_relations=[ConfirmedRelation(from_name="白芷", to_name="侯飞白", relation_type="盟友")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )


class MockAnnotationClient:
    """
    Mock AnnotationClient for testing

    创建时间: 2026-03-14
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 简化Mock类，移除已弃用方法

    修改时间: 2026-04-22
    任务: unify-estimated-token-accounting
    修改内容: 补充统一估算 token helper stub，覆盖 Phase1/Phase2 新记账路径
    """

    def __init__(self, mock_content="{}", should_fail=False):
        self._config = MagicMock()
        self._config.thinking_enabled = False
        self._config.temperature = 0.7
        self._config.max_tokens = 4096
        self._config.model = "test-model"
        self._analysis_logger = None
        self._call_count = 0
        self._phase1_call_count = 0
        self._phase2_call_count = 0
        self._should_fail_phase1 = False
        self._should_fail_phase2 = False
        self._fail_times_phase1 = 0
        self._fail_times_phase2 = 0
        self._token_usage_callback = None
        self._client = None
        self._task_type = "annotation"
        self._novel_id = "test-novel"
        self.mock_content = mock_content
        self.should_fail = should_fail
        self.call_count = 0
        self.recorded_token_usage: list[dict[str, object]] = []

    def _is_cloud_api(self) -> bool:
        return False

    def _log_annotation_start(self, is_cloud: bool, text: str, prev_summary, chunk_id, phase: str = ""):
        pass

    def _build_annotation_messages_v2(self, **kwargs):
        return [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

    def _build_foreshadowing_messages(self, **kwargs):
        return [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]

    def _process_annotation_response(self, response, is_cloud, chunk_id=None, phase=""):
        return ("{}", None, None)

    def _parse_annotation(self, content):
        return create_mock_annotation()

    def _validate_annotation(self, result, sources, chunk_id, content_clean=""):
        return result

    def _validate_and_retry_annotation(self, result, prompt, content, sources, chunk_id):
        return result

    def _record_estimated_token_usage_from_messages(self, messages, response_text, call_type, chunk_id, **kwargs):
        self.recorded_token_usage.append(
            {
                "method": "messages",
                "messages": messages,
                "response_text": response_text,
                "call_type": call_type,
                "chunk_id": chunk_id,
                "kwargs": kwargs,
            }
        )

    def _record_estimated_token_usage_from_response(self, messages, response, call_type, chunk_id, **kwargs):
        response_text = ""
        if getattr(response, "choices", None):
            response_text = getattr(response.choices[0].message, "content", "") or ""
        self.recorded_token_usage.append(
            {
                "method": "response",
                "messages": messages,
                "response": response,
                "response_text": response_text,
                "call_type": call_type,
                "chunk_id": chunk_id,
                "kwargs": kwargs,
            }
        )

    def _log_prompt_response(self, chunk_id, content_clean, thinking_content, extraction, messages, text, prev_summary):
        pass

    async def _call_annotation_api(self, messages, enable_thinking, chunk_id, response_model=None, call_type=None):
        self._call_count += 1
        if self.should_fail:
            raise ConnectionError("Connection failed")
        if response_model is not None:
            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response
        return MagicMock()

    def _call_api_stream(self, request_params, is_cloud=False):
        return MagicMock()

    def _get_thinking_params(self, enable_thinking):
        return {}

    def _build_extra_body(self, enable_thinking):
        return {}

    def _build_json_schema(self, response_model):
        return {"type": "json_schema"}

    def _parse_structured_response(self, response, response_model):
        return create_mock_foreshadowing()

    def _log_annotation_result(self, chunk_id, result, content_clean, thinking_content, extraction):
        pass


class TestPhase1Retry(unittest.IsolatedAsyncioTestCase):
    """
    Phase1 重试机制测试

    创建时间: 2026-03-14
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 更新测试以调用子模块函数
    """

    async def test_phase1_success_on_first_attempt(self):
        """Phase1 第一次尝试成功"""
        client = MockAnnotationClient()
        call_count = [0]

        async def mock_call_api(messages, enable_thinking, chunk_id, **kwargs):
            call_count[0] += 1
            return MagicMock()

        client._call_annotation_api = mock_call_api

        result = await annotate_chunk_phase1(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertEqual(call_count[0], 1)
        self.assertIsInstance(result, ChunkAnnotation)
        self.assertEqual(client.recorded_token_usage[0]["call_type"], "phase1")
        self.assertEqual(client.recorded_token_usage[0]["chunk_id"], 1)

    async def test_phase1_retry_on_connection_error(self):
        """Phase1 连接错误时重试"""
        client = MockAnnotationClient()
        call_count = [0]

        async def mock_call_api(messages, enable_thinking, chunk_id, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Connection failed")
            return MagicMock()

        client._call_annotation_api = mock_call_api

        result = await annotate_chunk_phase1(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertEqual(call_count[0], 3)
        self.assertIsInstance(result, ChunkAnnotation)

    async def test_phase1_fallback_to_annotation_fallback_client(self):
        """Phase1 主客户端失败后兜底客户端成功"""
        local_client = MockAnnotationClient()
        fallback_client = MockAnnotationClient()
        fallback_client._task_type = "annotation_fallback"

        local_call_count = [0]
        fallback_call_count = [0]

        async def local_call_api(messages, enable_thinking, chunk_id, **kwargs):
            local_call_count[0] += 1
            raise ConnectionError("Local connection failed")

        async def fallback_call_api(messages, enable_thinking, chunk_id, **kwargs):
            fallback_call_count[0] += 1
            return MagicMock()

        local_client._call_annotation_api = local_call_api
        fallback_client._call_annotation_api = fallback_call_api

        result = await annotate_chunk_phase1(
            client=local_client,
            text="测试文本",
            chunk_id=1,
            fallback_client=fallback_client,
        )

        self.assertEqual(local_call_count[0], settings.runtime.annotation.phase_max_retries)
        self.assertEqual(fallback_call_count[0], 1)
        self.assertIsInstance(result, ChunkAnnotation)
        self.assertEqual(fallback_client.recorded_token_usage[0]["kwargs"]["task_type"], "annotation")

    async def test_phase1_all_retries_exhausted(self):
        """Phase1 主客户端和兜底客户端都失败"""
        local_client = MockAnnotationClient()
        fallback_client = MockAnnotationClient()

        async def always_fail(messages, enable_thinking, chunk_id, **kwargs):
            raise ConnectionError("Connection failed")

        local_client._call_annotation_api = always_fail
        fallback_client._call_annotation_api = always_fail

        with self.assertRaises(Phase1MaxRetriesExceededError):
            await annotate_chunk_phase1(
                client=local_client,
                text="测试文本",
                chunk_id=1,
                fallback_client=fallback_client,
            )

    async def test_phase1_validation_failure_still_records_failed_attempt_tokens(self):
        """Phase1 响应已返回但校验失败时，也应记录失败尝试的 token。"""
        client = MockAnnotationClient()
        validation_call_count = [0]

        def validate_once_then_succeed(result, sources, chunk_id, content_clean=""):
            validation_call_count[0] += 1
            if validation_call_count[0] == 1:
                raise ValueError("validation failed")
            return result

        client._validate_annotation = validate_once_then_succeed

        result = await annotate_chunk_phase1(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertIsInstance(result, ChunkAnnotation)
        self.assertEqual(validation_call_count[0], 2)
        self.assertEqual(len(client.recorded_token_usage), 2)
        self.assertEqual(client.recorded_token_usage[0]["call_type"], "phase1")
        self.assertEqual(client.recorded_token_usage[1]["call_type"], "phase1")

    async def test_phase1_response_processing_failure_still_records_failed_attempt_tokens(self):
        """Phase1 响应清洗失败时，也应按已返回响应补记 token。"""
        client = MockAnnotationClient()
        process_call_count = [0]

        def fail_once_then_succeed(response, is_cloud, chunk_id=None, phase=""):
            process_call_count[0] += 1
            if process_call_count[0] == 1:
                raise ValueError("repetitive output detected")
            return ("{}", None, None)

        client._process_annotation_response = fail_once_then_succeed

        result = await annotate_chunk_phase1(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertIsInstance(result, ChunkAnnotation)
        self.assertEqual(process_call_count[0], 2)
        self.assertEqual(len(client.recorded_token_usage), 2)
        self.assertEqual(client.recorded_token_usage[0]["method"], "response")
        self.assertEqual(client.recorded_token_usage[0]["call_type"], "phase1")
        self.assertEqual(client.recorded_token_usage[1]["method"], "messages")
        self.assertEqual(client.recorded_token_usage[1]["call_type"], "phase1")


class TestPhase2Retry(unittest.IsolatedAsyncioTestCase):
    """
    Phase2 重试机制测试

    创建时间: 2026-03-14
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 更新测试以调用子模块函数
    """

    async def test_phase2_success_on_first_attempt(self):
        """Phase2 第一次尝试成功"""
        client = MockAnnotationClient()

        result = await annotate_chunk_phase2(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertIsInstance(result, ForeshadowingResult)
        self.assertEqual(client.recorded_token_usage[0]["call_type"], "phase2")
        self.assertEqual(client.recorded_token_usage[0]["chunk_id"], 1)

    @patch("src.models.local.annotation.runtime.record_model_interaction")
    async def test_phase2_persists_thinking_content(self, mock_record_model_interaction: MagicMock):
        """Phase2 会持久化 _process_annotation_response 提取出的 thinking_content。"""
        client = MockAnnotationClient()
        client._process_annotation_response = MagicMock(return_value=("{}", "thinking", MagicMock()))
        client._extract_reasoning_tokens = MagicMock(return_value=11)

        result = await annotate_chunk_phase2(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertIsInstance(result, ForeshadowingResult)
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["thinking_content"], "thinking")
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["reasoning_tokens"], 11)
        self.assertFalse(mock_record_model_interaction.call_args.kwargs["requested_thinking"])

    async def test_phase2_retry_on_structured_call_failure(self):
        """
        Phase2 结构化调用失败时重试。

        修改时间: 2026-04-24
        任务: fix-structured-output-review-findings
        修改内容: Instructor 运行时已移除，测试命名和错误文本改为结构化调用失败。
        """
        client = MockAnnotationClient()
        call_count = [0]

        async def mock_call_annotation_api(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("structured call connection failed")

            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response

        client._call_annotation_api = mock_call_annotation_api

        result = await annotate_chunk_phase2(
            client=client,
            text="测试文本",
            chunk_id=1,
        )

        self.assertEqual(call_count[0], 3)
        self.assertIsInstance(result, ForeshadowingResult)

    async def test_phase2_fallback_to_annotation_fallback_client(self):
        """Phase2 主客户端失败后兜底客户端成功"""
        local_client = MockAnnotationClient()
        fallback_client = MockAnnotationClient()
        fallback_client._task_type = "annotation_fallback"

        local_call_count = [0]
        fallback_call_count = [0]

        async def local_call_annotation_api(*args, **kwargs):
            local_call_count[0] += 1
            raise ConnectionError("Local connection failed")

        async def fallback_call_annotation_api(*args, **kwargs):
            fallback_call_count[0] += 1
            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response

        local_client._call_annotation_api = local_call_annotation_api
        fallback_client._call_annotation_api = fallback_call_annotation_api

        result = await annotate_chunk_phase2(
            client=local_client,
            text="测试文本",
            chunk_id=1,
            fallback_client=fallback_client,
        )

        self.assertEqual(local_call_count[0], settings.runtime.annotation.phase_max_retries)
        self.assertEqual(fallback_call_count[0], 1)
        self.assertIsInstance(result, ForeshadowingResult)
        self.assertEqual(fallback_client.recorded_token_usage[0]["kwargs"]["task_type"], "annotation")

    async def test_phase2_all_retries_exhausted(self):
        """Phase2 主客户端和兜底客户端都失败"""
        local_client = MockAnnotationClient()
        fallback_client = MockAnnotationClient()

        async def always_fail(*args, **kwargs):
            raise ConnectionError("Connection failed")

        local_client._call_annotation_api = always_fail
        fallback_client._call_annotation_api = always_fail

        with self.assertRaises(Phase2MaxRetriesExceededError):
            await annotate_chunk_phase2(
                client=local_client,
                text="测试文本",
                chunk_id=1,
                fallback_client=fallback_client,
            )

    async def test_phase2_passes_supplied_evidence_bundle_to_message_builder(self):
        """Phase2 只消费上游 evidence_bundle，且默认保持 current-text-only 输入边界。"""
        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="phase2_evidence_bundle")

        with patch(
            "src.models.local.annotation.phase2._build_foreshadowing_messages",
            return_value=[{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
        ) as mock_build_messages:
            result = await annotate_chunk_phase2(
                client=client,
                text="阿七摸到袖中发烫的玉佩，心里莫名发紧。",
                chunk_id=12,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result, ForeshadowingResult)
        self.assertIs(mock_build_messages.call_args.kwargs["evidence_bundle"], evidence_bundle)
        self.assertIs(mock_build_messages.call_args.kwargs["include_evidence_blocks"], False)

    async def test_phase2_can_enable_shared_evidence_blocks_via_settings(self):
        """Phase2 支持通过配置显式打开共享 evidence 注入，便于做 targeted ablation。"""
        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="phase2_evidence_bundle")

        with (
            patch("src.models.local.annotation.phase2.settings") as mock_settings,
            patch(
                "src.models.local.annotation.phase2._build_foreshadowing_messages",
                return_value=[{"role": "system", "content": "test"}, {"role": "user", "content": "test"}],
            ) as mock_build_messages,
        ):
            mock_settings.runtime.annotation.phase_max_retries = settings.runtime.annotation.phase_max_retries
            mock_settings.analysis.multi_phase_annotation.include_phase2_evidence = True

            result = await annotate_chunk_phase2(
                client=client,
                text="阿七摸到袖中发烫的玉佩，心里莫名发紧。",
                chunk_id=12,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result, ForeshadowingResult)
        self.assertIs(mock_build_messages.call_args.kwargs["evidence_bundle"], evidence_bundle)
        self.assertIs(mock_build_messages.call_args.kwargs["include_evidence_blocks"], True)


class TestTwoPhaseIntegration(unittest.IsolatedAsyncioTestCase):
    """
    双次调用集成测试

    创建时间: 2026-03-14
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 更新测试以调用子模块函数
    """

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_serial_passes_fallback_client(self, mock_settings):
        """串行模式传递 fallback_client 参数"""
        mock_settings.analysis.multi_phase_annotation.parallel = False

        client = MockAnnotationClient()
        fallback_client = MockAnnotationClient()

        result = await annotate_chunk_multi_phase(
            client=client,
            text="测试文本",
            chunk_id=1,
            fallback_client=fallback_client,
        )

        self.assertIsInstance(result.annotation, ChunkAnnotation)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_serial_passes_evidence_bundle_to_phase2(self, mock_settings):
        """串行模式会把上游 evidence_bundle 继续透传给 Phase2。"""
        mock_settings.analysis.multi_phase_annotation.parallel = False

        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="shared_phase_evidence_bundle")

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ) as mock_phase2,
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="测试文本",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        self.assertIs(mock_phase2.await_args.kwargs["evidence_bundle"], evidence_bundle)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_parallel_passes_fallback_client(self, mock_settings):
        """并行模式传递 fallback_client 参数"""
        mock_settings.analysis.multi_phase_annotation.parallel = True

        client = MockAnnotationClient()
        fallback_client = MockAnnotationClient()

        result = await annotate_chunk_multi_phase(
            client=client,
            text="测试文本",
            chunk_id=1,
            fallback_client=fallback_client,
        )

        self.assertIsInstance(result.annotation, ChunkAnnotation)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_parallel_passes_evidence_bundle_to_phase2(self, mock_settings):
        """并行模式也会把上游 evidence_bundle 继续透传给 Phase2。"""
        mock_settings.analysis.multi_phase_annotation.parallel = True

        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="shared_phase_evidence_bundle")

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ) as mock_phase2,
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="测试文本",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        self.assertIs(mock_phase2.await_args.kwargs["evidence_bundle"], evidence_bundle)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_serial_passes_evidence_bundle_to_phase3(self, mock_settings):
        """串行模式也会把上游 evidence_bundle 继续透传给 Phase3。"""
        mock_settings.analysis.multi_phase_annotation.parallel = False

        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="shared_phase_evidence_bundle")
        phase3_result = MagicMock(
            speaker_lengths={},
            canonical_attribution={},
            dialogues=[],
            dialogue_tones={},
            dialogue_identity_clues={},
        )

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.compute_dialogue_lengths_with_llm",
                new=AsyncMock(return_value=phase3_result),
            ) as mock_phase3,
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="他说：“你好。”",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        self.assertIs(mock_phase3.await_args.kwargs["evidence_bundle"], evidence_bundle)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_parallel_passes_evidence_bundle_to_phase3(self, mock_settings):
        """并行模式也会把上游 evidence_bundle 继续透传给 Phase3。"""
        mock_settings.analysis.multi_phase_annotation.parallel = True

        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="shared_phase_evidence_bundle")
        phase3_result = MagicMock(
            speaker_lengths={},
            canonical_attribution={},
            dialogues=[],
            dialogue_tones={},
            dialogue_identity_clues={},
        )

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.compute_dialogue_lengths_with_llm",
                new=AsyncMock(return_value=phase3_result),
            ) as mock_phase3,
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="他说：“你好。”",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        self.assertIs(mock_phase3.await_args.kwargs["evidence_bundle"], evidence_bundle)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_serial_passes_evidence_bundle_to_phase4(self, mock_settings):
        """串行模式也会把上游 evidence_bundle 继续透传给 Phase4。"""
        mock_settings.analysis.multi_phase_annotation.parallel = False

        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="shared_phase_evidence_bundle")

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation(["白芷", "侯飞白"])),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
                new=AsyncMock(return_value=[]),
            ) as mock_phase4,
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="白芷看向侯飞白。",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        self.assertIs(mock_phase4.await_args.kwargs["evidence_bundle"], evidence_bundle)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_parallel_passes_evidence_bundle_to_phase4(self, mock_settings):
        """并行模式也会把上游 evidence_bundle 继续透传给 Phase4。"""
        mock_settings.analysis.multi_phase_annotation.parallel = True

        client = MockAnnotationClient()
        evidence_bundle = MagicMock(name="shared_phase_evidence_bundle")

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation(["白芷", "侯飞白"])),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
                new=AsyncMock(return_value=[]),
            ) as mock_phase4,
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="白芷看向侯飞白。",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        self.assertIs(mock_phase4.await_args.kwargs["evidence_bundle"], evidence_bundle)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_serial_phase4_prompt_contains_shared_evidence_sections(self, mock_settings):
        """串行模式的 Phase4 真实 prompt 会消费 Level1/2/3 section。"""
        mock_settings.analysis.multi_phase_annotation.parallel = False

        client = MockAnnotationClient()
        evidence_bundle = create_phase4_evidence_bundle()

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation(["白芷", "侯飞白"])),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ),
            patch(
                "src.models.local.annotation.phase4.execute_phase4_call",
                new=AsyncMock(return_value=[]),
            ) as mock_phase4_call,
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="灰衣人抬眼看向侯飞白。",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        phase4_prompt = mock_phase4_call.await_args.kwargs["messages"][1]["content"]
        self.assertIn("<Narrative_Evidence_Level1>", phase4_prompt)
        self.assertIn("【近期活跃角色】", phase4_prompt)
        self.assertIn("<Vector_Evidence>", phase4_prompt)
        self.assertNotIn("<Disambig_Candidates>", phase4_prompt)

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_parallel_phase4_prompt_contains_shared_evidence_sections(self, mock_settings):
        """并行模式的 Phase4 真实 prompt 也会消费同一组 Level1/2/3 section。"""
        mock_settings.analysis.multi_phase_annotation.parallel = True

        client = MockAnnotationClient()
        evidence_bundle = create_phase4_evidence_bundle()

        with (
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase1",
                new=AsyncMock(return_value=create_mock_annotation(["白芷", "侯飞白"])),
            ),
            patch(
                "src.models.local.annotation.multi_phase.annotate_chunk_phase2",
                new=AsyncMock(return_value=create_mock_foreshadowing()),
            ),
            patch(
                "src.models.local.annotation.phase4.execute_phase4_call",
                new=AsyncMock(return_value=[]),
            ) as mock_phase4_call,
        ):
            result = await annotate_chunk_multi_phase(
                client=client,
                text="灰衣人抬眼看向侯飞白。",
                chunk_id=1,
                evidence_bundle=evidence_bundle,
            )

        self.assertIsInstance(result.annotation, ChunkAnnotation)
        phase4_prompt = mock_phase4_call.await_args.kwargs["messages"][1]["content"]
        self.assertIn("<Narrative_Evidence_Level1>", phase4_prompt)
        self.assertIn("【近期活跃角色】", phase4_prompt)
        self.assertIn("<Vector_Evidence>", phase4_prompt)
        self.assertNotIn("<Disambig_Candidates>", phase4_prompt)


if __name__ == "__main__":
    unittest.main()
