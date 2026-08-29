"""固定短语匹配器测试（§B2/§5.5）"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.linguistic.phrase_matcher import match_fixed_phrases

_TERMS = ["刀光剑影", "快意恩仇", "一帆风顺", "剑拔弩张", "碰钉子"]


class TestMatchFixedPhrases(unittest.TestCase):
    def _match(self, text: str, metric_enabled: bool = False):
        return match_fixed_phrases(
            text,
            _TERMS,
            lexicon_key="fixed_phrases.txt",
            lexicon_version_hash="h" * 64,
            metric_enabled=metric_enabled,
        )

    def test_longest_match_non_overlap(self) -> None:
        # "刀光剑影" 与 "剑拔弩张" 共享"剑"字：最长匹配优先取第一个命中
        text = "刀光剑影威慑天下，剑拔弩张两军对峙"
        hits = [h for h in self._match(text) if h.match_kind == "lexicon"]
        surfaces = {h.surface_text for h in hits}
        self.assertIn("刀光剑影", surfaces)
        overlaps = [
            (a, b)
            for i, a in enumerate(hits)
            for b in hits[i + 1 :]
            if a.local_start_char < b.local_end_char and b.local_start_char < a.local_end_char
        ]
        self.assertEqual(overlaps, [])

    def test_four_char_candidates_separated(self) -> None:
        text = "江湖人士快意恩仇，坐看风起云涌。"
        candidates = [h for h in self._match(text) if h.match_kind == "four_char_candidate"]
        # 已命中的四字词不产生候选
        self.assertNotIn("快意恩仇", [c.surface_text for c in candidates])
        self.assertTrue(all(c.is_metric_hit is False for c in candidates))

    def test_metric_hit_only_when_enabled(self) -> None:
        text = "江湖快意恩仇。"
        disabled = [h for h in self._match(text, metric_enabled=False) if h.match_kind == "lexicon"]
        enabled = [h for h in self._match(text, metric_enabled=True) if h.match_kind == "lexicon"]
        self.assertTrue(all(h.is_metric_hit is False for h in disabled))
        self.assertTrue(all(h.is_metric_hit is True for h in enabled))

    def test_empty_text_or_terms(self) -> None:
        self.assertEqual(self._match(""), [])
        self.assertEqual(match_fixed_phrases("文本", [], lexicon_key="k", lexicon_version_hash="h"), [])

    def test_hit_span_matches_original_slice(self) -> None:
        text = "起点一帆风顺，之后每况愈下。"
        for hit in self._match(text):
            self.assertEqual(text[hit.local_start_char : hit.local_end_char], hit.surface_text)


if __name__ == "__main__":
    unittest.main()