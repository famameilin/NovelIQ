import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import Settings, TaskModelConfig, load_task_config


class TestTaskModelConfigFromFile(unittest.TestCase):
    def test_load_task_config_annotation(self) -> None:
        config = load_task_config("annotation")
        self.assertIsNotNone(config.base_url)
        self.assertIsNotNone(config.model)


class TestTaskModelConfigFromEnv(unittest.TestCase):
    def test_from_env_with_all_values(self) -> None:
        """
        2026-08-08 用于验证 Settings 从平铺模型变量加载连接信息
        """

        env_vars = {
            "MODEL_BASE_URL": "https://api.example.com/v1",
            "MODEL_ID": "shared-text-model",
            "MODEL_KEY": "text-key",
            "EMBEDDING_MODEL_BASE_URL": "http://localhost:8080/v1",
            "EMBEDDING_MODEL_ID": "embedding-model",
            "EMBEDDING_MODEL_KEY": "sk-no-key-required",
            "ANNOTATION_MODEL": "legacy-model",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            new_settings = Settings.from_env()
            self.assertEqual(new_settings.models.annotation.model, "shared-text-model")
            self.assertEqual(new_settings.models.diagnosis.model, "shared-text-model")
            self.assertEqual(new_settings.models.paragraph_embedding.model, "embedding-model")


class TestTaskModelConfigValidate(unittest.TestCase):
    def test_validate_valid_config(self) -> None:
        config = TaskModelConfig(
            base_url="http://localhost:8000/v1",
            model="test-model",
            timeout_s=30.0,
        )
        config.validate()

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
    def test_load_annotation_config(self) -> None:
        config = load_task_config("annotation")
        self.assertIsNotNone(config.base_url)
        self.assertIsNotNone(config.model)

    def test_load_diagnosis_config(self) -> None:
        config = load_task_config("diagnosis")
        self.assertIsNotNone(config.base_url)
        self.assertIsNotNone(config.model)

    def test_load_invalid_task_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_task_config("invalid_task")  # type: ignore


if __name__ == "__main__":
    unittest.main()
