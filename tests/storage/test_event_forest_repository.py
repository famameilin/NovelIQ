"""事件森林/DAG 查询仓储测试

读取面输入为正式发布的完整事件（event_records + event_revisions 显式阶段链
+ event_links 语义形状）；章级声明只作为来源，读取时不冒充事件身份。
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.event_trees.organization import OrganizationEvidence
from src.event_trees.read.forest import EventForestQuery
from src.storage.models import NarrativeLink
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_declaration_relation,
    add_foreshadowing_action,
    first_paragraph,
    identity_every_declaration,
    paragraphs_of,
    publish_declarations,
    publish_draft,
)
from tests.support.storage_fixtures import fixture_id, storage_for

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _event_map(draft) -> dict[str, str]:
    return {event_id: event_id for event_id in draft.events}


def _publish(session, run_id, relations=()):
    """夹具明确判断各声明独立，并提交本例指定的正式事件关系"""
    draft, _meta = identity_every_declaration(session, run_id)
    mapping = _event_map(draft)
    for index, (source, target, kind) in enumerate(relations):
        draft.relate_events(
            key=f"relation-{index}",
            source_kind="event",
            source_id=mapping[source],
            target_kind="event",
            target_id=mapping[target],
            relation_type=kind,
            reason="本例明确判断两事件的关系",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    return publish_draft(session, run_id, draft)


def test_fetch_snapshot_returns_event_trees_and_causal_edges(db_session) -> None:
    """验证持久化后 fetch_snapshot 返回树视图与因果边"""
    text = "顾霜进入山门。\n顾霜拔剑。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="事件森林快照",
    )
    paragraphs = paragraphs_of(db_session, run_id, 1)
    record_id, _agent_id = add_annotation_source(db_session, run_id, 1)
    first_declaration = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraphs[0],
        title="进入山门",
        summary="顾霜进入山门",
    )
    second_declaration = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraphs[1],
        title="拔剑",
        summary="顾霜拔剑",
    )
    db_session.commit()

    mapping = _publish(db_session, run_id, [(first_declaration, second_declaration, "causal")])
    first_event, second_event = mapping[first_declaration], mapping[second_declaration]
    repo = EventForestQuery(storage_for(db_session))
    snapshot = repo.fetch_snapshot(run_id)
    assert snapshot is not None
    assert snapshot.chapter_order == 1
    assert len(snapshot.event_nodes) == 2
    nodes_by_desc = {node.description: node for node in snapshot.event_nodes}
    assert "顾霜进入山门" in nodes_by_desc
    assert "顾霜拔剑" in nodes_by_desc
    assert nodes_by_desc["顾霜进入山门"].event_id == first_event
    assert nodes_by_desc["顾霜拔剑"].event_id == second_event
    assert nodes_by_desc["顾霜进入山门"].tree_id == first_declaration
    assert nodes_by_desc["顾霜进入山门"].cause_role == "root"

    # 树视图：两棵树，因果边跨树；主链按原文顺序
    assert len(snapshot.event_trees) == 2
    gate_tree = next(tree for tree in snapshot.event_trees if tree.tree_id == first_declaration)
    assert gate_tree.root_event_id == first_declaration
    assert gate_tree.main_chain == [first_declaration]
    assert gate_tree.secondary_groups == []
    assert gate_tree.chapter_ids == [1]

    # 全书事件关系不任意投射到声明端点
    assert len(snapshot.causal_edges) == 1
    from src.event_trees.read.organization import EventTreeQuery

    assert len(EventTreeQuery(storage_for(db_session), run_id).fetch()["relations"]) == 1


def test_fetch_snapshot_excludes_foreshadowing_edges_from_causal_edges(db_session) -> None:
    """连续性提交的伏笔关联不混入因果边列表"""
    text = "顾霜立誓。\n顾霜离去。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="伏笔边不混因果",
    )
    paragraphs = paragraphs_of(db_session, run_id, 1)
    record_id, _agent_id = add_annotation_source(db_session, run_id, 1)
    root_declaration = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraphs[0],
        title="立誓",
        summary="顾霜立誓",
        is_foreshadowing_root=True,
        payoff_likelihood="high",
    )
    bind_declaration = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraphs[1],
        title="离去",
        summary="顾霜离去",
    )
    db_session.commit()

    _publish(db_session, run_id, [(root_declaration, bind_declaration, "foreshadowing")])
    snapshot = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    assert snapshot is not None
    assert snapshot.causal_edges == []
    assert repo_foreshadow_edges(db_session, run_id) == 1


def repo_foreshadow_edges(session, run_id: str) -> int:
    """伏笔边有独立读取通道：确认被排除的边确实还在（只过滤、不丢数据）"""
    from src.event_trees import storage_map as smap

    return int(
        session.execute(
            select(func.count())
            .select_from(NarrativeLink)
            .where(
                NarrativeLink.producer_agent_id.in_(smap.run_execution_ids(storage_for(session), run_id)),
                NarrativeLink.relation_type == "foreshadowing",
            )
        ).scalar_one()
    )


def test_source_branch_markers_do_not_infer_formal_structure(db_session) -> None:
    """验证次因分支（secondary）按因果前驱 target 归组"""
    text = "顾霜拔剑。\n顾霜喝止。\n顾霜降敌。\n顾霜追问。"
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=[text],
        title="次因分支聚合",
    )
    paragraphs = paragraphs_of(db_session, run_id, 1)
    record_id, _agent_id = add_annotation_source(db_session, run_id, 1)
    declarations = [
        add_declaration(
            db_session,
            record_id=record_id,
            paragraph=paragraph,
            title=summary,
            summary=summary,
            local_key=f"duel-{index}",
        )
        for index, (paragraph, summary) in enumerate(
            zip(paragraphs, ["顾霜拔剑", "顾霜喝止", "顾霜降敌", "顾霜追问"], strict=True)
        )
    ]
    db_session.commit()

    mapping, _draft = publish_declarations(db_session, run_id)
    snapshot = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    assert snapshot is not None
    # 来源的旧树标记不能替代诊断对正式身份与包含关系的判断
    assert len(snapshot.event_trees) == 4
    assert {tree.root_event_id for tree in snapshot.event_trees} == set(declarations)
    assert all(tree.main_chain == [tree.root_event_id] and tree.secondary_groups == [] for tree in snapshot.event_trees)
    assert snapshot.causal_edges == []
    nodes = {node.event_id: node for node in snapshot.event_nodes}
    assert all(node.parent_event_id is None for node in nodes.values())
    assert all(node.evidence_scope == "paragraph" for node in nodes.values())


def test_fetch_snapshot_includes_foreshadowing_edges(db_session) -> None:
    """验证 fetch_snapshot 返回伏笔树视图（伏笔即事件树）"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜立誓"],
        title="伏笔边快照",
    )
    paragraph = first_paragraph(db_session, run_id)
    record_id, agent_id = add_annotation_source(db_session, run_id, 1)
    event_id = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraph,
        phrase="顾霜立誓",
        title="顾霜立誓",
        summary="顾霜立誓",
        is_foreshadowing_root=True,
        payoff_likelihood="high",
    )
    add_foreshadowing_action(
        db_session,
        producer_agent_id=agent_id,
        source_event_id=event_id,
        paragraph=paragraph,
    )
    db_session.commit()

    mapping, _draft = publish_declarations(db_session, run_id)
    repo = EventForestQuery(storage_for(db_session))
    snapshot = repo.fetch_snapshot(run_id)
    assert snapshot is not None
    assert len(snapshot.foreshadowing_edges) == 1
    edge = snapshot.foreshadowing_edges[0]
    assert edge.description == "顾霜立誓"
    assert edge.root_event_id == event_id
    assert edge.payoff_event_id is None
    assert edge.status == "open"
    assert edge.active is True


