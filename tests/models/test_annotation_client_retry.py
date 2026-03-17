"""
Phase1/Phase2 独立重试机制测试

创建时间: 2026-03-14
创建者: TraeAI
任务: Phase1/Phase2独立重试机制
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.annotation_client import (
    AnnotationClient,
    Phase1MaxRetriesExceededError,
    Phase2MaxRetriesExceededError,
    PHASE_MAX_RETRIES,
)
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


class MockAnnotationClient(AnnotationClient):
    """
    Mock AnnotationClient for testing
    
    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 重构本地标注客户端集成 Instructor
    修改内容: 添加 _instructor_client 属性和 _get_instructor_client 方法
    """

    def __init__(self, mock_content="{}", should_fail=False):
        self._config = MagicMock()
        self._config.thinking_enabled = False
        self._config.max_retries = 2
        self._config.temperature = 0.7
        self._config.max_tokens = 4096
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

    def _call_annotation_api(self, messages, enable_thinking, chunk_id, response_model=None):
        self.call_count += 1

        if self.should_fail:
            raise ConnectionError("Connection error")

        if response_model is not None:
            # For testing phase2
            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=self.mock_content, reasoning_content="thinking"))]

        return mock_response

    def _process_annotation_response(self, response, is_cloud, chunk_id=None, phase=""):
        return ("{}", None, None)

    def _parse_annotation(self, content):
        return create_mock_annotation()

    def _validate_and_retry_annotation(self, result, prompt, content, sources, chunk_id):
        return result

    def _record_token_usage(self, response, phase, chunk_id):
        pass

    def _get_instructor_client(self):
        """Mock instructor client for testing"""
        mock_instructor = MagicMock()
        mock_instructor.chat.completions.create_with_completion.return_value = (
            create_mock_foreshadowing(),
            MagicMock(),
        )
        return mock_instructor


class TestPhase1Retry(unittest.TestCase):
    """
    Phase1 重试机制测试

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制
    """

    def test_phase1_success_on_first_attempt(self):
        """Phase1 第一次尝试成功"""
        client = MockAnnotationClient()
        call_count = [0]

        def mock_call_api(messages, enable_thinking, chunk_id):
            call_count[0] += 1
            return MagicMock()

        client._call_annotation_api = mock_call_api

        result = client._annotate_chunk_phase1(text="测试文本", chunk_id=1)

        self.assertEqual(call_count[0], 1)
        self.assertIsInstance(result, ChunkAnnotation)

    def test_phase1_retry_on_connection_error(self):
        """Phase1 连接错误时重试"""
        client = MockAnnotationClient()
        call_count = [0]

        def mock_call_api(messages, enable_thinking, chunk_id):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Connection failed")
            return MagicMock()

        client._call_annotation_api = mock_call_api

        result = client._annotate_chunk_phase1(text="测试文本", chunk_id=1)

        self.assertEqual(call_count[0], 3)
        self.assertIsInstance(result, ChunkAnnotation)

    def test_phase1_fallback_to_cloud(self):
        """Phase1 本地失败后云端成功"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        local_call_count = [0]
        cloud_call_count = [0]

        def local_call_api(messages, enable_thinking, chunk_id):
            local_call_count[0] += 1
            raise ConnectionError("Local connection failed")

        def cloud_call_api(messages, enable_thinking, chunk_id):
            cloud_call_count[0] += 1
            return MagicMock()

        local_client._call_annotation_api = local_call_api
        cloud_client._call_annotation_api = cloud_call_api

        result = local_client._annotate_chunk_phase1(
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
        )

        self.assertEqual(local_call_count[0], PHASE_MAX_RETRIES)
        self.assertEqual(cloud_call_count[0], 1)
        self.assertIsInstance(result, ChunkAnnotation)

    def test_phase1_all_retries_exhausted(self):
        """Phase1 本地和云端都失败"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        def always_fail(messages, enable_thinking, chunk_id):
            raise ConnectionError("Connection failed")

        local_client._call_annotation_api = always_fail
        cloud_client._call_annotation_api = always_fail

        with self.assertRaises(Phase1MaxRetriesExceededError):
            local_client._annotate_chunk_phase1(
                text="测试文本",
                chunk_id=1,
                cloud_client=cloud_client,
            )


class TestPhase2Retry(unittest.TestCase):
    """
    Phase2 重试机制测试

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 重构本地标注客户端集成 Instructor
    修改内容: 更新测试以适配 Instructor 集成
    """

    def test_phase2_success_on_first_attempt(self):
        """Phase2 第一次尝试成功"""
        client = MockAnnotationClient()

        result = client._annotate_chunk_phase2(text="测试文本", chunk_id=1)

        self.assertIsInstance(result, ForeshadowingResult)

    def test_phase2_retry_on_instructor_failure(self):
        """Phase2 Instructor 调用失败时重试"""
        client = MockAnnotationClient()
        call_count = [0]

        def mock_call_annotation_api(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Instructor connection failed")
            
            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response

        client._call_annotation_api = mock_call_annotation_api

        result = client._annotate_chunk_phase2(text="测试文本", chunk_id=1)

        self.assertEqual(call_count[0], 3)
        self.assertIsInstance(result, ForeshadowingResult)

    def test_phase2_fallback_to_cloud(self):
        """Phase2 本地失败后云端成功"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        local_call_count = [0]
        cloud_call_count = [0]

        def local_call_annotation_api(*args, **kwargs):
            local_call_count[0] += 1
            raise ConnectionError("Local connection failed")

        def cloud_call_annotation_api(*args, **kwargs):
            cloud_call_count[0] += 1
            result = create_mock_foreshadowing()
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="{}", reasoning_content="thinking"))]
            return result, response

        local_client._call_annotation_api = local_call_annotation_api
        cloud_client._call_annotation_api = cloud_call_annotation_api

        result = local_client._annotate_chunk_phase2(
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
        )

        self.assertEqual(local_call_count[0], PHASE_MAX_RETRIES)
        self.assertEqual(cloud_call_count[0], 1)
        self.assertIsInstance(result, ForeshadowingResult)

    def test_phase2_all_retries_exhausted(self):
        """Phase2 本地和云端都失败"""
        local_client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        def always_fail(*args, **kwargs):
            raise ConnectionError("Connection failed")

        local_client._call_annotation_api = always_fail
        cloud_client._call_annotation_api = always_fail

        with self.assertRaises(Phase2MaxRetriesExceededError):
            local_client._annotate_chunk_phase2(
                text="测试文本",
                chunk_id=1,
                cloud_client=cloud_client,
            )


