import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_documents, chunk_text, split_by_chapters


class TestChunking(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_text_basic(self) -> None:
        text = "\n\n".join(["a" * 600] * 4)
        chunks = await chunk_text(text, max_chars=1000, overlap=200, split_by_chapter=False)
        self.assertTrue(len(chunks) >= 1)
        self.assertEqual(chunks[0].start, 0)
        self.assertTrue(all(c.text for c in chunks))

    async def test_chunk_text_uses_real_text_offsets_after_strip(self) -> None:
        """
        创建时间: 2026-04-24
        任务: full-global-offset-rollout
        说明: chunk 的 start/end 应对应最终保留文本在原文中的真实位置，不能继续沿用 strip 前的粗边界。
        """
        text = "  第一段。  \n\n 第二段。"
        chunks = await chunk_text(text, max_chars=100, overlap=0, split_by_chapter=False)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "第一段。  \n\n 第二段。")
        self.assertEqual(chunks[0].start, 2)
        self.assertEqual(chunks[0].end, len(text))

    async def test_chunk_documents_accumulates_run_global_offsets(self) -> None:
        """
        创建时间: 2026-04-24
        任务: full-global-offset-rollout
        说明: 多文档分块时，后续文档的 chunk offset 应累加前序文档长度，形成 run 级连续全文坐标。
        """
        chunks = await chunk_documents(
            [" 第一篇。", " 第二篇。"],
            max_chars=100,
            overlap=0,
            split_by_chapter=False,
            
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].start, 1)
        self.assertEqual(chunks[0].end, 5)
        self.assertEqual(chunks[1].start, 6)
        self.assertEqual(chunks[1].end, 10)

    def test_split_by_chapters(self) -> None:
        text = "第1章 开始\n内容\n第2章 继续\n内容"
        chapters = split_by_chapters(text)
        self.assertEqual(len(chapters), 2)
        self.assertTrue(chapters[0][0].startswith("第1章"))


if __name__ == "__main__":
    unittest.main()
