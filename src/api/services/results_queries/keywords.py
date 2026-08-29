"""TextRank 关键词提取查询（《分析能力扩展路线图》赛道 A3）

在独立词共现图上查询时计算（窗口 5 共现 + PageRank），不与人物关系图
混用；停用词来自 Registry v3 的 stopwords.txt。关键词只表示词共现结构
信号，与 LDA 主题词可对照但口径独立。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import networkx as nx
from sqlalchemy.orm import Session

from src.lexicons.tables import STOPWORDS_TERMS
from src.storage.repositories import ParagraphRepository
from src.utils.text_utils import split_sentences, tokenize_words

_ALGORITHM_VERSION = "textrank-v1"
_WINDOW_SIZE = 5
_MIN_WORD_LENGTH = 2


def compute_keywords(run_id: str, session: Session, top_n: int = 10) -> dict[str, Any]:
    """段落全文的 TextRank 关键词（Top-N 词 + 权重）"""
    paragraph_repo = ParagraphRepository(session)
    rows = paragraph_repo.fetch_paragraph_rows(run_id)
    if not rows:
        return {
            "run_id": run_id,
            "keywords": [],
            "algorithm": {"version": _ALGORITHM_VERSION, "window": _WINDOW_SIZE, "top_n": top_n},
            "unavailable_reason": "no_paragraphs: 无段落事实源",
        }

    stopwords = set(STOPWORDS_TERMS)
    tokens: list[str] = []
    for row in rows:
        for sentence in split_sentences(row.text):
            tokens.extend(
                word
                for word in tokenize_words(sentence)
                if len(word) >= _MIN_WORD_LENGTH and word not in stopwords
            )

    # 词共现图（窗口 5，滑动窗口内两两共现计数）
    cooccurrence: defaultdict[tuple[str, str], int] = defaultdict(int)
    for i in range(len(tokens) - _WINDOW_SIZE + 1):
        window = tokens[i : i + _WINDOW_SIZE]
        for j, first in enumerate(window):
            for second in window[j + 1 :]:
                if first != second:
                    key = (first, second) if first < second else (second, first)
                    cooccurrence[key] += 1

    graph = nx.Graph()
    if not cooccurrence:
        return {
            "run_id": run_id,
            "keywords": [],
            "algorithm": {"version": _ALGORITHM_VERSION, "window": _WINDOW_SIZE, "top_n": top_n},
            "unavailable_reason": "no_cooccurrence: 过滤停用词后无可建图词元",
        }
    for (first, second), count in cooccurrence.items():
        graph.add_edge(first, second, weight=count)

    scores = nx.pagerank(graph, weight="weight")
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_n]
    keywords = [{"word": word, "score": round(score, 6)} for word, score in ranked]
    return {
        "run_id": run_id,
        "keywords": keywords,
        "algorithm": {
            "version": _ALGORITHM_VERSION,
            "window": _WINDOW_SIZE,
            "top_n": top_n,
            "vocab_count": graph.number_of_nodes(),
        },
        "unavailable_reason": None,
    }