import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import (
    SemanticChunker,
    Chunk,
    _is_onomatopoeia,
    _detect_onomatopoeia,
)


class TestOnomatopoeiaDetection(unittest.TestCase):
    """测试拟声词检测功能（模块级函数）"""

    def test_single_onomatopoeia(self):
        self.assertTrue(_is_onomatopoeia("轰"))
        self.assertTrue(_is_onomatopoeia("唳"))
        self.assertTrue(_is_onomatopoeia("砰"))
        self.assertTrue(_is_onomatopoeia("咔"))
        self.assertTrue(_is_onomatopoeia("嗖"))

    def test_onomatopoeia_with_punctuation(self):
        self.assertTrue(_is_onomatopoeia("轰！"))
        self.assertTrue(_is_onomatopoeia("唳！"))
        self.assertTrue(_is_onomatopoeia("砰！"))
        self.assertTrue(_is_onomatopoeia("咔嚓！"))

    def test_double_onomatopoeia(self):
        self.assertTrue(_is_onomatopoeia("轰轰"))
        self.assertTrue(_is_onomatopoeia("砰砰"))
        self.assertTrue(_is_onomatopoeia("咔嚓"))
        self.assertTrue(_is_onomatopoeia("哗啦"))

    def test_not_onomatopoeia(self):
        self.assertFalse(_is_onomatopoeia("他猛地一击"))
        self.assertFalse(_is_onomatopoeia("这是正常的一句话"))
        self.assertFalse(_is_onomatopoeia("人物说道"))
        self.assertFalse(_is_onomatopoeia("轰隆一声巨响传来，整个山洞都在颤抖"))

    def test_long_text_not_onomatopoeia(self):
        self.assertFalse(_is_onomatopoeia("轰隆一声巨响，整个山洞都在颤抖"))

    def test_detect_onomatopoeia_in_paragraphs(self):
        paragraphs = [
            (0, 10, "轰！"),
            (10, 20, "正常段落内容"),
            (20, 30, "砰砰！"),
        ]
        indices = _detect_onomatopoeia(paragraphs)
        self.assertEqual(indices, {0, 2})


class TestSemanticChunkerBasic(unittest.TestCase):
    """测试 SemanticChunker 基本功能"""

    def setUp(self):
        self.mock_embedding_client = MagicMock()

    def test_chunk_text_semantic_with_mock(self):
        """测试使用 mock embedding client 进行语义分块"""
        self.mock_embedding_client.embed_texts.return_value = [
            [0.1] * 10,
            [0.9] * 10,
            [0.1] * 10,
        ]

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "段落一内容。" * 50 + "\n\n" + "段落二内容。" * 50 + "\n\n" + "段落三内容。" * 50
        chunks = chunker.chunk_text_semantic(text)

        self.assertTrue(len(chunks) >= 1)
        for chunk in chunks:
            self.assertIsInstance(chunk, Chunk)
            self.assertTrue(len(chunk.text) > 0)

    def test_chunk_text_semantic_empty_text(self):
        """测试空文本返回空列表"""
        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        chunks = chunker.chunk_text_semantic("")
        self.assertEqual(len(chunks), 0)

    def test_chunk_text_semantic_single_paragraph(self):
        """测试单段落文本"""
        self.mock_embedding_client.embed_texts.return_value = [[0.1] * 10]

        chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
        text = "只有一个段落的内容。" * 100
        chunks = chunker.chunk_text_semantic(text)

        self.assertEqual(len(chunks), 1)
        self.assertTrue(len(chunks[0].text) > 0)


if __name__ == "__main__":
    unittest.main()
