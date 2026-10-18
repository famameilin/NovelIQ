"""固定输入的完整查询契约；只规范化明确的运行时字段"""

from __future__ import annotations

import asyncio
import json
import uuid
from itertools import count
from pathlib import Path
from typing import Any

ENDPOINTS = (
    "tabs/dashboard",
    "graph",
    "event-trees",
    "timeline",
    "topics",
    "topics/aggregate",
    "topics/series",
    "diagnosis",
    "graph/metrics",
    "results",
)


def prepare_scenario(session: Any, monkeypatch: Any) -> Any:
    """身份和模型训练种子固定，前后版本读取同一份提交后的记录与模型产物"""
    from src.config import settings
    from src.metrics.queries.global_stats import save_global_stats
    from src.workflows.topic import run_topic_model
    from tests.support import chapter_annotation_helpers, timeline_contract_helpers
    from tests.support.chapter_annotation_helpers import relation_fact
    from tests.support.timeline_contract_helpers import create_timeline_contract_scenario

    sequence = count()
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.uuid5(uuid.NAMESPACE_URL, f"module-contract:{next(sequence)}"))
    monkeypatch.setattr(chapter_annotation_helpers, "uuid4", uuid.uuid4)
    # 夹具模块各自 from uuid import uuid4 绑定在导入期：逐个改回序列身份，保证捕获可复现
    monkeypatch.setattr(timeline_contract_helpers, "uuid4", uuid.uuid4)
    scenario = create_timeline_contract_scenario(
        session,
        # 最终保留三角人物关系，避开旧版本空图故障及二分图 HITS 重根
        final_relations=[
            relation_fact(chapter_id=5, from_name=left, to_name=right, relation_type="友情")
            for left, right in [("顾承渊", "苏映雪"), ("顾承渊", "陆遥"), ("苏映雪", "陆遥")]
        ],
        events_by_chapter={
            1: [
                {
                    "description": "顾承渊踏入江湖",
                    "evidence_paragraph_id": 0,
                    "node_id": "arch-root",
                    "title": "踏入江湖",
                    "problem": "踏入江湖的问题",
                    "event_type": "启程",
                    "tree_id": "arrival",
                    "cause_role": "root",
                    "isforeshadowing": True,
                    "payoff_likelihood": "high",
                },
                {
                    "description": "顾承渊记下线索",
                    "evidence_paragraph_id": 0,
                    "node_id": "arch-main",
                    "title": "线索记录",
                    "problem": "线索记录的问题",
                    "event_type": "调查",
                    "tree_id": "arrival",
                    "parent_node_id": "arch-root",
                    "cause_role": "main",
                },
                {
                    "description": "顾承渊检查石碑",
                    "evidence_paragraph_id": 0,
                    "node_id": "arch-side",
                    "title": "石碑疑云",
                    "problem": "石碑疑云的问题",
                    "event_type": "调查",
                    "tree_id": "arrival",
                    "parent_node_id": "arch-root",
                    "cause_role": "secondary",
                },
            ],
            2: [
                {
                    "description": "苏映雪现身同行",
                    "evidence_paragraph_id": 1,
                    "node_id": "arch-second",
                    "title": "同行启程",
                    "problem": "同行启程的问题",
                    "event_type": "结伴",
                    "tree_id": "companion",
                    "cause_role": "root",
                },
                {
                    "node_id": "arch-follow",
                    "title": "踏入江湖",
                    "problem": "踏入江湖的问题",
                    "summary": "顾承渊踏入江湖并检查石碑",
                    "description": "顾承渊踏入江湖并检查石碑",
                    "event_type": "启程",
                    "status": "resolved",
                    "progress": "已查看石碑",
                    "evidence_paragraph_id": 1,
                },
            ],
        },
    )
    from tests.support import diagnosis_helpers

    monkeypatch.setattr(diagnosis_helpers, "uuid4", uuid.uuid4)
    from sqlalchemy import select

    from src.storage.models import ChapterAnnotation, EventDeclaration

    # 声明身份是铸造 uuid，场景中的 node_id 是本地键；分组按本地键解析到正式声明身份
    declaration_of = {
        str(local_key): str(declaration_id)
        for declaration_id, local_key in session.execute(
            select(EventDeclaration.declaration_id, EventDeclaration.local_key)
            .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
            .where(ChapterAnnotation.run_id == scenario.run_id)
        )
    }
    draft = diagnosis_helpers.declaration_event_draft(
        session,
        scenario.run_id,
        groups=[
            [declaration_of[key] for key in group]
            for group in [["arch-root", "arch-follow"], ["arch-main"], ["arch-side"], ["arch-second"]]
        ],
    )
    local_key_of = {identifier: key for key, identifier in declaration_of.items()}
    created = {
        local_key_of[identifier]: event.event_id
        for event in draft.events.values()
        for identifier in event.declaration_ids
    }
    _seed_complete_event_contract(draft, created)
    diagnosis_helpers.persist_event_draft(session, draft)
    monkeypatch.setattr(settings.topic_model, "min_paragraph_train_tokens", 1)
    asyncio.run(run_topic_model(scenario.run_id, session, num_topics=2, passes=1, iterations=10, force=True))
    save_global_stats(session, scenario.run_id)
    session.commit()
    return scenario