class TestTwoPhaseIntegration(unittest.TestCase):
    """
    双次调用集成测试

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Phase1/Phase2独立重试机制
    """

    @patch('src.models.local.annotation_client.settings')
    def test_two_phase_serial_passes_cloud_client(self, mock_settings):
        """串行模式传递 cloud_client 参数"""
        mock_settings.analysis.two_phase_annotation.parallel = False
        mock_settings.analysis.two_phase_annotation.enabled = True

        client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        phase1_cloud_received = [None]
        phase2_cloud_received = [None]

        def mock_phase1(*args, **kwargs):
            phase1_cloud_received[0] = kwargs.get('cloud_client')
            return create_mock_annotation()

        def mock_phase2(*args, **kwargs):
            phase2_cloud_received[0] = kwargs.get('cloud_client')
            return create_mock_foreshadowing()

        client._annotate_chunk_phase1 = mock_phase1
        client._annotate_chunk_phase2 = mock_phase2

        result = client._annotate_chunk_two_phase(
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
        )

        self.assertIs(phase1_cloud_received[0], cloud_client)
        self.assertIs(phase2_cloud_received[0], cloud_client)
        self.assertIsInstance(result.annotation, ChunkAnnotation)

    @patch('src.models.local.annotation_client.settings')
    def test_two_phase_parallel_passes_cloud_client(self, mock_settings):
        """并行模式传递 cloud_client 参数"""
        mock_settings.analysis.two_phase_annotation.parallel = True
        mock_settings.analysis.two_phase_annotation.enabled = True

        client = MockAnnotationClient()
        cloud_client = MockAnnotationClient()

        phase1_cloud_received = [None]
        phase2_cloud_received = [None]

        def mock_phase1(*args, **kwargs):
            phase1_cloud_received[0] = kwargs.get('cloud_client')
            return create_mock_annotation()

        def mock_phase2(*args, **kwargs):
            phase2_cloud_received[0] = kwargs.get('cloud_client')
            return create_mock_foreshadowing()

        client._annotate_chunk_phase1 = mock_phase1
        client._annotate_chunk_phase2 = mock_phase2

        result = client._annotate_chunk_two_phase(
            text="测试文本",
            chunk_id=1,
            cloud_client=cloud_client,
        )

        self.assertIs(phase1_cloud_received[0], cloud_client)
        self.assertIs(phase2_cloud_received[0], cloud_client)
        self.assertIsInstance(result.annotation, ChunkAnnotation)


if __name__ == "__main__":
    unittest.main()
