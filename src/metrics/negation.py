"""
否定处理共享计算层（docs/词表体系重设计-修订版实施计划.md M5）

供生产路径 `paragraph_metrics.compute_paragraph_metric_counts` 与
`emotion_metrics.lexical_sentiment_density` 共用，杜绝两处否定逻辑漂移。

规则：
1. 句边界：否定词必须与情绪词在同一句（句界为 。！？!? 与换行）
2. longest-match 去重：复合否定词优先匹配，非重叠 span 单词只计一次
3. 最近距离约束：否定 span 结束位置与情绪词起点之间 ≤1 个 token；
   例外——否定词位于小句开头（前文自上个分句界起仅标点/引号）时管辖整个
   小句，距离约束不适用；但否定与情绪词之间出现分句界（，、；：）或"的"
   （定语修饰，如"不灭的最后希望"）仍不翻转
4. 否定词分类（negation_words.txt 分组注释）：
   - hard   —— 参与翻转计数（单次计 1）
   - modal  —— 情态/推测标记（未必/莫非/难以…），不翻转极性
   - double —— 双重否定词组（不得不…），计 2 次，奇偶抵消
   - scope  —— VP 辖制否定（舍不得/不舍得…），辖制同小句内其后动词短语，
               不适用距离约束；分句界或"的"（定语）仍阻断
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.utils.text_utils import tokenize_words

_SECTION_PATTERN = "====="
_CLAUSE_BOUNDARY_CHARS = "，、；：,;:"
_QUOTE_CHARS = " \t'\"“”‘’…—"


def _span_at_clause_start(prefix: str, span: NegationSpan) -> bool:
    """否定 span 是否位于小句开头：自上一个分句界（，、；：）起仅标点/引号/空白"""
    head = prefix[: span.start]
    if not head:
        return True
    last_boundary = max(head.rfind(c) for c in _CLAUSE_BOUNDARY_CHARS)
    if last_boundary < 0:
        tail = head
    else:
        tail = head[last_boundary + 1 :]
    return not tail.strip(_QUOTE_CHARS)


@dataclass(frozen=True)
class NegationSpec:
    """否定词分类集合"""

    hard: frozenset[str]
    modal: frozenset[str]
    double: frozenset[str]
    scope: frozenset[str] = frozenset()

    @property
    def all_words(self) -> tuple[str, ...]:
        """全部否定词，按长度降序（longest-match 优先）"""
        return tuple(sorted(self.hard | self.modal | self.double | self.scope, key=len, reverse=True))


@dataclass(frozen=True)
class NegationSpan:
    """句内否定 span（[start, end) 字符区间）"""

    start: int
    end: int
    word: str
    kind: str  # hard | modal | double | scope


def _parse_spec(lines: list[str]) -> NegationSpec:
    hard: set[str] = set()
    modal: set[str] = set()
    double: set[str] = set()
    scope: set[str] = set()
    current: set[str] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") and _SECTION_PATTERN not in stripped:
            continue
        if stripped.startswith("#") and _SECTION_PATTERN in stripped:
            if "hard" in stripped:
                current = hard
            elif "modal" in stripped:
                current = modal
            elif "double" in stripped:
                current = double
            elif "scope" in stripped:
                current = scope
            else:
                current = None
            continue
        if current is not None:
            current.add(stripped)
    return NegationSpec(
        hard=frozenset(hard),
        modal=frozenset(modal),
        double=frozenset(double),
        scope=frozenset(scope),
    )


@lru_cache(maxsize=4)
def load_negation_spec(filepath: str | Path | None = None) -> NegationSpec:
    """
    加载否定词分类

    默认经注册表解析 data/lexicons/negation_words.txt（v3 唯一事实源）；
    显式 filepath 用于测试。
    """
    if filepath is None:
        from src.lexicons.registry import LexiconRegistry

        filepath = LexiconRegistry().get_file_paths("negation_words.txt")[0]
    with open(filepath, encoding="utf-8") as f:
        return _parse_spec(f.readlines())


def find_negation_spans(sentence: str, spec: NegationSpec) -> list[NegationSpan]:
    """
    句内否定 span 提取：longest-match（长度降序）非重叠匹配

    每个字符位置只归属一个最长命中词；复合词优先于其子串
    （"并没有"命中后，"并不"/"没有"/"没"/"不"不再重复计）。
    """
    spans: list[NegationSpan] = []
    occupied: list[bool] = [False] * len(sentence)
    word_kind: dict[str, str] = {}
    for word in spec.hard:
        word_kind[word] = "hard"
    for word in spec.modal:
        word_kind[word] = "modal"
    for word in spec.double:
        word_kind[word] = "double"
    for word in spec.scope:
        word_kind[word] = "scope"

    for word in spec.all_words:
        start = 0
        while True:
            idx = sentence.find(word, start)
            if idx < 0:
                break
            end = idx + len(word)
            # 该区间未被更长词占用则登记
            if not any(occupied[idx:end]):
                for i in range(idx, end):
                    occupied[i] = True
                spans.append(NegationSpan(start=idx, end=end, word=word, kind=word_kind[word]))
            start = idx + 1
    return sorted(spans, key=lambda s: s.start)


def _sentence_start(text: str, position: int) -> int:
    """定位 position 所在句的起点（句界：。！？!? 与换行）"""
    start = -1
    for marker in ("。", "！", "？", "!", "?", "\n"):
        idx = text.rfind(marker, 0, position)
        if idx > start:
            start = idx
    return start + 1


def is_flipped(text: str, emotion_start: int, spec: NegationSpec | None = None) -> bool:
    """
    判定情绪词是否被否定翻转

    规则：同一句内 + 否定 span 结束与情绪词起点之间 ≤1 token（小句首 hard 与
    scope 类除外）+ 有效否定数奇偶（有效否定数 = hard/scope 命中数 + double 命中数 ×2；
    modal 不参与）。
    """
    if emotion_start <= 0:
        return False
    if spec is None:
        spec = load_negation_spec()

    sent_start = _sentence_start(text, emotion_start)
    prefix = text[sent_start:emotion_start]
    if not prefix:
        return False

    spans = find_negation_spans(prefix, spec)
    if not spans:
        return False

    effective = 0
    for span in spans:
        if span.kind == "modal":
            continue
        gap = prefix[span.end :]
        if span.kind == "scope":
            # VP 辖制否定（舍不得/不舍得）：辖制同小句内其后动词短语，
            # 不适用距离约束；分句界或"的"（定语）仍阻断
            if any(c in gap for c in _CLAUSE_BOUNDARY_CHARS) or "的" in gap:
                continue
            effective += 1
            continue
        gap_tokens = tokenize_words(gap) if gap else []
        if len(gap_tokens) > 1:
            # 距离约束例外：小句首否定词（并没有/没有/不要…）管辖整个小句，
            # 但否定与情绪词之间出现分句界（，、；：）仍视为出界（计划 §5.2 例 3）；
            # 含"的"为定语修饰（不灭的/没察觉的），否定只辖相邻词，不翻转
            if not _span_at_clause_start(prefix, span) or any(c in gap for c in _CLAUSE_BOUNDARY_CHARS) or "的" in gap:
                continue
        if span.kind == "double":
            effective += 2
        else:
            effective += 1
    return effective % 2 == 1
