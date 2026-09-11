"""章内并行两段式：读者（只读顾问）工具面与运行器

设计文档《章内并行设计-子代理只读顾问与主代理单写者》§5/§6/§8.5：
- 读者只持有只读检索工具与 send_message，不持有任何写入/裁决工具；
- 消息是带逐字证据的结构化观察，服务端对引文做段内唯一命中校验，
  校验失败当场报错、消息不入池，读者在会话内改一版重发；
- 读者回复天然没有工具调用也不该有（上报完毕），完成判定走
  require_tool_call=False + 无工具回复即收束的读者图。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from .errors import AnnotationInputError, AnnotationInvariantError, AnnotationRetryableError
from .messages import (
    MESSAGE_KINDS,
    MessagePoolError,
    ReaderMessagePool,
)
from .prompts import READER_SYSTEM_PROMPT, build_reader_block_message
from .schema import (
    ChunkParagraphInfo,
    DialogueVerdict,
    EntityInput,
    NarrativeFunction,
    SentenceLabelInput,
    Tone,
    normalize_semantic_text,
    tone_catalog_text,
)
from .tools import (
    RELATION_DEFINITIONS,
    AnnotationQueryService,
    AnnotationToolLedger,
    build_search_tools,
)

if TYPE_CHECKING:
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.agents.stream import AgentStream

_CASE_SIGNALS = ("新疑点", "埋设", "加强", "坐实", "回收", "证伪")


@dataclass(slots=True)
class ReaderBlockContext:
    """单个子块读者的输入上下文（annotate 工作流构建一次，重试/续跑复用）"""

    # 0 基子块序号（消息池排序键）
    block_index: int
    block_count: int
    # 运行时子块负 ID（审计与候选提取身份）
    block_chunk_id: int
    block_text: str
    paragraph_info: ChunkParagraphInfo
    # 块内候选序号（1 基）→ 章级候选表序号（1 基；跨块引号无法对齐时为 None）
    candidate_number_map: dict[int, int | None]


def _require_int_in_range(
    value: Any,
    *,
    label: str,
    low: int,
    high: int,
) -> int:
    """2026-09-11 用于校验整数载荷（排除 bool）并返回原值"""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MessagePoolError(f"{label} 必须是 {low}..{high} 的整数")
    return value


def _validate_event_tree_payload(payload: dict[str, Any]) -> None:
    """2026-09-11 用于校验 event_tree 载荷结构（读者用名字，写者侧做实体编号解析）"""
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise MessagePoolError("event_tree.description 必须是非空字符串")
    participants = payload.get("participants")
    if not isinstance(participants, list) or not participants:
        raise MessagePoolError("event_tree.participants 必须是非空数组")
    _validate_event_participants(participants, label="event_tree.participants")
    children = payload.get("children") or []
    if not isinstance(children, list):
        raise MessagePoolError("event_tree.children 必须是数组")
    for child_index, child in enumerate(children):
        if not isinstance(child, dict):
            raise MessagePoolError(f"event_tree.children.{child_index} 必须是对象")
        child_participants = child.get("participants")
        if not isinstance(child_participants, list) or not child_participants:
            raise MessagePoolError(f"event_tree.children.{child_index}.participants 必须是非空数组")
        _validate_event_participants(
            child_participants,
            label=f"event_tree.children.{child_index}.participants",
        )


def _validate_event_participants(participants: list[Any], *, label: str) -> None:
    """2026-09-11 用于校验事件参与者结构：entity 用名字、character 带判断字段提案"""
    for index, participant in enumerate(participants):
        if not isinstance(participant, dict):
            raise MessagePoolError(f"{label}.{index} 必须是对象")
        entity = participant.get("entity")
        if not isinstance(entity, str) or not entity.strip():
            raise MessagePoolError(f"{label}.{index}.entity 必须是非空实体名（读者一律用名字，不用编号）")
        role = participant.get("role")
        if not isinstance(role, str) or not role.strip():
            raise MessagePoolError(f"{label}.{index}.role 必须是非空字符串")
        emotion = participant.get("emotion")
        if emotion is not None:
            _require_int_in_range(emotion, label=f"{label}.{index}.emotion", low=-2, high=2)


def _build_send_message_tool(
    ledger: AnnotationToolLedger,
    *,
    pool: ReaderMessagePool,
    block_index: int,
    candidate_number_map: dict[int, int | None],
):
    paragraph_info = ledger.paragraph_info
    if paragraph_info is None:
        raise AnnotationInvariantError("读者 send_message 证据校验需要段落坐标映射，paragraph_info 缺失")
    paragraph_text_by_id = dict(zip(paragraph_info.paragraph_ids, paragraph_info.texts, strict=True))

    def _validate_evidence(kind: str, evidence: Any) -> list[dict[str, Any]]:
        """§5.3：paragraph_id 属于本子块；quote 经 NFC 归一后在该段落内唯一命中（note 类可空）"""
        if evidence is None or evidence == []:
            if kind == "note":
                return []
            raise MessagePoolError(f"send_message.kind={kind} 必须提供至少一条 evidence 逐字引文")
        if not isinstance(evidence, list):
            raise MessagePoolError("evidence 必须是 [{paragraph_id, quote}] 数组")
        validated: list[dict[str, Any]] = []
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise MessagePoolError(f"evidence.{index} 必须是 {{paragraph_id, quote}} 对象")
            paragraph_id = item.get("paragraph_id")
            if isinstance(paragraph_id, bool) or not isinstance(paragraph_id, int):
                raise MessagePoolError(f"evidence.{index}.paragraph_id 必须是整数段落 id（见正文 <paragraph id=…>）")
            paragraph_text = paragraph_text_by_id.get(paragraph_id)
            if paragraph_text is None:
                raise MessagePoolError(
                    f"evidence.{index}.paragraph_id={paragraph_id} 不属于本子块"
                    "（只能引用 <CurrentSubBlock> 内列出的段落）"
                )
            quote = item.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                raise MessagePoolError(f"evidence.{index}.quote 必须是非空逐字摘录")
            normalized_text = unicodedata.normalize("NFC", paragraph_text)
            normalized_quote = unicodedata.normalize("NFC", quote)
            hits = normalized_text.count(normalized_quote)
            if hits == 0:
                raise MessagePoolError(
                    f"evidence.{index} 引文不在段落 {paragraph_id} 内（NFC 归一后未命中）："
                    "请从该段落原样摘录，不要改写"
                )
            if hits > 1:
                raise MessagePoolError(
                    f"evidence.{index} 引文在段落 {paragraph_id} 内命中 {hits} 处，不唯一：请加长摘录"
                )
            validated.append({"paragraph_id": paragraph_id, "quote": quote})
        return validated

    def _validate_payload(kind: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise MessagePoolError("payload 必须是对象")
        if kind == "metric":
            summary = payload.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise MessagePoolError("metric.summary 必须是非空字符串")
            _require_int_in_range(
                payload.get("emotional_valence"),
                label="metric.emotional_valence",
                low=-2,
                high=2,
            )
            narrative_function = payload.get("narrative_function")
            try:
                NarrativeFunction(str(narrative_function))
            except ValueError:
                raise MessagePoolError(
                    "metric.narrative_function 必须是闭合枚举: 冲突/铺垫/转折"
                ) from None
        elif kind == "entity":
            try:
                EntityInput.model_validate(payload)
            except Exception as exc:
                raise MessagePoolError(f"entity 载荷不符合实体合同: {exc}") from None
        elif kind == "event_tree":
            _validate_event_tree_payload(payload)
        elif kind == "dialogue":
            candidate_index = payload.get("candidate_index")
            candidate_count = len(ledger.dialogue_candidates)
            if (
                isinstance(candidate_index, bool)
                or not isinstance(candidate_index, int)
                or not 1 <= candidate_index <= candidate_count
            ):
                raise MessagePoolError(
                    f"dialogue.candidate_index 超出本块候选范围: expected 1..{candidate_count}"
                )
            verdict = payload.get("verdict")
            try:
                DialogueVerdict(str(verdict))
            except ValueError:
                raise MessagePoolError(
                    "dialogue.verdict 必须是 dialogue/inner_monologue/not_dialogue 三态之一"
                ) from None
            tone = payload.get("tone")
            if tone is not None:
                normalized_tone = normalize_semantic_text(str(tone), label="dialogue.tone")
                if normalized_tone not in Tone:
                    raise MessagePoolError(
                        f"dialogue.tone 必须是闭合语气枚举: {normalized_tone}，合法值: {tone_catalog_text()}"
                    )
        elif kind == "sentence_label":
            try:
                SentenceLabelInput.model_validate(payload)
            except Exception as exc:
                raise MessagePoolError(
                    "sentence_label 载荷不符合句标签合同（{sentence, emotion}，emotion 为 -2..2 整数）: "
                    f"{exc}"
                ) from None
        elif kind == "relation":
            from_entity = payload.get("from_entity")
            to_entity = payload.get("to_entity")
            if not isinstance(from_entity, str) or not from_entity.strip():
                raise MessagePoolError("relation.from_entity 必须是非空实体名（读者一律用名字）")
            if not isinstance(to_entity, str) or not to_entity.strip():
                raise MessagePoolError("relation.to_entity 必须是非空实体名（读者一律用名字）")
            if str(payload.get("relation_type")) not in RELATION_DEFINITIONS:
                raise MessagePoolError("relation.relation_type 必须是闭合关系类型注册表中的值")
        elif kind == "case":
            signal = payload.get("signal")
            if signal not in _CASE_SIGNALS:
                raise MessagePoolError(
                    "case.signal 必须是 新疑点/埋设/加强/坐实/回收/证伪 之一"
                )
            observation = payload.get("observation")
            if not isinstance(observation, str) or not observation.strip():
                raise MessagePoolError("case.observation 必须是非空字符串（文本侧事实陈述）")
        elif kind == "note":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise MessagePoolError("note.text 必须是非空字符串")
        else:
            raise MessagePoolError(f"未知消息 kind: {kind}")
        return payload

    @tool
    def send_message(
        kind: str,
        summary: str,
        payload: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
    ) -> str:
        """2026-09-11 章内并行（§5）用于把本块带逐字证据的观察上报给写者（唯一回传通道）

        - kind: metric/entity/event_tree/dialogue/sentence_label/relation/case/note；
        - summary: 一句话陈述；payload 按 kind 的载荷形状；
        - evidence: [{paragraph_id, quote}]，quote 必须是所指段落内的逐字摘录
          （NFC 归一后必须唯一命中），note 类可省略；
        - 没有引文支撑的观察不得上报；一律用名字，绝不把案例编号/实体编号写进消息；
        - 案例只陈述文本侧事实（新疑点/埋设/加强/坐实/回收/证伪）不裁决；
        - 句标签不限条数，本块值得打标的句子全部上报，选哪几句由写者决定；
        - 校验失败该次上报不入池，按报错改一版重发即可。
        """
        if ledger.phase != "chunk_open":
            raise MessagePoolError(f"阶段 {ledger.phase} 不允许 send_message")
        if kind not in MESSAGE_KINDS:
            raise MessagePoolError(f"未知消息 kind: {kind}，合法值: {'、'.join(MESSAGE_KINDS)}")
        if not isinstance(summary, str) or not summary.strip():
            raise MessagePoolError("summary 必须是非空字符串")
        validated_payload = _validate_payload(kind, payload)
        validated_evidence = _validate_evidence(kind, evidence or [])
        chapter_candidate_index: int | None = None
        if kind == "dialogue":
            chapter_candidate_index = candidate_number_map.get(int(validated_payload["candidate_index"]))
        message = pool.append(
            block_index=block_index,
            kind=kind,
            summary=summary.strip(),
            payload=validated_payload,
            evidence=validated_evidence,
            chapter_candidate_index=chapter_candidate_index,
        )
        return json.dumps({"accepted": True, "message_id": message.message_id}, ensure_ascii=False)

    return send_message


def build_reader_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
    *,
    pool: ReaderMessagePool,
    block_index: int,
    candidate_number_map: dict[int, int | None],
) -> list[Any]:
    """2026-09-11 章内并行（§4 权限矩阵）用于构建读者工具面：只读检索 + send_message"""
    tools = build_search_tools(query_service, ledger)
    tools.append(
        _build_send_message_tool(
            ledger,
            pool=pool,
            block_index=block_index,
            candidate_number_map=candidate_number_map,
        )
    )
    return tools


@dataclass(slots=True)
class ReaderRunOutcome:
    """2026-09-11 用于承载一次读者会话的产出（续跑上下文 + 授权足迹并入写者审计）"""

    # 读者会话完整消息链（追问续跑时作为前缀拼接）
    final_messages: list[BaseMessage]
    authorized_text_paragraph_ids: set[int]
    authorized_chapter_ids: set[int]


async def run_reader_agent(
    *,
    run_id: str,
    chapter_id: int,
    context: ReaderBlockContext,
    pool: ReaderMessagePool,
    query_service_factory: Any,
    session_factory: Any,
    llm: Any,
    graph_state: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: AgentAuditRecorder | None = None,
    chapter_label: str | None = None,
    novel_id: str = "default",
    prior_messages: list[BaseMessage] | None = None,
    writer_question: str | None = None,
    attempt_number: int = 1,
) -> ReaderRunOutcome:
    """2026-09-11 章内并行（§6/§8.5）用于运行单个子块读者会话（Phase A 或写者追问续跑）

    读者失败直接上抛由工作流按全有或全无处理；追问续跑（writer_question 非空）
    复用 Phase A 的完整消息链，读者带着原文上下文补查并经 send_message 入池。
    读者绝不触碰 FactGraph 的章节生命周期（begin/reset/drain 全归写者调用链）。
    """
    from src.agents.annotation.graph import build_reader_graph
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.config import settings

    recorder = audit_recorder or AgentAuditRecorder(session_factory)
    model_name = str(getattr(llm, "model_name", None) or getattr(llm, "model", "") or None) or None
    raw_base_url = str(getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or "")
    is_local = not raw_base_url or "localhost" in raw_base_url or "127.0.0.1" in raw_base_url
    model_provider = "local" if is_local else "cloud"
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation_reader",
        chapter_id=chapter_id,
        attempt_number=attempt_number,
        model_name=model_name,
        model_provider=model_provider,
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation_reader",
        call_type="agent",
        model_name=model_name or "unknown",
        model_provider=model_provider,
    )
    read_session = session_factory()
    try:
        from sqlalchemy import text as sql_text

        bind = read_session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            read_session.execute(sql_text("SET TRANSACTION READ ONLY"))
        query_service = query_service_factory(read_session)
        allow_future_context = settings.models.annotation.allow_future_context
        ledger = AnnotationToolLedger(
            run_scope=run_id,
            current_chapter_id=chapter_id,
            current_chunk_id=context.block_chunk_id,
            current_chunk_text=context.block_text,
            allow_future_context=allow_future_context,
            graph=graph_state,
            paragraph_info=context.paragraph_info,
            current_chapter_order=getattr(query_service, "current_chapter_order", None),
        )
        tools = build_reader_tools(
            query_service,
            ledger,
            pool=pool,
            block_index=context.block_index,
            candidate_number_map=context.candidate_number_map,
        )
        graph = build_reader_graph(
            llm,
            tools,
            ledger=ledger,
            max_iterations=max(1, settings.models.annotation.max_iterations),
            stream=stream,
            observer=observer,
            retries=settings.models.annotation.total_attempts,
        )
        if prior_messages is None:
            first_messages: list[BaseMessage] = [
                SystemMessage(content=READER_SYSTEM_PROMPT),
                HumanMessage(
                    content=build_reader_block_message(
                        block_number=context.block_index + 1,
                        block_total=context.block_count,
                        paragraph_info=context.paragraph_info,
                        candidates=ledger.dialogue_candidates,
                    )
                ),
            ]
        else:
            if writer_question is None:
                raise AnnotationInputError("追问续跑必须提供 writer_question")
            first_messages = [
                *prior_messages,
                HumanMessage(
                    content=(
                        f'<WriterQuestion block="{context.block_index + 1}">\n'
                        f"{writer_question}\n"
                        "</WriterQuestion>\n\n"
                        "请针对该问题补查并经 send_message 上报新的观察；"
                        "没有新发现就简短说明后直接结束。"
                    )
                ),
            ]
        result_state = await graph.ainvoke(
            {
                "messages": first_messages,
                "phase": "chunk_open",
                "iterations": 0,
                "error": None,
            }
        )
    except Exception as exc:
        try:
            read_session.rollback()
        finally:
            read_session.close()
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        if isinstance(exc, AnnotationRetryableError):
            raise
        raise AnnotationRetryableError(f"读者会话失败（块 {context.block_index + 1}）: {exc}") from exc
    try:
        read_session.rollback()
    finally:
        read_session.close()
    error = result_state.get("error")
    if error:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(error))
        raise AnnotationRetryableError(f"读者会话失败（块 {context.block_index + 1}）: {error}")
    recorder.finish_invocation(invocation_id, status="success")
    return ReaderRunOutcome(
        final_messages=list(result_state["messages"]),
        authorized_text_paragraph_ids=set(ledger.authorized_text_paragraph_ids),
        authorized_chapter_ids=set(ledger.authorized_chapter_ids),
    )


__all__ = [
    "ReaderBlockContext",
    "ReaderRunOutcome",
    "build_reader_tools",
    "run_reader_agent",
]
