"""主题模型 artifact 与语料哈希测试（§5.8 artifact_sha256 / training_corpus_hash）"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.topic.artifacts import compute_artifact_directory_sha256, compute_training_corpus_hash


class TestComputeArtifactDirectorySha256(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(__file__).parent / "_tmp_artifact_hash"
        self.tmp_dir.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        for child in self.tmp_dir.iterdir():
            if child.is_file():
                child.unlink()
        self.tmp_dir.rmdir()

    def test_consistent_for_same_content(self) -> None:
        (self.tmp_dir / "lda_model").write_text("model-bytes", encoding="utf-8")
        (self.tmp_dir / "dictionary").write_text("dict-bytes", encoding="utf-8")
        first = compute_artifact_directory_sha256(self.tmp_dir)
        second = compute_artifact_directory_sha256(self.tmp_dir)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_changes_with_file_content(self) -> None:
        (self.tmp_dir / "lda_model").write_text("model-bytes", encoding="utf-8")
        before = compute_artifact_directory_sha256(self.tmp_dir)
        (self.tmp_dir / "lda_model").write_text("model-bytes-v2", encoding="utf-8")
        after = compute_artifact_directory_sha256(self.tmp_dir)
        self.assertNotEqual(before, after)

    def test_changes_with_new_file(self) -> None:
        (self.tmp_dir / "lda_model").write_text("model-bytes", encoding="utf-8")
        before = compute_artifact_directory_sha256(self.tmp_dir)
        (self.tmp_dir / "labels.json").write_text("{}", encoding="utf-8")
        after = compute_artifact_directory_sha256(self.tmp_dir)
        self.assertNotEqual(before, after)

    def test_missing_directory_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            compute_artifact_directory_sha256(self.tmp_dir / "not-exists")


class TestComputeTrainingCorpusHash(unittest.TestCase):
    def _row(self, paragraph_id: int, content_hash: str):
        return type("Row", (), {"paragraph_id": paragraph_id, "content_hash": content_hash})()

    def test_deterministic_and_order_normalized(self) -> None:
        rows = [self._row(1, "a" * 64), self._row(2, "b" * 64), self._row(3, "c" * 64)]
        first = compute_training_corpus_hash(rows)
        second = compute_training_corpus_hash(list(reversed(rows)))
        self.assertEqual(len(first), 64)
        # 顺序规范化：同一批段落无论读取顺序，摘要保持一致（重跑契约稳定）
        self.assertEqual(first, second)
        self.assertEqual(first, compute_training_corpus_hash(rows))

    def test_content_hash_change_detected(self) -> None:
        rows = [self._row(1, "a" * 64), self._row(2, "b" * 64)]
        before = compute_training_corpus_hash(rows)
        rows[1] = self._row(2, "d" * 64)
        after = compute_training_corpus_hash(rows)
        self.assertNotEqual(before, after)

    def test_empty_sequence_is_stable(self) -> None:
        digest = compute_training_corpus_hash([])
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()