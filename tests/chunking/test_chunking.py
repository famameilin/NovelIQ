import asyncio
import io
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from loguru import logger

from src.chunking.chunker import chunk_documents, chunk_text


class TestChunking(unittest.IsolatedAsyncioTestCase):
    async def test_chunk_text_short_text_stays_single_chunk(self) -> None:
        text = "\n\n".join(["a" * 600] * 4)
        chunks = await chunk_text(text)
        self.assertTrue(len(chunks) >= 1)
        self.assertEqual(chunks[0].start, 0)
        self.assertTrue(all(c.text for c in chunks))
        self.assertEqual(
            [chunk.chapter_id for chunk in chunks],
            list(range(1, len(chunks) + 1)),
        )

    async def test_chunk_simple_splits_long_text_without_chapters(self) -> None:
        """无章节回退：超长文本按固定字数在段落/句子边界切分"""
        text = "\n\n".join(["a" * 600] * 4)
        chunks = await chunk_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text) <= 2000 for chunk in chunks))

    async def test_chunk_text_uses_real_text_offsets_after_strip(self) -> None:
        """
        创建时间: 2026-04-24
        任务: full-global-offset-rollout
        说明: chunk 的 start/end 应对应最终保留文本在原文中的真实位置，不能继续沿用 strip 前的粗边界。
        """
        text = "  第一段。  \n\n 第二段。"
        chunks = await chunk_text(text)

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
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].start, 1)
        self.assertEqual(chunks[0].end, 5)
        self.assertEqual(chunks[1].start, 6)
        self.assertEqual(chunks[1].end, 10)

    async def test_chunk_documents_accumulates_chapter_ids(self) -> None:
        """
        多文档分块时，后续文档的 chapter_id 应在 run 级全局章节编号中累加
        """
        chunks = await chunk_documents(
            ["第一章 甲\n内容。\n第二章 乙\n内容。", "第三章 丙\n内容。"],
        )
        self.assertEqual([chunk.chapter_id for chunk in chunks], [1, 2, 3])

    async def test_duplicate_chapter_titles_keep_distinct_occurrence_indices(self) -> None:
        """
        2026-08-02 用于保证重复章节标题按出现位置生成不同章节序号
        """
        text = "第1章 序章\n甲。\n第2章 中段\n乙。\n第1章 序章\n丙。"

        chunks = await chunk_text(text)

        self.assertEqual([chunk.chapter_id for chunk in chunks], [1, 2, 3])

    async def test_chapter_never_split_however_long(self) -> None:
        """
        2026-08-08 用于验证章节无论多长整章保持为一个 chunk，不再按字数切分
        """
        text = "第1章 长章\n" + "甲。" * 5000
        chunks = await chunk_text(text)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chapter_id, 1)
        self.assertGreater(len(chunks[0].text), 2000)

    def test_empty_chapter_with_title_is_skipped_and_logged(self) -> None:
        """
        2026-08-08 用于验证仅有标题无正文的章节不生成 chunk（目录中仍保留）且记录警告
        """
        text = "第七章\nxxxx\n第八章\n第九章\nyyyy"
        sink = io.StringIO()
        handler_id = logger.add(sink, level="WARNING", format="{message}")
        try:
            chunks = asyncio.run(chunk_text(text))
        finally:
            logger.remove(handler_id)

        self.assertEqual([chunk.chapter_id for chunk in chunks], [1, 3])
        self.assertIn("第八章", sink.getvalue())
        self.assertIn("已跳过", sink.getvalue())


if __name__ == "__main__":
    unittest.main()
