"""章内并行两段式：读者（只读顾问）工具面与运行器

设计文档《章内并行设计-子代理只读顾问与主代理单写者》§5/§6/§8.5，
2026-09-12 用户裁决修订上报合同：
- 读者只持有只读检索工具与 send_message，不持有任何写入/裁决工具；
- send_message 每轮激活只允许调用一次，载荷按观察类分组复合上报；
- 格式/枚举/引文核验失败不打回：观察照常送达写者，问题随回执 warnings
  呈现（写者是 LLM，读得懂带杂质的观察；唯一硬门槛保留在写者取证准入）；
- 读者回复没有工具调用即收束（require_tool_call=False 的读者图）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from .errors import AnnotationInputError, AnnotationInvariantError, AnnotationRetryableError
from .prompts import READER_SYSTEM_PROMPT, build_reader_block_message
from .reader_report import (
    REPORT_LIST_GROUPS,
    ReaderReport,
    decorate_evidence,
)
from .schema import (
    ChunkParagraphInfo,
    DialogueVerdict,
    EntityInput,
    NarrativeFunction,
    ParagraphLabelInput,
    require_tone,
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

    # 0 基子块序号（报告按块序渲染）
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
) -> None:
    """2026-09-11 用于校验整数载荷（排除 bool），不合规抛错由 send_message 降级为警告"""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} 必须是 {low}..{high} 的整数")


def _validate_event_tree_payload(payload: dict[str, Any]) -> None:
    """2026-09-11 用于校验 event_tree 载荷结构（读者用名字，写者侧做实体编号解析）"""
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("event_tree.description 必须是非空字符串")
    participants = payload.get("participants")
    if not isinstance(participants, list) or not participants:
        raise ValueError("event_tree.participants 必须是非空数组")
    _validate_event_participants(participants, label="event_tree.participants")
    children = payload.get("children") or []
    if not isinstance(children, list):
        raise ValueError("event_tree.children 必须是数组")
    for child_index, child in enumerate(children):
        if not isinstance(child, dict):
            raise ValueError(f"event_tree.children.{child_index} 必须是对象")
        child_participants = child.get("participants")
        if not isinstance(child_participants, list) or not child_participants:
            raise ValueError(f"event_tree.children.{child_index}.participants 必须是非空数组")
        _validate_event_participants(
            child_participants,
            label=f"event_tree.children.{child_index}.participants",
        )


def _validate_event_participants(participants: list[Any], *, label: str) -> None:
    """2026-09-11 用于校验事件参与者结构：entity 用名字、emotion 为 -2..2 整数"""
    for index, participant in enumerate(participants):
        if not isinstance(participant, dict):
            raise ValueError(f"{label}.{index} 必须是对象")
        entity = participant.get("entity")
        if not isinstance(entity, str) or not entity.strip():
            raise ValueError(f"{label}.{index}.entity 必须是非空实体名（读者一律用名字，不用编号）")
        role = participant.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"{label}.{index}.role 必须是非空字符串")
        emotion = participant.get("emotion")
        if emotion is not None:
            _require_int_in_range(emotion, label=f"{label}.{index}.emotion", low=-2, high=2)


def _check_payload(group: str, item: dict[str, Any], *, ledger: AnnotationToolLedger) -> None:
    """2026-09-12 用于按观察组执行合同检查（只产出报错文本，检查失败降级为警告）"""
    if group == "metric":
        summary = item.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("metric.summary 必须是非空字符串")
        _require_int_in_range(item.get("emotional_valence"), label="metric.emotional_valence", low=-2, high=2)
        try:
            NarrativeFunction(str(item.get("narrative_function")))
        except ValueError:
            raise ValueError("metric.narrative_function 必须是闭合枚举: 冲突/铺垫/转折") from None
    elif group == "entities":
        try:
            EntityInput.model_validate(item)
        except Exception as exc:
            raise ValueError(f"实体载荷不符合实体合同（{{name, entity_type, tags?, attributes?}}）: {exc}") from None
    elif group == "event_trees":
        _validate_event_tree_payload(item)
    elif group == "dialogues":
        candidate_index = item.get("candidate_index")
        candidate_count = len(ledger.dialogue_candidates)
        if (
            isinstance(candidate_index, bool)
            or not isinstance(candidate_index, int)
            or not 1 <= candidate_index <= candidate_count
        ):
            raise ValueError(
                f"dialogues.candidate_index 超出本块候选范围: expected 1..{candidate_count}"
                "（candidate_index 取本块 <DialogueCandidates> 表里展示的编号）"
            )
        try:
            DialogueVerdict(str(item.get("verdict")))
        except ValueError:
            raise ValueError("dialogues.verdict 必须是 dialogue/inner_monologue/not_dialogue 三态之一") from None
        tone = item.get("tone")
        if tone is not None:
            # 2026-09-14 写者侧 tone 已是真 enum 参数（schema 层拒绝），读者上报仍是
            # 自由文本，这里的校验只产出警告（问题随回执 warnings 呈现、观察照常送达）
            try:
                require_tone(tone)
            except ValueError as exc:
                raise ValueError(f"dialogues.tone 不符合合同: {exc}") from None
    elif group == "paragraph_labels":
        try:
            ParagraphLabelInput.model_validate(item)
        except Exception as exc:
            raise ValueError(
                "paragraph_labels 载荷不符合段落标签合同（{paragraph_id, emotion}，emotion 为 -2..2 整数）: "
                f"{exc}"
            ) from None
    elif group == "relations":
        for endpoint in ("from_entity", "to_entity"):
            value = item.get(endpoint)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"relations.{endpoint} 必须是非空实体名（读者一律用名字）")
        if str(item.get("relation_type")) not in RELATION_DEFINITIONS:
            raise ValueError("relations.relation_type 必须是闭合关系类型注册表中的值")
    elif group == "cases":
        if item.get("signal") not in _CASE_SIGNALS:
            raise ValueError("cases.signal 必须是 新疑点/埋设/加强/坐实/回收/证伪 之一")
        observation = item.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            raise ValueError("cases.observation 必须是非空字符串（文本侧事实陈述）")
    elif group == "notes":
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("notes.text 必须是非空字符串")


# 缺 evidence 仅告警的观察组（notes 可无引文；其余缺引文不能用于案例取证）
_EVIDENCE_OPTIONAL_GROUPS = frozenset({"notes"})


def _build_send_message_tool(
    ledger: AnnotationToolLedger,
    *,
    delivered: list[ReaderReport],
    block_index: int,
    candidate_number_map: dict[int, int | None],
):
    paragraph_info = ledger.paragraph_info
    if paragraph_info is None:
        raise AnnotationInvariantError("读者 send_message 证据核验需要段落坐标映射，paragraph_info 缺失")
    paragraph_text_by_id = dict(zip(paragraph_info.paragraph_ids, paragraph_info.texts, strict=True))

    @tool
    def send_message(
        entities: list[dict[str, Any]] | None = None,
        relations: list[dict[str, Any]] | None = None,
        paragraph_labels: list[dict[str, Any]] | None = None,
        dialogues: list[dict[str, Any]] | None = None,
        cases: list[dict[str, Any]] | None = None,
        event_trees: list[dict[str, Any]] | None = None,
        notes: list[dict[str, Any]] | None = None,
        metric: dict[str, Any] | None = None,
    ) -> str:
        """2026-09-12 章内并行用于把本块全部观察一次性上报给写者（整个会话只允许调用一次）

        - 载荷按观察类分组：entities/relations/paragraph_labels/dialogues/cases/
          event_trees/notes 为数组，metric 为单对象；没有观察的组省略即可；
        - 每条观察必须自带 evidence=[{paragraph_id, quote}]（本块段落内的逐字
          摘录，NFC 归一后必须唯一命中），notes 可省略；
        - 一律用名字，绝不把案例编号/实体编号写进上报；
        - dialogues 的 candidate_index 必须取本块 <DialogueCandidates> 表里展示的
          编号（块内 1 基，不是全章序号）；
        - 案例只陈述文本侧事实（signal: 新疑点/埋设/加强/坐实/回收/证伪）不裁决；
        - 段落标签不限条数，本块值得打标的段落全部上报（paragraph_id 取正文 ¶ 标记），
          最终提交哪几段由写者决定；
        - 格式或枚举不符也照常送达（回执 warnings 指出问题），不需要重发。
        """
        if ledger.phase != "chunk_open":
            raise AnnotationInputError(f"阶段 {ledger.phase} 不允许 send_message")
        if delivered:
            raise AnnotationInputError(
                "send_message 每轮激活只允许调用一次：本报告已送达写者，请直接结束会话"
            )
        report: dict[str, Any] = {}
        warnings: list[str] = []
        provided_groups: dict[str, Any] = {
            "entities": entities,
            "relations": relations,
            "paragraph_labels": paragraph_labels,
            "dialogues": dialogues,
            "cases": cases,
            "event_trees": event_trees,
            "notes": notes,
        }
        for group in REPORT_LIST_GROUPS:
            provided = provided_groups[group]
            if provided is None:
                continue
            items = provided if isinstance(provided, list) else [provided]
            if not isinstance(provided, list):
                warnings.append(f"{group} 必须是数组，已按单项处理")
            group_items: list[dict[str, Any]] = []
            for index, item in enumerate(items):
                label = f"{group}[{index}]"
                if not isinstance(item, dict):
                    warnings.append(f"{label} 必须是对象，已按原文送达写者")
                    group_items.append(
                        {"_raw": item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)}
                    )
                    continue
                clean_item = dict(item)
                try:
                    _check_payload(group, clean_item, ledger=ledger)
                except ValueError as exc:
                    warnings.append(f"{label} {exc}")
                if group == "dialogues":
                    _map_dialogue_candidate(clean_item, candidate_number_map=candidate_number_map)
                decorate_evidence(
                    clean_item,
                    label=label,
                    paragraph_text_by_id=paragraph_text_by_id,
                    warnings=warnings,
                    require_evidence=group not in _EVIDENCE_OPTIONAL_GROUPS,
                )
                group_items.append(clean_item)
            if group_items:
                report[group] = group_items
        if metric is not None:
            if not isinstance(metric, dict):
                warnings.append("metric 必须是对象，已按原文送达写者")
                report["metric"] = {"_raw": json.dumps(metric, ensure_ascii=False)}
            else:
                clean_metric = dict(metric)
                try:
                    _check_payload("metric", clean_metric, ledger=ledger)
                except ValueError as exc:
                    warnings.append(f"metric {exc}")
                decorate_evidence(
                    clean_metric,
                    label="metric",
                    paragraph_text_by_id=paragraph_text_by_id,
                    warnings=warnings,
                    require_evidence=True,
                )
                report["metric"] = clean_metric
        if not report:
            warnings.append("本次 send_message 未包含任何观察项，没有内容送达写者")
            return json.dumps(
                {"accepted": True, "report_delivered": False, "warnings": warnings},
                ensure_ascii=False,
            )
        delivered.append(ReaderReport(block_index=block_index, report=report, warnings=warnings))
        return json.dumps(
            {"accepted": True, "report_delivered": True, "block": block_index + 1, "warnings": warnings},
            ensure_ascii=False,
        )

    return send_message


def _map_dialogue_candidate(item: dict[str, Any], *, candidate_number_map: dict[int, int | None]) -> None:
    """2026-09-12 用于把对话观察的块内候选序号折算为章级序号（无法对齐时交给写者自对）"""
    candidate_index = item.get("candidate_index")
    if isinstance(candidate_index, bool) or not isinstance(candidate_index, int):
        return
    chapter_index = candidate_number_map.get(candidate_index)
    if chapter_index is not None:
        item["chapter_candidate_index"] = chapter_index


def build_reader_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
    *,
    delivered: list[ReaderReport],
    block_index: int,
    candidate_number_map: dict[int, int | None],
) -> list[Any]:
    """2026-09-11 章内并行（§4 权限矩阵）用于构建读者工具面：只读检索 + send_message"""
    tools = build_search_tools(query_service, ledger)
    tools.append(
        _build_send_message_tool(
            ledger,
            delivered=delivered,
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
    # 2026-09-12 本轮激活的一次性上报（读者未调用 send_message 时为 None）
    report: ReaderReport | None = None


async def run_reader_agent(
    *,
    run_id: str,
    chapter_id: int,
    context: ReaderBlockContext,
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
    复用 Phase A 的完整消息链，读者带着原文上下文补查并一次性上报新观察。
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
    delivered: list[ReaderReport] = []
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
            delivered=delivered,
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
                        "请针对该问题补查，并把新观察经一次 send_message 上报"
                        "（只带上与问题相关及补查中新发现的观察）；"
                        "没有新发现就简短说明后直接结束，不必调用工具。"
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
        report=delivered[0] if delivered else None,
    )


__all__ = [
    "ReaderBlockContext",
    "ReaderRunOutcome",
    "build_reader_tools",
    "run_reader_agent",
]
