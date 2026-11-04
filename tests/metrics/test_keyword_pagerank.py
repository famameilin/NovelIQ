"""验证关键词共现图的 PageRank 与标准加权图结果一致"""

import networkx as nx
import pytest

from src.metrics.aggregate.algorithms import _keyword_pagerank


@pytest.mark.parametrize(
    "edges",
    [
        {("甲", "乙"): 1},
        {("甲", "乙"): 1, ("乙", "丙"): 1, ("丙", "甲"): 1},
        {("丁", "甲"): 7, ("乙", "丁"): 3, ("甲", "乙"): 1, ("戊", "己"): 2},
        {("甲", "乙"): 1, ("甲", "丙"): 1, ("甲", "丁"): 1, ("甲", "戊"): 1},
    ],
)
def test_keyword_scores_match_weighted_networkx_with_stable_ties(edges):
    graph = nx.Graph()
    for (left, right), weight in edges.items():
        graph.add_edge(left, right, weight=weight)
    expected = nx.pagerank(graph, weight="weight")

    actual = _keyword_pagerank(edges)

    assert list(actual) == list(expected)
    assert actual == pytest.approx(expected, abs=1e-15)
    assert sorted(actual, key=actual.__getitem__, reverse=True) == sorted(
        expected, key=expected.__getitem__, reverse=True
    )
