import json
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.ingest.reader import ingest_path, load_metadata, read_text_file
from src.preprocess.cleaning import normalize_text, strip_empty_lines
from src.preprocess.segment import split_paragraphs, split_sentences


class TestIngest(unittest.TestCase):
    def test_read_text_file_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("你好", encoding="utf-8")
            self.assertEqual(read_text_file(path), "你好")

    def test_load_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meta.json"
            payload = {"title": "书名", "author": "作者", "genre": "类型"}
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            data = load_metadata(path)
            self.assertEqual(data["title"], "书名")

    def test_ingest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a.txt").write_text("第一章", encoding="utf-8")
            (base / "b.txt").write_text("第二章", encoding="utf-8")
            meta = base / "meta.json"
            meta.write_text(
                json.dumps({"title": "书名", "author": "作者"}, ensure_ascii=False),
                encoding="utf-8",
            )
            docs = ingest_path(base, meta)
            self.assertEqual(len(docs), 2)
            self.assertEqual(docs[0].title, "书名")
            self.assertEqual(docs[0].author, "作者")

    def test_ingest_sample_novel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            novel_dir = Path(tmp) / "novel"
            novel_dir.mkdir()
            (novel_dir / "chapter1.txt").write_text("第一章 开始\n\n这是测试内容。" * 50, encoding="utf-8")
            (novel_dir / "chapter2.txt").write_text("第二章 继续\n\n更多测试内容。" * 50, encoding="utf-8")
            docs = ingest_path(novel_dir)
            self.assertGreaterEqual(len(docs), 1)
            self.assertTrue(docs[0].text.strip())

    def test_ingest_and_preprocess_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            novel_dir = Path(tmp) / "novel"
            novel_dir.mkdir()
            content = "第一章 测试\n\n这是测试文本。包含多个句子。对话：「你好」。"
            (novel_dir / "test.txt").write_text(content * 20, encoding="utf-8")
            docs = ingest_path(novel_dir)
            text = docs[0].text
        normalized = normalize_text(text)
        cleaned = strip_empty_lines(normalized)
        paragraphs_raw = split_paragraphs(normalized)
        paragraphs = split_paragraphs(cleaned)
        sentences = split_sentences(cleaned)
        self.assertGreaterEqual(len(paragraphs_raw), 1)
        self.assertGreaterEqual(len(sentences), 1)
        if "\n\n" in normalized:
            self.assertGreaterEqual(len(paragraphs_raw), 2)
        if any(punct in cleaned for punct in ("。", "！", "？", "!", "?")):
            self.assertGreater(len(sentences), 1)
        self.assertTrue(all("\n\n" not in p for p in paragraphs))
        self.assertTrue(all("\n" not in s for s in sentences))
        self.assertTrue(all(s.strip() for s in sentences))


if __name__ == "__main__":
    unittest.main()
