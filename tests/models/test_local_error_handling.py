"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 本地模型错误处理测试

修改时间: 2026-03-16
修改者: TraeAI
任务: 更新测试用例适配新架构
修改内容: 适配 LiteLLM 异常类型，将 openai 异常替换为 litellm 异常

修改时间: 2026-04-24
任务: fix-structured-output-review-findings
修改内容: 移除 Instructor 工厂 mock，测试直接注入 OpenAI-compatible mock client

修改时间: 2026-04-24
任务: fix-async-unittest-error-handling-tests
修改内容: 将 unittest.TestCase 中的 async 测试改为同步方法显式 asyncio.run，确保 pytest 真正执行断言

修改时间: 2026-03-16
修改者: TraeAI
任务: 修复测试耗时问题
修改内容: 直接 Mock litellm.completion 而非使用 LiteLLM 类，避免内部重试"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.annotation import Phase1MaxRetriesExceededError
from src.models.local.schema import ForeshadowingResult


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


def _create_foreshadowing_result() -> ForeshadowingResult:
    return ForeshadowingResult(
        has_foreshadowing=False,
        foreshadowing_type=None,
        anchor_text="",
        anchor_reason="",
        confidence="high",
    )


class TestErrorHandling(unittest.TestCase):
    def test_connection_error_raises_phase1_max_retries_error(self) -> None:
        """
        修改时间: 2026-04-24
        任务: fix-structured-output-review-findings
        修改内容: Instructor 参数已移除，测试改为直接注入 mock client。

        修改时间: 2026-04-24
        任务: fix-async-unittest-error-handling-tests
        修改内容: unittest 测试方法改为同步入口，内部用 asyncio.run 执行异步标注调用。
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        error = ConnectionError("Connection error")
        mock_client.chat.completions.create.side_effect = error
        mock_client.chat.completions.create_with_completion.side_effect = error

        client = AnnotationClient(
            task_type="annotation",
            config=config,
            client=mock_client,
        )
        with self.assertRaises(Phase1MaxRetriesExceededError) as ctx:
            asyncio.run(client.annotate_chunk("测试文本"))
        self.assertIn("Connection error", str(ctx.exception))

    def test_timeout_error_raises_phase1_max_retries_error(self) -> None:
        """
        修改时间: 2026-04-24
        任务: fix-structured-output-review-findings
        修改内容: Instructor 参数已移除，测试改为直接注入 mock client。

        修改时间: 2026-04-24
        任务: fix-async-unittest-error-handling-tests
        修改内容: unittest 测试方法改为同步入口，内部用 asyncio.run 执行异步标注调用。
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
            timeout_s=30.0,
        )
        mock_client = MagicMock()
        error = TimeoutError("Request timed out")
        mock_client.chat.completions.create.side_effect = error
        mock_client.chat.completions.create_with_completion.side_effect = error

        client = AnnotationClient(
            task_type="annotation",
            config=config,
            client=mock_client,
        )
        with self.assertRaises(Phase1MaxRetriesExceededError) as ctx:
            asyncio.run(client.annotate_chunk("测试文本"))
        self.assertIn("Request timed out", str(ctx.exception))

    def test_api_status_error_raises_phase1_max_retries_error(self) -> None:
        """
        修改时间: 2026-04-24
        任务: fix-structured-output-review-findings
        修改内容: Instructor 参数已移除，测试改为直接注入 mock client。

        修改时间: 2026-04-24
        任务: fix-async-unittest-error-handling-tests
        修改内容: unittest 测试方法改为同步入口，内部用 asyncio.run 执行异步标注调用。
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        error = RuntimeError("Internal Server Error")
        mock_client.chat.completions.create.side_effect = error
        mock_client.chat.completions.create_with_completion.side_effect = error

        client = AnnotationClient(
            task_type="annotation",
            config=config,
            client=mock_client,
        )
        with self.assertRaises(Phase1MaxRetriesExceededError) as ctx:
            asyncio.run(client.annotate_chunk("测试文本"))
        self.assertIn("Internal Server Error", str(ctx.exception))

    def test_disambiguate_connection_error_raises_connection_error(self) -> None:
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖
        修改内容: 直接 Mock mock_client.chat.completions.create

        修改时间: 2026-04-09
        修改者: TraeAI
        任务: 修复异步测试问题
        修改内容: 添加 @patch 装饰器来 Mock call_disambiguate_api，避免调用异步方法
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )

        mock_client = MagicMock()

        client = DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )

        with patch("src.models.disambiguation.call_disambiguate_api") as mock_api:
            mock_api.side_effect = ConnectionError("Connection error")
            with self.assertRaises(ConnectionError):
                asyncio.run(client.disambiguate_characters(_candidates("张三")))

    def test_annotate_without_model_raises_value_error(self) -> None:
        config = TaskModelConfig(base_url="http://test:8000/v1", model=None)
        mock_client = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            AnnotationClient(task_type="annotation", config=config, client=mock_client)
        self.assertIn("model 不能为空", str(ctx.exception))

    def test_disambiguate_without_model_raises_value_error(self) -> None:
        config = TaskModelConfig(base_url="http://test:8000/v1", model=None)
        mock_client = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            DisambiguationClient(task_type="incremental_disambig", config=config, client=mock_client)
        self.assertIn("model 不能为空", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
