import asyncio
import io
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from loguru import logger

from src.text_processing.paragraphs import chunk_text


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
        """chunk 的 start/end 应对应最终保留文本在原文中的真实位置，不能继续沿用 strip 前的粗边界。"""
        text = "  第一段。  \n\n 第二段。"
        chunks = await chunk_text(text)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "第一段。  \n\n 第二段。")
        self.assertEqual(chunks[0].start, 2)
        self.assertEqual(chunks[0].end, len(text))

    async def test_duplicate_chapter_titles_keep_distinct_occurrence_indices(self) -> None:
        """保证重复章节标题按出现位置生成不同章节序号"""
        text = "第1章 序章\n甲。\n第2章 中段\n乙。\n第1章 序章\n丙。"

        chunks = await chunk_text(text)

        self.assertEqual([chunk.chapter_id for chunk in chunks], [1, 2, 3])

    async def test_chapter_never_split_however_long(self) -> None:
        """验证章节无论多长整章保持为一个 chunk，不再按字数切分"""
        text = "第1章 长章\n" + "甲。" * 5000
        chunks = await chunk_text(text)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chapter_id, 1)
        self.assertGreater(len(chunks[0].text), 2000)

    def test_empty_chapter_with_title_is_skipped_and_logged(self) -> None:
        """验证仅有标题无正文的章节不生成 chunk（目录中仍保留）且记录警告"""
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
