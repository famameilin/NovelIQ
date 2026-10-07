"""读侧统计聚合（设计文档《章节粒度分析指标重设计》§8、§13.1、§13.2）

2026-10-06 自 `src/api/services/results_queries/` 收归读侧聚合模块：章节/全书指标、
情绪趋势窗口、角色榜与叙事焦点评分。全部函数只吃行数据与纯 dict，返回纯 dict 载荷，
响应模型装配留在 api 读侧。

聚合口径（§8）：
- 比率一律分子/分母聚合，禁止平均段落密度（§8.1）
- 句长均值/方差从充分统计量（count/sum/sum_sq）恢复（§8.2）
- TTR/MTLD 等非可加指标在目标文本序列上直接计算（§8.3）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.metrics.aggregate.algorithms import safe_ratio
from src.metrics.aggregate.normalization import read_emotion_score
from src.metrics.style_metrics import mtld, ttr
from src.text_processing.tokenize import tokenize
from src.utils.character_reference_policy import decide_character_reference


@dataclass
class ChapterAccumulator:
    """章节分子/分母与充分统计量累加器（§8.1/8.2）"""

    chapter_id: int
    paragraph_count: int = 0
    total_chars: int = 0
    total_tokens: int = 0
    positive_weight_sum: float = 0.0
    negative_weight_sum: float = 0.0
    fight_weight_sum: float = 0.0
    exclaim_count: int = 0
    question_count: int = 0
    pause_count: int = 0
    dialogue_char_count: int = 0
    sentence_count: int = 0
    sentence_char_sum: float = 0.0
    sentence_char_sum_sq: float = 0.0
    texts: list[str] = field(default_factory=list)


def aggregate_chapter_metrics(
    paragraph_rows: Any,
    metric_rows: Any,
    annotations_by_chapter_id: dict[int, Any],
) -> dict[str, Any]:
    """
    章节汇总 + 全书聚合（§13.2）

    - 段落与指标按 paragraph_id 对齐，缺任一侧的段落跳过
    - 章节/全书 TTR、MTLD 在拼接后的章节/全书文本上直接计算一次
    - 章节标签取调用方给定的章节标注映射，无标注的章节对应字段为 None
    """
    metric_by_paragraph_id = {int(row.paragraph_id): row for row in metric_rows}
    chapters_by_id: dict[int, ChapterAccumulator] = {}
    for paragraph_row in paragraph_rows:
        metric_row = metric_by_paragraph_id.get(int(paragraph_row.paragraph_id))
        if metric_row is None:
            continue
        chapter_id = int(paragraph_row.chapter_id)
        accumulator = chapters_by_id.setdefault(chapter_id, ChapterAccumulator(chapter_id=chapter_id))
        accumulator.paragraph_count += 1
        accumulator.total_chars += int(paragraph_row.char_count)
        accumulator.total_tokens += int(metric_row.token_count)
        accumulator.positive_weight_sum += float(metric_row.positive_weight_sum)
        accumulator.negative_weight_sum += float(metric_row.negative_weight_sum)
        accumulator.fight_weight_sum += float(metric_row.fight_weight_sum)
        accumulator.exclaim_count += int(metric_row.exclaim_count)
        accumulator.question_count += int(metric_row.question_count)
        accumulator.pause_count += int(metric_row.pause_count)
        accumulator.dialogue_char_count += int(metric_row.dialogue_char_count)
        accumulator.sentence_count += int(metric_row.sentence_count)
        accumulator.sentence_char_sum += float(metric_row.sentence_char_sum)
        accumulator.sentence_char_sum_sq += float(metric_row.sentence_char_sum_sq)
        accumulator.texts.append(str(paragraph_row.text))

    chapters = [
        build_chapter_summary(accumulator, annotations_by_chapter_id.get(accumulator.chapter_id))
        for accumulator in chapters_by_id.values()
    ]
    return {"chapters": chapters, "book": build_book_aggregate(chapters, chapters_by_id)}


def build_chapter_summary(accumulator: ChapterAccumulator, annotation: Any | None) -> dict[str, Any]:
    """单章汇总载荷（TTR/MTLD 在本章拼接文本上计算）"""
    tokens = tokenize("".join(accumulator.texts)) if accumulator.texts else []
    sentence_mean = safe_ratio(accumulator.sentence_char_sum, accumulator.sentence_count)
    sentence_var: float | None = None
    if accumulator.sentence_count > 0 and sentence_mean is not None:
        sentence_var = max(
            0.0,
            accumulator.sentence_char_sum_sq / accumulator.sentence_count - sentence_mean * sentence_mean,
        )
    return {
        "chapter_id": accumulator.chapter_id,
        "paragraph_count": accumulator.paragraph_count,
        "total_chars": accumulator.total_chars,
        "total_tokens": accumulator.total_tokens,
        "pos_density": safe_ratio(accumulator.positive_weight_sum, accumulator.total_tokens),
        "neg_density": safe_ratio(accumulator.negative_weight_sum, accumulator.total_tokens),
        "net_density": safe_ratio(
            accumulator.positive_weight_sum - accumulator.negative_weight_sum,
            accumulator.total_tokens,
        ),
        "fight_density": safe_ratio(accumulator.fight_weight_sum, accumulator.total_tokens),
        "exclaim_per_100_chars": safe_ratio(accumulator.exclaim_count * 100.0, accumulator.total_chars),
        "question_per_100_chars": safe_ratio(accumulator.question_count * 100.0, accumulator.total_chars),
        "pause_per_100_chars": safe_ratio(accumulator.pause_count * 100.0, accumulator.total_chars),
        "dialogue_ratio": safe_ratio(accumulator.dialogue_char_count, accumulator.total_chars),
        "avg_sent_len": sentence_mean,
        "sent_len_std": math.sqrt(sentence_var) if sentence_var is not None else None,
        "ttr": ttr(tokens) if tokens else None,
        "mtld": mtld(tokens) if tokens else None,
        "narrative_function": (
            str(annotation.event_type) if annotation is not None and annotation.event_type else None
        ),
        "pivot_moment": (
            bool(annotation.pivot_moment) if annotation is not None and annotation.pivot_moment is not None else None
        ),
        "cliffhanger": (
            bool(annotation.cliffhanger) if annotation is not None and annotation.cliffhanger is not None else None
        ),
        "emotional_valence": (
            read_emotion_score(annotation.emotional_valence)
            if annotation is not None and annotation.emotional_valence is not None
            else None
        ),
    }


def build_book_aggregate(
    chapter_metrics: list[dict[str, Any]],
    chapters_by_id: dict[int, ChapterAccumulator],
) -> dict[str, Any]:
    """全书聚合载荷（比例分母只计有效章节，不用零值伪造）"""
    total_chapters = len(chapter_metrics)
    total_paragraphs = sum(item["paragraph_count"] for item in chapter_metrics)
    total_chars = sum(item["total_chars"] for item in chapter_metrics)
    total_tokens = sum(item["total_tokens"] for item in chapter_metrics)
    positive_weight_sum = sum(acc.positive_weight_sum for acc in chapters_by_id.values())
    negative_weight_sum = sum(acc.negative_weight_sum for acc in chapters_by_id.values())
    fight_weight_sum = sum(acc.fight_weight_sum for acc in chapters_by_id.values())
    exclaim_count = sum(acc.exclaim_count for acc in chapters_by_id.values())
    question_count = sum(acc.question_count for acc in chapters_by_id.values())
    pause_count = sum(acc.pause_count for acc in chapters_by_id.values())
    dialogue_char_count = sum(acc.dialogue_char_count for acc in chapters_by_id.values())
    sentence_count = sum(acc.sentence_count for acc in chapters_by_id.values())
    sentence_char_sum = sum(acc.sentence_char_sum for acc in chapters_by_id.values())
    sentence_char_sum_sq = sum(acc.sentence_char_sum_sq for acc in chapters_by_id.values())

    book_text = "".join(text for acc in chapters_by_id.values() for text in acc.texts)
    book_tokens = tokenize(book_text) if book_text else []

    sentence_mean = safe_ratio(sentence_char_sum, sentence_count)
    sentence_var: float | None = None
    if sentence_count > 0 and sentence_mean is not None:
        sentence_var = max(0.0, sentence_char_sum_sq / sentence_count - sentence_mean * sentence_mean)

    narrative_share: dict[str, float] = {}
    valence_share: dict[int, float] = {}
    pivot_chapters = 0
    pivot_valid_chapters = 0
    cliffhanger_chapters = 0
    cliffhanger_valid_chapters = 0
    narrative_valid_chapters = 0
    valence_valid_chapters = 0
    for chapter in chapter_metrics:
        if chapter["narrative_function"]:
            narrative_valid_chapters += 1
            narrative_share[chapter["narrative_function"]] = (
                narrative_share.get(chapter["narrative_function"], 0.0) + 1.0
            )
        if chapter["emotional_valence"] is not None:
            valence_valid_chapters += 1
            valence_share[chapter["emotional_valence"]] = valence_share.get(chapter["emotional_valence"], 0.0) + 1.0
        if chapter["pivot_moment"] is not None:
            pivot_valid_chapters += 1
            if chapter["pivot_moment"]:
                pivot_chapters += 1
        if chapter["cliffhanger"] is not None:
            cliffhanger_valid_chapters += 1
            if chapter["cliffhanger"]:
                cliffhanger_chapters += 1

    if narrative_valid_chapters > 0:
        narrative_share = {
            label: round(count / narrative_valid_chapters, 6) for label, count in narrative_share.items()
        }
    if valence_valid_chapters > 0:
        valence_share = {label: round(count / valence_valid_chapters, 6) for label, count in valence_share.items()}

    return {
        "total_chapters": total_chapters,
        "total_paragraphs": total_paragraphs,
        "total_chars": total_chars,
        "total_tokens": total_tokens,
        "pos_density": safe_ratio(positive_weight_sum, total_tokens),
        "neg_density": safe_ratio(negative_weight_sum, total_tokens),
        "net_density": safe_ratio(positive_weight_sum - negative_weight_sum, total_tokens),
        "fight_density": safe_ratio(fight_weight_sum, total_tokens),
        "exclaim_per_100_chars": safe_ratio(exclaim_count * 100.0, total_chars),
        "question_per_100_chars": safe_ratio(question_count * 100.0, total_chars),
        "pause_per_100_chars": safe_ratio(pause_count * 100.0, total_chars),
        "dialogue_ratio": safe_ratio(dialogue_char_count, total_chars),
        "avg_sent_len": sentence_mean,
        "sent_len_std": math.sqrt(sentence_var) if sentence_var is not None else None,
        "ttr": ttr(book_tokens) if book_tokens else None,
        "mtld": mtld(book_tokens) if book_tokens else None,
        "chapter_narrative_function_share": narrative_share,
        "chapter_pivot_rate": (pivot_chapters / pivot_valid_chapters if pivot_valid_chapters > 0 else None),
        "chapter_cliffhanger_rate": (
            cliffhanger_chapters / cliffhanger_valid_chapters if cliffhanger_valid_chapters > 0 else None
        ),
        "chapter_emotional_valence_share": valence_share,
    }


def aggregate_emotion_trend_windows(
    paragraph_rows: Any,
    metric_rows: Any,
    *,
    range_start: float | None,
    range_end: float | None,
    window_paragraphs: int,
) -> list[dict[str, Any]]:
    """
    情绪趋势窗口聚合（§13.1 展示层，缩放自适应窗口）

    - 输入为段落充分统计量（paragraphs + paragraph_metrics 对齐），
      命中判定用原始分子（positive_weight_sum/negative_weight_sum > 0），
      请求时无词典/分词开销
    - 每窗段落数 window_paragraphs 作用于 range 过滤后的段落集，服务端钳制到 5~40
    - 覆盖率为命中段占比；池化密度为分子/分母聚合（§8.1），分母为零返回 None
    - 窗口载荷含 token_total，供调用方做加权展示平滑
    """
    metric_by_paragraph_id = {int(row.paragraph_id): row for row in metric_rows}
    total_chars = sum(int(row.char_count) for row in paragraph_rows)

    entries: list[tuple[Any, Any, float]] = []
    for row in paragraph_rows:
        metric = metric_by_paragraph_id.get(int(row.paragraph_id))
        if metric is None:
            continue
        midpoint = (int(row.global_start_char) + int(row.global_end_char)) / 2
        position = midpoint / total_chars if total_chars > 0 else 0.0
        if range_start is not None:
            if range_end is None or position < range_start or position > range_end:
                continue
        entries.append((row, metric, position))

    paragraph_total = len(entries)
    if paragraph_total == 0:
        return []

    window_size = max(5, min(40, int(window_paragraphs)))

    windows: list[dict[str, Any]] = []
    for index in range(0, paragraph_total, window_size):
        chunk = entries[index : index + window_size]
        token_total = sum(int(metric.token_count) for _, metric, _ in chunk)
        pos_sum = sum(float(metric.positive_weight_sum) for _, metric, _ in chunk)
        neg_sum = sum(float(metric.negative_weight_sum) for _, metric, _ in chunk)
        pos_hit = sum(1 for _, metric, _ in chunk if float(metric.positive_weight_sum) > 0)
        neg_hit = sum(1 for _, metric, _ in chunk if float(metric.negative_weight_sum) > 0)
        hit_paragraphs = sum(
            1 for _, metric, _ in chunk if float(metric.positive_weight_sum) + float(metric.negative_weight_sum) > 0
        )
        count = len(chunk)
        first_row, _, first_position = chunk[0]
        _, _, last_position = chunk[-1]
        center_position = (first_position + last_position) / 2.0
        windows.append(
            {
                "window_index": index // window_size,
                "position": center_position,
                "start_position": first_position,
                "end_position": last_position,
                "paragraph_start": int(first_row.paragraph_id),
                "paragraph_end": int(chunk[-1][0].paragraph_id),
                "chapter_start": int(first_row.chapter_id),
                "chapter_end": int(chunk[-1][0].chapter_id),
                "pos_coverage": pos_hit / count,
                "neg_coverage": neg_hit / count,
                "pooled_pos_density": safe_ratio(pos_sum, token_total),
                "pooled_neg_density": safe_ratio(neg_sum, token_total),
                "pooled_net_density": safe_ratio(pos_sum - neg_sum, token_total),
                "token_total": token_total,
                "hit_paragraphs": hit_paragraphs,
                "paragraph_total": count,
            }
        )

    return windows


def merge_character_appearances(
    rows: Any,
    name_resolution: dict[str, str],
) -> list[dict[str, Any]]:
    """按代表角色名归并出现次数、角色功能分布与情感均值（丢弃未解析局部引用）"""
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        name: str = row.surface_name
        decision = decide_character_reference(
            name,
            resolved_global_name=row.resolved_global_name,
        )
        canonical = decision.resolved_global_name
        if canonical is None:
            continue
        canonical = name_resolution.get(canonical, canonical)
        role_function: str = str(row.role_function) if row.role_function else "unknown"
        emotion_score = read_emotion_score(row.emotion_score)

        if canonical not in merged:
            merged[canonical] = {
                "count": 1,
                "role_function_counts": {role_function: 1},
                "weighted_score": emotion_score,
            }
        else:
            merged[canonical]["count"] += 1
            merged[canonical]["weighted_score"] += emotion_score
            rf_counts = merged[canonical]["role_function_counts"]
            rf_counts[role_function] = rf_counts.get(role_function, 0) + 1

    appearances: list[dict[str, Any]] = []
    for name, data in merged.items():
        avg_score = data["weighted_score"] / data["count"] if data["count"] > 0 else 0
        rf_counts = data["role_function_counts"]
        total_count = data["count"]
        dominant_role = max(rf_counts, key=lambda key: rf_counts[key] or 0)
        dominant_count = rf_counts[dominant_role]
        dominant_ratio = dominant_count / total_count if total_count > 0 else 0.0

        appearances.append(
            {
                "name": name,
                "appearance_count": int(total_count),
                "dominant_role_function": dominant_role,
                "role_function_distribution": rf_counts,
                "dominant_role_ratio": dominant_ratio,
                "narrative_focus_score": None,
                "is_focus_character": False,
                "avg_emotion_score": avg_score,
            }
        )
    return appearances


def rank_character_appearances(
    appearances: list[dict[str, Any]],
    *,
    name_resolution: dict[str, str],
    arc_scores: dict[str, float] | None,
    focus_characters: list[str] | None,
    main_characters: list[str] | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """按出现次数排序；诊断名单齐备时对齐代表名并计算叙事焦点评分，最后截断"""
    appearances.sort(key=lambda item: item["appearance_count"], reverse=True)
    if arc_scores is not None and main_characters is not None and focus_characters is not None:
        main_resolved = [name_resolution.get(name, name) for name in main_characters]
        focus_resolved = [name_resolution.get(name, name) for name in focus_characters]
        arc_resolved = {name_resolution.get(name, name): score for name, score in arc_scores.items()}
        calculate_narrative_focus_scores(appearances, arc_resolved, focus_resolved, main_resolved)

    if limit is None:
        return appearances
    return appearances[:limit]


def calculate_narrative_focus_scores(
    appearances: list[dict[str, Any]],
    arc_scores: dict[str, float],
    focus_characters: list[str],
    main_characters: list[str],
) -> list[dict[str, Any]]:
    """四项等权（出现量/主体占比/弧线分/主阵容）计算叙事焦点分"""
    if not appearances:
        return appearances

    max_appearance = max(item["appearance_count"] for item in appearances)
    focus_character_set = set(focus_characters)

    for item in appearances:
        appearance_norm = item["appearance_count"] / max_appearance if max_appearance > 0 else 0.0
        subject_count = item["role_function_distribution"].get("主体", 0)
        subject_ratio = subject_count / item["appearance_count"] if item["appearance_count"] > 0 else 0.0
        arc_score = arc_scores.get(item["name"], 0.0)
        arc_norm = arc_score / 10.0 if arc_score > 0 else 0.0
        in_main_cast = 1.0 if item["name"] in main_characters else 0.0
        narrative_focus_score = 0.25 * appearance_norm + 0.25 * subject_ratio + 0.25 * arc_norm + 0.25 * in_main_cast
        item["narrative_focus_score"] = round(narrative_focus_score, 4)
        item["is_focus_character"] = item["name"] in focus_character_set

    return appearances
