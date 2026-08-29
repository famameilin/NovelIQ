"""Word2Vec 模块测试（§5.6/§5.7/C3，预训练初始化 + 按书微调）"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from gensim.models import KeyedVectors

from src.linguistic import (
    build_pos_embeddings,
    compute_corpus_hash,
    resolve_pretrained_file,
    train_book_model,
)

_SENTENCES = [
    ["江湖", "恩怨", "快意", "恩仇"],
    ["刀光", "剑影", "江湖", "风波"],
    ["白衣", "胜雪", "江湖", "行侠"],
    ["快意", "恩仇", "刀光", "剑影"],
    ["江湖", "风波", "白衣", "行侠"],
]

_DIM = 4
_PRETRAINED_WORDS = ["江湖", "刀光", "恩仇", "侠"]


def _write_pretrained_file(directory: Path) -> Path:
    """写一个极小 word2vec 文本格式文件（dim=4，含书内词与书外词"侠"）"""
    path = directory / "fixture.vec"
    lines = [f"{len(_PRETRAINED_WORDS)} {_DIM}"]
    for i, word in enumerate(_PRETRAINED_WORDS):
        vec = " ".join(f"{(i + j) / 10:.1f}" for j in range(_DIM))
        lines.append(f"{word} {vec}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestResolvePretrainedFile(unittest.TestCase):
    def test_resolve_and_missing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pretrained = _write_pretrained_file(Path(tmp))
            path, binary = resolve_pretrained_file(Path(tmp))
            self.assertFalse(binary)
            self.assertEqual(path, pretrained)
            with self.assertRaises(FileNotFoundError):
                resolve_pretrained_file(Path(tmp) / "nope")


class TestTrainBookModel(unittest.TestCase):
    def test_finetune_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pretrained = _write_pretrained_file(Path(tmp))
            train_result = train_book_model(
                _SENTENCES,
                "test-run",
                pretrained_path=pretrained,
                min_count=1,
                epochs=1,
                output_dir=Path(tmp),
            )
            self.assertEqual(train_result.embedding_dimension, _DIM)
            unique_words = {word for sentence in _SENTENCES for word in sentence}
            self.assertEqual(train_result.vocabulary_size, len(unique_words))
            self.assertEqual(train_result.training_document_count, 5)
            total = sum(len(sentence) for sentence in _SENTENCES)
            self.assertEqual(train_result.training_token_count, total)
            self.assertEqual(len(train_result.artifact_sha256), 64)
            self.assertTrue((Path(tmp) / "test-run.model").exists())

    def test_empty_corpus_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pretrained = _write_pretrained_file(Path(tmp))
            with self.assertRaises(ValueError):
                train_book_model([[], []], "test-run", pretrained_path=pretrained, output_dir=Path(tmp))


class TestComputeCorpusHash(unittest.TestCase):
    def test_deterministic_and_order_sensitive(self) -> None:
        first = compute_corpus_hash(_SENTENCES)
        second = compute_corpus_hash(_SENTENCES)
        self.assertEqual(first, second)
        self.assertNotEqual(first, compute_corpus_hash(list(reversed(_SENTENCES))))


class TestBuildPosEmbeddings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        pretrained = _write_pretrained_file(Path(self._tmp.name))
        train_book_model(
            _SENTENCES,
            "pos-test",
            pretrained_path=pretrained,
            min_count=1,
            epochs=1,
            output_dir=Path(self._tmp.name),
        )
        self.vectors = KeyedVectors.load(str(Path(self._tmp.name) / "pos-test.model"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_group_average_and_coverage(self) -> None:
        tokens = [
            {"text": "江湖", "pos_group": "noun"},
            {"text": "刀光", "pos_group": "noun"},
            {"text": "白衣", "pos_group": "noun"},
            {"text": "不存在词", "pos_group": "verb"},
        ]
        rows = build_pos_embeddings(tokens, self.vectors, paragraph_id=0, source_content_hash="a" * 64)
        by_group = {row.pos_group: row for row in rows}
        noun = by_group["noun"]
        self.assertEqual(noun.source_token_count, 3)
        self.assertEqual(noun.in_vocabulary_token_count, 3)
        verb = by_group["verb"]
        self.assertEqual(verb.in_vocabulary_token_count, 0)
        self.assertIsNone(verb.embedding_vector)
        # 组内均值为词向量均值（float32/float64 混合计算，按容差比较）
        expected = [
            sum(self.vectors.wv[word][i] for word in ["江湖", "刀光", "白衣"]) / 3
            for i in range(self.vectors.wv.vector_size)
        ]
        self.assertEqual(len(noun.embedding_vector), len(expected))
        max_diff = max(abs(a - float(b)) for a, b in zip(noun.embedding_vector, expected, strict=True))
        self.assertLess(max_diff, 1e-6)


if __name__ == "__main__":
    unittest.main()
