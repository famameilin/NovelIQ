"""
创建时间: 2025-03-11
创建者: TraeAI
任务: Embedding客户端测试

修改时间: 2026-03-16
修改者: TraeAI
任务: 更新测试用例适配新架构
修改内容: 适配 LiteLLM，将 openai.OpenAI mock 替换为 litellm.embedding mock
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

import numpy as np

from src.models.local.embedding import EmbeddingClient


class TestEmbeddingClient(unittest.TestCase):
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

    @patch("src.models.local.embedding.litellm.embedding")
    def test_get_embedding_success(self, mock_embedding: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.total_tokens = 20
        mock_embedding.return_value = mock_response

        client = EmbeddingClient(base_url="http://test", model="test-model")
        result = client.get_embedding("测试文本")

        self.assertEqual(result, [0.1, 0.2, 0.3])
        mock_embedding.assert_called_once()

    @patch("src.models.local.embedding.litellm.embedding")
    def test_get_embedding_empty_text(self, mock_embedding: MagicMock) -> None:
        client = EmbeddingClient(base_url="http://test", model="test-model")
        result = client.get_embedding("")

        self.assertEqual(result, [])
        mock_embedding.assert_not_called()


if __name__ == "__main__":
    unittest.main()