def test_source_relation_proposal_does_not_rewrite_published_direction(db_session) -> None:
    """同段声明的来源候选关系不能改写已经发布的正式因果关系"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜入门，随后立誓。"])
    paragraph = first_paragraph(db_session, run_id)
    record_id, agent_id = add_annotation_source(db_session, run_id, 1)
    first_declaration = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraph,
        phrase="顾霜入门",
        title="入门",
        summary="顾霜入门",
    )
    second_declaration = add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraph,
        phrase="随后立誓",
        title="立誓",
        summary="顾霜立誓",
    )
    add_declaration_relation(
        db_session,
        producer_agent_id=agent_id,
        source_event_id=first_declaration,
        target_event_id=second_declaration,
        paragraph=paragraph,
        relation_type="causal",
    )
    db_session.commit()

    _publish(db_session, run_id)
    snapshot = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    assert snapshot is not None
    assert set(snapshot.derived_event_order) == {first_declaration, second_declaration}
    assert (
        snapshot.derived_event_order
        == EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id).derived_event_order
    )
    assert len(snapshot.causal_edges) == 1
    # 节点坐标来自各声明自身的原文证据，不由来源候选关系重新绑定
    assert snapshot.event_nodes[0].char_start == 0
    assert snapshot.event_nodes[1].char_start == paragraph.text.find("随后立誓")
    # 章级关系保留原声明端点，全书关系单独保留
    add_declaration_relation(
        db_session,
        producer_agent_id=agent_id,
        source_event_id=second_declaration,
        target_event_id=first_declaration,
        paragraph=paragraph,
        relation_type="causal",
    )
    db_session.commit()
    refreshed = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    assert {(edge.source_event_id, edge.target_event_id) for edge in refreshed.causal_edges} == {
        (first_declaration, second_declaration),
        (second_declaration, first_declaration),
    }


def test_fetch_snapshot_returns_none_for_missing_run(db_session) -> None:
    """验证不存在的 run 查询返回 None"""
    repo = EventForestQuery(storage_for(db_session))
    snapshot = repo.fetch_snapshot(fixture_id(__name__, "nonexistent-run-id"))
    assert snapshot is None


def test_fetch_snapshot_filters_by_chapter_id(db_session) -> None:
    """验证 chapter_id 参数按章节边界截断事件节点"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜进入山门。", "顾霜拔剑。"],
        chapter_ids=[1, 2],
        title="章节边界截断",
    )
    first_record, _agent_id = add_annotation_source(db_session, run_id, 1)
    second_record, _execution_id_2 = add_annotation_source(db_session, run_id, 2)
    add_declaration(
        db_session,
        record_id=first_record,
        paragraph=first_paragraph(db_session, run_id, chapter_id=1),
        title="进入山门",
        summary="顾霜进入山门",
    )
    add_declaration(
        db_session,
        record_id=second_record,
        paragraph=first_paragraph(db_session, run_id, chapter_id=2),
        title="拔剑",
        summary="顾霜拔剑",
    )
    db_session.commit()

    publish_declarations(db_session, run_id)
    repo = EventForestQuery(storage_for(db_session))
    # 只取第 1 章：只有 1 个事件节点
    snapshot_ch1 = repo.fetch_snapshot(run_id, chapter_id=1)
    assert snapshot_ch1 is not None
    assert len(snapshot_ch1.event_nodes) == 1
    assert snapshot_ch1.event_nodes[0].description == "顾霜进入山门"

    # 取全部（最新版本=第 2 章）：2 个事件节点
    snapshot_all = repo.fetch_snapshot(run_id)
    assert snapshot_all is not None
    assert len(snapshot_all.event_nodes) == 2
    assert {node.description for node in snapshot_all.event_nodes} == {
        "顾霜进入山门",
        "顾霜拔剑",
    }