def _seed_complete_event_contract(draft: Any, created: dict[str, str]) -> None:
    """由显式身份、包含、真实关系与证据组成正式发布候选"""
    from src.event_trees.organization import ConflictClaim, OrganizationEvidence

    def evidence(paragraph_id):
        return [OrganizationEvidence(paragraph_id=paragraph_id)]

    arrival, stele, clue, companion = (created[key] for key in ("arch-root", "arch-side", "arch-main", "arch-second"))
    for parent, child in [(arrival, stele), (stele, clue)]:
        draft.contain(parent_event_id=parent, child_event_id=child, reason="明确的事件包含", evidence=evidence(0))
    main = draft.register_arc(
        key="main",
        kind="main",
        title="初入江湖",
        objective="寻找同行者",
        role="核心问题",
        reason="旅程目标",
        evidence=evidence(0),
    )
    subplot = draft.register_arc(
        key="subplot",
        kind="subplot",
        title="石碑之谜",
        objective="解开石碑来历",
        role="支线",
        reason="石碑引出后续谜团",
        evidence=evidence(0),
    )
    for event_id, arc_id, role, reason, paragraph in [
        (arrival, main, "主线推进", "旅程开端", 0),
        (companion, main, "主线推进", "同行加入旅程", 1),
        (stele, subplot, "支线起点", "石碑谜团出现", 0),
        (clue, subplot, "支线推进", "线索推进谜团", 0),
    ]:
        draft.link_event_arc(event_id=event_id, arc_id=arc_id, role=role, reason=reason, evidence=evidence(paragraph))
    opened = draft.register_outcome(
        key="opened", title="江湖之路开启", description="顾承渊正式踏上江湖路", evidence=evidence(4)
    )
    unsolved = draft.register_outcome(
        key="unsolved", title="石碑秘密未解", description="石碑来历仍无答案", evidence=evidence(0)
    )
    for event_id, outcome_id, reason, paragraph in [
        (arrival, opened, "旅程开启之路", 0),
        (companion, opened, "同行促成启程", 1),
        (arrival, unsolved, "调查未有结论", 0),
    ]:
        draft.link_event_outcome(event_id=event_id, outcome_id=outcome_id, reason=reason, evidence=evidence(paragraph))
    for key, source, target, kind, reason, paragraph in [
        ("causal", arrival, companion, "causal", "踏入江湖促成同行", 1),
        ("reference", clue, stele, "reference", "记录的线索涉及石碑疑云", 0),
        ("foreshadow", arrival, companion, "foreshadowing", "初入江湖埋设同行伏笔", 0),
    ]:
        draft.relate_events(
            key=key,
            source_kind="event",
            source_id=source,
            target_kind="event",
            target_id=target,
            relation_type=kind,
            reason=reason,
            evidence=evidence(paragraph),
        )
    draft.register_conflict(
        key="years",
        subject_kind="event",
        subject_id=arrival,
        claims=[
            ConflictClaim(claim="入行十年", evidence=evidence(0)),
            ConflictClaim(claim="入行十四年", evidence=evidence(1)),
        ],
        reason="原文对入行年数说法不一",
    )


