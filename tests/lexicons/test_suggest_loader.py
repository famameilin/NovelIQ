"""
lexicons suggest 模块测试

覆盖 src/lexicons/suggest.py（词表扩展建议）。

2026-08-12 创建，补齐 0% 覆盖率模块。
2026-08-15 词表 v3：loader.py 已删除（仅测试引用），相关用例移除；
expand_lexicons 不再产出 proper_nouns 类别（词表已删）；
无 registry.yaml 的目录直接报错（v3 强约束，禁止 fallback）。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from src.lexicons.suggest import (
    _extract_combat_terms,
    _extract_proper_nouns,
    _extract_semantic_terms,
    _extract_sensory_terms,
    collect_fallback_terms,
    collect_tokens,
    expand_lexicons,
    is_chinese_term,
    pick_candidates,
    read_lexicon,
    update_lexicons_from_texts,
    write_lexicon,
)

# ============================================================================
# suggest.py 纯函数
# ============================================================================


def test_is_chinese_term() -> None:
    assert is_chinese_term("青云宗")
    assert is_chinese_term("玄") is False  # 单字
    assert is_chinese_term("青云宗弟子太多了") is False  # 超 6 字
    assert is_chinese_term("abc") is False
    assert is_chinese_term("青云宗123") is False


def test_read_lexicon_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "terms.txt"
    path.write_text("# 注释行\n词一\n\n词二\n", encoding="utf-8")
    assert read_lexicon(path) == {"词一", "词二"}


def test_write_lexicon_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "terms.txt"
    write_lexicon(path, ["词三", "词一"])
    assert read_lexicon(path) == {"词一", "词三"}
    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")


def test_collect_tokens_and_fallback() -> None:
    tokens = collect_tokens(["青云宗弟子修炼"])
    assert isinstance(tokens, list) and tokens
    fallback = collect_fallback_terms(["青云宗弟子"])
    assert fallback and all(len(term) >= 2 for term in fallback)


def test_pick_candidates_filters_and_sorts() -> None:
    freq = Counter({"青云宗": 5, "宗门": 3, "其他门派": 2, "测试词": 1})
    result = pick_candidates(freq, {"宗门"}, lambda t: True, limit=10, min_freq=2)
    # "宗门" 已在 existing 被排除；"其他门派" 命中前缀黑名单；"测试词" 低于 min_freq
    assert result == ["青云宗"]


def test_pick_candidates_respects_limit_and_predicate() -> None:
    freq = Counter({"甲乙": 4, "丙丁": 3, "戊己": 2})
    result = pick_candidates(freq, set(), lambda t: t != "丙丁", limit=1, min_freq=2)
    assert result == ["甲乙"]


def test_extract_proper_nouns_by_suffixes() -> None:
    freq = Counter({"青云宗": 4, "玄天剑": 3, "仙子": 2, "仙尊": 2, "宗门弟子": 2, "无名宗": 2})
    result = _extract_proper_nouns(freq, set(), (), ("仙子", "老祖"), ("宗", "门"), ("剑",), {"仙尊", "仙子"})
    # "仙子" 命中 title 后缀但属于 title_only；"仙尊" 属于 title_only；"宗门弟子" 无匹配后缀
    assert result == ["青云宗", "玄天剑", "无名宗"]


def test_extract_combat_terms() -> None:
    freq = Counter({"斩杀": 4, "攻击": 3, "杀招": 2, "战斗": 2, "方法": 2})
    result = _extract_combat_terms(freq, set(), ("斩", "杀", "击"), ("方法",))
    # "战斗" 不含词干；"方法" 命中停用子串
    assert result == ["斩杀", "攻击", "杀招"]


def test_extract_sensory_terms_excludes_stop_words() -> None:
    freq = Counter({"香气": 4, "冰冷": 3, "明白": 2, "暗器": 2})
    result = _extract_sensory_terms(freq, set(), ("香", "冷", "暗"), ("方法",), {"明白"})
    assert result == ["香气", "冰冷", "暗器"]


def test_extract_semantic_terms_from_full_text() -> None:
    result = _extract_semantic_terms("宿命难违，他选择牺牲自己。", {"牺牲"}, ("宿命", "牺牲", "救赎"))
    assert result == ["宿命"]


# ============================================================================
# suggest.py 集成（临时词表目录，v3 要求目录内带 registry.yaml）
# ============================================================================

_REGISTRY_TEMPLATE = """\
version: "3.0"
lexicons:
  combat.txt:
    kind: tension
  sensory.txt:
    kind: style
  semantic_category.txt:
    kind: style
"""


@pytest.fixture
def lexicon_dir(tmp_path: Path) -> Path:
    (tmp_path / "registry.yaml").write_text(_REGISTRY_TEMPLATE, encoding="utf-8")
    (tmp_path / "combat.txt").write_text("斩杀\n", encoding="utf-8")
    (tmp_path / "sensory.txt").write_text("香气\n", encoding="utf-8")
    (tmp_path / "semantic_category.txt").write_text("救赎\n", encoding="utf-8")
    return tmp_path


def test_expand_lexicons_detects_semantic_combat_sensory(lexicon_dir: Path) -> None:
    texts = ["宿命难违" + "青云宗" * 8]
    additions = expand_lexicons(texts, lexicon_dir)
    assert additions["semantic_category"] == ["宿命"]
    assert isinstance(additions["combat"], list)
    assert isinstance(additions["sensory"], list)
    # v3：proper_nouns 词表已删，不再产出该类别
    assert "proper_nouns" not in additions


def test_expand_lexicons_without_registry_yaml_raises(tmp_path: Path) -> None:
    # v3 强约束：目录无 registry.yaml 直接报错，不再回退
    with pytest.raises(FileNotFoundError):
        expand_lexicons(["一段普通的中文测试文本"], tmp_path)


def test_update_lexicons_from_texts_applies_merge(tmp_path: Path) -> None:
    (tmp_path / "registry.yaml").write_text(_REGISTRY_TEMPLATE, encoding="utf-8")
    path = tmp_path / "semantic_category.txt"
    path.write_text("已有词\n", encoding="utf-8")
    (tmp_path / "combat.txt").write_text("斩杀\n", encoding="utf-8")
    (tmp_path / "sensory.txt").write_text("香气\n", encoding="utf-8")
    additions = update_lexicons_from_texts(["宿命" * 3 + "青云宗" * 3], tmp_path, apply=True)
    content = path.read_text(encoding="utf-8")
    assert "已有词" in content
    # apply 只写非空类别
    if additions["semantic_category"]:
        assert additions["semantic_category"][0] in content


def test_update_lexicons_from_texts_without_apply(tmp_path: Path) -> None:
    (tmp_path / "registry.yaml").write_text(_REGISTRY_TEMPLATE, encoding="utf-8")
    path = tmp_path / "semantic_category.txt"
    path.write_text("已有词\n", encoding="utf-8")
    (tmp_path / "combat.txt").write_text("斩杀\n", encoding="utf-8")
    (tmp_path / "sensory.txt").write_text("香气\n", encoding="utf-8")
    update_lexicons_from_texts(["宿命" * 3], tmp_path, apply=False)
    assert path.read_text(encoding="utf-8") == "已有词\n"
