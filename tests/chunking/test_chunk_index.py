import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_text
from src.chunking.index import build_chunk_index


class TestChunkIndex(unittest.IsolatedAsyncioTestCase):
    async def test_build_chunk_index(self) -> None:
        text = "\n\n".join(["a" * 600] * 3)
        chunks = await chunk_text(text)
        index = build_chunk_index(chunks)
        self.assertEqual(index.total(), len(chunks))
        self.assertEqual(index.get(0).index, 0)


if __name__ == "__main__":
    unittest.main()
