"""事件树契约：完整事件读取、同结构事件卡、关系定位与原文来源

夹具自足：三章真实原文与标注来源链 + 六份章级声明，沿正式诊断草稿发布
（完整事件/阶段链/包含/关系/叙事线/结果/伏笔动作），读取面用公开 API 与
EventTreeQuery；证据坐标一律来自真实原文，不手写画布位置。
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select

from src.event_trees.read.organization import CONTRACT_VERSION, EventTreeQuery, RunRequiresRebuildError
from src.storage.models import (
    DiagnosisReport,
    EventRevision,
    NarrativeLink,
    Paragraph,
    SourceEvidence,
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_diagnosis_context,
    add_foreshadowing_action,
    close_structure,
    first_paragraph,
    identity_every_declaration,
    publish_draft,
)
from tests.support.run_records import set_run_status

TEXTS = ["第一章正文。\n第一章非证据段落。", "第二章正文。", "第三章正文。\n第三章余波。"]


@dataclass(frozen=True)
class EventTreeScenario:
    novel_id: str
    run_id: str
    task_id: str
    session_id: str
    execution_id: str
    events: dict[str, str]
    revisions: dict[str, str]
    declarations: dict[str, str]
    arcs: dict[str, str]
    outcomes: dict[str, str]
    actions: dict[str, str]


def _paragraphs(session: Any, run_id: str) -> dict[int, Paragraph]:
    result: dict[int, Paragraph] = {}
    for row in session.scalars(select(Paragraph).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id)):
        result.setdefault(row.chapter_id, row)
    return result


def _identity_evidence():
    from src.event_trees.organization import OrganizationEvidence

    return [OrganizationEvidence(paragraph_id=0)]


def _seed_scenario(session: Any) -> EventTreeScenario:
    novel_id, run_id = create_run_with_chunks(
        session, texts=TEXTS, chapter_ids=[1, 2, 3], title="Event Tree Contract"
    )
    set_run_status(session, run_id, "completed")
    paragraphs = _paragraphs(session, run_id)
    session_id, execution_id = add_diagnosis_context(session, run_id)
    annotations: dict[int, str] = {}
    declarations: dict[str, str] = {}

    def declare(chapter: int, key: str, phrase: str, *, paragraph: Paragraph | None = None, **kwargs: Any) -> None:
        record_id = annotations[chapter]
        declarations[key] = add_declaration(
            session,
            record_id=record_id,
            paragraph=paragraph if paragraph is not None else paragraphs[chapter],
            phrase=phrase,
            title=kwargs.pop("title", "踏入江湖"),
            problem=kwargs.pop("problem", "能否前行"),
            summary=kwargs.pop("summary", phrase),
            event_type=kwargs.pop("event_type", "行动"),
            **kwargs,
        )

    for chapter in (1, 2, 3):
        record_id, _execution = add_annotation_source(session, run_id, chapter, role="event")
        annotations[chapter] = record_id
    third_chapter_second = list(
        session.scalars(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == 3)
            .order_by(Paragraph.paragraph_index)
        )
    )[1]
    declare(1, "p1", "第一章正文", title="踏入江湖", summary="概要第一版", status="ongoing",
            participants=(("顾承渊", "主体"),))
    declare(2, "p4", "第二章正文", title="踏入江湖", summary="概要第二版", status="resolved",
            progress="已确认新版进展", participants=(("顾承渊", "主体"),))
    declare(2, "p2", "第二章", title="石碑疑云", problem="石碑是什么", summary="石碑疑云的初始概要",
            status="ongoing", participants=(("苏映雪", "主体"),))
    declare(2, "p5", "正文", title="线索记录", problem="线索是否可靠", summary="线索记录的初始概要",
            status="resolved")
    declare(3, "p3", "第三章", title="同行启程", problem="能否同行", summary="同行启程的初始概要", status="ongoing")
    declare(3, "p6", "第三章余波", paragraph=third_chapter_second, title="城外余波", problem="余波如何",
            summary="城外余波的初始概要", status="ongoing")
    session.flush()
    draft, _meta = identity_every_declaration(
        session,
        run_id,
        groups=[
            [declarations["p1"], declarations["p4"]],
            [declarations["p2"]],
            [declarations["p5"]],
            [declarations["p3"]],
            [declarations["p6"]],
        ],
        context=(session_id, execution_id),
    )
    mapping = {key: item.event_id for item in draft.events.values() for key in item.declaration_ids}
    events = {
        alias: mapping[declarations[key]]
        for alias, key in (("e1", "p1"), ("e2", "p2"), ("e3", "p5"), ("e4", "p3"), ("e5", "p6"))
    }
    draft.contain(
        parent_event_id=events["e1"],
        child_event_id=events["e2"],
        reason="石碑是旅程中的独立小问题",
        evidence=_identity_evidence(),
    )
    draft.contain(
        parent_event_id=events["e2"],
        child_event_id=events["e3"],
        reason="记录线索属于石碑调查",
        evidence=_identity_evidence(),
    )
    draft.relate_events(
        key="causal-1",
        source_kind="event",
        source_id=events["e1"],
        target_kind="event",
        target_id=events["e4"],
        relation_type="causal",
        reason="踏入江湖促成同行",
        evidence=_identity_evidence(),
    )
    draft.relate_events(
        key="reference-1",
        source_kind="event",
        source_id=events["e1"],
        target_kind="event",
        target_id=events["e2"],
        relation_type="reference",
        reason="石碑事件引用调查声明",
        evidence=_identity_evidence(),
    )
    draft.relate_events(
        key="foreshadow-1",
        source_kind="event",
        source_id=events["e1"],
        target_kind="event",
        target_id=events["e5"],
        relation_type="foreshadowing",
        reason="初入江湖埋设同行伏笔",
        evidence=_identity_evidence(),
    )
    close_structure(session, draft, evidence_paragraph_id=int(paragraphs[1].paragraph_id))
    arcs = {
        "a1": draft.register_arc(
            key="journey", kind="main", title="主线旅程", objective="完成旅程", role="核心问题",
            reason="主线", evidence=_identity_evidence(),
        ),
        "a2": draft.register_arc(
            key="stele", kind="subplot", title="石碑之谜", objective="解开石碑", role="支线",
            reason="支线", evidence=_identity_evidence(),
        ),
    }
    outcomes = {
        "o1": draft.register_outcome(
            key="journey-open", title="江湖之路开启", description="正式踏上江湖路",
            evidence=_identity_evidence(),
        ),
        "o2": draft.register_outcome(
            key="stele-open", title="石碑秘密未解", description="调查未有结论",
            evidence=_identity_evidence(),
        ),
    }
    for event_key, arc_key, role, reason in (
        ("e1", "a1", "主线推进", "旅程开端"),
        ("e1", "a2", "支线引出", "石碑引出支线"),
        ("e2", "a2", "支线起点", "谜团出现"),
        ("e4", "a1", "主线推进", "同行加入"),
    ):
        draft.link_event_arc(
            event_id=events[event_key], arc_id=arcs[arc_key], role=role, reason=reason,
            evidence=_identity_evidence(),
        )
    for event_key, outcome_key, reason in (
        ("e1", "o1", "旅程开启"),
        ("e4", "o1", "同行促成"),
        ("e1", "o2", "调查无果"),
    ):
        draft.link_event_outcome(
            event_id=events[event_key], outcome_id=outcomes[outcome_key], reason=reason,
            evidence=_identity_evidence(),
        )
    publish_draft(session, run_id, draft)
    revisions = {
        row.declaration_id: row.revision_id
        for row in session.scalars(
            select(EventRevision).where(EventRevision.event_id.in_(list(events.values())))
        )
    }
    actions = {
        "f1": add_foreshadowing_action(
            session,
            producer_execution_id=execution_id,
            source_declaration_id=declarations["p1"],
            paragraph=paragraphs[1],
            action_type="setup",
            operation_order=1,
        ),
        "f2": add_foreshadowing_action(
            session,
            producer_execution_id=execution_id,
            source_declaration_id=declarations["p1"],
            target_declaration_id=declarations["p3"],
            paragraph=paragraphs[3],
            action_type="payoff",
            operation_order=2,
        ),
    }
    session.commit()
    return EventTreeScenario(
        novel_id=novel_id,
        run_id=run_id,
        task_id=run_id[:8],
        session_id=session_id,
        execution_id=execution_id,
        events=events,
        revisions={key: revisions[declarations[key]] for key in ("p1", "p4", "p2", "p5", "p3", "p6")},
        declarations=declarations,
        arcs=arcs,
        outcomes=outcomes,
        actions=actions,
    )


def _seed_legacy_run(session: Any) -> tuple[str, str]:
    novel_id, run_id = create_run_with_chunks(session, texts=["旧契约章节。"], chapter_ids=[1], title="Legacy Run")
    set_run_status(session, run_id, "completed")
    add_annotation_source(session, run_id, 1, role="event", contract_version="event-tree-2026-10-13")
    session.commit()
    return novel_id, run_id


def _seed_empty_contract_run(session: Any) -> tuple[str, str]:
    novel_id, run_id = create_run_with_chunks(session, texts=["空运行章节。"], chapter_ids=[1], title="Empty Run")
    set_run_status(session, run_id, "completed")
    # 正式保存的版本标记允许合法零事件运行
    add_annotation_source(session, run_id, 1, role="event")
    session.commit()
    return novel_id, run_id


def _url(scenario: EventTreeScenario) -> str:
    return f"/api/novels/{scenario.novel_id}/event-trees"


def _params(scenario: EventTreeScenario, **extra: Any) -> dict[str, Any]:
    return {"task_id": scenario.task_id, **extra}


def test_list_payload_fields_counts_and_top_level_pagination(api_client, db_session):
    scenario = _seed_scenario(db_session)
    response = api_client.get(_url(scenario), params=_params(scenario))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "organization_status",
        "run_id",
        "contract_version",
        "chapters",
        "counts",
        "arcs",
        "events",
        "outcomes",
        "event_arc_links",
        "event_outcome_links",
        "relations",
        "foreshadowing_actions",
        "next_cursor",
    }
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["run_id"] == scenario.run_id
    assert [row["chapter_id"] for row in body["chapters"]] == [1, 2, 3]
    assert body["counts"] == {
        "top_level_events": 3,
        "child_events": 2,
        "all_events": 5,
        "declarations": 6,
        "outcomes": 2,
        "event_outcome_links": 3,
        "arcs": 2,
        "event_arc_links": 4,
        "relations": 3,
        "foreshadowing_actions": 2,
    }
    # 仅顶层大事件出现在画布分页中，子事件不冒充画布标记
    assert [row["event_id"] for row in body["events"]] == [
        scenario.events["e1"],
        scenario.events["e4"],
        scenario.events["e5"],
    ]
    entry = body["events"][0]
    assert set(entry) == {
        "event_id",
        "title",
        "summary",
        "event_type",
        "status",
        "first_text_position",
        "chapter_id",
        "chapter_order",
    }
    # 当前内容取阶段链尾（第二章声明），事件归属仍是最初证据章
    assert entry["summary"] == "概要第二版" and entry["chapter_id"] == 1 and entry["chapter_order"] == 1
    assert {row["arc_id"] for row in body["arcs"]} == set(scenario.arcs.values())
    assert {row["outcome_id"] for row in body["outcomes"]} == set(scenario.outcomes.values())
    assert len(body["event_arc_links"]) == 4 and len(body["event_outcome_links"]) == 3
    assert len(body["relations"]) == 3
    assert [row["action_id"] for row in body["foreshadowing_actions"]] == [
        scenario.actions["f1"],
        scenario.actions["f2"],
    ]
    action = body["foreshadowing_actions"][0]
    assert action["endpoint_kind"] == "event"
    assert action["root_event_id"] == scenario.events["e1"]
    assert action["target_event_id"] is None
    assert "owner_event_id" not in action
    payoff = body["foreshadowing_actions"][1]
    assert payoff["target_event_id"] == scenario.events["e4"]
    assert body["next_cursor"] is None


def test_multi_page_cursor_consumes_all_pages(api_client, db_session):
    scenario = _seed_scenario(db_session)
    expected = [
        row["event_id"]
        for row in api_client.get(_url(scenario), params=_params(scenario)).json()["events"]
    ]
    assert expected == [scenario.events["e1"], scenario.events["e4"], scenario.events["e5"]]
    first = api_client.get(_url(scenario), params=_params(scenario, limit=2)).json()
    assert [row["event_id"] for row in first["events"]] == expected[:2]
    assert first["next_cursor"]
    second = api_client.get(_url(scenario), params=_params(scenario, limit=2, cursor=first["next_cursor"])).json()
    assert [row["event_id"] for row in second["events"]] == expected[2:]
    assert second["next_cursor"] is None
    # 分页只是传输边界：计数与关联数据每页完整返回
    for page in (first, second):
        assert page["counts"]["all_events"] == 5 and len(page["relations"]) == 3


def test_current_annotation_does_not_hide_old_diagnosis_contract(db_session):
    _, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    session_id, _execution = add_diagnosis_context(db_session, run_id)
    add_annotation_source(db_session, run_id, 1, role="event")
    db_session.add(
        DiagnosisReport(
            report_id=str(uuid.uuid4()),
            session_id=session_id,
            contract_version="event-tree-2026-10-13",
        )
    )
    db_session.flush()
    with pytest.raises(RunRequiresRebuildError):
        EventTreeQuery(db_session, run_id).fetch()


def test_cursor_rejects_other_run_and_tampered_context(api_client, db_session):
    scenario = _seed_scenario(db_session)
    first = api_client.get(_url(scenario), params=_params(scenario, limit=1)).json()
    other = _seed_scenario(db_session)
    rejected = api_client.get(_url(other), params=_params(other, limit=1, cursor=first["next_cursor"]))
    assert rejected.status_code == 400
    data = json.loads(base64.urlsafe_b64decode(first["next_cursor"].encode()).decode())
    data["query"][2] = "nodes"
    tampered = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    assert api_client.get(_url(scenario), params=_params(scenario, limit=1, cursor=tampered)).status_code == 400


def test_detail_same_shape_dto_children_characters_arcs_ancestry_revision(api_client, db_session):
    scenario = _seed_scenario(db_session)
    url = f"{_url(scenario)}/nodes/{scenario.events['e1']}"
    detail = api_client.get(url, params=_params(scenario)).json()
    assert set(detail) == {
        "kind",
        "event_id",
        "run_id",
        "title",
        "summary",
        "progress",
        "event_type",
        "status",
        "arcs",
        "characters",
        "direct_children",
        "evidence",
        "evidence_scope",
        "source_chapters",
        "ancestry",
        "revision_id",
        "relations",
    }
    assert detail["kind"] == "event" and detail["run_id"] == scenario.run_id
    assert detail["summary"] == "概要第二版" and detail["progress"] == "已确认新版进展"
    assert detail["revision_id"] == scenario.revisions["p4"]
    # 直接子事件不含孙事件；卡片逐级进入
    assert [row["event_id"] for row in detail["direct_children"]] == [scenario.events["e2"]]
    assert all(set(row) == {"event_id", "title", "event_type", "status"} for row in detail["direct_children"])
    # 未在正式图谱确认身份前，参与者不冒充事件卡人物（机构与地点更不会被当成涉及人物）
    assert detail["characters"] == []
    # 全部实际关联叙事线及依据
    assert {row["arc_id"] for row in detail["arcs"]} == {scenario.arcs["a1"], scenario.arcs["a2"]}
    assert all({"arc_id", "title", "kind", "role", "reason"} <= set(row) for row in detail["arcs"])
    # 当前版本证据与事件证据合并：跨章来源保留
    assert detail["source_chapters"] == [1, 2]
    assert detail["evidence_scope"] == "paragraph"
    assert detail["ancestry"] == []

    grandchild = api_client.get(f"{_url(scenario)}/nodes/{scenario.events['e3']}", params=_params(scenario)).json()
    assert grandchild["ancestry"] == [scenario.events["e1"], scenario.events["e2"]]
    assert grandchild["revision_id"] == scenario.revisions["p5"] and grandchild["summary"] == "线索记录的初始概要"
    child = api_client.get(f"{_url(scenario)}/nodes/{scenario.events['e2']}", params=_params(scenario)).json()
    assert [row["event_id"] for row in child["direct_children"]] == [scenario.events["e3"]]


def test_detail_unknown_node_is_404(api_client, db_session):
    scenario = _seed_scenario(db_session)
    assert api_client.get(f"{_url(scenario)}/nodes/{uuid.uuid4()}", params=_params(scenario)).status_code == 404
    # 声明身份不能当完整事件详情读取
    assert (
        api_client.get(
            f"{_url(scenario)}/nodes/{scenario.declarations['p1']}", params=_params(scenario)
        ).status_code
        == 404
    )


def test_relation_entries_carry_location_fields(api_client, db_session):
    scenario = _seed_scenario(db_session)
    body = api_client.get(_url(scenario), params=_params(scenario)).json()
    positions = {row["event_id"]: row["first_text_position"] for row in body["events"]}
    by_target = {(row["target_kind"], row["target_id"]): row for row in body["relations"]}
    event_target = by_target[("event", scenario.events["e4"])]
    assert event_target["top_level_event_id"] == scenario.events["e4"]
    assert event_target["ancestor_event_ids"] == []
    assert "owner_event_id" not in event_target
    assert event_target["evidence_position"] == positions[scenario.events["e4"]]
    declaration_target = by_target[("event", scenario.events["e2"])]
    assert declaration_target["top_level_event_id"] == scenario.events["e1"]
    assert declaration_target["ancestor_event_ids"] == [scenario.events["e1"]]
    assert "owner_event_id" not in declaration_target
    owned_by_top = by_target[("event", scenario.events["e5"])]
    assert "owner_event_id" not in owned_by_top
    assert owned_by_top["top_level_event_id"] == scenario.events["e5"]

    detail = api_client.get(f"{_url(scenario)}/nodes/{scenario.events['e4']}", params=_params(scenario)).json()
    # 详情内关系定位落在对端：e4 的因果来源 e1 给出其画布入口
    assert [row["source_id"] for row in detail["relations"]] == [scenario.events["e1"]]
    incoming = detail["relations"][0]
    assert incoming["top_level_event_id"] == scenario.events["e1"]
    assert incoming["ancestor_event_ids"] == []
    assert incoming["evidence_position"] == positions[scenario.events["e1"]]


def test_source_endpoint_event_and_declaration_paths(api_client, db_session):
    scenario = _seed_scenario(db_session)
    base = f"{_url(scenario)}/nodes/{scenario.events['e1']}/source"
    event_source = api_client.get(base, params=_params(scenario))
    assert event_source.status_code == 200
    assert event_source.json()["chapter_id"] == 1
    # 跨章事件：其他证据章节同样可读，不被单一 chapter_id 裁掉
    cross = api_client.get(base, params=_params(scenario, chapter_id=2))
    assert cross.status_code == 200 and cross.json()["chapter_id"] == 2
    assert "第二章正文" in cross.json()["paragraphs"][0]["text"]
    denied = api_client.get(base, params=_params(scenario, chapter_id=3))
    assert denied.status_code == 404

    declaration_source = api_client.get(
        f"{_url(scenario)}/nodes/{scenario.declarations['p1']}/source",
        params=_params(scenario, kind="declaration"),
    )
    assert declaration_source.status_code == 200
    assert "第一章正文" in declaration_source.json()["paragraphs"][0]["text"]
    assert len(declaration_source.json()["paragraphs"]) == 2
    expected_evidence = EventTreeQuery(db_session, scenario.run_id).declaration_source(
        scenario.declarations["p1"]
    )
    assert declaration_source.json()["evidence"] == expected_evidence
    assert len(declaration_source.json()["evidence"]) == 1
    assert declaration_source.json()["evidence_scope"] == "paragraph"
    assert declaration_source.json()["locator"] == {
        "target_kind": "declaration",
        "target_id": scenario.declarations["p1"],
        "title": "踏入江湖",
        "top_level_event_id": None,
        "ancestor_event_ids": [],
        "evidence_position": expected_evidence[0]["char_start"],
    }
    child_declaration = api_client.get(
        f"{_url(scenario)}/nodes/{scenario.declarations['p2']}/source",
        params=_params(scenario, kind="declaration"),
    ).json()["locator"]
    assert child_declaration["target_id"] == scenario.declarations["p2"]
    assert "owner_event_id" not in child_declaration
    assert child_declaration["top_level_event_id"] is None
    assert child_declaration["ancestor_event_ids"] == []
    invalid_kind = api_client.get(base, params=_params(scenario, kind="node"))
    assert invalid_kind.status_code == 422


def test_source_rejects_declaration_from_other_run(api_client, db_session):
    scenario = _seed_scenario(db_session)
    other = _seed_scenario(db_session)
    response = api_client.get(
        f"{_url(scenario)}/nodes/{other.declarations['p1']}/source",
        params=_params(scenario, kind="declaration"),
    )
    assert response.status_code == 404


def test_legacy_run_requires_rebuild_on_all_endpoints(api_client, db_session):
    scenario = _seed_scenario(db_session)
    novel_id, run_id = _seed_legacy_run(db_session)
    params = {"task_id": run_id[:8]}
    for url in (
        f"/api/novels/{novel_id}/event-trees",
        f"/api/novels/{novel_id}/event-trees/nodes/{scenario.events['e1']}",
        f"/api/novels/{novel_id}/event-trees/nodes/{scenario.events['e1']}/source",
    ):
        response = api_client.get(url, params=params)
        assert response.status_code == 400, url
        assert response.json()["detail"]["code"] == "RUN_REQUIRES_REBUILD"
        assert "重建" in response.json()["detail"]["message"]


def test_list_has_no_search_contract(api_client, db_session):
    scenario = _seed_scenario(db_session)
    body = api_client.get(_url(scenario), params=_params(scenario)).json()
    assert "matches" not in body and "q" not in body and "nodes" not in body
    detail = api_client.get(f"{_url(scenario)}/nodes/{scenario.events['e1']}", params=_params(scenario)).json()
    assert "matches" not in detail and "references" not in detail
    with_q = api_client.get(_url(scenario), params=_params(scenario, q="石碑"))
    assert with_q.status_code in (200, 422)
    if with_q.status_code == 200:
        assert "matches" not in with_q.json()


def test_saved_contract_allows_zero_events(api_client, db_session):
    novel_id, run_id = _seed_empty_contract_run(db_session)
    response = api_client.get(f"/api/novels/{novel_id}/event-trees", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    assert set(response.json()["counts"].values()) == {0}
    assert response.json()["events"] == [] and response.json()["next_cursor"] is None


@pytest.mark.parametrize("invalid", ["missing_binding", "missing_link_evidence", "missing_declaration_evidence"])
def test_corrupt_saved_contract_is_rejected_without_get_repair(api_client, db_session, invalid):
    scenario = _seed_scenario(db_session)
    if invalid == "missing_binding":
        # 已保存之后新增的声明没有任何正式身份绑定
        record_id, _execution = add_annotation_source(db_session, scenario.run_id, 2, role="metric")
        orphan = add_declaration(
            db_session,
            record_id=record_id,
            paragraph=first_paragraph(db_session, scenario.run_id, chapter_id=2),
            phrase="第二章",
            title="未绑定声明",
        )
    elif invalid == "missing_link_evidence":
        link_id = db_session.scalars(
            select(NarrativeLink.link_id).where(
                NarrativeLink.semantic_source_event_id == scenario.events["e1"],
                NarrativeLink.semantic_target_event_id == scenario.events["e4"],
            )
        ).one()
        for row in db_session.scalars(
            select(SourceEvidence).where(SourceEvidence.narrative_link_id == link_id)
        ):
            db_session.delete(row)
    else:
        orphan = scenario.declarations["p2"]
        for row in db_session.scalars(
            select(SourceEvidence).where(SourceEvidence.declaration_id == orphan)
        ):
            db_session.delete(row)
    db_session.commit()
    response = api_client.get(_url(scenario), params=_params(scenario))
    assert response.status_code == 400
    db_session.expire_all()
    # 读取不修补已保存对象：缺失的来源仍在原处缺失
    if invalid == "missing_binding":
        assert db_session.get(EventRevision, scenario.revisions["p2"]) is not None
    elif invalid == "missing_link_evidence":
        assert not list(
            db_session.scalars(select(SourceEvidence).where(SourceEvidence.narrative_link_id == link_id))
        )
    else:
        assert not list(
            db_session.scalars(select(SourceEvidence).where(SourceEvidence.declaration_id == orphan))
        )


def test_declaration_source_and_export_also_reject_legacy_run(api_client, db_session):
    novel_id, run_id = _seed_legacy_run(db_session)
    params = {"task_id": run_id[:8], "kind": "declaration"}
    response = api_client.get(f"/api/novels/{novel_id}/event-trees/nodes/missing/source", params=params)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "RUN_REQUIRES_REBUILD"
    exported = api_client.get(f"/api/novels/{novel_id}/results", params={"task_id": run_id[:8]})
    assert exported.status_code == 400
    assert exported.json()["detail"]["code"] == "RUN_REQUIRES_REBUILD"


def test_incoming_relation_locator_preserves_direction(api_client, db_session):
    scenario = _seed_scenario(db_session)
    detail = api_client.get(f"{_url(scenario)}/nodes/{scenario.events['e4']}", params=_params(scenario)).json()
    relation = detail["relations"][0]
    assert relation["target_id"] == scenario.events["e4"]
    assert relation["locator"]["target_kind"] == "event"
    assert relation["locator"]["target_id"] == scenario.events["e1"]
    assert relation["locator"]["title"] == "踏入江湖"
    assert relation["evidence"]


def test_cross_chapter_source_keeps_prior_revision_evidence(api_client, db_session):
    scenario = _seed_scenario(db_session)
    # 当前版本在第二章时，首版声明仍授权读取第一章
    detail = api_client.get(f"{_url(scenario)}/nodes/{scenario.events['e1']}", params=_params(scenario)).json()
    assert detail["revision_id"] == scenario.revisions["p4"]
    response = api_client.get(
        f"{_url(scenario)}/nodes/{scenario.events['e1']}/source", params=_params(scenario, chapter_id=1)
    )
    assert response.status_code == 200 and response.json()["chapter_id"] == 1


def test_export_preserves_formal_events_declarations_and_version_sources(db_session):
    scenario = _seed_scenario(db_session)
    exported = EventTreeQuery(db_session, scenario.run_id).export()
    assert {row["event_id"] for row in exported["event_records"]} == set(scenario.events.values())
    assert all(row["problem"] and row["current_revision_id"] for row in exported["event_records"])
    assert {row["declaration_id"] for row in exported["declarations"]} == set(scenario.declarations.values())
    assert all(row["declaration_id"] and row["evidence"] for row in exported["declarations"])
    assert len(exported["containments"]) == 2
    assert {row["revision_id"] for row in exported["revisions"]} == set(scenario.revisions.values())
    assert all(
        row["source_operation_id"] and row["source_execution_id"] and row["evidence"] for row in exported["revisions"]
    )
    # 同一结果有两个来源，且同一大事件形成两个结果，两项独立依据均保留
    links = exported["event_outcome_links"]
    assert sum(row["outcome_id"] == scenario.outcomes["o1"] for row in links) == 2
    assert sum(row["event_id"] == scenario.events["e1"] for row in links) == 2
    assert all(row["evidence"] for row in links)
