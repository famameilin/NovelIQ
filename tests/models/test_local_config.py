import json
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
        2026-08-03 用于验证 Settings 只从两个模型 JSON 对象加载连接信息
        """

        env_vars = {
            "MODEL": json.dumps(
                {
                    "base_url": "https://api.example.com/v1",
                    "model": "shared-text-model",
                    "api_key": "text-key",
                }
            ),
            "EMBEDDING_MODEL": json.dumps(
                {
                    "base_url": "http://localhost:8080/v1",
                    "model": "embedding-model",
                    "api_key": "sk-no-key-required",
                }
            ),
            "CHUNK_MAX_CHARS": "3000",
            "CHUNK_OVERLAP": "150",
            "ANNOTATION_MODEL": "legacy-model",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            new_settings = Settings.from_env()
            self.assertEqual(new_settings.models.annotation.model, "shared-text-model")
            self.assertEqual(new_settings.models.diagnosis.model, "shared-text-model")
            self.assertEqual(new_settings.models.paragraph_embedding.model, "embedding-model")
            self.assertEqual(new_settings.chunking.max_chars, 2000)
            self.assertEqual(new_settings.chunking.start_chars, 4000)


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
