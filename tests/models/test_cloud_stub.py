"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 云端模型客户端测试

修改时间: 2026-03-17
修改者: TraeAI
任务: 移除 Instructor 依赖
修改内容: 使用 LiteLLM 的 JSON Schema 模式替代 Instructor
"""
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.cloud.client import ConfiguredCloudModelClient, NullCloudModelClient
from src.models.cloud.schema import CloudAnalysis


def create_mock_stream_response(content: str):
    """
    创建模拟的流式 API 响应生成器

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: 适配流式输出模式
    """
    # 将内容分成多个 chunk 模拟流式输出
    chunk_size = 50
    for i in range(0, len(content), chunk_size):
        chunk_content = content[i:i+chunk_size]
        delta = MagicMock()
        delta.content = chunk_content
        delta.reasoning_content = None
        
        choice = MagicMock()
        choice.delta = delta
        
        chunk = MagicMock()
        chunk.choices = [choice]
        
        yield chunk


class TestCloudStub(unittest.TestCase):
    def test_null_client(self) -> None:
        client = NullCloudModelClient()
        analysis = client.diagnose({"summary": "测试"})
        payload = analysis.to_dict()
        self.assertIn("foreshadow_rate", payload)

    def test_configured_client(self) -> None:
        content = json.dumps({
            "novel_id": "n1",
            "foreshadow_rate": 0.5,
            "arc_scores": [0.1],
            "narrative_type": "三幕",
            "topic_labels": ["成长"],
            "diagnosis": "ok",
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = create_mock_stream_response(content)

        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = ConfiguredCloudModelClient(config, client=mock_client)
        
        analysis = client.diagnose({"novel_id": "n1", "summary": "测试"})

        self.assertEqual(analysis.novel_id, "n1")
        self.assertEqual(analysis.foreshadow_rate, 0.5)
        self.assertEqual(analysis.topic_labels, ["成长"])


if __name__ == "__main__":
    unittest.main()
