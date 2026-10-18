"新结构测试使用的身份分配与事务隔离装配"

from __future__ import annotations

import unicodedata
from functools import cache
from typing import Any
from uuid import UUID

from sqlalchemy import select

from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import CONTRACT_VERSION
from src.storage import Storage, new_id
from src.storage.detached import detached


def uuid7() -> UUID:
    return UUID(new_id())


@cache
def fixture_id(*identity) -> str:
    return new_id()


def mention_id(*identity) -> str:
    return fixture_id("entity", *identity)


def relation_id(*identity) -> str:
    return fixture_id("relation", *identity)


class _FixtureRunner:
    def __init__(self, session):
        self.session = session

    def run(self, operation, *, read_only=False):
        self.session.flush()
        if read_only:
            return detached(operation(self.session))
        with self.session.begin_nested():
            result = detached(operation(self.session))
            self.session.flush()
        self.session.commit()
        return result


def storage_for(session):
    if isinstance(session, Storage):
        return session
    return Storage(_runner=_FixtureRunner(session))


def _character_entity_ids(session, run_id: str, names: list[str]) -> dict[str, str]:
    """诊断名单引用同 run 的正式 character；名称比较沿用 NFC/strip/casefold 身份合同"""
    from src.storage.models import GraphEntity

    if not names:
        return {}
    rows = session.scalars(
        select(GraphEntity).where(GraphEntity.run_id == run_id, GraphEntity.entity_type == "character")
    )
    by_name = {unicodedata.normalize("NFC", row.canonical_name).strip().casefold(): row.entity_id for row in rows}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        entity_id = by_name.get(unicodedata.normalize("NFC", name).strip().casefold())
        if entity_id is None:
            missing.append(name)
        else:
            resolved[name] = entity_id
    if missing:
        raise ValueError(f"诊断名单包含不属于本 run 的正式角色实体: {missing}")
    return resolved


def insert_report_fixture(session, run_id: str, session_id: str, analysis: AgentAnalysis) -> str:
    """写入正式诊断报告及标签/名单/评分条目；同一会话只允许一份报告"""

    from src.storage.models import AnalysisAssessment, DiagnosisReport, Execution

    owner = session.get(Execution, session_id)
    if owner is None or owner.session_run_id != run_id:
        raise ValueError("诊断报告缺少本 run 的真实诊断会话")
    report_id = new_id()
    organization = analysis.narrative_organization
    session.add(
        DiagnosisReport(
            report_id=report_id,
            session_id=session_id,
            contract_version=CONTRACT_VERSION,
            diagnosis=analysis.diagnosis,
            value_logic_type=analysis.value_logic_type,
            value_logic_reason=analysis.value_logic_reason,
            power_stance_score=analysis.power_stance_score,
            power_stance_reason=analysis.power_stance_reason,
            common_people_dignity=analysis.common_people_dignity,
            dignity_reason=analysis.dignity_reason,
            cultural_depth_score=analysis.cultural_depth_score,
            cultural_depth_reason=analysis.cultural_depth_reason,
            narrative_arc_type=analysis.narrative_arc_type,
            focus_structure=analysis.focus_structure,
            theme_color=analysis.theme_color,
            identity_snapshot=organization.identity_snapshot if organization is not None else None,
            structure_snapshot=organization.structure_snapshot if organization is not None else None,
        )
    )
    # 报告行先落库：条目的 report_id 外键不靠 ORM 表排序保证
    session.flush()

    def _assessment(**fields: Any) -> None:
        session.add(AnalysisAssessment(assessment_id=new_id(), report_id=report_id, **fields))

    for ordinal, label in enumerate(analysis.genre_labels):
        _assessment(ordinal=ordinal, genre_label=label)
    for ordinal, label in enumerate(analysis.style_labels):
        _assessment(ordinal=ordinal, style_label=label)
    for topic_key, label in analysis.topic_labels.items():
        _assessment(topic_id=int(topic_key), topic_label=label)
    scores = _character_entity_ids(session, run_id, list(analysis.arc_scores))
    for name, score in analysis.arc_scores.items():
        _assessment(scored_entity_id=scores[name], character_score=float(score))
    for cast_role, members in (
        ("focus", analysis.focus_characters),
        ("main", analysis.main_characters),
        ("core", analysis.core_cast),
    ):
        resolved = _character_entity_ids(session, run_id, list(members))
        for ordinal, name in enumerate(members):
            _assessment(cast_role=cast_role, ordinal=ordinal, cast_entity_id=resolved[name])
    session.flush()
    return report_id


def entity_id(*identity):
    return fixture_id("entity", *identity)


def natural_record(session, model, identity):
    return session.scalar(select(model).filter_by(**identity))


def storage_factory(factory):
    from sqlalchemy.orm import Session, sessionmaker

    from src.storage.operations import OperationRunner

    if isinstance(factory, sessionmaker):
        return lambda: Storage(_runner=OperationRunner(factory))

    def build():
        session = factory()
        if isinstance(session, Storage):
            return session
        if isinstance(session, Session) and not session.info.get("fixture_shared"):
            return Storage(_runner=OperationRunner(lambda: session))
        if not isinstance(session, Session):
            return Storage(_runner=OperationRunner(lambda: session))
        return storage_for(session)

    return build


@cache
def _stub_task_id(run_id):
    from src.storage.ids import new_task_id

    return new_task_id()


def task_for_run(run_id, session=None):
    "真实运行读取 task 映射，内存桩使用独立分配的短 ID"
    from src.storage.db import get_session_factory
    from src.storage.models import AnalysisRun

    if session is not None:
        session.flush()
        row = session.get(AnalysisRun, run_id)
        if row is not None:
            return row.task_id
    try:
        valid = UUID(run_id).version == 7
    except ValueError:
        valid = False
    if valid:
        with get_session_factory()() as session:
            task_id = session.scalar(select(AnalysisRun.task_id).where(AnalysisRun.run_id == run_id))
        if task_id is not None:
            return task_id
    return _stub_task_id(run_id)
