from __future__ import annotations

import json
import time
import uuid

from src.chunking.chunker import Chunk
from src.storage.models import ChunkCharacter, ChunkDialogue, ChunkRelation
from src.storage.models.core import DisambigCheckpoint
from src.storage.repositories import ChunkRepository, RunRepository
from scripts.db.backfill_character_references import backfill_run


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: backfill 集成测试需要真实 novel/run/chunk 外键，避免直接写历史行时触发约束错误。
    """
    from src.storage.models import Novel

    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


def test_backfill_run_applies_checkpoint_reference_resolutions_to_history_rows(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: backfill 脚本必须先消费 checkpoint reference_resolutions，再把历史 chunk_* 行反写成可读侧消费的 resolved 字段。
    """
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Reference Backfill",
    )
    ChunkRepository(db_session).insert_chunks(run_id, [Chunk(index=1, text="我看向白芷。", start=0, end=100)])

    chunk_character = ChunkCharacter(
        chunk_id=1,
        run_id=run_id,
        name="我",
        surface_name="我",
        reference_kind="pov_slot",
        reference_slot="POV_SLOT_C1_我",
        resolved_global_name=None,
        global_skip_reason="unresolved pov reference",
        role_function="主体",
        action="看向",
        action_type="其他",
        emotion_score="neutral",
    )
    chunk_dialogue = ChunkDialogue(
        chunk_id=1,
        run_id=run_id,
        speaker=["我"],
        speaker_references=[
            {
                "surface_name": "我",
                "reference_kind": "pov_slot",
                "reference_slot": "POV_SLOT_C1_我",
                "resolved_global_name": None,
                "can_enter_global_character": False,
                "global_skip_reason": "unresolved pov reference",
            }
        ],
        content="“我来了。”",
    )
    chunk_relation = ChunkRelation(
        chunk_id=1,
        run_id=run_id,
        from_char="我",
        to_char="白芷",
        from_reference_kind="pov_slot",
        to_reference_kind="global_character",
        resolved_from_global_name=None,
        resolved_to_global_name="白芷",
        reference_skip_reason="我: unresolved pov reference",
        type="盟友",
        change="新建",
        evidence="我看向白芷。",
        confidence=0.8,
        projection_status="pending",
    )
    db_session.add_all([chunk_character, chunk_dialogue, chunk_relation])
    db_session.add(
        DisambigCheckpoint(
            run_id=run_id,
            state_json=json.dumps(
                {
                    "discovered_names": ["我", "白芷"],
                    "known_canonical_names": ["白芷"],
                    "alias_merges": [],
                    "reference_resolutions": [["我", "汪淼"]],
                    "unresolved_references": [],
                    "review_status": [],
                    "pending_relations": [],
                    "entity_types": {},
                    "version": 3,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                },
                ensure_ascii=False,
            ),
            updated_at=time.time(),
        )
    )
    db_session.commit()

    report = backfill_run(db_session, run_id, apply=True, rebuild_graph=False)
    db_session.commit()
    db_session.refresh(chunk_character)
    db_session.refresh(chunk_dialogue)
    db_session.refresh(chunk_relation)

    assert report.character_rows == 1
    assert report.dialogue_rows == 1
    assert report.relation_rows == 1
    assert chunk_character.resolved_global_name == "汪淼"
    assert chunk_character.reference_kind == "pov_slot"
    assert chunk_dialogue.speaker_references[0]["resolved_global_name"] == "汪淼"
    assert chunk_relation.resolved_from_global_name == "汪淼"
    assert chunk_relation.resolved_to_global_name == "白芷"
