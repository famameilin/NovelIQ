import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.cloud.client import ConfiguredCloudModelClient, NullCloudModelClient


def create_mock_stream_response(content: str):
    chunk_size = 50
    for i in range(0, len(content), chunk_size):
        chunk_content = content[i : i + chunk_size]
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
        analysis = client.diagnose({"summary": "test"})
        payload = analysis.to_dict()
        self.assertIn("foreshadow_rate", payload)

    def test_configured_client(self) -> None:
        content = json.dumps(
            {
                "novel_id": "n1",
                "foreshadow_rate": 0.5,
                "arc_scores": [0.1],
                "narrative_type": "three-act",
                "topic_labels": ["growth"],
                "diagnosis": "ok",
            }
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = create_mock_stream_response(content)

        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = ConfiguredCloudModelClient(config, client=mock_client)

        analysis = client.diagnose({"novel_id": "n1", "summary": "test"})

        self.assertEqual(analysis.novel_id, "n1")
        self.assertEqual(analysis.foreshadow_rate, 0.5)
        self.assertEqual(analysis.topic_labels, ["growth"])

    def test_configured_client_disambiguate_delegates(self) -> None:
        mock_client = MagicMock()
        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = ConfiguredCloudModelClient(config, client=mock_client)

        expected_alias_map = {"alias_a": "zhangsan"}
        fake_result = MagicMock(merge_target_map=expected_alias_map)

        with patch.object(client._disambiguation_client, "disambiguate_characters", return_value=fake_result) as mock_disambiguate:
            result = client.disambiguate_characters(
                candidates=["zhangsan", "alias_a"],
                context_sentences={"alias_a": "alias_a smiled"},
                existing_names=["zhangsan"],
            )

        self.assertEqual(result, expected_alias_map)
        mock_disambiguate.assert_called_once_with(
            candidates=["zhangsan", "alias_a"],
            context_sentences={"alias_a": "alias_a smiled"},
            existing_names=["zhangsan"],
        )


if __name__ == "__main__":
    unittest.main()
