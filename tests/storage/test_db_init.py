from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from src.storage.db import _create_graph_read_views, _ensure_runtime_schema, get_session_factory, init_db
from src.storage.models import Base


def test_continuity_schema_uses_direct_graph_persistence_contract() -> None:
    """2026-08-07 用于验证 ORM 直接表达章节图版本与事实版本来源"""
    assert "continuity_facts" not in Base.metadata.tables
    assert "graph_fact_versions" not in Base.metadata.tables
    assert "graph_relation_events" not in Base.metadata.tables

    mapping_columns = Base.metadata.tables["case_resolution_mappings"].columns
    case_columns = Base.metadata.tables["case_pool_cases"].columns
    fact_columns = Base.metadata.tables["graph_facts"].columns
    entity_columns = Base.metadata.tables["graph_entities"].columns
    dialogue_columns = Base.metadata.tables["dialogue_records"].columns
    assert {
        "case_id",
        "type",
        "target_ref",
        "resolution",
        "evidence_chunk_id",
        "target_fact_id",
        "target_fact_revision",
        "target_dialogue_id",
        "target_setup_id",
    } <= set(mapping_columns.keys())
    assert {"type", "chunk_id", "target_key", "target_ref"} <= set(case_columns.keys())
    assert {"graph_version_id", "source_kind", "annotation_id", "payload_path", "evidence"} <= set(fact_columns.keys())
    assert "attributes" in entity_columns
    assert {
        "dialogue_id",
        "run_id",
        "chunk_id",
        "chapter_id",
        "candidate_key",
        "content",
        "start",
        "end",
        "speaker",
        "tone",
        "is_inner_monologue",
        "description",
        "confidence",
        "evidence",
    } <= set(dialogue_columns.keys())


def test_init_db_creates_final_graph_tables_and_excludes_paragraph_embeddings() -> None:
    with (
        patch("src.storage.db.get_engine", return_value=object()),
        patch("src.storage.models.Base.metadata.create_all") as mock_create_all,
        patch("src.storage.db._create_graph_read_views") as mock_create_graph_read_views,
        patch("src.storage.db._ensure_runtime_schema") as mock_ensure_runtime_schema,
        patch("src.storage.db._assert_focus_contract_schema"),
        patch("src.storage.db._assert_annotation_contract_schema"),
        patch("src.storage.db._assert_agent_audit_contract_schema"),
    ):
        init_db()

    table_names = [table.name for table in mock_create_all.call_args.kwargs["tables"]]
    assert "paragraph_embeddings" not in table_names
    assert {
        "graph_versions",
        "graph_facts",
        "entity_state_versions",
        "graph_relations",
        "graph_relation_versions",
        "dialogue_records",
        "agent_invocations",
        "agent_turns",
        "agent_tool_calls",
        "token_usage",
    } <= set(table_names)
    mock_create_graph_read_views.assert_called_once()
    mock_ensure_runtime_schema.assert_called_once()


def test_init_db_rejects_removed_level3_parameter() -> None:
    """2026-08-07 用于验证数据库初始化不再保留旧 Level3 分支参数"""
    with pytest.raises(TypeError, match="include_level3_tables"):
        init_db(include_level3_tables=True)


def test_init_db_runs_focus_contract_guard_after_runtime_schema() -> None:
    """
    验证 init_db() 主链路会在 create_all 和 runtime schema 之后执行 focus-contract fail-closed 校验。

    创建时间: 2026-04-27
    任务: fix-focus-contract-runtime-schema-conflict
    说明: 这条测试专门覆盖 init_db() 的真实调用顺序，避免后续再把 focus-contract 校验从主链路上绕开。
    """
    fake_engine = object()
    with (
        patch("src.storage.db.get_engine", return_value=fake_engine),
        patch("src.storage.models.Base.metadata.create_all"),
        patch("src.storage.db._ensure_runtime_schema") as mock_ensure_runtime_schema,
        patch("src.storage.db._assert_focus_contract_schema") as mock_assert_focus_contract_schema,
        patch("src.storage.db._assert_annotation_contract_schema") as mock_assert_annotation_contract_schema,
        patch("src.storage.db._assert_agent_audit_contract_schema") as mock_assert_agent_audit_contract_schema,
    ):
        init_db()

    mock_ensure_runtime_schema.assert_called_once_with(fake_engine)
    mock_assert_focus_contract_schema.assert_called_once_with(fake_engine)
    mock_assert_annotation_contract_schema.assert_called_once_with(fake_engine)
    mock_assert_agent_audit_contract_schema.assert_called_once_with(fake_engine)


