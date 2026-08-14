from unittest.mock import patch

import pytest
from sqlalchemy import text

from src.storage.db import get_session_factory, init_db
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
        "target_fact_id",
        "target_fact_revision",
        "target_dialogue_id",
        "target_setup_id",
    } <= set(mapping_columns.keys())
    assert {"type", "chunk_id", "target_key", "target_ref"} <= set(case_columns.keys())
    assert {
        "graph_version_id",
        "source_kind",
        "annotation_id",
        "payload_path",
        "fact_revision",
    } <= set(fact_columns.keys())
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
        "confidence",
    } <= set(dialogue_columns.keys())


def test_init_db_creates_final_graph_tables_and_excludes_paragraph_embeddings() -> None:
    with (
        patch("src.storage.db.get_engine", return_value=object()),
        patch("src.storage.models.Base.metadata.create_all") as mock_create_all,
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


def test_init_db_rejects_removed_level3_parameter() -> None:
    """2026-08-07 用于验证数据库初始化不再保留旧 Level3 分支参数"""
    with pytest.raises(TypeError, match="include_level3_tables"):
        init_db(include_level3_tables=True)


def test_init_db_runs_contract_guards_after_create_all() -> None:
    """
    验证 init_db() 主链路会在 create_all 之后执行 fail-closed 合同校验。

    创建时间: 2026-04-27
    任务: fix-focus-contract-runtime-schema-conflict
    说明: 这条测试专门覆盖 init_db() 的真实调用顺序，避免后续再把合同校验从主链路上绕开。
    """
    fake_engine = object()
    with (
        patch("src.storage.db.get_engine", return_value=fake_engine),
        patch("src.storage.models.Base.metadata.create_all"),
        patch("src.storage.db._assert_focus_contract_schema") as mock_assert_focus_contract_schema,
        patch("src.storage.db._assert_annotation_contract_schema") as mock_assert_annotation_contract_schema,
        patch("src.storage.db._assert_agent_audit_contract_schema") as mock_assert_agent_audit_contract_schema,
    ):
        init_db()

    mock_assert_focus_contract_schema.assert_called_once_with(fake_engine)
    mock_assert_annotation_contract_schema.assert_called_once_with(fake_engine)
    mock_assert_agent_audit_contract_schema.assert_called_once_with(fake_engine)


def test_agent_audit_contract_guard_rejects_missing_audit_tables(db_session) -> None:
    """2026-08-10 用于验证缺少新审计表时启动直接失败"""
    from src.storage.db import _assert_agent_audit_contract_schema

    db_session.execute(text("DROP TABLE IF EXISTS agent_invocations CASCADE"))
    db_session.commit()

    with pytest.raises(RuntimeError, match="agent_invocations 表不存在"):
        _assert_agent_audit_contract_schema(db_session.get_bind())


def test_no_legacy_runtime_schema_compat_path_remains() -> None:
    """
    2026-08-12 用于验证旧库兼容路径已彻底移除（只有最新口径）：
    init_db 不再补列/补外键/拒绝旧结构，schema 完全由 create_all 表达。
    """
    import src.storage.db as db_module

    for legacy_name in (
        "_ensure_runtime_schema",
        "_ensure_analysis_related_foreign_keys",
        "_normalize_analysis_related_novel_ids",
        "_assert_no_orphans",
        "_constraint_exists",
    ):
        assert not hasattr(db_module, legacy_name), f"旧兼容代码 {legacy_name} 不应存在"


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
        # 2026-08-13 P2：补齐指向 chunks 的复合 FK（run_id 仍只声明一次）；
        # 列表按 (列名, 引用表, 引用列, ondelete) 字母序排序
        (("end_chunk_id", "run_id"), ("chunks", "chunks"), ("chunk_id", "run_id"), "CASCADE"),
        (("run_id",), ("analysis_runs",), ("run_id",), "CASCADE"),
        (("start_chunk_id", "run_id"), ("chunks", "chunks"), ("chunk_id", "run_id"), "CASCADE"),
    ]
