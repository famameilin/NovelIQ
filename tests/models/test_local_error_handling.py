import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

import openai

from src.config import TaskModelConfig
from src.models.local.annotation_client import Phase1MaxRetriesExceededError
from src.models.local.unified_client import UnifiedModelClient


class TestErrorHandling(unittest.TestCase):
    def test_connection_error_raises_phase1_max_retries_error(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        with self.assertRaises(Phase1MaxRetriesExceededError) as ctx:
            client.annotate_chunk("测试文本")
        self.assertIn("Connection error", str(ctx.exception))

    def test_timeout_error_raises_phase1_max_retries_error(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
            timeout_s=30.0,
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APITimeoutError(request=MagicMock())
        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        with self.assertRaises(Phase1MaxRetriesExceededError) as ctx:
            client.annotate_chunk("测试文本")
        self.assertIn("Request timed out", str(ctx.exception))

    def test_api_status_error_raises_phase1_max_retries_error(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIStatusError(
            message="Internal Server Error",
            response=mock_response,
            body={},
        )
        client = UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        with self.assertRaises(Phase1MaxRetriesExceededError) as ctx:
            client.annotate_chunk("测试文本")
        self.assertIn("Internal Server Error", str(ctx.exception))

    def test_disambiguate_connection_error_raises_connection_error(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(request=MagicMock())
        client = UnifiedModelClient(task_type="incremental_disambig", config=config, client=mock_client)
        with self.assertRaises(ConnectionError):
            client.disambiguate_characters(["张三"])

    def test_annotate_without_model_raises_value_error(self) -> None:
        config = TaskModelConfig(base_url="http://test:8000/v1", model=None)
        mock_client = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            UnifiedModelClient(task_type="annotation", config=config, client=mock_client)
        self.assertIn("model 不能为空", str(ctx.exception))

    def test_disambiguate_without_model_raises_value_error(self) -> None:
        config = TaskModelConfig(base_url="http://test:8000/v1", model=None)
        mock_client = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            UnifiedModelClient(task_type="incremental_disambig", config=config, client=mock_client)
        self.assertIn("model 不能为空", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