def test_agent_audit_contract_guard_rejects_legacy_model_interactions(db_session) -> None:
    """2026-08-10 用于验证旧库残留 model_interactions 时启动直接失败（不做运行时兼容建表）"""
    from sqlalchemy import text as sql_text

    from src.storage.db import _assert_agent_audit_contract_schema

    db_session.execute(sql_text("CREATE TABLE model_interactions (id SERIAL PRIMARY KEY)"))
    db_session.commit()

    with pytest.raises(RuntimeError, match="model_interactions 仍存在"):
        _assert_agent_audit_contract_schema(db_session.get_bind())


def test_agent_audit_contract_guard_rejects_missing_audit_tables(db_session) -> None:
    """2026-08-10 用于验证缺少新审计表时启动直接失败"""
    from src.storage.db import _assert_agent_audit_contract_schema

    db_session.execute(text("DROP TABLE IF EXISTS model_interactions CASCADE"))
    db_session.execute(text("DROP TABLE IF EXISTS agent_invocations CASCADE"))
    db_session.commit()

    with pytest.raises(RuntimeError, match="agent_invocations 表不存在"):
        _assert_agent_audit_contract_schema(db_session.get_bind())


def test_runtime_schema_does_not_backfill_legacy_focus_contract_columns() -> None:
    """
    验证 PostgreSQL runtime schema 不会再补旧 protagonist-contract 列。

    创建时间: 2026-04-27
    任务: fix-focus-contract-runtime-schema-conflict
    说明: 当前主线以 focus-contract fail-closed 为准；
          若 runtime schema 仍偷偷补 `protagonist/main_characters/core_cast/theme_color`，就会和启动校验自相矛盾。
    """
    fake_engine = MagicMock()
    fake_engine.dialect.name = "postgresql"
    fake_conn = MagicMock()
    fake_engine.begin.return_value.__enter__.return_value = fake_conn

    with (
        patch("src.storage.db._table_exists", return_value=False),
        patch("src.storage.db._ensure_analysis_related_foreign_keys"),
    ):
        _ensure_runtime_schema(fake_engine)

    executed_sql = [str(call.args[0]) for call in fake_conn.execute.call_args_list]

    expected_foreshadow_sql = "ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS foreshadow_expectation"
    expected_thread_confidence_sql = "ALTER TABLE foreshadowing_threads ADD COLUMN IF NOT EXISTS confidence"
    assert any(expected_foreshadow_sql in sql for sql in executed_sql)
    assert any(expected_thread_confidence_sql in sql for sql in executed_sql)
    assert any("ALTER TABLE graph_entities ADD COLUMN IF NOT EXISTS attributes" in sql for sql in executed_sql)
    assert any(
        "ALTER TABLE case_resolution_mappings ADD COLUMN IF NOT EXISTS target_dialogue_id" in sql
        for sql in executed_sql
    )
    assert any(
        "ALTER TABLE case_resolution_mappings ADD COLUMN IF NOT EXISTS target_setup_id" in sql
        for sql in executed_sql
    )
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS protagonist" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS main_characters" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS core_cast" in sql for sql in executed_sql)
    assert not any("ALTER TABLE cloud_analysis ADD COLUMN IF NOT EXISTS theme_color" in sql for sql in executed_sql)


