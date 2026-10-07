import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.text_processing.preprocess import normalize_text, split_paragraphs, split_sentences


class TestCleaning(unittest.TestCase):
    def test_normalize_text(self) -> None:
        raw = "  第一章\r\n\r\n第二章\u3000  \t内容  "
        normalized = normalize_text(raw)
        self.assertEqual(normalized, "第一章\n\n第二章 内容")


class TestSegment(unittest.TestCase):
    def test_split_paragraphs(self) -> None:
        text = "第一段\n\n第二段\n\n\n第三段"
        self.assertEqual(split_paragraphs(text), ["第一段", "第二段", "第三段"])

    def test_split_sentences(self) -> None:
        text = "你好！我来了。好么？\n行"
        self.assertEqual(split_sentences(text), ["你好", "我来了", "好么", "行"])


if __name__ == "__main__":
    unittest.main()
