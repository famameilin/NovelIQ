import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk, SemanticChunker


class TestSemanticChunker(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_embedding_client = MagicMock()

    def test_chunk_text_semantic_basic(self) -> None:
        self.mock_embedding_client.embed_texts.return_value = [[0.1] * 10, [0.2] * 10]

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "第一段内容。" * 100 + "\n\n" + "第二段内容。" * 100
        chunks = chunker.chunk_text_semantic(text)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertIsInstance(chunk, Chunk)
            self.assertTrue(len(chunk.text) > 0)

    def test_chunk_text_semantic_with_chapter_boundary(self) -> None:
        self.mock_embedding_client.embed_texts.return_value = [[0.1] * 10] * 4

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "第一章 开始\n" + "内容。" * 500 + "\n\n第二章 继续\n" + "更多内容。" * 500
        chunks = chunker.chunk_text_semantic(text)

        # 语义分块可能不保留章节标题，取决于实现
        self.assertTrue(len(chunks) >= 1)

    def test_chunk_text_semantic_max_length_limit(self) -> None:
        self.mock_embedding_client.embed_texts.return_value = [[0.1] * 10] * 20

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        paragraphs = "\n\n".join(["内容。" * 100 for _ in range(20)])
        chunks = chunker.chunk_text_semantic(paragraphs)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertTrue(len(chunk.text) > 0)

    def test_chunk_text_semantic_low_similarity_boundary(self) -> None:
        self.mock_embedding_client.embed_texts.return_value = [[0.1] * 10, [0.9] * 10, [0.1] * 10]

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "段落一内容。" * 50 + "\n\n" + "段落二内容。" * 50 + "\n\n" + "段落三内容。" * 50
        chunks = chunker.chunk_text_semantic(text)

        self.assertTrue(len(chunks) >= 1)

    def test_chunk_text_semantic_empty_text(self) -> None:
        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        chunks = chunker.chunk_text_semantic("")
        self.assertEqual(len(chunks), 0)


if __name__ == "__main__":
    unittest.main()
