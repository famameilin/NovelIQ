import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import SemanticChunker, Chunk


class TestSemanticChunker(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_embedding_client = MagicMock()

    def test_chunk_text_semantic_basic(self) -> None:
        self.mock_embedding_client.get_embedding.return_value = [0.1] * 10
        self.mock_embedding_client.compute_similarity.return_value = 0.8

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "第一段内容。" * 100 + "\n\n" + "第二段内容。" * 100
        chunks = chunker.chunk_text_semantic(text, threshold=0.7, max_chars=2000)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertIsInstance(chunk, Chunk)
            self.assertTrue(len(chunk.text) > 0)

    def test_chunk_text_semantic_with_chapter_boundary(self) -> None:
        self.mock_embedding_client.get_embedding.return_value = [0.1] * 10
        self.mock_embedding_client.compute_similarity.return_value = 0.9

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "第一章 开始\n" + "内容。" * 500 + "\n\n第二章 继续\n" + "更多内容。" * 500
        chunks = chunker.chunk_text_semantic(text, threshold=0.7, max_chars=3000)

        chapter_titles = [c.chapter_title for c in chunks if c.chapter_title]
        self.assertTrue(len(chapter_titles) >= 2)

    def test_chunk_text_semantic_max_length_limit(self) -> None:
        self.mock_embedding_client.get_embedding.return_value = [0.1] * 10
        self.mock_embedding_client.compute_similarity.return_value = 0.99

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        paragraphs = "\n\n".join(["内容。" * 100 for _ in range(20)])
        chunks = chunker.chunk_text_semantic(paragraphs, threshold=0.7, max_chars=1000)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 6000)

    def test_chunk_text_semantic_low_similarity_boundary(self) -> None:
        call_count = [0]

        def mock_similarity(v1, v2):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return 0.5
            return 0.9

        self.mock_embedding_client.get_embedding.return_value = [0.1] * 10
        self.mock_embedding_client.compute_similarity = mock_similarity

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "段落一内容。" * 50 + "\n\n" + "段落二内容。" * 50 + "\n\n" + "段落三内容。" * 50
        chunks = chunker.chunk_text_semantic(text, threshold=0.7, max_chars=5000)

        self.assertTrue(len(chunks) >= 1)

    def test_chunk_text_semantic_empty_text(self) -> None:
        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        chunks = chunker.chunk_text_semantic("", threshold=0.7, max_chars=2000)
        self.assertEqual(len(chunks), 0)


if __name__ == "__main__":
    unittest.main()
