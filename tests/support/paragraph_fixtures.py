"""
段落级 API 测试夹具（paragraph-curves / chapter-metrics 端点）

提供：completed run + 一章一个 chunk 的原文、手工 ParagraphSpan/指标/曲线行、
以及最小章节标注（agent-semantic-v2 合同）。
"""

from __future__ import annotations

import uuid

from src.agents.annotation.schema import (
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundEntityDirectory,
    ChunkMetricsInput,
    EmotionalValence,
    NarrativeFunction,
)
from src.chunking.chunker import Chunk
from src.chunking.spans import ParagraphSpan
from src.storage.repositories import (
    ChapterAnnotationRepository,
    ChapterRepository,
    ParagraphRepository,
    RunRepository,
)
from src.storage.repositories.paragraph_repository import ParagraphCurveRow, ParagraphMetricRow
from tests.support.analysis_factories import insert_test_novel


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
    RunRepository(db_session).update_run_status(run_id, "completed")
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
        RunRepository(db_session).update_run_status(run_id, status)
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
    """构造坐标自洽的段落（global = chunk_offset + local），text 长度决定坐标跨度"""
    local_end = local_start + len(text)
    return ParagraphSpan(
        paragraph_index=paragraph_index,
        source_paragraph_index=0,
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
    char_count: int = 0,
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
    """构造段落指标行（未用到的计数/充分统计量默认 0）"""
    return ParagraphMetricRow(
        paragraph_id=paragraph_id,
        token_count=token_count,
        char_count=char_count,
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
        function_word_counts={},
        semantic_category_counts={},
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


def insert_chapter_annotation(
    db_session,
    run_id: str,
    *,
    chapter_id: int,
    narrative_function: str = "铺垫",
    emotional_valence: str = "neutral",
    pivot_moment: bool = False,
    cliffhanger: bool = False,
) -> None:
    """写入一章一个 chunk 的最小章节标注（agent-semantic-v2 合同）"""
    annotation = BoundChapterAnnotation(
        chapter_summary=f"章节 {chapter_id} 摘要",
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chapter_id,
                metrics=ChunkMetricsInput(
                    summary=f"章节 {chapter_id} 摘要",
                    emotional_valence=EmotionalValence(emotional_valence),
                    narrative_function=NarrativeFunction(narrative_function),
                    pivot_moment=pivot_moment,
                    cliffhanger=cliffhanger,
                ),
                entities=BoundEntityDirectory.model_validate({"entities": []}),
                character_observations=[],
                dialogues=[],
                events=[],
                relations=[],
                foreshadowings=[],
            )
        ],
    )
    ChapterAnnotationRepository(db_session).add_annotation(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
    )
    db_session.commit()
