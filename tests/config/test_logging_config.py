import sys
from pathlib import Path
import tempfile
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from loguru import logger
from src.config.logging_config import LoggingConfig, setup_logging


class TestLoggingConfig(unittest.TestCase):
    def setUp(self) -> None:
        logger.remove()

    def tearDown(self) -> None:
        logger.remove()

    def test_setup_logging_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "app.log"
            config = LoggingConfig(level="DEBUG", log_file=log_path, console=False)
            file_handler_id, console_file_handler_id = setup_logging(config)
            logger.info("test-message")
            if file_handler_id >= 0:
                logger.remove(file_handler_id)
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("test-message", content)

    def test_setup_logging_verbose_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "app.log"
            config = LoggingConfig(level="DEBUG", log_file=log_path, console=True)
            file_handler_id, console_file_handler_id = setup_logging(config, verbose=True)
            logger.info("verbose-test-message")
            if file_handler_id >= 0:
                logger.remove(file_handler_id)
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("verbose-test-message", content)

    def test_setup_logging_debug_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "app.log"
            config = LoggingConfig(level="DEBUG", log_file=log_path, console=True)
            file_handler_id, console_file_handler_id = setup_logging(config, debug=True)
            logger.debug("debug-test-message")
            if file_handler_id >= 0:
                logger.remove(file_handler_id)
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("debug-test-message", content)
    
    def test_setup_logging_console_file(self) -> None:
        """
        测试终端日志文件功能
        
        创建时间: 2026-03-12
        创建者: TraeAI
        任务: 添加终端日志文件支持
        """
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "app.log"
            console_log_path = Path(tmp) / "console.log"
            config = LoggingConfig(
                level="DEBUG",
                log_file=log_path,
                console=True,
                console_log_file=console_log_path,
            )
            file_handler_id, console_file_handler_id = setup_logging(config, verbose=True)
            logger.info("console-test-message")
            if file_handler_id >= 0:
                logger.remove(file_handler_id)
            if console_file_handler_id >= 0:
                logger.remove(console_file_handler_id)
            
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("console-test-message", content)
            
            console_content = console_log_path.read_text(encoding="utf-8")
            self.assertIn("console-test-message", console_content)

    def test_logging_config_from_file(self) -> None:
        config = LoggingConfig.from_file()
        self.assertEqual(config.level, "DEBUG")
        self.assertTrue(config.console)


if __name__ == "__main__":
    unittest.main()
