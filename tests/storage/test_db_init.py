from unittest.mock import patch

import pytest
from sqlalchemy import text

from src.storage.db import get_session_factory, init_db
from src.storage.models import Base


def test_continuity_schema_uses_direct_graph_persistence_contract() -> None:
    """2026-08-19 用于验证 ORM 直接表达 run 与章节历史事实"""
    assert "continuity_" + "facts" not in Base.metadata.tables
    assert "graph_fact_" + "versions" not in Base.metadata.tables
    assert "graph_relation_" + "events" not in Base.metadata.tables
    forbidden_tables = {
        "graph_" + "versions",
        "entity_state_" + "versions",
        "graph_relation_" + "versions",
    }
    assert forbidden_tables.isdisjoint(Base.metadata.tables)

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
        "target_dialogue_id",
        "target_setup_id",
    } <= set(mapping_columns.keys())
    assert {"type", "chapter_id", "target_key", "target_ref"} <= set(case_columns.keys())
    assert {
        "run_id",
        "chapter_id",
        "fact_id",
        "source_kind",
        "annotation_id",
        "payload_path",
        "effective_chapter_id",
        "evidence",
    } <= set(fact_columns.keys())
    assert "attributes" in entity_columns
    assert {
        "dialogue_id",
        "run_id",
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
    ):
        init_db()

    table_names = [table.name for table in mock_create_all.call_args.kwargs["tables"]]
    assert "paragraph_embeddings" not in table_names
    assert {
        "graph_facts",
        "entity_states",
        "graph_relations",
        "relation_states",
        "event_nodes",
        "event_edges",
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


def test_init_db_uses_current_metadata_without_schema_guards() -> None:
    """2026-08-19 用于验证初始化只创建当前 ORM 元数据"""
    fake_engine = object()
    with (
        patch("src.storage.db.get_engine", return_value=fake_engine),
        patch("src.storage.models.Base.metadata.create_all"),
    ):
        init_db()

    import src.storage.db as db_module

    assert not any(name.startswith("_assert_") for name in dir(db_module))


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
        "entity_states_chapter_run_fkey",
        "graph_facts_run_id_fkey",
        "graph_facts_effective_chapter_run_fkey",
        "relation_states_chapter_run_fkey",
        "event_nodes_chapter_run_fkey",
        "event_edges_source_chapter_run_fkey",
        "event_edges_target_chapter_run_fkey",
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


def test_fresh_schema_uses_chapter_keys_without_version_tables() -> None:
    """2026-08-19 用于验证新 schema 只保留章节复合键"""

    with get_session_factory()() as session:
        version_tables = session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN (
                    'graph_' || 'versions', 'graph_fact_' || 'versions', 'entity_state_' || 'versions',
                    'graph_relation_' || 'versions', 'graph_relation_' || 'events'
                  )
                """
            )
        ).scalars().all()
        version_columns = session.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND column_name IN (
                    'analysis_' || 'contract_' || 'version', 'contract_' || 'version',
                    'reference_' || 'contract_' || 'version', 'graph_' || 'version_' || 'id',
                    'fact_' || 'revision', 'event_' || 'revision', 'relation_' || 'version_' || 'id',
                    'relation_' || 'revision', 'state_' || 'revision', 'rerun_' || 'required',
                    'rerun_' || 'reason'
                  )
                """
            )
        ).all()

    assert version_tables == []
    assert version_columns == []


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
        # M9a-2：chunks 表合并进 chapters 后，FK 指向 chapters 的 chapter_id
        # 列表按 (列名, 引用表, 引用列, ondelete) 字母序排序
        (("end_chapter_id", "run_id"), ("chapters", "chapters"), ("chapter_id", "run_id"), "CASCADE"),
        (("run_id",), ("analysis_runs",), ("run_id",), "CASCADE"),
        (("start_chapter_id", "run_id"), ("chapters", "chapters"), ("chapter_id", "run_id"), "CASCADE"),
    ]
