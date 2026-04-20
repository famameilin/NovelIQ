"""
创建时间: 2025-03-11
创建者: TraeAI
任务: Embedding客户端测试

修改时间: 2026-03-16
修改者: TraeAI
任务: 更新测试用例适配新架构
修改内容: 适配 LiteLLM，将 openai.OpenAI mock 替换为 litellm.embedding mock

修改时间: 2026-03-21
修改者: TraeAI
任务: migrate-litellm-to-openai-sdk
修改内容: 更新测试用例适配 OpenAI SDK

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容: 更新测试用例，适配 API key 必填的改动

修改时间: 2026-04-20
修改者: Codex (GPT-5)
任务: batch-embedding-requests
修改内容: 补充批量 embedding 请求测试，验证 embed_texts 会按配置批量调用 embeddings.create
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

import numpy as np

from src.models.local.embedding import EmbeddingClient


class TestEmbeddingClient(unittest.IsolatedAsyncioTestCase):
    def test_compute_similarity_identical_vectors(self) -> None:
        vec = [1.0, 2.0, 3.0]
        similarity = EmbeddingClient.compute_similarity(vec, vec)
        self.assertAlmostEqual(similarity, 1.0, places=5)

    def test_compute_similarity_orthogonal_vectors(self) -> None:
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        similarity = EmbeddingClient.compute_similarity(vec1, vec2)
        self.assertAlmostEqual(similarity, 0.0, places=5)

    def test_compute_similarity_opposite_vectors(self) -> None:
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [-1.0, 0.0, 0.0]
        similarity = EmbeddingClient.compute_similarity(vec1, vec2)
        self.assertAlmostEqual(similarity, -1.0, places=5)

    def test_compute_similarity_empty_vectors(self) -> None:
        similarity = EmbeddingClient.compute_similarity([], [])
        self.assertEqual(similarity, 0.0)

    def test_compute_similarity_different_dimensions(self) -> None:
        vec1 = [1.0, 2.0]
        vec2 = [1.0, 2.0, 3.0]
        similarity = EmbeddingClient.compute_similarity(vec1, vec2)
        self.assertEqual(similarity, 0.0)

    def test_compute_similarity_partial_similarity(self) -> None:
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 1.0, 0.0]
        similarity = EmbeddingClient.compute_similarity(vec1, vec2)
        expected = 1.0 / np.sqrt(2)
        self.assertAlmostEqual(similarity, expected, places=5)

    @patch("src.models.local.embedding.AsyncOpenAI")
    async def test_get_embedding_success(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.total_tokens = 20
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        client = EmbeddingClient(
            base_url="http://test",
            model="test-model",
            api_key="test-key",
            embedding_dim=3,
        )
        result = await client.get_embedding("测试文本")

        self.assertEqual(result, [0.1, 0.2, 0.3])
        mock_client.embeddings.create.assert_called_once()

    @patch("src.models.local.embedding.AsyncOpenAI")
    async def test_get_embedding_empty_text(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        client = EmbeddingClient(base_url="http://test", model="test-model", api_key="test-key")
        result = await client.get_embedding("")

        self.assertEqual(result, [])
        mock_client.embeddings.create.assert_not_called()

    @patch("src.models.local.embedding.AsyncOpenAI")
    async def test_get_embedding_raises_on_dimension_mismatch(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_response.usage = None
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        client = EmbeddingClient(
            base_url="http://test",
            model="test-model",
            api_key="test-key",
            embedding_dim=4,
        )

        with self.assertRaisesRegex(ValueError, "embedding dimension mismatch"):
            await client.get_embedding("测试文本")

    @patch("src.models.local.embedding.AsyncOpenAI")
    async def test_embed_texts_batches_requests(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        first_response = MagicMock()
        first_response.data = [
            MagicMock(index=i, embedding=[float(i), float(i) + 0.5]) for i in range(8)
        ]
        first_response.usage = None

        second_response = MagicMock()
        second_response.data = [
            MagicMock(index=i, embedding=[float(i + 8), float(i + 8) + 0.5]) for i in range(2)
        ]
        second_response.usage = None

        mock_client.embeddings.create = AsyncMock(side_effect=[first_response, second_response])

        client = EmbeddingClient(
            base_url="http://test",
            model="test-model",
            api_key="test-key",
            embedding_dim=2,
        )
        result = await client.embed_texts([f"文本{i}" for i in range(10)])

        self.assertEqual(len(result), 10)
        self.assertEqual(result[0], [0.0, 0.5])
        self.assertEqual(result[7], [7.0, 7.5])
        self.assertEqual(result[8], [8.0, 8.5])
        self.assertEqual(result[9], [9.0, 9.5])
        self.assertEqual(mock_client.embeddings.create.await_count, 2)
        self.assertEqual(
            mock_client.embeddings.create.await_args_list[0].kwargs["input"],
            [f"文本{i}" for i in range(8)],
        )
        self.assertEqual(
            mock_client.embeddings.create.await_args_list[1].kwargs["input"],
            [f"文本{i}" for i in range(8, 10)],
        )

    @patch("src.models.local.embedding.AsyncOpenAI")
    async def test_embed_texts_preserves_empty_text_positions(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        response = MagicMock()
        response.data = [
            MagicMock(index=0, embedding=[0.1, 0.2]),
            MagicMock(index=1, embedding=[0.3, 0.4]),
        ]
        response.usage = None
        mock_client.embeddings.create = AsyncMock(return_value=response)

        client = EmbeddingClient(
            base_url="http://test",
            model="test-model",
            api_key="test-key",
            embedding_dim=2,
        )
        result = await client.embed_texts(["有效1", "", "  ", "有效2"])

        self.assertEqual(result, [[0.1, 0.2], [], [], [0.3, 0.4]])
        self.assertEqual(mock_client.embeddings.create.await_count, 1)
        self.assertEqual(mock_client.embeddings.create.await_args.kwargs["input"], ["有效1", "有效2"])


if __name__ == "__main__":
    unittest.main()
