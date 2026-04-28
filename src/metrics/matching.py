"""
增强匹配模块 (Enhanced Matching v2)

提供两种匹配模式:
  - phrase 模式: 子串匹配 + token 匹配，处理未登录词（如"冷笑""道心破碎"）
  - fuzzy 模式: 在 phrase 基础上增加编辑距离容错，处理分词变体（如"剑气"/"剑罡"）

设计原则:
  - phrase 模式为默认模式
  - 复用现有基础设施: _count_non_overlapping_spans 已在 lexicon_metrics 中实现


"""

from __future__ import annotations

from collections.abc import Sequence


def count_token_hits_enhanced(
    text: str,
    tokens: Sequence[str],
    terms: Sequence[str],
    mode: str = "phrase",
) -> int:
    """
    多模式词条命中计数。

    Args:
        text: 原始文本
        tokens: 分词后的 token 序列
        terms: 词条集合
        mode: 匹配模式
            - "phrase":  子串匹配 + token 匹配，处理未登录词（默认）
            - "fuzzy":   在 phrase 基础上增加编辑距离容错

    Returns:
        命中次数
    """
    if not tokens or not terms:
        return 0

    term_set = {t for t in terms if t}
    if not term_set:
        return 0

    if mode == "phrase":
        return _count_phrase_hits(text, tokens, term_set)

    if mode == "fuzzy":
        return _count_fuzzy_hits(text, tokens, term_set)

    raise ValueError(f"Unknown match mode: {mode}, expected 'phrase' or 'fuzzy'")


def _count_phrase_hits(text: str, tokens: Sequence[str], term_set: set[str]) -> int:
    """
    短语级匹配: 同时支持子串匹配和 token 匹配。

    策略:
      1. 长词优先匹配（避免短词吞掉长词的一部分）
      2. 已匹配的文本区间不再重复计数（非重叠 span）
      3. 单字 token 不参与子串匹配（减少噪音）
    """
    from .lexicon_metrics import _count_non_overlapping_spans

    counts = _count_non_overlapping_spans(text, term_set, tokens)
    return sum(counts.values())


def _count_fuzzy_hits(text: str, tokens: Sequence[str], term_set: set[str], max_edit_distance: int = 1) -> int:
    """
    模糊匹配: 在短语匹配基础上增加编辑距离容错。

    对于每个未命中的 token，检查是否与某个词条的编辑距离 ≤ max_edit_distance。
    仅对长度 ≥ 2 的 token/词条做模糊匹配（单字模糊无意义）。

    性能注意: 此模式比 phrase 慢约 3-5x，
              仅建议用于 tension 相关指标等关键路径。
    """
    base_count = _count_phrase_hits(text, tokens, term_set)

    fuzzy_hits = 0
    matched_tokens = set()

    for token in tokens:
        if not token or len(token) < 2 or token in term_set or token in matched_tokens:
            continue

        for term in term_set:
            if len(term) < 2:
                continue
            if _edit_distance(token, term) <= max_edit_distance:
                fuzzy_hits += 1
                matched_tokens.add(token)
                break

    return base_count + fuzzy_hits


def _edit_distance(s1: str, s2: str) -> int:
    """
    计算 Levenshtein 编辑距离。

    使用空间优化的 DP 实现（O(min(m,n)) 空间）。
    """
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))

    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]
