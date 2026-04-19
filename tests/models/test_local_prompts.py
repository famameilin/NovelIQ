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

修改时间: 2026-03-18
修改者: TraeAI
任务: 移除已废弃的内部方法测试
修改内容: _build_messages 和 _build_disambiguate_messages 方法已移除，简化测试
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient


class TestLocalPrompts(unittest.TestCase):
    def test_phase_prompts_declare_shared_evidence_priority_rules(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        phase1_prompt = (repo_root / "config" / "prompts" / "phase1.txt").read_text(encoding="utf-8")
        disambig_prompt = (repo_root / "config" / "prompts" / "disambiguate.txt").read_text(encoding="utf-8")
        phase3_prompt = (repo_root / "config" / "prompts" / "phase3.txt").read_text(encoding="utf-8")
        phase4_prompt = (repo_root / "config" / "prompts" / "phase4.txt").read_text(encoding="utf-8")

        self.assertIn("当前文本中明确出现的事实 > 显式输入", phase1_prompt)
        self.assertIn("不得仅凭共享证据把未在 <Current_Chunk> 中逐字出现的人写入 characters", phase1_prompt)
        self.assertIn("图谱提示、共享 evidence 和历史召回只能作为支持证据", disambig_prompt)
        self.assertIn("当前文本里明确出现的说话动作、称呼关系、自报身份", phase3_prompt)
        self.assertIn("关系 evidence 必须落在当前文本原句上", phase4_prompt)

    def test_annotation_client_initialization(self) -> None:
        """测试标注客户端能正确初始化"""
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )

        client = AnnotationClient(
            task_type="annotation",
            config=config,
        )

        # 验证客户端已初始化
        self.assertIsNotNone(client._client)

    def test_disambiguation_client_initialization(self) -> None:
        """测试消歧客户端能正确初始化"""
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        mock_client = MagicMock()

        client = DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=mock_client,
        )

        # 验证客户端已初始化
        self.assertIsNotNone(client._client)


if __name__ == "__main__":
    unittest.main()
