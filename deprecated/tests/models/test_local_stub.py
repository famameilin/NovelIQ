import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.local.unified_client import UnifiedModelClient


class TestLocalStub(unittest.TestCase):
    def test_unified_client_can_be_created(self) -> None:
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        client = UnifiedModelClient(task_type="annotation", config=config)
        self.assertIsNotNone(client)


if __name__ == "__main__":
    unittest.main()
