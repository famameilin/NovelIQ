"""完整事件存储契约测试（2026-10-16 全库 3NF 改造）

覆盖新关系的建表冒烟、候选键/唯一约束与 CheckConstraint/领域触发器在 DB 级的
生效：complete_events + 真实生产执行、event_revisions 显式连续阶段链与声明绑定、
narrative_links 单父包含与语义端点的互斥形状、冲突主体/陈述、组织核对逐对判断、
伏笔动作幂等与证据所有者列。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.storage.models import (
    AnalysisRun,
    Base,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    ConflictClaim,
    ConflictRecord,
    EventDeclaration,
    EventForeshadowingAction,
    EventRevision,
    Execution,
    GraphFact,
    NarrativeGroup,
    NarrativeLink,
    Novel,
    OrganizationCheck,
    Paragraph,
    SourceEvidence,
    WorkItem,
    naive_utcnow,
)

CONTRACT = "event-tree-declarations-v1"

NEW_TABLES = [
    "event_declarations",
    "declaration_participants",
    "complete_events",
    "event_revisions",
    "narrative_links",
    "narrative_groups",
    "organization_checks",
    "conflict_records",
    "conflict_claims",
    "event_foreshadowing_actions",
    "source_evidence",
    "book_cases",
    "case_entries",
    "diagnosis_reports",
]


class _Fixture:
    """自足夹具：小说/运行/章节/段落 + 标注来源身份 + 诊断会话/work/执行"""

    def __init__(self, session: Session, *, title: str, chapters: int = 1) -> None:
        self.session = session
        self.novel_id = uuid.uuid4().hex[:8]
        self.run_id = str(uuid.uuid4())
        session.add(
            Novel(
                novel_id=self.novel_id,
                filename=f"{self.novel_id}.txt",
                file_path=f"tests/{self.novel_id}.txt",
                file_size=32,
                title=title,
            )
        )
        # 无 relationship：跨表插入按依赖分层 flush（先父后子）
        session.flush()
        session.add(
            AnalysisRun(
                run_id=self.run_id,
                novel_id=self.novel_id,
                status="completed",
                progress=1.0,
                task_kind="test",
                created_at=naive_utcnow(),
            )
        )
        self.paragraph_ids: list[int] = []
        self.declarations: list[str] = []
        # 主表先落库：无 relationship 的复合外键不参与 ORM 依赖排序
        session.flush()
        offset = 0
        paragraph_id = 0
        for chapter_id in range(1, chapters + 1):
            text = f"第{chapter_id}章顾霜进入山门。"
            session.add(
                Chapter(
                    run_id=self.run_id,
                    chapter_id=chapter_id,
                    sequence=chapter_id,
                    title=f"第{chapter_id}章",
                    display_title=f"第{chapter_id}章",
                    level="chapter",
                    start_pos=offset,
                    end_pos=offset + len(text),
                    text=text,
                    char_offset=offset,
                )
            )
            session.add(
                Paragraph(
                    run_id=self.run_id,
                    paragraph_id=paragraph_id,
                    chapter_id=chapter_id,
                    paragraph_index=0,
                    source_paragraph_index=0,
                    fragment_index=0,
                    local_start_char=0,
                    text=text,
                    created_at=naive_utcnow(),
                )
            )
            self.paragraph_ids.append(paragraph_id)
            offset += len(text)
            paragraph_id += 1
        # 章节与段落先落库：标注 work 的复合外键不参与 ORM 依赖排序
        session.flush()
        # 标注 work/执行/记录：声明的真实来源链
        self.annotation_work_id = f"annotation-work-{self.novel_id}"
        self.annotation_execution_id = uuid.uuid4().hex
        session.add(
            WorkItem(
                work_id=self.annotation_work_id,
                role="solo",
                annotation_run_id=self.run_id,
                annotation_chapter_id=1,
            )
        )
        session.flush()
        session.add(
            Execution(
                execution_id=self.annotation_execution_id,
                work_id=self.annotation_work_id,
                attempt_number=1,
                started_at=naive_utcnow(),
                status="success",
            )
        )
        session.flush()
        self.record_id = str(uuid.uuid4())
        session.add(
            ChapterAnnotation(
                record_id=self.record_id,
                execution_id=self.annotation_execution_id,
                contract_version=CONTRACT,
                chapter_consolidation_version="v1",
                created_at=naive_utcnow(),
            )
        )
        # 诊断会话/work/执行：完整事件与关系的真实生产者
        self.session_id = f"diagnosis-session-{self.novel_id}"
        self.work_id = f"diagnosis-work-{self.novel_id}"
        self.execution_id = uuid.uuid4().hex
        session.add(
            Execution(
                execution_id=self.session_id,
                session_run_id=self.run_id,
                session_created_at=naive_utcnow(),
            )
        )
        session.flush()
        session.add(WorkItem(work_id=self.work_id, role="report", diagnosis_session_id=self.session_id))
        session.flush()
        session.add(
            Execution(
                execution_id=self.execution_id,
                work_id=self.work_id,
                attempt_number=1,
                started_at=naive_utcnow(),
                status="success",
            )
        )
        session.flush()

    def make_declaration(self, chapter_id: int = 1, *, phrase: str = "顾霜", payoff: str | None = None) -> str:
        """插入不可变声明与原文证据（证据区间由真实原文派生）"""
        declaration_id = str(uuid.uuid4())
        paragraph_id = self.paragraph_ids[chapter_id - 1]
        paragraph = self.session.get(Paragraph, {"run_id": self.run_id, "paragraph_id": paragraph_id})
        start = str(paragraph.text).find(phrase)
        assert start >= 0
        self.session.add(
            EventDeclaration(
                declaration_id=declaration_id,
                record_id=self.record_id,
                local_key=f"el-{declaration_id[:8]}",
                title=f"入山{chapter_id}",
                problem="能否进入山门",
                summary=str(paragraph.text),
                event_type="行程",
                status="ongoing",
                progress=None,
                is_foreshadowing_root=payoff is not None,
                payoff_likelihood=payoff,
                created_at=naive_utcnow(),
            )
        )
        self.session.flush()
        self.session.add(
            SourceEvidence(
                evidence_id=str(uuid.uuid4()),
                ordinal=0,
                paragraph_id=paragraph_id,
                start_char=start,
                end_char=start + len(phrase),
                declaration_id=declaration_id,
            )
        )
        self.session.flush()
        self.declarations.append(declaration_id)
        return declaration_id

    def make_event(self, *, local_key: str | None = None) -> str:
        event_id = str(uuid.uuid4())
        self.session.add(
            CompleteEvent(
                event_id=event_id,
                producer_execution_id=self.execution_id,
                local_key=local_key or event_id,
                identity_reason="夹具显式判断该身份",
            )
        )
        self.session.flush()
        return event_id

    def make_revision(self, event_id: str, *, stage_index: int = 0, declaration_id: str | None = None) -> str:
        revision_id = str(uuid.uuid4())
        if declaration_id is None:
            self.session.add(
                EventRevision(
                    revision_id=revision_id,
                    event_id=event_id,
                    stage_index=stage_index,
                    origin_title="独立阶段",
                    origin_problem="独立阶段问题",
                    origin_summary="独立阶段正文",
                    origin_event_type="行动",
                    origin_status="ongoing",
                    origin_progress=None,
                )
            )
        else:
            self.session.add(
                EventRevision(
                    revision_id=revision_id,
                    event_id=event_id,
                    stage_index=stage_index,
                    declaration_id=declaration_id,
                )
            )
        self.session.flush()
        return revision_id

    def make_fact(self) -> int:
        fact = GraphFact(
            run_id=self.run_id,
            entity_id=None,
            fact_type="character",
            subject_entity_id=None,
            direct_producer_execution_id=self.execution_id,
            source_operation_key=f"op-{uuid.uuid4().hex[:8]}",
            created_at=naive_utcnow(),
        )
        self.session.add(fact)
        self.session.flush()
        return int(fact.graph_fact_id)


def _fixture(session: Session, title: str, chapters: int = 1) -> _Fixture:
    fixture = _Fixture(session, title=title, chapters=chapters)
    session.commit()
    return fixture


def test_create_all_smoke(db_session: Session) -> None:
    """全部组织关系存在于 metadata 且可由会话级 create_all 建表查询"""
    for table_name in NEW_TABLES:
        assert table_name in Base.metadata.tables, f"metadata 缺少 {table_name}"
    fixture = _fixture(db_session, "建表冒烟")
    # 共享架构下不能断言整库为空：按本夹具生产者归属核对新表尚无数据
    for model in (
        CompleteEvent,
        NarrativeLink,
        OrganizationCheck,
        ConflictRecord,
        NarrativeGroup,
        EventForeshadowingAction,
    ):
        count = db_session.execute(
            select(func.count()).select_from(model).where(model.producer_execution_id == fixture.execution_id)
        ).scalar_one()
        assert count == 0
    # 版本表经事件归属核对；证据表无运行归属，按本夹具声明归属查询
    revisions = db_session.execute(
        select(func.count())
        .select_from(EventRevision)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(CompleteEvent.producer_execution_id == fixture.execution_id)
    ).scalar_one()
    assert revisions == 0
    evidence = db_session.execute(
        select(func.count()).select_from(SourceEvidence).where(SourceEvidence.declaration_id.in_(fixture.declarations))
    ).scalar_one()
    assert evidence == 0
    assert fixture.run_id


def test_containment_single_parent_violates_unique_child(db_session: Session) -> None:
    """同 child 不同 parent 第二次插入违反 (contained_child_id) 唯一（单父保留）"""
    fixture = _fixture(db_session, "单父约束")
    parent_a = fixture.make_event(local_key="parent-a")
    parent_b = fixture.make_event(local_key="parent-b")
    child = fixture.make_event(local_key="child")
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="首次归属",
            contained_child_id=child,
            contained_parent_id=parent_a,
        )
    )
    db_session.commit()
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="重复归属",
            contained_child_id=child,
            contained_parent_id=parent_b,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_containment_self_reference_violates_ck(db_session: Session) -> None:
    """contained_child_id = contained_parent_id 违反不自含 CheckConstraint"""
    fixture = _fixture(db_session, "自含约束")
    event_id = fixture.make_event()
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="自含",
            contained_child_id=event_id,
            contained_parent_id=event_id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_containment_cycle_is_rejected_by_trigger(db_session: Session) -> None:
    """包含关系成环由领域触发器拒绝"""
    fixture = _fixture(db_session, "包含成环")
    first, second = fixture.make_event(local_key="a"), fixture.make_event(local_key="b")
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="首次归属",
            contained_child_id=second,
            contained_parent_id=first,
        )
    )
    db_session.commit()
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="反向归属成环",
            contained_child_id=first,
            contained_parent_id=second,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_declaration_binding_unique_source_and_stage(db_session: Session) -> None:
    """一项声明只能绑定一个版本，一个事件的一个阶段序号只有一行"""
    fixture = _fixture(db_session, "声明绑定唯一")
    declaration_a = fixture.make_declaration(chapter_id=1)
    declaration_b = fixture.make_declaration(chapter_id=1, phrase="山门")
    event_a = fixture.make_event(local_key="a")
    event_b = fixture.make_event(local_key="b")
    fixture.make_revision(event_a, stage_index=0, declaration_id=declaration_a)
    db_session.commit()
    # 同声明换事件：绑定声明唯一索引冲突
    with pytest.raises(IntegrityError):
        fixture.make_revision(event_b, stage_index=0, declaration_id=declaration_a)
    db_session.rollback()
    # 同事件同阶段序号：候选键冲突
    with pytest.raises(IntegrityError):
        fixture.make_revision(event_a, stage_index=0, declaration_id=declaration_b)
    db_session.rollback()


def test_revision_source_shape_is_exclusive(db_session: Session) -> None:
    """阶段正文来源恰一：绑定声明与独立 origin 正文不能同时存在"""
    fixture = _fixture(db_session, "阶段来源互斥")
    declaration = fixture.make_declaration(chapter_id=1)
    event_id = fixture.make_event()
    db_session.add(
        EventRevision(
            revision_id=str(uuid.uuid4()),
            event_id=event_id,
            stage_index=0,
            declaration_id=declaration,
            origin_title="冲突来源",
            origin_problem="冲突来源",
            origin_summary="冲突来源",
            origin_event_type="行动",
            origin_status="ongoing",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_revision_stage_chain_starts_at_zero_and_is_continuous(db_session: Session) -> None:
    """阶段序号必须从 0 连续（领域触发器在提交时校验）"""
    fixture = _fixture(db_session, "阶段链连续")
    event_id = fixture.make_event()
    fixture.make_revision(event_id, stage_index=1)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    event_id = fixture.make_event(local_key="second")
    fixture.make_revision(event_id, stage_index=0)
    fixture.make_revision(event_id, stage_index=2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_semantic_relation_requires_exclusive_endpoint_kinds(db_session: Session) -> None:
    """语义/因果形状必须两端各恰一，且不能混入包含列"""
    fixture = _fixture(db_session, "关系端点形状")
    source = fixture.make_event(local_key="source")
    target = fixture.make_event(local_key="target")
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="缺目标端点",
            semantic_source_event_id=source,
            relation_type="causal",
            source_operation_local_key="op-1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="混入包含列",
            semantic_source_event_id=source,
            semantic_target_event_id=target,
            relation_type="causal",
            source_operation_local_key="op-2",
            contained_parent_id=source,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_semantic_relation_operation_is_idempotent(db_session: Session) -> None:
    """同执行同操作只能产生一条语义关系"""
    fixture = _fixture(db_session, "关系操作幂等")
    source = fixture.make_event(local_key="source")
    target = fixture.make_event(local_key="target")
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="显式判断",
            semantic_source_event_id=source,
            semantic_target_event_id=target,
            relation_type="causal",
            source_operation_local_key="op-1",
        )
    )
    db_session.commit()
    db_session.add(
        NarrativeLink(
            link_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="重复操作",
            semantic_source_event_id=source,
            semantic_target_event_id=target,
            relation_type="causal",
            source_operation_local_key="op-1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_organization_check_pair_unique_and_direction(db_session: Session) -> None:
    """结构对同一对只接受一个判断，且不得反向重复登记"""
    fixture = _fixture(db_session, "结构核对唯一")
    source = fixture.make_event(local_key="source")
    target = fixture.make_event(local_key="target")
    db_session.add(
        OrganizationCheck(
            check_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="无包含或因果关系",
            source_event_id=source,
            target_event_id=target,
            disposition="independent",
            snapshot_hash="hash",
        )
    )
    db_session.commit()
    db_session.add(
        OrganizationCheck(
            check_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="重复判断",
            source_event_id=source,
            target_event_id=target,
            disposition="contains",
            snapshot_hash="hash2",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    db_session.add(
        OrganizationCheck(
            check_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="反向重复",
            source_event_id=target,
            target_event_id=source,
            disposition="part_of",
            snapshot_hash="hash3",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_organization_check_declaration_pair_unique(db_session: Session) -> None:
    """声明对比逐对只接受一个判断"""
    fixture = _fixture(db_session, "声明对比唯一")
    source = fixture.make_declaration(chapter_id=1)
    target = fixture.make_declaration(chapter_id=1, phrase="山门")
    db_session.add(
        OrganizationCheck(
            check_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="两项声明是独立问题",
            source_declaration_id=source,
            target_declaration_id=target,
            disposition="independent",
        )
    )
    db_session.commit()
    db_session.add(
        OrganizationCheck(
            check_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            reason="重复判断",
            source_declaration_id=source,
            target_declaration_id=target,
            disposition="same_event",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_conflict_requires_two_claims_and_single_subject(db_session: Session) -> None:
    """冲突至少两条独立陈述（延迟触发器），主体三类恰一"""
    fixture = _fixture(db_session, "冲突主体")
    event_id = fixture.make_event()
    conflict_id = str(uuid.uuid4())
    db_session.add(
        ConflictRecord(
            conflict_id=conflict_id,
            producer_execution_id=fixture.execution_id,
            reason="原文两种说法",
            subject_event_id=event_id,
        )
    )
    db_session.flush()
    db_session.add(
        ConflictClaim(
            claim_id=str(uuid.uuid4()),
            conflict_id=conflict_id,
            claim_ordinal=0,
            producer_execution_id=fixture.execution_id,
            claim_text="等待十年",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    second = str(uuid.uuid4())
    declaration = fixture.make_declaration(chapter_id=1)
    db_session.add(
        ConflictRecord(
            conflict_id=second,
            producer_execution_id=fixture.execution_id,
            reason="主体同时给两类",
            subject_event_id=event_id,
            subject_declaration_id=declaration,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_conflict_claims_keep_independent_ordinals(db_session: Session) -> None:
    """各条陈述的序号唯一且各自保留自己的生产者"""
    fixture = _fixture(db_session, "冲突陈述")
    event_id = fixture.make_event()
    conflict_id = str(uuid.uuid4())
    declaration = fixture.make_declaration(chapter_id=1)
    db_session.add(
        ConflictRecord(
            conflict_id=conflict_id,
            producer_execution_id=fixture.execution_id,
            reason="同一次等待时长的两项说法不一致",
            subject_event_id=event_id,
        )
    )
    db_session.flush()
    for ordinal, text in enumerate(("等待十年", "等待十四年")):
        db_session.add(
            ConflictClaim(
                claim_id=str(uuid.uuid4()),
                conflict_id=conflict_id,
                claim_ordinal=ordinal,
                producer_execution_id=fixture.execution_id,
                claim_text=text,
            )
        )
    db_session.commit()
    rows = list(
        db_session.scalars(
            select(ConflictClaim).where(ConflictClaim.conflict_id == conflict_id).order_by(ConflictClaim.claim_ordinal)
        )
    )
    assert [row.claim_text for row in rows] == ["等待十年", "等待十四年"]
    db_session.add(
        ConflictClaim(
            claim_id=str(uuid.uuid4()),
            conflict_id=conflict_id,
            claim_ordinal=0,
            producer_execution_id=fixture.execution_id,
            claim_text="重复序号",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    assert declaration


def test_foreshadowing_action_operation_and_type_constraints(db_session: Session) -> None:
    """伏笔动作以执行+操作幂等，动作类型受封闭词表约束"""
    fixture = _fixture(db_session, "伏笔动作")
    declaration = fixture.make_declaration(chapter_id=1, payoff="high")
    db_session.add(
        EventForeshadowingAction(
            action_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            source_operation_local_key="setup-1",
            operation_order=1,
            action_type="setup",
            source_declaration_id=declaration,
        )
    )
    db_session.commit()
    db_session.add(
        EventForeshadowingAction(
            action_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            source_operation_local_key="setup-1",
            operation_order=2,
            action_type="reinforce",
            source_declaration_id=declaration,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    db_session.add(
        EventForeshadowingAction(
            action_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            source_operation_local_key="setup-2",
            operation_order=2,
            action_type="invalid",
            source_declaration_id=declaration,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_evidence_char_order_and_single_owner(db_session: Session) -> None:
    """证据区间必须非空，且九个所有者恰一"""
    fixture = _fixture(db_session, "证据所有者")
    event_id = fixture.make_event()
    declaration = fixture.make_declaration(chapter_id=1)
    db_session.add(
        SourceEvidence(
            evidence_id=str(uuid.uuid4()),
            ordinal=0,
            paragraph_id=0,
            start_char=3,
            end_char=3,
            complete_event_id=event_id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    db_session.add(
        SourceEvidence(
            evidence_id=str(uuid.uuid4()),
            ordinal=0,
            paragraph_id=0,
            start_char=0,
            end_char=2,
            complete_event_id=event_id,
            declaration_id=declaration,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_evidence_paragraph_must_belong_to_owner_run(db_session: Session) -> None:
    """证据段号必须属于所有者所在 run 的段落（领域触发器）"""
    fixture = _fixture(db_session, "证据段号归属")
    event_id = fixture.make_event()
    db_session.add(
        SourceEvidence(
            evidence_id=str(uuid.uuid4()),
            ordinal=0,
            paragraph_id=999,
            start_char=0,
            end_char=1,
            complete_event_id=event_id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_narrative_group_parent_must_be_line_and_acyclic(db_session: Session) -> None:
    """父线只能指向线形状节点，父链不得成环"""
    fixture = _fixture(db_session, "叙事线父链")
    outcome_id = str(uuid.uuid4())
    db_session.add(
        NarrativeGroup(
            group_id=outcome_id,
            producer_execution_id=fixture.execution_id,
            title="身份获确认",
            outcome_description="身份最终得到证实",
        )
    )
    db_session.flush()
    db_session.add(
        NarrativeGroup(
            group_id=str(uuid.uuid4()),
            producer_execution_id=fixture.execution_id,
            title="身份线",
            arc_kind="main",
            arc_objective="确认身份",
            arc_role="主线",
            arc_reason="围绕身份持续推进",
            parent_arc_id=outcome_id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_execution_shape_is_single_type(db_session: Session) -> None:
    """同一真实执行不能同时是整轮会话和 work 尝试"""
    fixture = _fixture(db_session, "执行形状")
    db_session.add(
        Execution(
            execution_id=uuid.uuid4().hex,
            session_run_id=fixture.run_id,
            session_created_at=naive_utcnow(),
            work_id=fixture.work_id,
            attempt_number=1,
            started_at=naive_utcnow(),
            status="success",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_work_item_shape_is_single_kind(db_session: Session) -> None:
    """work 的四种形状互斥，标注与程序身份不能混填"""
    fixture = _fixture(db_session, "工作形状")
    db_session.add(
        WorkItem(
            work_id=f"bad-work-{uuid.uuid4().hex[:8]}",
            role="event",
            annotation_run_id=fixture.run_id,
            annotation_chapter_id=1,
            program_code="chapter_check",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