def test_analysis_related_foreign_keys_exist_in_runtime_schema() -> None:
    """
    2026-08-05 用于验证测试库已具备章节标注连续性与数据库图主链外键
    """
    expected_constraints = {
        "analysis_runs_novel_id_fkey",
        "chapter_annotations_run_id_fkey",
        "case_pool_cases_run_id_fkey",
        "graph_versions_first_chunk_run_fkey",
        "graph_versions_last_chunk_run_fkey",
        "graph_facts_run_id_fkey",
        "graph_facts_effective_chunk_run_fkey",
        "graph_relation_versions_relation_id_fkey",
        "cloud_analysis_novel_id_fkey",
        "global_context_novel_id_fkey",
        "token_usage_novel_id_fkey",
    }

    with get_session_factory()() as session:
        rows = session.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND constraint_type = 'FOREIGN KEY'
                  AND constraint_name = ANY(:constraint_names)
                """
            ),
            {"constraint_names": list(expected_constraints)},
        ).scalars().all()

    assert set(rows) == expected_constraints


def test_fresh_schema_uses_chapter_graph_versions_without_legacy_event_table() -> None:
    """
    验证 pytest fresh schema 不再创建 timeline / graph projection 版本列。

    创建时间: 2026-04-28
    任务: remove-timeline-version-columns
    说明: 当前主线不再依赖 run-level version 标签 gate；
          fresh schema 下若还出现这两个列，说明旧兼容层又被带回来了。
    """

    with get_session_factory()() as session:
        column_rows = session.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'analysis_runs'
                  AND column_name IN ('graph_projection_version', 'timeline_contract_version')
                """
            )
        ).all()
        legacy_table = session.execute(
            text("SELECT to_regclass('graph_relation_events')")
        ).scalar_one_or_none()
        constraints = set(
            session.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = current_schema()
                  AND table_name = 'graph_versions'
                  AND constraint_type = 'UNIQUE'
                """
            )
            ).scalars()
        )

    assert column_rows == []
    assert legacy_table is None
    assert {
        "uq_graph_versions_run_chapter",
        "uq_graph_versions_run_order",
        "uq_graph_versions_annotation",
    } <= constraints


def test_graph_read_views_project_latest_state_active_relations_and_participants(db_session) -> None:
    """2026-08-07 用于验证当前图三个 SQL View 选择最新章节版本并过滤失效关系"""
    from tests.support.chapter_annotation_helpers import (
        character_fact,
        create_run_with_chunks,
        persist_chapter_annotation,
        relation_fact,
    )

    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜结盟", "林渡受伤且关系断裂"],
        chapter_ids=[1, 2],
        title="当前图 SQL View",
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(chunk_id=0, name="林渡", action="结盟"),
            character_fact(chunk_id=0, name="顾霜", action="结盟"),
        ],
        relations=[
            relation_fact(
                chunk_id=0,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
            )
        ],
    )
    db_session.commit()
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=2,
        characters=[character_fact(chunk_id=1, name="林渡", action="受伤")],
        relations=[
            relation_fact(
                chunk_id=1,
                from_name="林渡",
                to_name="顾霜",
                relation_type="盟友",
                change_kind="break",
            )
        ],
    )
    db_session.commit()
    _create_graph_read_views(db_session.get_bind())

    current_states = db_session.execute(
        text(
            """
            SELECT entity.canonical_name, current_state.state_revision, current_state.state
            FROM entity_state_current AS current_state
            JOIN graph_entities AS entity ON entity.entity_id = current_state.entity_id
            WHERE current_state.run_id = :run_id
            ORDER BY entity.canonical_name
            """
        ),
        {"run_id": run_id},
    ).mappings().all()
    active_relations = db_session.execute(
        text("SELECT relation_id FROM graph_relations_current WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).scalars().all()
    participants = db_session.execute(
        text(
            """
            SELECT entity.canonical_name, participant.current_degree
            FROM graph_entity_participants AS participant
            JOIN graph_entities AS entity ON entity.entity_id = participant.entity_id
            WHERE participant.run_id = :run_id
            ORDER BY entity.canonical_name
            """
        ),
        {"run_id": run_id},
    ).all()

    assert {
        row["canonical_name"]: row["state_revision"]
        for row in current_states
    } == {"林渡": 2, "顾霜": 1}
    assert next(row["state"] for row in current_states if row["canonical_name"] == "林渡")["action"] == "受伤"
    assert active_relations == []
    assert dict(participants) == {"林渡": 0, "顾霜": 0}


def test_stage_summaries_metadata_has_single_run_id_foreign_key() -> None:
    """
    创建时间: 2026-04-27
    任务: fix-stage-summary-orm-duplicate-fk
    说明: StageSummary.run_id 只应在 ORM 元数据里声明一次外键；
          否则 schema diff 会持续把同义 FK 误报成元数据漂移。
    """
    stage_summaries = Base.metadata.tables["stage_summaries"]
    foreign_keys = sorted(
        (
            tuple(column.name for column in constraint.columns),
            tuple(element.column.table.name for element in constraint.elements),
            tuple(element.column.name for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in stage_summaries.foreign_key_constraints
    )

    assert foreign_keys == [
        (("run_id",), ("analysis_runs",), ("run_id",), "CASCADE"),
    ]
