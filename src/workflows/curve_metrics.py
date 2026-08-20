"""
曲线/统计相关的度量计算（从 preprocess 中拆出）

聚合与预处理都会用到的通用计算放在这里，减少模块间交叉依赖

2026-08-14 M8b：chunk 级曲线计算（compute_emotion_curve / compute_tension_signals /
compute_rhythm_curve / compute_emotion_curve_weighted）已删除——曲线事实源
改为 paragraph_curves（预处理阶段落库），聚合侧按章节从段落充分统计量重算。
2026-08-15 词表 v3：WeightedLexiconSet 随 get_weighted_lexicon_set 删除
（无生产消费者，benchmark 改用 registry 直接组装）。
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.metrics.style_metrics import mtld, ttr
from src.preprocess.tokenize import tokenize


def _last_extreme_index(values: list[float], *, want_max: bool) -> int:
    """§19.14 并列极值取最后出现的索引（rindex 语义）"""
    extreme = max(values) if want_max else min(values)
    return len(values) - 1 - values[::-1].index(extreme)


def compute_global_stats(conn: Session, run_id: str) -> list[tuple[str, float | None]]:
    """
    计算全局统计（§9.1 聚合守恒，2026-08-14 M8b 段落化重写）

    数据源从 chunk_style/chunk_curves 切换为段落事实源：
     - TTR/MTLD 在全文字符序列上直接计算，不再取各章均值
    - avg_sent_len 从句子充分统计量恢复（Σ句长 / Σ句数）
    - emotion_avg 为全书分子/分母守恒密度（Σpos − Σneg）/ Σtoken
    - emotion/rhythm 的 std/max/min 与峰值定位基于段落密度序列，
      并列极值取最后出现的段落（rindex 语义）
    """
    from src.storage.models import Paragraph, ParagraphCurve, ParagraphMetric

    rows = conn.execute(
        select(
            Paragraph.chapter_id,
            Paragraph.text,
            ParagraphMetric.token_count,
            ParagraphMetric.sentence_count,
            ParagraphMetric.sentence_char_sum,
            ParagraphMetric.positive_weight_sum,
            ParagraphMetric.negative_weight_sum,
            ParagraphCurve.net_density,
            ParagraphCurve.surface_tension,
        )
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id)
            & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
            isouter=True,
        )
        .join(
            ParagraphCurve,
            (ParagraphCurve.run_id == Paragraph.run_id)
            & (ParagraphCurve.paragraph_id == Paragraph.paragraph_id),
            isouter=True,
        )
        .where(Paragraph.run_id == run_id)
        .order_by(Paragraph.global_start_char, Paragraph.paragraph_id)
    ).fetchall()

    global_stats: list[tuple[str, float | None]] = []

    token_total = sum(int(row.token_count or 0) for row in rows)
    pos_total = sum(float(row.positive_weight_sum or 0.0) for row in rows)
    neg_total = sum(float(row.negative_weight_sum or 0.0) for row in rows)
    sentence_count = sum(int(row.sentence_count or 0) for row in rows)
    sentence_char_sum = sum(float(row.sentence_char_sum or 0.0) for row in rows)

    book_text = "".join(str(row.text) for row in rows if row.text)
    book_tokens = tokenize(book_text) if book_text else []
    if book_tokens:
        mtld_value = mtld(book_tokens)
        global_stats.append(("avg_mtld", float(mtld_value) if mtld_value is not None else None))
        global_stats.append(("avg_ttr", float(ttr(book_tokens))))
    if sentence_count > 0:
        global_stats.append(("avg_sent_len", sentence_char_sum / sentence_count))

    if token_total > 0:
        global_stats.append(("emotion_avg", (pos_total - neg_total) / token_total))

    emotion_indices = [i for i, row in enumerate(rows) if row.net_density is not None]
    emotion_values = [float(rows[i].net_density) for i in emotion_indices]
    if emotion_values:
        mean = sum(emotion_values) / len(emotion_values)
        variance = sum((d - mean) ** 2 for d in emotion_values) / len(emotion_values)
        global_stats.append(("emotion_std", math.sqrt(variance)))
        global_stats.append(("emotion_max", max(emotion_values)))
        global_stats.append(("emotion_min", min(emotion_values)))
        max_idx = _last_extreme_index(emotion_values, want_max=True)
        min_idx = _last_extreme_index(emotion_values, want_max=False)
        # 极值下标属于过滤后的 emotion_values，必须经 emotion_indices 映射回未过滤的 rows；
        # 直接 rows[max_idx] 会在存在 NULL 密度行（0-token 段，§15.2）时定位到错误章节
        global_stats.append(("emotion_peak_chapter_id", float(rows[emotion_indices[max_idx]].chapter_id)))
        global_stats.append(("emotion_min_chapter_id", float(rows[emotion_indices[min_idx]].chapter_id)))

    tension_indices = [i for i, row in enumerate(rows) if row.surface_tension is not None]
    tension_values = [float(rows[i].surface_tension) for i in tension_indices]
    if tension_values:
        mean = sum(tension_values) / len(tension_values)
        variance = sum((v - mean) ** 2 for v in tension_values) / len(tension_values)
        global_stats.append(("rhythm_avg", mean))
        global_stats.append(("rhythm_std", math.sqrt(variance)))
        global_stats.append(("rhythm_max", max(tension_values)))
        global_stats.append(("rhythm_min", min(tension_values)))
        tension_max_idx = _last_extreme_index(tension_values, want_max=True)
        tension_min_idx = _last_extreme_index(tension_values, want_max=False)
        global_stats.append(("rhythm_peak_chapter_id", float(rows[tension_indices[tension_max_idx]].chapter_id)))
        global_stats.append(("rhythm_min_chapter_id", float(rows[tension_indices[tension_min_idx]].chapter_id)))

    return global_stats
