import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import load_task_config


class TestDiagnosisConfig(unittest.TestCase):
    def test_load_diagnosis_config(self) -> None:
        config = load_task_config("diagnosis")
        self.assertIsNotNone(config.base_url)
        self.assertIsNotNone(config.model)


if __name__ == "__main__":
    unittest.main()
