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

    @patch("src.models.local.embedding.openai.OpenAI")
    def test_get_embedding_success(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
        mock_client.embeddings.create.return_value = mock_response

        client = EmbeddingClient(base_url="http://test", model="test-model")
        result = client.get_embedding("测试文本")

        self.assertEqual(result, [0.1, 0.2, 0.3])
        mock_client.embeddings.create.assert_called_once_with(
            model="test-model",
            input="测试文本",
        )

    @patch("src.models.local.embedding.openai.OpenAI")
    def test_get_embedding_empty_text(self, mock_openai_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        client = EmbeddingClient(base_url="http://test", model="test-model")
        result = client.get_embedding("")

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
