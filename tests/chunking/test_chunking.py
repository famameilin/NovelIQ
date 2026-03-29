import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_text, split_by_chapters


class TestChunking(unittest.TestCase):
    def test_chunk_text_basic(self) -> None:
        text = "\n\n".join(["a" * 600] * 4)
        chunks = chunk_text(text, max_chars=1000, overlap=200, split_by_chapter=False, use_semantic=False)
        # 分块数量取决于具体实现，验证基本属性即可
        self.assertTrue(len(chunks) >= 1)
        self.assertEqual(chunks[0].start, 0)
        self.assertTrue(all(c.text for c in chunks))

    def test_split_by_chapters(self) -> None:
        text = "第1章 开始\n内容\n第2章 继续\n内容"
        chapters = split_by_chapters(text)
        self.assertEqual(len(chapters), 2)
        # API 返回 (title, content) 元组
        self.assertTrue(chapters[0][0].startswith("第1章"))


if __name__ == "__main__":
    unittest.main()
