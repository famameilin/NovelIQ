import sys
from pathlib import Path
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_text, detect_chapters


class TestChunking(unittest.TestCase):
    def test_chunk_text_basic(self) -> None:
        text = "\n\n".join(["a" * 600] * 4)
        chunks = chunk_text(text, max_chars=1000, overlap=200, split_by_chapter=False, use_semantic=False)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].start, 0)
        self.assertTrue(all(c.text for c in chunks))

    def test_detect_chapters(self) -> None:
        text = "第1章 开始\n内容\n第2章 继续\n内容"
        chapters = detect_chapters(text)
        self.assertEqual(len(chapters), 2)
        self.assertTrue(chapters[0][2].startswith("第1章"))


if __name__ == "__main__":
    unittest.main()
