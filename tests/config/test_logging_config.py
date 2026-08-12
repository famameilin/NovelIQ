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


def test_setup_logging_module_files_match_real_src_namespaces() -> None:
    """
    2026-08-12 用于验证模块文件 sink 使用真实命名空间前缀（src.*）：
    settings.json 的模块键与 loguru 实际 record name 前缀一致，模块日志才会写入文件。
    loguru 的 record name 取自调用帧，测试通过 patch 显式模拟真实 src 前缀。
    """
    with tempfile.TemporaryDirectory() as tmp:
        config = LoggingSettings(
            console_level="INFO",
            log_dir=tmp,
            modules={
                "src.config": LoggingModuleSettings(file="config.log", level="DEBUG"),
                "src.workflows": LoggingModuleSettings(file="workflow.log", level="DEBUG"),
            },
        )
        setup_logging(config)
        src_logger = logger.patch(lambda record: record.update(name="src.config.logging_setup"))
        workflow_logger = logger.patch(lambda record: record.update(name="src.workflows.annotate"))
        src_logger.info("src-namespace-message")
        workflow_logger.info("workflow-namespace-message")
        config_content = (Path(tmp) / "config.log").read_text(encoding="utf-8")
        workflow_content = (Path(tmp) / "workflow.log").read_text(encoding="utf-8")
        logger.remove()
        assert "src-namespace-message" in config_content
        assert "src-namespace-message" not in workflow_content
        assert "workflow-namespace-message" in workflow_content


def test_console_sinks_separate_project_and_third_party(capsys) -> None:
    """
    2026-08-12 用于验证控制台双 sink 分工：
    src.* 第一方日志按 console_level 输出；第三方日志按 third_party_level 输出，
    不再出现第一方日志被过滤、第三方日志重复输出的问题。
    """
    with tempfile.TemporaryDirectory() as tmp:
        config = LoggingSettings(
            console_level="INFO",
            third_party_level="WARNING",
            log_dir=tmp,
        )
        setup_logging(config)
        project_logger = logger.patch(lambda record: record.update(name="src.api.routes.results"))
        project_logger.info("project-info-message")
        third_party_logger = logger.patch(lambda record: record.update(name="sqlalchemy.engine"))
        third_party_logger.warning("third-party-warning-message")
        third_party_logger.info("third-party-info-message")
        logger.remove()

    captured = capsys.readouterr()
    assert "project-info-message" in captured.err
    assert "third-party-warning-message" in captured.err
    assert "third-party-info-message" not in captured.err


if __name__ == "__main__":
    unittest.main()
