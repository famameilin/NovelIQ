import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from loguru import logger

from src.config.logging_setup import setup_logging
from src.config.schemas.logging import LoggingModuleSettings, LoggingSettings


class TestLoggingSetup(unittest.TestCase):
    def setUp(self) -> None:
        logger.remove()

    def tearDown(self) -> None:
        logger.remove()

    def test_setup_logging_writes_module_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = LoggingSettings(
                console_level="INFO",
                file_level="DEBUG",
                log_dir=tmp,
                modules={
                    "test_logging_config": LoggingModuleSettings(file="api.log", level="DEBUG"),
                },
            )
            setup_logging(config)
            logger.info("test-module-message")
            content = (Path(tmp) / "api.log").read_text(encoding="utf-8")
            logger.remove()
            self.assertIn("test-module-message", content)

    def test_setup_logging_module_filter_isolates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = LoggingSettings(
                console_level="INFO",
                log_dir=tmp,
                modules={
                    "test_logging_config": LoggingModuleSettings(file="api.log", level="DEBUG"),
                    "src.workflow": LoggingModuleSettings(file="workflow.log", level="DEBUG"),
                },
            )
            setup_logging(config)
            logger.info("workflow-message")
            api_content = (Path(tmp) / "api.log").read_text(encoding="utf-8")
            workflow_content = (Path(tmp) / "workflow.log").read_text(encoding="utf-8")
            logger.remove()
            self.assertIn("workflow-message", api_content)
            self.assertEqual(workflow_content, "")

    def test_setup_logging_uses_configured_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = LoggingSettings(
                console_level="ERROR",
                log_dir=tmp,
                modules={
                    "test_logging_config": LoggingModuleSettings(file="api.log", level="WARNING"),
                },
            )
            setup_logging(config)
            logger.info("should-be-filtered")
            api_content = (Path(tmp) / "api.log").read_text(encoding="utf-8")
            logger.remove()
            self.assertNotIn("should-be-filtered", api_content)


if __name__ == "__main__":
    unittest.main()
