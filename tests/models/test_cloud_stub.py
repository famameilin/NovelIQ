import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import TaskModelConfig
from src.models.cloud import NullCloudModelClient
from src.models.diagnosis import DiagnosisClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.disambiguation import DisambiguationPromptContext
from src.models.local.schema import DisambiguateResponseModel
from src.workflows.retry_utils import MaxRetriesExceededError


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
        self.assertIn("foreshadow_expectation", payload)

    def test_diagnosis_client(self) -> None:
        content = json.dumps(
            {
                "novel_id": "n1",
                "foreshadow_expectation": 0.5,
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
        client = DiagnosisClient(config, client=mock_client)

        analysis = asyncio.run(client.diagnose({"novel_id": "n1", "summary": "test"}))

        self.assertEqual(analysis.novel_id, "n1")
        self.assertEqual(analysis.foreshadow_expectation, 0.5)
        self.assertEqual(analysis.topic_labels, ["growth"])

    def test_diagnosis_failed_parse_still_records_token_usage(self) -> None:
        """诊断响应已返回但 JSON 解析失败时，仍应记录 token。"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="not-json"))]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        recorded_calls: list[dict[str, object]] = []

        def token_usage_callback(
            novel_id: str,
            task_type: str,
            call_type: str,
            model: str,
            prompt_tokens: int,
            total_tokens: int,
            completion_tokens: int | None,
            chunk_id: int | None,
        ) -> None:
            recorded_calls.append(
                {
                    "novel_id": novel_id,
                    "task_type": task_type,
                    "call_type": call_type,
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": total_tokens,
                    "completion_tokens": completion_tokens,
                    "chunk_id": chunk_id,
                }
            )

        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = DiagnosisClient(
            config,
            client=mock_client,
            token_usage_callback=token_usage_callback,
            novel_id="n1",
        )

        with patch("src.models.diagnosis.settings") as mock_settings:
            mock_settings.runtime.diagnosis.max_retries = 1
            with self.assertRaises(MaxRetriesExceededError):
                asyncio.run(
                    client.diagnose(
                        {
                            "novel_id": "n1",
                            "messages": [{"role": "user", "content": "请输出 JSON"}],
                        }
                    )
                )

        self.assertEqual(len(recorded_calls), 1)
        self.assertEqual(recorded_calls[0]["task_type"], "diagnosis")
        self.assertEqual(recorded_calls[0]["call_type"], "diagnosis")
        self.assertGreater(recorded_calls[0]["prompt_tokens"], 0)

    def test_disambiguation_client_disambiguate_delegates(self) -> None:
        mock_client = MagicMock()
        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = DisambiguationClient(config=config, client=mock_client)

        expected_canonical_decisions = {"alias_a": "zhangsan"}
        fake_response = DisambiguateResponseModel(canonical_decisions=expected_canonical_decisions)

        with patch(
            "src.models.disambiguation.call_disambiguate_api",
            new=AsyncMock(return_value=fake_response),
        ) as mock_call:
            result = asyncio.run(
                client.disambiguate_characters(
                    candidates=_candidates("zhangsan", "alias_a"),
                    context_sentences={"alias_a": "alias_a smiled"},
                    existing_names=["zhangsan"],
                )
            )

        mock_call.assert_awaited_once()
        self.assertEqual(mock_call.await_args.kwargs["client"], client)
        self.assertEqual(mock_call.await_args.kwargs["config"], client._config)
        self.assertEqual(mock_call.await_args.kwargs["log_type"], "disambiguate_characters")
        self.assertIsInstance(mock_call.await_args.kwargs["messages"], list)
        self.assertGreater(len(mock_call.await_args.kwargs["messages"]), 0)
        self.assertEqual(result.canonical_decisions["alias_a"], expected_canonical_decisions["alias_a"])
        self.assertEqual(result.canonical_decisions["zhangsan"], "zhangsan")

    def test_disambiguation_client_disambiguate_delegates_non_empty_prompt_context(self) -> None:
        mock_client = MagicMock()
        config = TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k")
        client = DisambiguationClient(config=config, client=mock_client)

        prompt_context = DisambiguationPromptContext(
            existing_character_hint="【已存在角色锚点】\n- 张三",
            graph_hint="【图谱已确认的关系】\n- 张三 ←朋友→ 李四",
            shared_evidence_context="<Vector_Evidence>\n[Chunk 7] 灰衣人忽然开口。\n</Vector_Evidence>",
        )
        fake_response = DisambiguateResponseModel(canonical_decisions={"alias_a": "zhangsan"})

        with patch(
            "src.models.disambiguation.call_disambiguate_api",
            new=AsyncMock(return_value=fake_response),
        ) as mock_call:
            asyncio.run(
                client.disambiguate_characters(
                    candidates=_candidates("zhangsan", "alias_a"),
                    context_sentences={"alias_a": "alias_a smiled"},
                    existing_names=["zhangsan"],
                    prompt_context=prompt_context,
                )
            )

        mock_call.assert_awaited_once()
        self.assertIsInstance(mock_call.await_args.kwargs["messages"], list)
        prompt_text = json.dumps(mock_call.await_args.kwargs["messages"], ensure_ascii=False)
        self.assertIn("已存在角色锚点", prompt_text)
        self.assertIn("图谱已确认的关系", prompt_text)
        self.assertIn("Vector_Evidence", prompt_text)


if __name__ == "__main__":
    unittest.main()
