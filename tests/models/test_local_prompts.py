"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 本地模型提示词测试

修改时间: 2026-03-16
修改者: TraeAI
任务: 修复 Mock 配置
修改内容: 使用依赖注入 instructor_client_factory，避免 instructor 内部检查

修改时间: 2026-03-16
修改者: TraeAI
任务: 修复 Mock 配置问题
修改内容: 直接检查 _build_messages 的结果，而不是通过 mock 调用参数
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.local.unified_client import UnifiedModelClient
from src.models.local.schema import ForeshadowingResult, DisambiguateResponseModel


class MockInstructorClient:
    """
    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 修复 Mock 配置
    说明: 模拟 instructor 包装后的客户端，直接返回结构化结果，绕过 instructor 内部处理
    """

    def __init__(self, return_value):
        self._return_value = return_value

    class ChatCompletions:
        def __init__(self, return_value):
            self._return_value = return_value

        def create(self, **kwargs):
            # 直接返回预期的结果对象，绕过 instructor 内部处理
            return self._return_value

        def create_with_completion(self, **kwargs):
            # 返回元组 (result, completion)
            mock_completion = MagicMock()
            mock_completion.choices = [MagicMock()]
            mock_completion.choices[0].message.refusal = None
            return (self._return_value, mock_completion)

    @property
    def chat(self):
        class Chat:
            def __init__(self, return_value):
                self.completions = MockInstructorClient.ChatCompletions(return_value)
        return Chat(self._return_value)


class TestLocalPrompts(unittest.TestCase):
    def test_annotate_chunk_includes_system_prompt(self) -> None:
        """
        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 修复 Mock 配置问题
        修改内容: 直接检查 _build_messages 的结果，而不是通过 mock 调用参数
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )

        client = UnifiedModelClient(
            task_type="annotation",
            config=config,
        )

        # 直接检查 _build_messages 构建的消息
        messages = client._annotation_client._build_messages("测试文本")

        system_messages = [m for m in messages if m.get("role") == "system"]
        self.assertGreater(len(system_messages), 0)
        self.assertIn("网文标注系统", system_messages[0].get("content", ""))

    def test_annotate_chunk_includes_few_shot_examples(self) -> None:
        """
        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 修复 Mock 配置问题
        修改内容: 直接检查 _build_messages 的结果，而不是通过 mock 调用参数
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )

        client = UnifiedModelClient(
            task_type="annotation",
            config=config,
        )

        # 直接检查 _build_messages 构建的消息
        messages = client._annotation_client._build_messages("测试文本")

        user_messages = [m for m in messages if m.get("role") == "user"]
        # 至少有1个用户消息（待分析文本）+ few-shot examples中的用户消息
        self.assertGreater(len(user_messages), 1)

    def test_disambiguate_characters_includes_system_prompt(self) -> None:
        """
        修改时间: 2026-03-17
        修改者: TraeAI
        任务: 移除 Instructor 依赖
        修改内容: 直接检查 _build_disambiguate_messages 的结果
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()

        client = UnifiedModelClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )

        # 直接检查 _build_disambiguate_messages 构建的消息
        messages = client._disambiguation_client._build_disambiguate_messages(["张三"])

        system_messages = [m for m in messages if m.get("role") == "system"]
        self.assertGreater(len(system_messages), 0)
        self.assertIn("人名消歧系统", system_messages[0].get("content", ""))


if __name__ == "__main__":
    unittest.main()
