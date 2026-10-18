"""本领域的独立只读投影，不返回 HTTP 模型

章节标注按 chapter_annotations 宽表取具名指标：

- 章号与章内角色取记录自身归属列
- 情绪效价/叙事功能/转折/悬念为标注记录的独立具名列
- coverage_warnings 按固定覆盖规则对 analysis_assessments 的逐段情绪条目投影
- 章节完成与角色集合沿用 src.work.policy 的完成判定（saved 由正式记录存在性表达）
"""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from src.event_trees.read.foreshadowing import foreshadowing_by_chapter as read_foreshadowing
from src.storage import Storage
from src.storage.records.annotation import ChapterAnnotationRow, SavedAnnotationRecord
from src.work.policy import completed_chapters

#: 每章段落情绪标签最低覆盖段数（与标注冻结合同 src/agents/annotation/state_metrics.py 同源）
PARAGRAPH_LABEL_MIN_PER_CHAPTER = 2
#: 段落情绪标签覆盖缺口告警文案（固定覆盖规则的确定性投影）
PARAGRAPH_LABEL_WARNING_TEMPLATE = "情绪标签覆盖: 仅标注 {count} 段（每章应自选 2-3 段）"
#: 度量指标角色（章级具名指标取该角色的正式记录）
METRIC_ROLES = ("annotation", "metric")


def paragraph_label_coverage_warnings(label_count: int) -> list[str]:
    """固定覆盖规则投影：低于最低段数时给出确定性告警，达标则为空"""
    if label_count >= PARAGRAPH_LABEL_MIN_PER_CHAPTER:
        return []
    return [PARAGRAPH_LABEL_WARNING_TEMPLATE.format(count=label_count)]


def _fetch_paragraph_label_counts(session: Storage, record_ids: list[str]) -> dict[str, int]:
    """按标注记录统计逐段情绪条目数（analysis_assessments 的情绪形状）"""
    if not record_ids:
        return {}
    return {
        str(row.record_id): int(row.label_count)
        for row in session.reads.metrics_queries_annotations_fetch_paragraph_label_counts_1(record_ids)
    }


def fetch_chapter_annotations_full(session: Storage, run_id: str) -> list[ChapterAnnotationRow]:
    """从正式章节标注记录展开完整章节标注

    只取角色集合与登记角色一致、且按标注合同完成的章节；具名指标取度量指标角色的
    正式记录，不做任何载荷兼容读取（未登记记录按缺省处理）。
    """
    foreshadowing_by_chapter = read_foreshadowing(session, run_id)
    repository = session.annotations
    saved_records = repository.fetch_saved_outputs(run_id)
    roles = repository.fetch_role_records(run_id)
    complete_chapters = completed_chapters(roles)
    expected_roles: dict[int, set[str]] = defaultdict(set)
    for role_record in roles:
        expected_roles[role_record.chapter_id].add(role_record.role)
    records_by_chapter: dict[int, list[SavedAnnotationRecord]] = defaultdict(list)
    for record in saved_records:
        records_by_chapter[record.chapter_id].append(record)

    label_counts = _fetch_paragraph_label_counts(session, [record.record_id for record in saved_records])
    rows: list[ChapterAnnotationRow] = []
    for chapter_id, records in records_by_chapter.items():
        saved_roles = {record.role for record in records if record.role is not None}
        if chapter_id not in complete_chapters or saved_roles != expected_roles.get(chapter_id, set()):
            continue
        metric = next((record for record in records if record.role in METRIC_ROLES), None)
        if metric is None:
            continue
        rows.append(
            ChapterAnnotationRow(
                chapter_id=chapter_id,
                # 度量指标角色的具名指标由真实产出保证非空：annotation/metric 的完整性
                # 检查要求 metrics 整域存在（agents/annotation/agent.py validate），且只
                # 保存通过该检查的 work；列本身可空但不覆盖该角色的已保存记录。
                emotional_valence=cast(int, metric.emotional_valence),
                event_type=cast(str, metric.narrative_function),
                pivot_moment=cast(bool, metric.pivot_moment),
                cliffhanger=cast(bool, metric.cliffhanger),
                coverage_warnings=paragraph_label_coverage_warnings(label_counts.get(metric.record_id, 0)),
                **foreshadowing_by_chapter.get(chapter_id, {}),
            )
        )
    sequence_map = repository.fetch_chapter_sequence_map(run_id)
    return sorted(rows, key=lambda row: (sequence_map.get(row.chapter_id, row.chapter_id), row.chapter_id))
