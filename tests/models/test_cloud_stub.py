import sys
from pathlib import Path
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.cloud.client import ConfiguredCloudModelClient, NullCloudModelClient


class TestCloudStub(unittest.TestCase):
    def test_null_client(self) -> None:
        client = NullCloudModelClient()
        analysis = client.diagnose({"summary": "测试"})
        analysis.validate()
        payload = analysis.to_dict()
        self.assertIn("foreshadow_rate", payload)

    def test_configured_client(self) -> None:
        class FakeMessage:
            def __init__(self, content: str) -> None:
                self.content = content

        class FakeChoice:
            def __init__(self, content: str) -> None:
                self.message = FakeMessage(content)

        class FakeResponse:
            def __init__(self, content: str) -> None:
                self.choices = [FakeChoice(content)]

        class FakeCompletions:
            def create(self, model: str, messages: list, **kwargs) -> FakeResponse:
                content = (
                    '{"foreshadow_rate": 0.5, "arc_scores": [0.1], "narrative_type": "三幕", '
                    '"topic_labels": ["成长"], "diagnosis": "ok"}'
                )
                return FakeResponse(content)

        class FakeChat:
            def __init__(self) -> None:
                self.completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self) -> None:
                self.chat = FakeChat()

        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = ConfiguredCloudModelClient(config, client=FakeOpenAI())
        analysis = client.diagnose({"novel_id": "n1", "summary": "测试"})
        self.assertEqual(analysis.novel_id, "n1")
        self.assertEqual(analysis.foreshadow_rate, 0.5)
        self.assertEqual(analysis.topic_labels, ["成长"])


if __name__ == "__main__":
    unittest.main()
