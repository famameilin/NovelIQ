from __future__ import annotations

from sqlalchemy import text

from src.chunking.chunker import Chunk
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation, DialogueSnapshot
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    DiagnosisRepository,
    RunRepository,
    StatsRepository,
)
from src.workflows.annotate_helpers.sentence import build_context_sentences


def _candidates(*names: str) -> list[dict[str, int | str]]:
    return [{"name": name, "count": 1} for name in names]


def _build_annotation(foreshadowing_desc: str) -> ChunkAnnotation:
    return ChunkAnnotation(
        emotional_valence="neutral",
        event_type="高潮",
        pivot_moment=True,
        cliffhanger=False,
        has_foreshadowing=True,
        foreshadowing_type="causal",
        foreshadowing_desc=foreshadowing_desc,
        characters=[],
        dialogues=[],
        chunk_summary="",
    )


def test_build_context_sentences_respects_run_id(db_session) -> None:
    run_repo = RunRepository(db_session)
    run_1 = run_repo.create_run(novel_id="novel_ctx", source_path="test", title="Run1")
    run_2 = run_repo.create_run(novel_id="novel_ctx", source_path="test", title="Run2")

    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(
        run_1,
        [
            Chunk(index=1, start=0, end=10, text="prefix"),
            Chunk(index=2, start=11, end=30, text="zhangsan 就是掌柜。"),
        ],
    )
    chunk_repo.insert_chunks(
        run_2,
        [
            Chunk(index=99, start=0, end=10, text="run2-prefix"),
            Chunk(index=100, start=11, end=30, text="zhangsan 是叛徒。"),
        ],
    )

    ann_repo = AnnotationRepository(db_session)
    ann_repo.insert_chunk_characters(
        run_1,
        2,
        [CharacterSnapshot(name="zhangsan", role_function="主体", action="说话", action_type="对话", emotion_score="neutral")],
    )
    ann_repo.insert_chunk_characters(
        run_2,
        100,
        [CharacterSnapshot(name="zhangsan", role_function="主体", action="说话", action_type="对话", emotion_score="neutral")],
    )

    stats_repo = StatsRepository(db_session)
    stats_repo.insert_chunk_summary(run_1, 1, "run1-summary")
    stats_repo.insert_chunk_summary(run_2, 99, "run2-summary")

    ann_repo.insert_chunk_dialogues(
        run_1,
        2,
        [DialogueSnapshot(speaker="zhangsan", content="test", identity_clue="run1-clue")],
        [10],
    )
    ann_repo.insert_chunk_dialogues(
        run_2,
        100,
        [DialogueSnapshot(speaker="zhangsan", content="test", identity_clue="run2-clue")],
        [10],
    )

    result = build_context_sentences(db_session, _candidates("zhangsan"), alias_keywords=["就是"], prev_chunks=1, run_id=run_1)

    assert "zhangsan" in result
    context = result["zhangsan"]
    assert "run1-summary" in context
    assert "run1-clue" in context
    assert "run2-summary" not in context
    assert "run2-clue" not in context
    assert "叛徒" not in context


def test_diagnosis_repository_joins_are_run_isolated(db_session) -> None:
    run_repo = RunRepository(db_session)
    run_1 = run_repo.create_run(novel_id="novel_diag", source_path="test", title="Run1")
    run_2 = run_repo.create_run(novel_id="novel_diag", source_path="test", title="Run2")

    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(run_1, [Chunk(index=0, start=0, end=10, text="run1-text")])
    chunk_repo.insert_chunks(run_2, [Chunk(index=0, start=0, end=10, text="run2-text")])

    ann_repo = AnnotationRepository(db_session)
    ann_repo.insert_chunk_annotation(run_1, 0, _build_annotation("run1-foreshadowing"))
    ann_repo.insert_chunk_annotation(run_2, 0, _build_annotation("run2-foreshadowing"))

    db_session.execute(
        text(
            "INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density, run_id) "
            "VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :run_id)"
        ),
        {"chunk_id": 0, "pos": 0.1, "neg": 0.05, "net": 0.2, "smoothed": 0.1, "run_id": run_1},
    )
    db_session.execute(
        text(
            "INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density, run_id) "
            "VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :run_id)"
        ),
        {"chunk_id": 0, "pos": 0.1, "neg": 0.05, "net": 0.3, "smoothed": 0.1, "run_id": run_2},
    )
    db_session.commit()

    diag_repo = DiagnosisRepository(db_session)

    pivot_blocks = diag_repo.fetch_pivot_blocks(run_1)
    high_tension = diag_repo.fetch_high_tension_chunks(run_1, limit=10)
    foreshadowing = diag_repo.fetch_foreshadowing_chunks(run_1, limit=10)
    pivot_moments = diag_repo.fetch_pivot_moments(run_1, limit=10)

    assert len(pivot_blocks) == 1
    assert len(high_tension) == 1
    assert len(foreshadowing) == 1
    assert len(pivot_moments) == 1

    assert pivot_blocks[0][1] == "run1-text"
    assert high_tension[0][1] == "run1-text"
    assert foreshadowing[0][1] == "run1-text"
    assert pivot_moments[0][1] == "run1-text"
