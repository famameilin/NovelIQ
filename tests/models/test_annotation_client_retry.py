"""
Phase1/Phase2 独立重试机制测试

创建时间: 2026-03-14
创建者: TraeAI
任务: Phase1/Phase2独立重试机制

修改时间: 2026-03-18
修改者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
修改内容: 更新测试以调用子模块函数
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.annotation import (
    PHASE_MAX_RETRIES,
    Phase1MaxRetriesExceededError,
    Phase2MaxRetriesExceededError,
)
from src.models.local.annotation.multi_phase import annotate_chunk_multi_phase
from src.models.local.annotation.phase1 import annotate_chunk_phase1
from src.models.local.annotation.phase2 import annotate_chunk_phase2
from src.models.local.schema import ChunkAnnotation, ForeshadowingResult


def create_mock_annotation() -> ChunkAnnotation:
    return ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        foreshadowing_type=None,
        foreshadowing_desc="",
        characters=[],
        relations=[],
        dialogues=[],
        character_appearances=[],
        chunk_summary="测试摘要",
    )


def create_mock_foreshadowing() -> ForeshadowingResult:
    return ForeshadowingResult(
        has_foreshadowing=True,
        foreshadowing_type="因果伏笔",
        anchor_text="测试锚点文本",
        anchor_reason="测试锚点原因",
        confidence="high",
    )


class MockAnnotationClient:
    """
    Mock AnnotationClient for testing

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 简化Mock类，移除已弃用方法
    """

    def __init__(self, mock_content="{}", should_fail=False):
        self._config = MagicMock()
        self._config.thinking_enabled = False
        self._config.max_retries = 2
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
        self._instructor_client = None
        self._client = None
        self._task_type = "annotate"
        self._novel_id = "test-novel"
        self.mock_content = mock_content
        self.should_fail = should_fail
        self.call_count = 0

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

    def _record_token_usage(self, response, phase, chunk_id):
        pass

    def _log_prompt_response(self, chunk_id, content_clean, thinking_content, extraction, messages, text, prev_summary):
        pass

    def _get_instructor_client(self):
        return None

    async def _call_annotation_api(self, messages, enable_thinking, chunk_id, response_model=None):
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
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 更新测试以调用子模块函数
    """

    async def test_phase1_success_on_first_attempt(self):
        """Phase1 第一次尝试成功"""
        client = MockAnnotationClient()
        call_count = [0]

        async def mock_call_api(messages, enable_thinking, chunk_id):
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

    async def test_phase1_retry_on_connection_error(self):
        """Phase1 连接错误时重试"""
        client = MockAnnotationClient()
        call_count = [0]

        async def mock_call_api(messages, enable_thinking, chunk_id):
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

    async def test_phase1_fallback_to_cloud(self):
        """Phase1 本地失败后云端成功"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        local_call_count = [0]
        cloud_call_count = [0]

        async def local_call_api(messages, enable_thinking, chunk_id):
            local_call_count[0] += 1
            raise ConnectionError("Local connection failed")

        async def cloud_call_api(messages, enable_thinking, chunk_id):
            cloud_call_count[0] += 1
            return MagicMock()

        local_client._call_annotation_api = local_call_api
        cloud_client._call_annotation_api = cloud_call_api

        result = await annotate_chunk_phase1(
            client=local_client,
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
        )

        self.assertEqual(local_call_count[0], PHASE_MAX_RETRIES)
        self.assertEqual(cloud_call_count[0], 1)
        self.assertIsInstance(result, ChunkAnnotation)

    async def test_phase1_all_retries_exhausted(self):
        """Phase1 本地和云端都失败"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        async def always_fail(messages, enable_thinking, chunk_id):
            raise ConnectionError("Connection failed")

        local_client._call_annotation_api = always_fail
        cloud_client._call_annotation_api = always_fail

        with self.assertRaises(Phase1MaxRetriesExceededError):
            await annotate_chunk_phase1(
                client=local_client,
                text="测试文本",
                chunk_id=1,
                cloud_client=cloud_client,
            )


class TestPhase2Retry(unittest.IsolatedAsyncioTestCase):
    """
    Phase2 重试机制测试

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    修改者: TraeAI
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

    async def test_phase2_retry_on_instructor_failure(self):
        """Phase2 Instructor 调用失败时重试"""
        client = MockAnnotationClient()
        call_count = [0]

        async def mock_call_annotation_api(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Instructor connection failed")

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

    async def test_phase2_fallback_to_cloud(self):
        """Phase2 本地失败后云端成功"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        local_call_count = [0]
        cloud_call_count = [0]

        async def local_call_annotation_api(*args, **kwargs):
            local_call_count[0] += 1
            raise ConnectionError("Local connection failed")

        async def cloud_call_annotation_api(*args, **kwargs):
            cloud_call_count[0] += 1
            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response

        local_client._call_annotation_api = local_call_annotation_api
        cloud_client._call_annotation_api = cloud_call_annotation_api

        result = await annotate_chunk_phase2(
            client=local_client,
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
        )

        self.assertEqual(local_call_count[0], PHASE_MAX_RETRIES)
        self.assertEqual(cloud_call_count[0], 1)
        self.assertIsInstance(result, ForeshadowingResult)

    async def test_phase2_all_retries_exhausted(self):
        """Phase2 本地和云端都失败"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        async def always_fail(*args, **kwargs):
            raise ConnectionError("Connection failed")

        local_client._call_annotation_api = always_fail
        cloud_client._call_annotation_api = always_fail

        with self.assertRaises(Phase2MaxRetriesExceededError):
            await annotate_chunk_phase2(
                client=local_client,
                text="测试文本",
                chunk_id=1,
                cloud_client=cloud_client,
            )

    async def test_phase2_passes_supplied_evidence_bundle_to_message_builder(self):
        """Phase2 只消费上游 evidence_bundle，不再自行触发新的取证分支。"""
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


class TestTwoPhaseIntegration(unittest.IsolatedAsyncioTestCase):
    """
    双次调用集成测试

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    修改内容: 更新测试以调用子模块函数
    """

    @patch("src.models.local.annotation.multi_phase.settings")
    async def test_two_phase_serial_passes_cloud_client(self, mock_settings):
        """串行模式传递 cloud_client 参数"""
        mock_settings.analysis.multi_phase_annotation.parallel = False

        client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        result = await annotate_chunk_multi_phase(
            client=client,
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
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
    async def test_two_phase_parallel_passes_cloud_client(self, mock_settings):
        """并行模式传递 cloud_client 参数"""
        mock_settings.analysis.multi_phase_annotation.parallel = True

        client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        result = await annotate_chunk_multi_phase(
            client=client,
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
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


if __name__ == "__main__":
    unittest.main()
