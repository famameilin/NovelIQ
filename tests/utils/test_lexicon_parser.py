"""lexicon_parser 行解析测试：整行/行内注释、加权列、draft "词  # 证据" 格式。"""

from pathlib import Path

from src.utils.lexicon_parser import load_lexicon_terms, load_weighted_lexicon, parse_lexicon_term


class TestParseLexiconTerm:
    def test_plain_term(self) -> None:
        assert parse_lexicon_term("皱眉") == "皱眉"

    def test_full_line_comment(self) -> None:
        assert parse_lexicon_term("# 注释行") == ""

    def test_blank_line(self) -> None:
        assert parse_lexicon_term("   ") == ""

    def test_weighted_tab(self) -> None:
        assert parse_lexicon_term("恐惧\t3") == "恐惧"

    def test_inline_comment_draft_format(self) -> None:
        assert parse_lexicon_term("一丝丝  # w2v 相似 0.7297（种子 恐惧）") == "一丝丝"

    def test_inline_comment_after_weight(self) -> None:
        assert parse_lexicon_term("恐惧\t3  # 备注") == "恐惧"

    def test_hash_without_leading_space_is_kept(self) -> None:
        assert parse_lexicon_term("词#不含空白") == "词#不含空白"


class TestLoadLexiconTerms:
    def test_draft_file_format(self, tmp_path: Path) -> None:
        f = tmp_path / "draft.txt"
        f.write_text("# 头注释\n一丝丝  # w2v 相似 0.7297\n一僵  # 出现 111 局部框架 131\n\n", encoding="utf-8")
        assert load_lexicon_terms(f) == ["一丝丝", "一僵"]


class TestLoadWeightedLexicon:
    def test_inline_comment_stripped(self, tmp_path: Path) -> None:
        f = tmp_path / "weighted.txt"
        f.write_text("恐惧\t3  # 备注\n愤怒\t2\n", encoding="utf-8")
        assert load_weighted_lexicon(f) == {"恐惧": 3, "愤怒": 2}
