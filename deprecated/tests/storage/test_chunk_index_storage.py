import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_text
from src.chunking.index import build_chunk_index
from src.storage.chunk_index import read_chunk_index, write_chunk_index


class MockEmbeddingClient:
    def __init__(self, *args, **kwargs):
        pass
    
    def get_embedding(self, text: str):
        import random
        return [random.random() for _ in range(768)]
    
    @staticmethod
    def compute_similarity(vec1, vec2):
        return 0.5


class TestChunkIndexStorage(unittest.TestCase):
    @patch("src.chunking.chunker.EmbeddingClient", MockEmbeddingClient)
    def test_write_read_chunk_index(self) -> None:
        text = "\n\n".join(["a" * 600] * 3)
        chunks = chunk_text(text, max_chars=1000, split_by_chapter=False)
        index = build_chunk_index(chunks)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunks.json"
            write_chunk_index(index, path)
            loaded = read_chunk_index(path)
            self.assertEqual(loaded.total(), index.total())
            self.assertEqual(loaded.get(0).text, index.get(0).text)


if __name__ == "__main__":
    unittest.main()
