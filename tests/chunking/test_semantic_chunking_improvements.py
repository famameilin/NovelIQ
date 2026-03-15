import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import (
    SemanticChunker,
    Chunk,
)


class TestOnomatopoeiaDetection(unittest.TestCase):
    def setUp(self):
        self.chunker = SemanticChunker()

    def test_single_onomatopoeia(self):
        self.assertTrue(self.chunker._is_onomatopoeia("轰"))
        self.assertTrue(self.chunker._is_onomatopoeia("唳"))
        self.assertTrue(self.chunker._is_onomatopoeia("砰"))
        self.assertTrue(self.chunker._is_onomatopoeia("咔"))
        self.assertTrue(self.chunker._is_onomatopoeia("嗖"))

    def test_onomatopoeia_with_punctuation(self):
        self.assertTrue(self.chunker._is_onomatopoeia("轰！"))
        self.assertTrue(self.chunker._is_onomatopoeia("唳！"))
        self.assertTrue(self.chunker._is_onomatopoeia("砰！"))
        self.assertTrue(self.chunker._is_onomatopoeia("咔嚓！"))

    def test_double_onomatopoeia(self):
        self.assertTrue(self.chunker._is_onomatopoeia("轰轰"))
        self.assertTrue(self.chunker._is_onomatopoeia("砰砰"))
        self.assertTrue(self.chunker._is_onomatopoeia("咔嚓"))
        self.assertTrue(self.chunker._is_onomatopoeia("哗啦"))

    def test_not_onomatopoeia(self):
        self.assertFalse(self.chunker._is_onomatopoeia("他猛地一击"))
        self.assertFalse(self.chunker._is_onomatopoeia("这是正常的一句话"))
        self.assertFalse(self.chunker._is_onomatopoeia("人物说道"))
        self.assertFalse(self.chunker._is_onomatopoeia("轰隆一声巨响传来，整个山洞都在颤抖"))

    def test_long_text_not_onomatopoeia(self):
        self.assertFalse(self.chunker._is_onomatopoeia("轰隆一声巨响，整个山洞都在颤抖"))


class TestDynamicThreshold(unittest.TestCase):
    def setUp(self):
        self.mock_embedding_client = MagicMock()
        self.chunker = SemanticChunker(embedding_client=self.mock_embedding_client)

    def test_dynamic_threshold_computation(self):
        similarities = [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45]
        threshold = self.chunker._compute_dynamic_threshold(similarities)
        self.assertTrue(0.3 <= threshold <= 0.9)

    def test_dynamic_threshold_with_percentile_10(self):
        similarities = [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5, 0.45]
        threshold = self.chunker._compute_dynamic_threshold(similarities)
        expected_idx = int(len(similarities) * 0.1)
        sorted_sims = sorted(similarities)
        expected = max(0.3, min(0.9, sorted_sims[expected_idx]))
        self.assertAlmostEqual(threshold, expected, places=2)

    def test_dynamic_threshold_empty_similarities(self):
        threshold = self.chunker._compute_dynamic_threshold([])
        self.assertEqual(threshold, 0.5)


class TestMinCharsConstraint(unittest.TestCase):
    def setUp(self):
        self.mock_embedding_client = MagicMock()
        self.chunker = SemanticChunker(embedding_client=self.mock_embedding_client)

    def test_merge_short_chunks(self):
        chunks = [
            Chunk(index=0, text="短", start=0, end=1),
            Chunk(index=1, text="正常长度的文本内容" * 10, start=1, end=100),
        ]
        merged = self.chunker._apply_min_chars_constraint(chunks, max_chars=3000)
        self.assertEqual(len(merged), 1)

    def test_keep_long_chunks(self):
        long_text = "这是一个很长的文本内容" * 10
        chunks = [
            Chunk(index=0, text=long_text, start=0, end=len(long_text)),
        ]
        merged = self.chunker._apply_min_chars_constraint(chunks, max_chars=3000)
        self.assertEqual(len(merged), 1)

    def test_last_chunk_merge(self):
        chunks = [
            Chunk(index=0, text="正常长度的文本内容" * 10, start=0, end=100),
            Chunk(index=1, text="短", start=100, end=101),
        ]
        merged = self.chunker._apply_min_chars_constraint(chunks, max_chars=3000)
        self.assertEqual(len(merged), 1)


class TestWindowEmbeddings(unittest.TestCase):
    def setUp(self):
        self.mock_embedding_client = MagicMock()
        self.mock_embedding_client.get_embedding.return_value = [0.1] * 10
        self.chunker = SemanticChunker(embedding_client=self.mock_embedding_client)

    def test_window_embedding_computation(self):
        paragraphs = [
            (0, 10, "第一段"),
            (10, 20, "第二段"),
            (20, 30, "第三段"),
            (30, 40, "第四段"),
            (40, 50, "第五段"),
        ]
        window_embeddings = self.chunker._compute_window_embeddings(paragraphs)
        self.assertEqual(len(window_embeddings), 5)

    def test_window_embedding_boundary(self):
        paragraphs = [
            (0, 10, "第一段"),
            (10, 20, "第二段"),
        ]
        window_embeddings = self.chunker._compute_window_embeddings(paragraphs)
        self.assertEqual(len(window_embeddings), 2)


class TestBackwardCompatibility(unittest.TestCase):
    def setUp(self):
        self.mock_embedding_client = MagicMock()
        self.mock_embedding_client.get_embedding.return_value = [0.1] * 10
        self.mock_embedding_client.compute_similarity.return_value = 0.5

    def test_fixed_threshold_mode(self):
        with patch('src.chunking.chunker.settings') as mock_settings:
            mock_settings.chunking.semantic_window_size = 3
            mock_settings.chunking.semantic_percentile = 10
            mock_settings.chunking.semantic_min_chars = 50
            mock_settings.chunking.semantic_use_dynamic_threshold = False
            mock_settings.chunking.semantic_threshold = 0.7
            mock_settings.chunking.semantic_max_chars = 3000

            chunker = SemanticChunker(embedding_client=self.mock_embedding_client)
            chunker._use_dynamic_threshold = False
            chunker._min_chars = 50

            text = "段落一内容。" * 50 + "\n\n" + "段落二内容。" * 50
            chunks = chunker.chunk_text_semantic(text, threshold=0.7, max_chars=3000)
            self.assertTrue(len(chunks) >= 1)


if __name__ == "__main__":
    unittest.main()
