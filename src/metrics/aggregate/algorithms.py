"""读侧算法与数值方法（《分析能力扩展路线图》赛道 A1/A2/A3、§5.11 D2、§13.1）

从 `src/api/services/results_queries/` 收归的纯计算：图结构指标、TextRank 关键词、
主题分布 JS 散度与变化候选、展示平滑与曲线保点。全部函数只依赖快照/行数据与
配置，不依赖 API 响应模型——调用方负责取数与装配。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import networkx as nx
import networkx.algorithms.community as nx_comm
import numpy as np
from loguru import logger
from sqlalchemy.orm import Session

from src.config import settings
from src.lexicons.tables import STOPWORDS_TERMS
from src.metrics.robust_smooth import robust_local_regression
from src.storage.repositories import ParagraphRepository
from src.utils.text_utils import split_sentences, tokenize_words

GRAPH_METRICS_VERSION = "graph-metrics-v1"
KEYWORD_ALGORITHM_VERSION = "textrank-v1"
WINDOW_SIZE = 5
MIN_WORD_LENGTH = 2


class InsufficientGraphNodesError(ValueError):
    """代表性格据少于 2 个节点，图结构指标无从计算"""


def safe_ratio(numerator: float, denominator: float) -> float | None:
    """分母 <= 0 时返回 None（§15.2：分母为零不伪造数值）"""
    if denominator <= 0:
        return None
    return numerator / denominator


def clamp_coverage(value: float | None) -> float | None:
    """2026-08-15 将后端平滑覆盖率限制在可解释的 0~1 值域"""
    if value is None:
        return None
    return max(0.0, min(1.0, value))


def _undirected_edge_key(source: str, target: str) -> tuple[str, str]:
    """2026-08-31 用于把双向端点规范为同一个无向边键并保留并行关系计数"""
    return (source, target) if source <= target else (target, source)


def compute_graph_structure_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    """PageRank / HITS / Louvain 结构指标（赛道 A1/A2）

    输入为代表性格据快照（与 /graph 端点同一视图：别名归并、去 same_character
    与自环），无向 + 边权=关系计数；算法结果只表示结构信号，
    不解释为故事阵营或正式人物重要性结论。
    """
    character_names = {node["name"] for node in snapshot["nodes"] if node["entity_type"] == "character"}
    edge_counts: Counter[tuple[str, str]] = Counter(
        _undirected_edge_key(edge["source_name"], edge["target_name"])
        for edge in snapshot["edges"]
        if edge["source_name"] in character_names and edge["target_name"] in character_names
    )
    graph = nx.Graph()
    graph.add_nodes_from(character_names)
    for (source, target), count in edge_counts.items():
        graph.add_edge(source, target, weight=count)
    if graph.number_of_nodes() < 2:
        raise InsufficientGraphNodesError("人物节点少于 2 个，无法计算图结构指标")

    metrics: dict[str, Any] = {
        "algorithm": {
            "version": GRAPH_METRICS_VERSION,
            "graph": {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "directed": False,
                "edge_weight": "relation_count",
                "alias_merge": "resolve_name",
                "same_character_filter": True,
            },
        }
    }

    pagerank_scores = nx.pagerank(graph, weight="weight")
    metrics["pagerank"] = {name: round(score, 6) for name, score in pagerank_scores.items()}

    try:
        hub_scores, authority_scores = nx.hits(graph)
        metrics["hits"] = {
            "authority": {name: round(score, 6) for name, score in authority_scores.items()},
            "hub": {name: round(score, 6) for name, score in hub_scores.items()},
        }
    except (nx.PowerIterationFailedConvergence, ValueError, ZeroDivisionError) as exc:
        logger.warning("HITS 未收敛，authority/hub 返回空: {}", exc)
        metrics["hits"] = {"authority": {}, "hub": {}, "unavailable_reason": f"hits_not_converged: {exc}"}

    try:
        communities = nx_comm.louvain_communities(graph, weight="weight", seed=42)
        modularity = nx_comm.modularity(graph, communities, weight="weight")
        metrics["communities"] = {
            "community_ids": {
                name: community_id for community_id, community in enumerate(communities) for name in community
            },
            "modularity": round(float(modularity), 6),
            # 结构社区不直接等同于故事阵营（§A2 解释边界）
            "interpretation": "structural_community_only",
        }
    except ValueError as exc:
        logger.warning("Louvain 社区发现失败: {}", exc)
        metrics["communities"] = {"community_ids": {}, "modularity": None, "unavailable_reason": str(exc)}

    return metrics


def compute_keywords(run_id: str, session: Session, top_n: int = 10) -> dict[str, Any]:
    """段落全文的 TextRank 关键词（Top-N 词 + 权重，赛道 A3）

    在独立词共现图上计算（窗口 5 共现 + PageRank），不与人物关系图混用；
    停用词来自 Registry v3 的 stopwords.txt。关键词只表示词共现结构信号，
    与 LDA 主题词可对照但口径独立。
    """
    paragraph_repo = ParagraphRepository(session)
    rows = paragraph_repo.fetch_paragraph_rows(run_id)
    algorithm = {"version": KEYWORD_ALGORITHM_VERSION, "window": WINDOW_SIZE, "top_n": top_n}
    if not rows:
        return {
            "run_id": run_id,
            "keywords": [],
            "algorithm": algorithm,
            "unavailable_reason": "no_paragraphs: 无段落事实源",
        }

    stopwords = set(STOPWORDS_TERMS)
    tokens: list[str] = []
    for row in rows:
        for sentence in split_sentences(row.text):
            tokens.extend(
                word for word in tokenize_words(sentence) if len(word) >= MIN_WORD_LENGTH and word not in stopwords
            )

    # 词共现图（窗口 5，滑动窗口内两两共现计数）
    cooccurrence: defaultdict[tuple[str, str], int] = defaultdict(int)
    for i in range(len(tokens) - WINDOW_SIZE + 1):
        window = tokens[i : i + WINDOW_SIZE]
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
            "algorithm": algorithm,
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
        "algorithm": {**algorithm, "vocab_count": graph.number_of_nodes()},
        "unavailable_reason": None,
    }


def kl_divergence_log2(p: np.ndarray, q: np.ndarray) -> float:
    """p log2(p/q)，p == 0 处贡献为 0；q 在 p > 0 处恒正（由 m 构造保证）"""
    mask = p > 0
    return float(np.sum(p[mask] * np.log2(p[mask] / q[mask])))


def jensen_shannon_divergence(p: list[float] | np.ndarray, q: list[float] | np.ndarray) -> float:
    """
    以 2 为底、范围 [0, 1] 的 JS 散度（§5.11 D2 的 topic_shift_score 定义）

    若调用 SciPy jensenshannon 返回的是距离，需平方一次才是散度；
    本实现直接按散度定义计算，避免依赖与二次方修正。
    """
    p_arr = np.asarray(p, dtype=np.float64)
    q_arr = np.asarray(q, dtype=np.float64)
    if p_arr.shape != q_arr.shape or p_arr.size == 0:
        raise ValueError("JS 散度需要同维、非空的概率向量")
    midpoint = 0.5 * (p_arr + q_arr)
    return 0.5 * (kl_divergence_log2(p_arr, midpoint) + kl_divergence_log2(q_arr, midpoint))


def shift_config(window_size: int, min_tokens: int, threshold: float, max_candidates: int) -> dict[str, Any]:
    return {
        "window_size": window_size,
        "min_tokens_per_window": min_tokens,
        "score_threshold": threshold,
        "max_candidates": max_candidates,
    }


def compute_topic_shift_candidates(
    series: dict[str, Any],
    *,
    window_size: int | None = None,
    min_tokens_per_window: int | None = None,
    score_threshold: float | None = None,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    """
    主题变化候选点（D2）：相邻不重叠窗口的归一化主题分布 JS 散度

    窗口分布 = 窗口内段落权重的入模 token 加权平均；窗口实际入模 token
    总数低于 min_tokens_per_window 时跳过，避免极短段落制造高噪声尖峰。
    候选点位置取前窗口最后一段的字符结束位置。
    """
    shift_settings = settings.topic_model.topic_shift
    window_size = window_size if window_size is not None else shift_settings.window_size
    min_tokens = min_tokens_per_window if min_tokens_per_window is not None else shift_settings.min_tokens_per_window
    threshold = score_threshold if score_threshold is not None else shift_settings.score_threshold
    max_candidates = max_candidates if max_candidates is not None else shift_settings.max_candidates

    # 2026-08-31 API 参数虽有 FastAPI 约束，服务函数仍需保护直接调用入口
    if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 1:
        raise ValueError(f"window_size 必须是 >=1 的整数，当前值: {window_size!r}")
    if isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or min_tokens < 1:
        raise ValueError(f"min_tokens_per_window 必须是 >=1 的整数，当前值: {min_tokens!r}")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ValueError(f"score_threshold 必须在 (0, 1] 区间内，当前值: {threshold!r}")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 1:
        raise ValueError(f"max_candidates 必须是 >=1 的整数，当前值: {max_candidates!r}")

    points = series.get("points") or []
    if len(points) < 2:
        return {
            "unavailable_reason": "insufficient_windows: 段落样本不足，无法构成至少两个窗口",
            "candidates": [],
            "config": shift_config(window_size, min_tokens, threshold, max_candidates),
        }

    window_aggs: list[tuple[int, int, np.ndarray, float]] = []
    i = 0
    n = len(points)
    while i < n:
        end = min(i + window_size, n)
        tokens = np.array([float(p["token_count"]) for p in points[i:end]], dtype=np.float64)
        token_total = float(tokens.sum())
        if token_total >= min_tokens:
            weights = np.array([p["weights"] for p in points[i:end]], dtype=np.float64)
            weighted_sum = np.sum(weights * tokens[:, None], axis=0)
            window_dist = weighted_sum / token_total
            window_aggs.append((i, end - 1, window_dist, token_total))
        i = end

    candidates: list[dict[str, Any]] = []
    for left, right in zip(window_aggs, window_aggs[1:], strict=False):
        if len(candidates) >= max_candidates:
            break
        score = jensen_shannon_divergence(left[2], right[2])
        if score < threshold:
            continue
        candidates.append(
            {
                "position": int(points[right[0]]["start_position"]),
                "paragraph_start": points[left[0]]["paragraph_id"],
                "paragraph_end": points[left[1]]["paragraph_id"],
                "score": round(float(score), 6),
                "window_token_total": int(left[3]),
            }
        )

    return {
        "unavailable_reason": None if candidates else "no_candidates: 相邻窗口未达到阈值",
        "candidates": candidates,
        "config": shift_config(window_size, min_tokens, threshold, max_candidates),
    }


def smooth_emotion_series(
    values: list[float | None],
    *,
    positions: list[float],
    weights: list[float],
) -> list[float | None]:
    """2026-08-15 用于对单条窗口序列执行 LOWESS 展示平滑

    平滑参数取 settings.metrics（带宽 / 最小点数）；返回与输入等长的序列，
    无法拟合的槽位保持 None。调用方负责保留原始值，避免平滑覆盖可审计数据。
    """
    valid = [(index, value) for index, value in enumerate(values) if value is not None]
    if not valid:
        return [None] * len(values)
    min_points = int(getattr(settings.metrics, "lowess_min_points", 7) or 7)
    bandwidth = float(getattr(settings.metrics, "lowess_bandwidth", 0.02) or 0.02)
    fitted = robust_local_regression(
        [positions[index] for index, _ in valid],
        [float(value) for _, value in valid],
        weights=[weights[index] for index, _ in valid],
        bandwidth=bandwidth,
        min_points=min_points,
    )
    mapped: list[float | None] = [None] * len(values)
    for (index, _), value in zip(valid, fitted, strict=True):
        mapped[index] = float(value)
    return mapped


def must_keep_curve_indices(
    chapter_ids: list[int],
    net_densities: list[float | None],
) -> list[int]:
    """章节边界（每章首个与末个段落）+ net_density 全局峰值索引（None 按 0）

    曲线降采样时这些点必须保留，避免章节切分与峰值在传输层被抹平（§13.1）。
    """
    keep_set: set[int] = set()
    chapter_first_last: dict[int, list[int]] = {}
    for index, chapter_id in enumerate(chapter_ids):
        bounds = chapter_first_last.setdefault(chapter_id, [index, index])
        bounds[1] = index
    for first_index, last_index in chapter_first_last.values():
        keep_set.add(first_index)
        keep_set.add(last_index)

    best_index = -1
    best_value: float | None = None
    for index, raw_value in enumerate(net_densities):
        value = float(raw_value) if raw_value is not None else 0.0
        if best_value is None or value > best_value:
            best_value = value
            best_index = index
    if best_index >= 0:
        keep_set.add(best_index)

    return sorted(keep_set)
