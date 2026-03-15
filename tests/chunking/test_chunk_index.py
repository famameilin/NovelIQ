import sys
from pathlib import Path
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_text
from src.chunking.index import build_chunk_index


class TestChunkIndex(unittest.TestCase):
    def test_build_chunk_index(self) -> None:
        text = "\n\n".join(["a" * 600] * 3)
        chunks = chunk_text(text, max_chars=1000, split_by_chapter=False, use_semantic=False)
        index = build_chunk_index(chunks)
        self.assertEqual(index.total(), len(chunks))
        self.assertEqual(index.get(0).index, 0)


if __name__ == "__main__":
    unittest.main()
