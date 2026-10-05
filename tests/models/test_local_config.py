import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import Settings, TaskModelConfig, load_task_config


class TestTaskModelConfigFromEnv(unittest.TestCase):
    def test_from_env_with_all_values(self) -> None:
        """
        2026-08-08 用于验证 Settings 从平铺模型变量加载连接信息
        """

        env_vars = {
            "MODEL_POOL": json.dumps([{"base_url": "https://api.example.com/v1", "model_id": "text-model",
                                       "api_key": "text-key", "weight": 1, "max_in_flight": 3}]),
            "DIAGNOSIS_MODEL_ID": "text-model",
            "EMBEDDING_MODEL_BASE_URL": "http://localhost:8080/v1",
            "EMBEDDING_MODEL_ID": "embedding-model",
            "EMBEDDING_MODEL_KEY": "sk-no-key-required",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            new_settings = Settings.from_env()
            self.assertEqual(new_settings.models.model_pool[0].model_id, "text-model")
            self.assertEqual(new_settings.models.model_pool[0].max_in_flight, 3)
            self.assertEqual(new_settings.models.diagnosis_model_id, "text-model")
            self.assertEqual(new_settings.models.paragraph_embedding.model, "embedding-model")


class TestTaskModelConfigValidate(unittest.TestCase):
    def test_validate_missing_base_url_raises(self) -> None:
        config = TaskModelConfig(model="test-model")
        with self.assertRaises(ValueError) as ctx:
            config.validate()
        self.assertIn("base_url 不能为空", str(ctx.exception))

    def test_validate_missing_model_raises(self) -> None:
        config = TaskModelConfig(base_url="http://localhost:8000/v1")
        with self.assertRaises(ValueError) as ctx:
            config.validate()
        self.assertIn("model 不能为空", str(ctx.exception))


class TestLoadTaskConfig(unittest.TestCase):
    def test_load_invalid_task_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_task_config("invalid_task")  # type: ignore


if __name__ == "__main__":
    unittest.main()