def capture(client: Any, novel_id: str, task_id: str) -> dict[str, Any]:
    """捕获完整响应和实际导出文件，不以部分字段断言代替结果对照"""
    import json

    result = {}
    for endpoint in ENDPOINTS:
        params: dict[str, str | int] = {"task_id": task_id}
        response = client.get(f"/api/novels/{novel_id}/{endpoint}", params=params)
        assert response.status_code == 200, f"{endpoint}: {response.text}"
        result[endpoint] = response.json()
    result["export"] = json.loads(Path(result["results"]["file_path"]).read_text(encoding="utf-8"))
    return result


#: 序列铸号的字段：graph_facts 主键及其派生的推进变化 id 是数据库序列值，
#: 同一场景在不同测试顺序下取到不同数字，按值秩归一后引用与排序结构保持不变
_FACT_ID_KEY = "fact_id"
_FACT_ID_LIST_KEY = "source_fact_ids"
_DERIVED_ID_KEY = "plotline_change_id"


def _mask_sequence_ids(value: Any) -> Any:
    """图事实主键与由其铸造的推进变化 id 按值秩（升序/首现序）替换为占位符"""
    fact_values: set[str] = set()
    derived_values: list[str] = []

    def collect(node: Any, key: str) -> None:
        if isinstance(node, dict):
            for item_key, item in node.items():
                collect(item, item_key)
        elif isinstance(node, list):
            for item in node:
                collect(item, key)
        elif isinstance(node, str):
            if key == _FACT_ID_KEY and node.isdigit():
                fact_values.add(node)
            elif key == _FACT_ID_LIST_KEY and node.isdigit():
                fact_values.add(node)
            elif key == _DERIVED_ID_KEY:
                derived_values.append(node)

    collect(value, "")
    fact_map = {item: f"fact#{rank}" for rank, item in enumerate(sorted(fact_values, key=int))}
    derived_map = {item: f"plotline#{rank}" for rank, item in enumerate(dict.fromkeys(derived_values))}

    def rebuild(node: Any, key: str) -> Any:
        if isinstance(node, dict):
            return {item_key: rebuild(item, item_key) for item_key, item in node.items()}
        if isinstance(node, list):
            return [rebuild(item, key) for item in node]
        if isinstance(node, str) and key in {_FACT_ID_KEY, _FACT_ID_LIST_KEY}:
            return fact_map.get(node, node)
        if key == _DERIVED_ID_KEY and isinstance(node, str):
            return derived_map.get(node, node)
        return node

    return rebuild(value, "")


def normalize(value: Any, path: tuple[str, ...] = (), *, stable_collections: bool = True) -> Any:
    """运行字段按路径屏蔽；仅两处无序关系集合规范化，有序业务数据不排序"""
    if not path:
        value = _mask_sequence_ids(value)
    if path in {("results", "file_path"), ("export", "generated_at")}:
        return "<runtime>"
    if isinstance(value, dict):
        return {
            key: normalize(item, (*path, key), stable_collections=stable_collections) for key, item in value.items()
        }
    if isinstance(value, list):
        if stable_collections and path in {("graph", "edges"), ("export", "character_relations")}:
            value = sorted(value, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
        return [
            normalize(item, (*path, str(index)), stable_collections=stable_collections)
            for index, item in enumerate(value)
        ]
    return value


def differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """输出精确字段路径，完整快照差异可直接定位且不会隐藏数组排序变化"""
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            return [f"{path}: 字段集合不同"]
        return [diff for key in expected for diff in differences(expected[key], actual[key], f"{path}/{key}")]
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: 长度 {len(expected)} != {len(actual)}"]
        return [
            diff
            for index, (left, right) in enumerate(zip(expected, actual, strict=True))
            for diff in differences(left, right, f"{path}/{index}")
        ]
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]
