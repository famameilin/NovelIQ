from __future__ import annotations

from collections.abc import Sequence

from src.models.cloud.schema import CloudAnalysis
from src.storage.models import Novel
from src.storage.repositories import StatsRepository


def insert_graph_test_novel(db_session, novel_id: str) -> None:
    """为 graph snapshot contract 测试补 novels 主表记录"""
    if len(novel_id) > 8:
        raise ValueError(f"graph snapshot test novel_id must be 8 chars or fewer, got: {novel_id}")

    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


def insert_graph_test_chunks(db_session, run_id: str, chunk_ids: range) -> None:
    """为 graph relation event 测试补齐 chapters 外键依赖（M9a-2：chunks 表已合并）"""
    from src.chunking.chunker import Chunk
    from src.storage.repositories import ChapterRepository

    ChapterRepository(db_session).insert_chapter_texts(
        run_id,
        [
            Chunk(
                index=chunk_id,
                chapter_id=chunk_id + 1,
                start=0,
                end=len(f"chunk-{chunk_id}"),
                text=f"chunk-{chunk_id}",
            )
            for chunk_id in chunk_ids
        ],
    )
    db_session.commit()


def insert_focus_contract_cloud_analysis(
    db_session,
    *,
    novel_id: str,
    run_id: str,
    focus_characters: Sequence[str],
    main_characters: Sequence[str] | None = None,
    core_cast: Sequence[str] | None = None,
    topic_labels: Sequence[str] | None = None,
) -> None:
    """
    插入一条最小合法的 cloud_analysis 记录，满足 graph/timeline 相关测试的焦点合同 gate
    """
    focus_names = list(focus_characters)
    main_names = list(main_characters or focus_names)
    core_names = list(core_cast or main_names)
    arc_names = list(dict.fromkeys([*focus_names, *main_names, *core_names]))
    arc_scores = {name: float(9 - index * 0.5) for index, name in enumerate(arc_names)}

    analysis = CloudAnalysis(
        novel_id=novel_id,
        foreshadow_expectation=0.42,
        arc_scores=arc_scores,
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels=list(topic_labels or ["关系命运"]),
        diagnosis="测试用焦点合同 diagnosis",
        focus_structure="single" if len(focus_names) == 1 else "dual" if len(focus_names) == 2 else "ensemble",
        focus_characters=focus_names,
        main_characters=main_names,
        core_cast=core_names,
    )
    StatsRepository(db_session).insert_cloud_analysis(run_id, analysis)
