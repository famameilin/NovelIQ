import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_documents, chunk_text, split_by_chapters


class TestChunking(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_text_short_text_stays_single_chunk(self) -> None:
        text = "\n\n".join(["a" * 600] * 4)
        chunks = await chunk_text(text, max_chars=1000)
        self.assertTrue(len(chunks) >= 1)
        self.assertEqual(chunks[0].start, 0)
        self.assertTrue(all(c.text for c in chunks))
        self.assertEqual(
            [chunk.chapter_index for chunk in chunks],
            list(range(1, len(chunks) + 1)),
        )

    async def test_chunk_text_splits_when_over_start_chars(self) -> None:
        text = "\n\n".join(["a" * 600] * 4)
        chunks = await chunk_text(text, max_chars=1000, start_chars=1000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 1000 for chunk in chunks))

    async def test_chunk_text_uses_real_text_offsets_after_strip(self) -> None:
        """
        创建时间: 2026-04-24
        任务: full-global-offset-rollout
        说明: chunk 的 start/end 应对应最终保留文本在原文中的真实位置，不能继续沿用 strip 前的粗边界。
        """
        text = "  第一段。  \n\n 第二段。"
        chunks = await chunk_text(text, max_chars=100)

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

    async def test_duplicate_chapter_titles_keep_distinct_occurrence_indices(self) -> None:
        """
        2026-08-02 用于保证重复章节标题按出现位置生成不同章节序号
        """
        text = "第1章 序章\n甲。\n第2章 中段\n乙。\n第1章 序章\n丙。"

        chunks = await chunk_text(text, max_chars=100)

        self.assertEqual([chunk.chapter_index for chunk in chunks], [1, 2, 3])
        self.assertEqual(chunks[0].chapter_title, chunks[2].chapter_title)

    async def test_chapter_within_start_chars_stays_whole(self) -> None:
        """
        2026-08-08 用于验证章节不超过 start_chars 时整章一个 chunk
        """
        text = "第1章 短章\n" + "甲。" * 100
        chunks = await chunk_text(text, max_chars=50, start_chars=4000)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chapter_title, "第1章 短章")
        self.assertGreater(len(chunks[0].text), 50)


if __name__ == "__main__":
    unittest.main()
