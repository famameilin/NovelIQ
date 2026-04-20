import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig, load_task_config


class TestDiagnosisConfig(unittest.TestCase):
    def test_load_diagnosis_config(self) -> None:
        config = load_task_config("diagnosis")
        self.assertIsNotNone(config.base_url)
        self.assertIsNotNone(config.model)

    def test_diagnosis_config_validate(self) -> None:
        config = TaskModelConfig(
            base_url="http://example.com",
            model="gpt-test",
            api_key="test-key",
            timeout_s=10,
        )
        config.validate()
        self.assertEqual(config.base_url, "http://example.com")
        self.assertEqual(config.model, "gpt-test")
        self.assertEqual(config.timeout_s, 10)


if __name__ == "__main__":
    unittest.main()
