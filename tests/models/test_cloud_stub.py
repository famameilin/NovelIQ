import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.cloud.client import ConfiguredCloudModelClient, NullCloudModelClient


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


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
        analysis = asyncio.run(client.diagnose({"summary": "test"}))
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

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=content))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = ConfiguredCloudModelClient(config, client=mock_client)

        analysis = asyncio.run(client.diagnose({"novel_id": "n1", "summary": "test"}))

        self.assertEqual(analysis.novel_id, "n1")
        self.assertEqual(analysis.foreshadow_rate, 0.5)
        self.assertEqual(analysis.topic_labels, ["growth"])

    def test_configured_client_disambiguate_delegates(self) -> None:
        mock_client = MagicMock()
        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = ConfiguredCloudModelClient(config, client=mock_client)

        expected_canonical_decisions = {"alias_a": "zhangsan"}
        fake_result = MagicMock(canonical_decisions=expected_canonical_decisions)

        with patch.object(
            client._disambiguation_client, "disambiguate_characters", return_value=fake_result
        ) as mock_disambiguate:
            result = asyncio.run(
                client.disambiguate_characters(
                    candidates=_candidates("zhangsan", "alias_a"),
                    context_sentences={"alias_a": "alias_a smiled"},
                    existing_names=["zhangsan"],
                )
            )

        self.assertEqual(result, expected_canonical_decisions)
        mock_disambiguate.assert_called_once_with(
            candidates=_candidates("zhangsan", "alias_a"),
            context_sentences={"alias_a": "alias_a smiled"},
            existing_names=["zhangsan"],
            prompt_context=None,
        )


if __name__ == "__main__":
    unittest.main()
