import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.api.models.events import StreamEvent
from src.chunking.chunker import Chunk, SemanticChunker


class TestSemanticChunker(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.mock_embedding_client = MagicMock()

    async def asyncSetUp(self) -> None:
        async def mock_embed_texts(texts):
            return [[0.1] * 10, [0.2] * 10]

        self.mock_embedding_client.embed_texts = mock_embed_texts

    async def test_chunk_text_semantic_basic(self) -> None:
        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "第一段内容。" * 100 + "\n\n" + "第二段内容。" * 100
        chunks = await chunker.chunk_text_semantic(text)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertIsInstance(chunk, Chunk)
            self.assertTrue(len(chunk.text) > 0)

    async def test_chunk_text_semantic_with_chapter_boundary(self) -> None:
        async def mock_embed_texts(texts):
            return [[0.1] * 10] * 4

        self.mock_embedding_client.embed_texts = mock_embed_texts

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "第一章 开始\n" + "内容。" * 500 + "\n\n第二章 继续\n" + "更多内容。" * 500
        chunks = await chunker.chunk_text_semantic(text)

        self.assertTrue(len(chunks) >= 1)

    async def test_chunk_text_semantic_max_length_limit(self) -> None:
        async def mock_embed_texts(texts):
            return [[0.1] * 10] * 20

        self.mock_embedding_client.embed_texts = mock_embed_texts

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        paragraphs = "\n\n".join(["内容。" * 100 for _ in range(20)])
        chunks = await chunker.chunk_text_semantic(paragraphs)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertTrue(len(chunk.text) > 0)

    async def test_chunk_text_semantic_low_similarity_boundary(self) -> None:
        async def mock_embed_texts(texts):
            return [[0.1] * 10, [0.9] * 10, [0.1] * 10]

        self.mock_embedding_client.embed_texts = mock_embed_texts

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "段落一内容。" * 50 + "\n\n" + "段落二内容。" * 50 + "\n\n" + "段落三内容。" * 50
        chunks = await chunker.chunk_text_semantic(text)

        self.assertTrue(len(chunks) >= 1)

    async def test_chunk_text_semantic_empty_text(self) -> None:
        async def mock_embed_texts(texts):
            return []

        self.mock_embedding_client.embed_texts = mock_embed_texts

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        chunks = await chunker.chunk_text_semantic("")
        self.assertEqual(len(chunks), 0)

    async def test_chunk_text_semantic_emits_embedding_progress(self) -> None:
        emitted: list[StreamEvent] = []

        async def mock_embed_texts(texts, *, progress_callback=None):
            if progress_callback is not None:
                await progress_callback(1, 2, len(texts))
                await progress_callback(2, 2, len(texts))
            return [[0.1] * 10 for _ in texts]

        async def capture(event: StreamEvent) -> None:
            emitted.append(event)

        self.mock_embedding_client.embed_texts = mock_embed_texts

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client, emitter=capture)
        text = "第一段内容。" * 10 + "\n\n" + "第二段内容。" * 10 + "\n\n" + "第三段内容。" * 10
        await chunker.chunk_text_semantic(text)

        self.assertEqual(len(emitted), 2)
        self.assertTrue(all(event.action == "progress" for event in emitted))
        self.assertTrue(all(event.sub_stage == "semantic_chunking_embedding" for event in emitted))
        self.assertEqual(emitted[0].current, 1)
        self.assertEqual(emitted[0].total, 2)
        self.assertEqual(emitted[0].sub_percent, 50.0)
        self.assertEqual(emitted[1].current, 2)
        self.assertEqual(emitted[1].sub_percent, 100.0)


if __name__ == "__main__":
    unittest.main()
