"""
诊断 Agent 运行入口（LangGraph 工具化自主取证）

审计: 每次诊断运行开启 agent_invocations 行，模型回合与工具调用通过
AgentTurnObserver 写入独立短事务；失败路径同样保留完整审计记录。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.agents.stream import AgentStream
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import EventOrganizationDraft, NarrativeOrganization

from .evidence import DiagnosisEvidenceLedger


class DiagnosisAgentRunError(RuntimeError):
    """诊断 agent 运行失败"""


def _model_name(llm: Any) -> str | None:
    """用于从模型对象稳定读取审计用模型名"""
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "") or None) or None


def _validate_topic_label_ids(
    analysis: AgentAnalysis,
    *,
    expected_ids: set[int],
) -> None:
    """核对标签键与本轮模型实际 topic_id 完全一致"""
    actual_ids = {int(topic_id) for topic_id in analysis.topic_labels}
    if actual_ids != expected_ids:
        raise ValueError(
            "topic_labels IDs must match available topic data: "
            f"expected {sorted(expected_ids)}, got {sorted(actual_ids)}"
        )


def _finalize_diagnosis_result(
    analysis: AgentAnalysis,
    *,
    novel_id: str,
    foreshadow_expectation: float | None,
    organization: NarrativeOrganization | None = None,
) -> AgentAnalysis:
    """用于以运行元数据和伏笔 ledger 确定性收口诊断终态"""
    payload = analysis.model_dump()
    payload["novel_id"] = novel_id
    payload["foreshadow_expectation"] = foreshadow_expectation
    payload["narrative_organization"] = organization
    return AgentAnalysis.model_validate(payload)


def _validate_diagnosis_submission(
    analysis: AgentAnalysis,
    *,
    expected_topic_ids: set[int],
    evidence_ledger: DiagnosisEvidenceLedger,
    organization_draft: EventOrganizationDraft | None = None,
) -> None:
    """用于同时校验诊断结果主题合同与工具取证来源"""
    _validate_topic_label_ids(analysis, expected_ids=expected_topic_ids)
    evidence_ledger.require_evidence()
    if organization_draft is not None:
        organization_draft.finish()


async def _run_diagnosis_agent(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    execution_id: str,
    novel_title: str | None = None,
    llm: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: Any | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    domain: Any = None,
    bus: Any = None,
) -> AgentAnalysis:
    """诊断只运行独立会话：案例会话自取办理，报告会话收尾，依赖与最终保存由领域完成"""
    from src.agents.turn_observer import AgentTurnObserver, build_invocation_context
    from src.audit.module import AuditMessages
    from src.config import settings
    from src.event_bus import EventBus, Message
    from src.model_pool.configuration import load_task_config
    from src.model_pool.llm import build_chat_model

    from .work_runtime import DiagnosisWorkScheduler

    active_bus = bus or EventBus()
    domain_session: Session | None = None
    if domain is None:
        from .domain import create_diagnosis_domain

        domain_session = open_diagnosis_session(session)
        try:
            domain = create_diagnosis_domain(
                session=domain_session,
                run_id=run_id,
                novel_id=novel_id,
                execution_id=execution_id,
                novel_title=novel_title,
            )
        except BaseException:
            # 构造中途失败也要交还连接：会话挂在 idle in transaction 会拖住后续建表与清库
            domain_session.close()
            domain_session = None
            raise
    model_id = settings.models.diagnosis_model_id
    if not model_id:
        raise DiagnosisAgentRunError("请从模型池指定诊断模型")

    def observer_factory(progress: Any) -> Any:
        recorder = audit_recorder or AuditMessages(
            active_bus, run_id, progress.key, progress.execution_id, progress.role
        )
        if hasattr(recorder, "sequence"):
            recorder.sequence = progress.audit_sequence
        # 审计登记真实 invocation 要求会话身份已存在：派发时先登记整轮会话
        domain.register_session_identity()
        context = build_invocation_context(
            run_id=run_id,
            task_type="diagnosis",
            execution_id=progress.execution_id,
            attempt_number=1,
            model=model_id,
            case_anchor=None,
            role=progress.role,
        )
        local_id = recorder.start_invocation(**context)
        observer = AgentTurnObserver(recorder, invocation_id=local_id, context=context)
        observer._turn_counter = progress.physical_sequence
        return observer

    async def barrier() -> None:
        if audit_recorder is None:
            await active_bus.request(
                Message(topic="audit.barrier", source="diagnosis", target=f"audit:{run_id}", run_id=run_id)
            )

    scheduler = DiagnosisWorkScheduler(
        run_id=run_id,
        domain=domain,
        bus=active_bus,
        model_id=model_id,
        llm_factory=lambda selected: (
            llm
            if llm is not None
            else build_chat_model("diagnosis", config=load_task_config("diagnosis", model_id=selected))
        ),
        observer_factory=observer_factory,
        audit_barrier=barrier,
        is_cancelled=is_cancelled,
        stream=stream,
        model_retries=max(1, settings.models.diagnosis.total_attempts),
    )
    from src.utils.cancellation import run_cancellable

    try:
        return await run_cancellable(scheduler.run(), is_cancelled)
    except BaseException as error:
        retain = getattr(domain, "retain_pending_cases", None)
        if callable(retain):
            try:
                retain(error)
            except BaseException as retention_error:
                from loguru import logger

                logger.exception("诊断失败后的案例登记保存失败，原始错误: {}", error)
                raise BaseExceptionGroup("诊断失败且待处理案例未成功保存", [error, retention_error]) from error
        raise
    finally:
        close = getattr(domain, "close", None)
        if callable(close):
            close()
        if domain_session is not None:
            domain_session.close()


def open_diagnosis_session(session: Session) -> Session:
    """落前序阶段在管线会话上的未提交写入，再开独立诊断会话

    诊断阶段若共用管线会话，管线会话会被流式 emitter 持续 commit；一次提交中途被打断
    就把会话留在 PREPARED 中间态，此后诊断的任意一次读取都抛 "session is in 'prepared'
    state" 并伪装成工具依赖故障。开工先 commit 管线会话（前序阶段写入对独立会话可见，
    per-work 读会话同权），之后整轮诊断只用独立会话读写与保存，不受管线会话事务状态影响。
    """
    session.commit()
    bind = session.get_bind()
    return Session(bind=getattr(bind, "engine", bind))


async def run_diagnosis_agent(
    *,
    session: Session,
    run_id: str,
    novel_id: str,
    novel_title: str | None = None,
    llm: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: Any | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> AgentAnalysis:
    """正式入口只派发诊断work；旧契约由领域入口拒绝，不回退单会话生产"""
    from src.audit.module import AuditModule
    from src.event_bus import EventBus
    from src.storage.db import get_session_factory
    from src.utils.identity import stable_digest

    bus = EventBus()
    audit = AuditModule(bus, run_id, get_session_factory()) if audit_recorder is None else None
    try:
        return await _run_diagnosis_agent(
            session=session,
            run_id=run_id,
            novel_id=novel_id,
            execution_id=stable_digest("diagnosis_declarations", run_id),
            novel_title=novel_title,
            llm=llm,
            stream=stream,
            audit_recorder=audit_recorder,
            is_cancelled=is_cancelled,
            bus=bus,
        )
    finally:
        if audit is not None:
            await audit.close()
