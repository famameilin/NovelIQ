import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import settings
from src.config.schemas.model import WeightedModelSettings
from src.model_pool.configuration import load_task_config


class TestDiagnosisConfig(unittest.TestCase):
    def test_load_diagnosis_config(self) -> None:
        pool = [WeightedModelSettings("diagnosis", "https://diagnosis.example/v1", "test-key", max_in_flight=2)]
        with (
            patch.object(settings.models, "model_pool", pool),
            patch.object(
                settings.models,
                "diagnosis_model_id",
                "diagnosis",
            ),
        ):
            config = load_task_config("diagnosis")
            self.assertEqual(config.base_url, "https://diagnosis.example/v1")
            self.assertEqual(config.model, "diagnosis")
            self.assertEqual(config.max_in_flight, 2)


if __name__ == "__main__":
    unittest.main()
