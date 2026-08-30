"""Word2Vec 模块测试（§5.6/§5.7/C3，预训练初始化 + 按书微调）"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gensim.models import KeyedVectors, Word2Vec

from src.linguistic import (
    build_pos_embeddings,
    load_shared_pretrained_vectors,
    reset_pretrained_cache,
    resolve_shared_pretrained_path,
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


def _load_vectors(directory: Path) -> KeyedVectors:
    """2026-08-30 用于从最小预训练源文件加载测试共享向量"""
    source = _write_pretrained_file(directory)
    return KeyedVectors.load_word2vec_format(str(source), binary=False)


class TestTrainBookModel(unittest.TestCase):
    def test_finetune_and_contract(self) -> None:
        """2026-08-30 用于验证微调产物遵循 run 私有路径与落库摘要契约"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pretrained = _load_vectors(tmp_path)
            run_model_dir = tmp_path / "test-run"
            with patch(
                "src.storage.path_resolver.resolve_run_model_dir",
                return_value=run_model_dir,
            ) as resolve_dir:
                train_result = train_book_model(
                    _SENTENCES,
                    "test-run",
                    pretrained_vectors=pretrained,
                    min_count=1,
                    epochs=1,
                )
            self.assertEqual(train_result.embedding_dimension, _DIM)
            unique_words = {word for sentence in _SENTENCES for word in sentence}
            self.assertEqual(train_result.vocabulary_size, len(unique_words))
            self.assertEqual(train_result.training_document_count, 5)
            total = sum(len(sentence) for sentence in _SENTENCES)
            self.assertEqual(train_result.training_token_count, total)
            self.assertEqual(train_result.artifact_key, "models/word2vec/test-run/word2vec.model")
            self.assertTrue((run_model_dir / "word2vec.model").exists())
            resolve_dir.assert_called_once_with("test-run", "word2vec")

    def test_empty_corpus_raises(self) -> None:
        """2026-08-30 用于验证空语料在创建 run 模型目录前明确失败"""
        with tempfile.TemporaryDirectory() as tmp:
            pretrained = _load_vectors(Path(tmp))
            with self.assertRaises(ValueError):
                train_book_model([[], []], "test-run", pretrained_vectors=pretrained)


class TestBuildPosEmbeddings(unittest.TestCase):
    def setUp(self) -> None:
        """2026-08-30 用于在临时 run 目录准备词性聚合测试模型"""
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        pretrained = _load_vectors(tmp_path)
        run_model_dir = tmp_path / "pos-test"
        with patch("src.storage.path_resolver.resolve_run_model_dir", return_value=run_model_dir):
            train_book_model(
                _SENTENCES,
                "pos-test",
                pretrained_vectors=pretrained,
                min_count=1,
                epochs=1,
            )
        self.vectors = Word2Vec.load(str(run_model_dir / "word2vec.model"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_group_average_and_coverage(self) -> None:
        tokens = [
            {"text": "江湖", "pos_group": "noun"},
            {"text": "刀光", "pos_group": "noun"},
            {"text": "白衣", "pos_group": "noun"},
            {"text": "不存在词", "pos_group": "verb"},
        ]
        rows = build_pos_embeddings(tokens, self.vectors, paragraph_id=0)
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


class TestLoadSharedPretrained(unittest.TestCase):
    def setUp(self) -> None:
        """2026-08-30 用于在共享向量测试前清空进程缓存"""
        reset_pretrained_cache()

    def tearDown(self) -> None:
        """2026-08-30 用于在共享向量测试后清空进程缓存"""
        reset_pretrained_cache()

    def test_loads_kv_from_model_dir(self) -> None:
        """2026-08-30 用于验证唯一 kv 以只读内存映射加载并复用缓存"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _write_pretrained_file(tmp_path)
            vectors = KeyedVectors.load_word2vec_format(str(source), binary=False)
            kv_path = tmp_path / "fixture.kv"
            vectors.save(str(kv_path))

            with patch("src.linguistic.word2vec.KeyedVectors.load", wraps=KeyedVectors.load) as mocked_load:
                loaded = load_shared_pretrained_vectors(tmp_path)
            self.assertEqual(loaded.vector_size, _DIM)
            self.assertIn("江湖", loaded)
            mocked_load.assert_called_once_with(str(kv_path.resolve()), mmap="r")
            # 同进程缓存：再次加载返回同一对象
            self.assertIs(load_shared_pretrained_vectors(tmp_path), loaded)

    def test_multiple_kv_files_raise(self) -> None:
        """2026-08-30 用于验证共享目录含多个 kv 主文件时拒绝模糊选择"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "first.kv").touch()
            (tmp_path / "second.kv").touch()

            with self.assertRaisesRegex(ValueError, "恰好包含一个 .kv"):
                resolve_shared_pretrained_path(tmp_path)

    def test_missing_kv_raises(self) -> None:
        """2026-08-30 用于验证共享目录缺少 kv 主文件时明确报错"""
        with tempfile.TemporaryDirectory() as tmp:
            _write_pretrained_file(Path(tmp))
            with self.assertRaises(FileNotFoundError):
                load_shared_pretrained_vectors(Path(tmp))


if __name__ == "__main__":
    unittest.main()
