"""
段落级 API 测试夹具（paragraph-curves / chapter-metrics 端点）

提供：completed run + 一章一个 chunk 的原文、手工 ParagraphSpan/指标/曲线行、
以及最小章节标注（agent-semantic-v2 合同）。
"""

from __future__ import annotations

import math
import uuid

from src.agents.annotation.output_models import BoundChapterAnnotation
from src.fact_graph.inputs import ChapterMetricsInput
from src.fact_graph.vocabulary import NarrativeFunction
from src.storage.repositories import (
    ChapterRepository,
    ParagraphRepository,
    RunRepository,
)
from src.storage.repositories.paragraph_repository import ParagraphCurveRow, ParagraphMetricRow
from src.text_processing.models import Chunk, ParagraphSpan
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import commit_test_annotation
from tests.support.run_records import set_run_status


def create_completed_run(
    db_session,
    *,
    chapter_texts: list[str],
    title: str = "段落接口测试",
) -> tuple[str, str]:
    """创建 completed run 与一章一个 chunk 的原文（chunk.index 从 0 起，chapter_id 从 1 起）"""
    novel_id = "p" + uuid.uuid4().hex[:7]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title=title,
    )
    offset = 0
    chunks: list[Chunk] = []
    for chapter_index, text in enumerate(chapter_texts):
        chunks.append(
            Chunk(
                index=chapter_index,
                text=text,
                start=offset,
                end=offset + len(text),
                chapter_id=chapter_index + 1,
            )
        )
        offset += len(text)
    ChapterRepository(db_session).insert_chapter_texts(run_id, chunks)
    set_run_status(RunRepository(db_session).session, run_id, "completed")
    return novel_id, run_id


def create_run_with_status(
    db_session,
    *,
    chapter_texts: list[str],
    status: str,
) -> tuple[str, str]:
    """创建指定终态/运行态的 run（用于 409/400 门禁测试）"""
    novel_id = "q" + uuid.uuid4().hex[:7]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="段落接口门禁测试",
    )
    if status != "pending":
        set_run_status(RunRepository(db_session).session, run_id, status)
    return novel_id, run_id


def make_span(
    *,
    paragraph_id: int,
    chapter_id: int,
    paragraph_index: int,
    text: str,
    local_start: int,
    chunk_offset: int,
    token_count: int = 1,
) -> ParagraphSpan:
    """构造坐标自洽的段落（global = chunk_offset + local），text 长度决定坐标跨度

    段落身份按「来源自然段 + 片段序号」唯一：默认一个段落就是一个自然段，
    超长拆分的片段由调用方显式给出相同的来源序号与不同片段序号。
    """
    local_end = local_start + len(text)
    return ParagraphSpan(
        paragraph_index=paragraph_index,
        source_paragraph_index=paragraph_index,
        fragment_index=0,
        local_start_char=local_start,
        local_end_char=local_end,
        text=text,
        paragraph_id=paragraph_id,
        chapter_id=chapter_id,
        global_start_char=chunk_offset + local_start,
        global_end_char=chunk_offset + local_end,
        token_count=token_count,
    )


def insert_spans(db_session, run_id: str, spans: list[ParagraphSpan]) -> None:
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    db_session.commit()


def make_metric_row(
    paragraph_id: int,
    *,
    token_count: int = 0,
    sentence_count: int = 0,
    sentence_char_sum: float = 0.0,
    sentence_char_sum_sq: float = 0.0,
    positive_weight_sum: float = 0.0,
    negative_weight_sum: float = 0.0,
    fight_weight_sum: float = 0.0,
    exclaim_count: int = 0,
    question_count: int = 0,
    pause_count: int = 0,
    dialogue_char_count: int = 0,
) -> ParagraphMetricRow:
    """构造段落指标行（未用到的计数/充分统计量默认 0）

    char_count 与张力/功能词分类不在此行：前者是正文长度读投影，
    后两者分别是 paragraph_features 行与 paragraph_metrics 的明确列。
    """
    return ParagraphMetricRow(
        paragraph_id=paragraph_id,
        token_count=token_count,
        sentence_count=sentence_count,
        sentence_char_sum=sentence_char_sum,
        sentence_char_sum_sq=sentence_char_sum_sq,
        positive_weight_sum=positive_weight_sum,
        negative_weight_sum=negative_weight_sum,
        fight_weight_sum=fight_weight_sum,
        exclaim_count=exclaim_count,
        question_count=question_count,
        pause_count=pause_count,
        dialogue_char_count=dialogue_char_count,
        sensory_hit_count=0,
        imagery_hit_count=0,
        metaphor_sentence_count=0,
        body_reaction_hit_count=0,
    )


def insert_metrics(db_session, run_id: str, rows: list[ParagraphMetricRow]) -> None:
    ParagraphRepository(db_session).insert_paragraph_metrics(run_id, rows)
    db_session.commit()


def make_curve_row(
    paragraph_id: int,
    *,
    pos_density: float | None = None,
    neg_density: float | None = None,
    net_density: float | None = None,
    smoothed_net_density: float | None = None,
    surface_tension: float | None = None,
    smoothed_surface_tension: float | None = None,
) -> ParagraphCurveRow:
    return ParagraphCurveRow(
        paragraph_id=paragraph_id,
        pos_density=pos_density,
        neg_density=neg_density,
        net_density=net_density,
        smoothed_net_density=smoothed_net_density,
        surface_tension=surface_tension,
        smoothed_surface_tension=smoothed_surface_tension,
    )


def insert_curves(db_session, run_id: str, rows: list[ParagraphCurveRow]) -> None:
    ParagraphRepository(db_session).insert_paragraph_curves(run_id, rows)
    db_session.commit()


def insert_tension_observations(db_session, run_id: str, rows: list[tuple[int, float]]) -> None:
    """写入段落表面张力 z 观测；展示值是 sigmoid 读投影，不落展示列"""
    from src.storage.repositories.paragraph.writer import insert_paragraph_tension_observations

    insert_paragraph_tension_observations(db_session, run_id, rows)
    db_session.commit()


def tension_z_for_display(display_value: float) -> float:
    """展示张力值对应的正式 z 观测（与读面 sigmoid 投影互为逆运算）"""
    clipped = min(max(display_value, 1e-6), 1 - 1e-6)
    return math.log(clipped / (1 - clipped))


def insert_chapter_annotation(
    db_session,
    run_id: str,
    *,
    chapter_id: int,
    narrative_function: str = "铺垫",
    emotional_valence: int = 0,
    pivot_moment: bool = False,
    cliffhanger: bool = False,
) -> None:
    """写入单章最小章节标注（agent-semantic-v2 合同；2026-09-19 章即块拍平）"""
    annotation = BoundChapterAnnotation(
        metrics=ChapterMetricsInput(
            summary=f"章节 {chapter_id} 摘要",
            emotional_valence=emotional_valence,
            narrative_function=NarrativeFunction(narrative_function),
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
        ),
        character_observations=[],
        dialogues=[],
        events=[],
    )
    commit_test_annotation(
        db_session,
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
    )
