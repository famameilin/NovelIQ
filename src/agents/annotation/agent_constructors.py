"""
章内 agent 构造器：八类记录构造器、收尾工具与程序面回执 helper
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from src.agents.annotation.agent_ir import (
    CONFIDENCE_VALUES,
    DIALOGUE_VERDICTS,
    ENTITY_TYPES,
    NARRATIVE_FUNCTIONS,
    RELATION_TYPES,
    RUNTIME_ROLES,
    TONE_VALUES,
    AgentAnnotation,
    AgentDialogue,
    AgentEntity,
    AgentEvent,
    AgentLabel,
    AgentMetric,
    AgentParticipant,
    AgentPending,
    AgentRelation,
    normalize_evidence,
)
from src.agents.annotation.ir_validation import (
    _reject,
    _require_enum,
    _require_local_key,
    _require_name,
    _require_paragraph_id,
    _require_score,
    _require_text,
    namespace_el,
    namespace_event_el,
)
from src.event_trees.vocabulary import (
    _EVENT_ONLY_ROLE_WORDS,
    normalize_event_participant_role,
)
from src.fact_graph.inputs import EntityNameRef
from src.fact_graph.schema import EL_PATH_SEP, ENTITY_TAG_MAX_CHARS, ENTITY_TAG_MAX_COUNT
from src.fact_graph.vocabulary import (
    Confidence,
    DialogueVerdict,
    EntityType,
    NarrativeFunction,
    RelationType,
    Tone,
    clamp_emotion_score,
    normalize_role_function,
)

from .program_contract import _READ_TOOL_NAMES


def _record_of(agent: AgentAnnotation, field: str) -> str:
    """用于在记录键里带上职责名（三个 agent 的审计行按它分流）

    职责名与域同名时只保留一层前缀：事件 agent 的字段本就以 event/ 开头，再套职责名
    会渲染成 event/event/t1。
    """
    prefix = f"{agent.role}/"
    return field if field.startswith(prefix) else f"{prefix}{field}"


def _written_receipt(record: str, ref: dict[str, Any]) -> dict[str, Any]:
    """用于构造一次写入成功的程序面回执（构造器与工具同一封信）"""
    return {"status": "written", "record": record, "ref": dict(ref)}


def _sync_entity_ref(ref: dict[str, Any], production_receipt: Any) -> None:
    """用于把实体 ref 的大类对齐生产层的生效记录

    同章内另一条 lane 先登记过同名实体时，生产层按部分更新合并保留登记大类、
    丢弃本次入参的 entity_type；ref 若照抄输入，模型看到的大类与现实不符。
    """
    if not isinstance(production_receipt, dict):
        return
    if ref.get("kind") in {"plotline", "foreshadow_action", "complete_event"}:
        ref.update(production_receipt.get("ref") or {})
        return
    if ref.get("kind") != "entity":
        return
    content = production_receipt.get("content")
    if isinstance(content, dict) and "entity_type" in content:
        ref["entity_type"] = content["entity_type"]


def _tool_receipt(name: str, payload: Any) -> Any:
    """用于把一次工具调用的产出收敛成程序面回执

    检索类的产出就是数据本身（程序要拿它绑变量、遍历、取长度），套信封会毁掉读的语义，
    所以原样返回；其余工具（案例/finish）统一成 {status, record, ref}——工具自己那套
    {"accepted": ...} 是生产层的回执，不会漏到程序面。
    """
    if name in _READ_TOOL_NAMES:
        return payload if payload is not None else {}
    body: dict[str, Any] = payload if isinstance(payload, dict) else {}
    if str(body.get("status") or "") == "written":
        return {**body, "ref": dict(body.get("ref") or {})}
    ref = {key: value for key, value in body.items() if key not in {"accepted", "status", "record"}}
    return _written_receipt(str(body.get("record") or name), ref)


def _refused_receipt(name: str, record: str | None, payload: Any) -> dict[str, Any]:
    """用于把一次被拒的产出收敛成同一个信封（构造器校验失败与生产拒绝同一形状）

    生产层的非结构化失败是 {"accepted": false, "tool": ..., "error": ...}；构造器校验失败
    与结构化拒绝已经是 record/field/code/expected/message。两者都归一到这里。
    """
    body: dict[str, Any] = payload if isinstance(payload, dict) else {}
    if str(body.get("status") or "") == "rejected":
        return body
    return {
        "status": "rejected",
        "record": str(record or body.get("record") or name),
        "code": str(body.get("code") or "tool_error"),
        "message": str(body.get("error") or body.get("message") or ""),
    }


def _receipt_message(receipt: Any) -> str:
    """用于取回执里的人类可读原因（回执不是对象时退化成它的字符串形式）"""
    if isinstance(receipt, dict):
        return str(receipt.get("message") or receipt.get("error") or "")
    return str(receipt or "")


def _put_by(items: list[Any], item: Any, *, key: Any) -> None:
    """用于按自然键写入或整体替换（同键重写=更新语义，与正式写入同口径）"""
    for index, existing in enumerate(items):
        if key(existing) == key(item):
            items[index] = item
            return
    items.append(item)


def _normalize_el(value: Any, *, record: str) -> str:
    """用于校验事件 el 层级路径的形态（根=树键、子=树键/节点键）"""
    text = _require_text(value, record=record, field_name="el")
    if text.count(EL_PATH_SEP) > 1:
        raise _reject(
            f"el 的层级最多两层（树键/节点键）：{text}",
            record=record,
            field="el",
            code="bad_el",
            expected="根事件 el=树键（如 t1）；子事件 el=树键/节点键（如 t1/e2）",
        )
    return text


def _normalize_participants(raw: Any, *, record: str, book: _ConstructorBook) -> list[AgentParticipant]:
    """用于校验参与者清单的形状（名字与大类由运行时解析并自动登记），并归一角色取值

    role/narrative_role/emotion 缺省或写偏都不拒绝——role 未知词
    交生产面按实体登记类型给默认，叙事功能近义词归一（未收录收敛为主体），
    情绪分值越界按边界钳制；地点等事件专属角色词写进叙事功能仍当场拒（字段误用）。
    """
    if raw is None:
        raise _reject(
            "participants 需要参与者数组",
            record=record,
            field="participants",
            code="missing_field",
            expected='[{"name": 正文名字, "entity_type": 实体大类, "role": ..., "narrative_role": ..., '
            '"action": ..., "emotion": ...}]',
        )
    if not isinstance(raw, (list, tuple)) or not raw:
        raise _reject(
            "participants 必须是非空数组",
            record=record,
            field="participants",
            code="invalid_value",
            expected='[{"name": 正文名字, "entity_type": 实体大类, "role": ...}]，至少一个参与者',
        )
    normalized: list[AgentParticipant] = []
    for index, item in enumerate(raw):
        entry = item if isinstance(item, dict) else {}
        ref = _name_ref(
            {key: value for key, value in entry.items() if key not in {"role", "narrative_role", "action", "emotion"}},
            record=record,
            field_name=f"participants[{index}]",
        )
        narrative_role = entry.get("narrative_role")
        if isinstance(narrative_role, str) and narrative_role.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise _reject(
                f"participants[{index}].narrative_role 不接受 {narrative_role.strip()}: "
                "地点、行动者等只用于 role 字段；人物功能使用 主体/客体/发送者/接收者/帮助者/反对者/见证者",
                record=record,
                field=f"participants[{index}].narrative_role",
                code="invalid_value",
                expected="、".join(RUNTIME_ROLES),
            )
        normalized.append(
            AgentParticipant(
                name=ref.name,
                entity_type=ref.entity_type,
                role=normalize_event_participant_role(entry.get("role")),
                narrative_role=normalize_role_function(narrative_role),
                action=(
                    _require_text(action, record=record, field_name=f"participants[{index}].action")
                    if (action := entry.get("action")) is not None
                    else None
                ),
                emotion=clamp_emotion_score(entry.get("emotion")),
            )
        )
    return normalized


@dataclass(slots=True)
class _ConstructorCall:
    """一次构造器调用的产出：校验好的记录 + 要交给生产边界的那一笔写入

    构造器是纯校验器（当场可拒绝、不碰 journal），运行时拿本对象
    经生产单条事务边界把 `args` 写进正式账本，**写入成功才**调 `commit()` 落 journal。
    因此 agent 的列表恒等于"已经落库的记录"：模型引用一个键，就一定有一条已生效的
    正式记录在它背后。
    """

    record: str
    ref: dict[str, Any]
    commit: Callable[[], None]
    # 生产工具名与入参；label 与指标同属 write_metrics 一个域，不能单独落库，故 tool=None
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _ConstructorBook:
    """构造器闭包共用的 agent 态与取值边界"""

    agent: AgentAnnotation
    role: str
    paragraph_text_by_id: dict[int, str]
    candidate_total: int


def _event_write_args(
    book: _ConstructorBook,
    item: AgentEvent,
    *,
    characters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """用于把一条事件记录翻成 write_event 入参（el 按角色命名空间化）

    characters 省略=不动该节点已有参与者（生产口径：给出即整体替换、省略即保留），
    所以 event 与 participants 两个构造器共用本函数。
    """
    args: dict[str, Any] = {
        "el": namespace_event_el(book.role, item.el),
        "title": item.title,
        "problem": item.problem,
        "summary": item.summary,
        "event_type": item.event_type,
        "status": item.status,
        "progress": item.progress,
        "evidence": item.evidence[0].paragraph_id,
    }
    args["isforeshadowing"] = item.isforeshadowing
    if item.confidence is not None:
        args["confidence"] = item.confidence
    if characters is not None:
        args["characters"] = characters
    return args


def _name_ref(value: Any, *, record: str, field_name: str) -> EntityNameRef:
    """只接正文名字与大类，身份解析交给生产运行时"""
    try:
        return EntityNameRef.model_validate(value)
    except ValidationError as exc:
        raise _reject(
            f"{field_name} 必须写正文名字与大类：{exc}",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="{name: 正文名字, entity_type: character/item/location/organization}",
        ) from None


def build_agent_constructors(
    agent: AgentAnnotation,
    *,
    paragraph_text_by_id: dict[int, str],
    candidate_total: int,
) -> list[tuple[str, Any, str]]:
    """用于构造 agent 命名空间里的记录构造器（返回 (名字, 可调用, 一句话说明) 列表）

    每个构造器当场校验、当场给出要写的那一笔：成功时运行时立即经生产单条事务边界
    落库（写入生效），失败抛 AnnotationStageRejection（只废这一条，程序继续跑后面的
    语句）。三个 agent 拿到的是同一份构造器清单，引用键按角色命名空间化
    落库（namespace_el），所以三个 agent 的同名局部键互不占用。
    """
    # 聚合模块会反向导入构造器，运行时再读取目录顺序以避免首次导入环
    from .agent_program import _AGENT_CONSTRUCTOR_ORDER

    book = _ConstructorBook(
        agent=agent,
        role=agent.role,
        paragraph_text_by_id=paragraph_text_by_id,
        candidate_total=candidate_total,
    )

    def entity(
        id: str,
        name: str,
        entity_type: EntityType,
        evidence: int,
        tags: list[str] | None = None,
        description: str | None = None,
        representative: bool | None = None,
    ) -> _ConstructorCall:
        """登记本章的一个实体（id 是本章实体的局部键，name 照抄正文写法）

        id 形如 a1/a2…，在本章内唯一；同 id 重写=更新该实体，引用实体一律写正文名字与大类，不写 id。
        entity_type 取闭集 character/item/location/organization（有生命就是 character）。
        机构名称兼指所在场所时按 organization 登记，只有纯地理场所才用 location。
        evidence 写该名字出现段落的段首号（正文每段开头的 `N：` 里的 N）。
        representative=True 表示该名字是同一个人物的规范写法（外号/别称登记时不写）；
        省略=保留现值，False=清除标记。
        """
        record = _record_of(agent, f"entity/{id}")
        normalized_id = _require_local_key(id, record=record, field_name="id")
        normalized_name = _require_name(name, record=record, field_name="name")
        kind = _require_enum(entity_type, ENTITY_TYPES, record=record, field_name="entity_type")
        normalized_tags: list[str] = []
        for tag in tags or []:
            cleaned = _require_text(tag, record=record, field_name="tags")
            if len(cleaned) > ENTITY_TAG_MAX_CHARS:
                raise _reject(
                    f"标签超过 {ENTITY_TAG_MAX_CHARS} 个字：{cleaned}",
                    record=record,
                    field="tags",
                    code="invalid_value",
                    expected=f"最多 {ENTITY_TAG_MAX_COUNT} 个标签、每个最多 {ENTITY_TAG_MAX_CHARS} 个字",
                )
            if cleaned not in normalized_tags:
                normalized_tags.append(cleaned)
        if len(normalized_tags) > ENTITY_TAG_MAX_COUNT:
            raise _reject(
                f"标签超过 {ENTITY_TAG_MAX_COUNT} 个",
                record=record,
                field="tags",
                code="invalid_value",
                expected=f"最多 {ENTITY_TAG_MAX_COUNT} 个标签、每个最多 {ENTITY_TAG_MAX_CHARS} 个字",
            )
        if representative is not None and not isinstance(representative, bool):
            raise _reject(
                "representative 必须是布尔值",
                record=record,
                field="representative",
                code="invalid_value",
                expected="True/False，或省略以保留现值",
            )
        item = AgentEntity(
            id=normalized_id,
            name=normalized_name,
            entity_type=kind,
            tags=normalized_tags,
            description=(
                _require_text(description, record=record, field_name="description") if description is not None else None
            ),
            representative=representative,
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        args: dict[str, Any] = {
            "name": item.name,
            "entity_type": item.entity_type,
            "el": namespace_el(book.role, item.id),
        }
        if tags is not None:
            args["tags"] = list(item.tags)
        if item.description is not None:
            args["description"] = item.description
        if item.representative is not None:
            args["representative"] = item.representative
        return _ConstructorCall(
            record=record,
            tool="write_entity",
            args=args,
            ref={"kind": "entity", "id": item.id, "name": item.name, "entity_type": item.entity_type},
            commit=lambda: _put_by(agent.entities, item, key=lambda existing: existing.id),
        )

    def relation(
        from_entity: EntityNameRef,
        to_entity: EntityNameRef,
        relation_type: RelationType,
        evidence: int | None = None,
    ) -> _ConstructorCall:
        """写一条闭合关系边（两端写正文名字与大类，运行时解析并自动登记，不判身份、不判别名）

        relation_type 取闭合关系类型表；方向与两端类型约束在参数说明里。
        本章只确认局部关系（建边），不带 change_kind 关系变化——跨章关系变化由
        write_link 关联工具承担。
        正文只说见面/对峙这类没有闭合关系可表达的，宁缺勿滥——用 pending 登记。
        """
        record = _record_of(agent, "relation")
        source = _name_ref(from_entity, record=record, field_name="from_entity")
        target = _name_ref(to_entity, record=record, field_name="to_entity")
        record = _record_of(agent, f"relation/{source.name}-{target.name}")
        # 建边不消费 evidence（同生产面的口径）：给了也不报错，只不落进这条记录
        item = AgentRelation(
            from_entity=source,
            to_entity=target,
            relation_type=_require_enum(relation_type, RELATION_TYPES, record=record, field_name="relation_type"),
            evidence=(
                normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id)
                if evidence is not None
                else ()
            ),
        )
        args: dict[str, Any] = {
            "from_entity": item.from_entity.model_dump(mode="json"),
            "to_entity": item.to_entity.model_dump(mode="json"),
            "relation_type": item.relation_type,
        }
        return _ConstructorCall(
            record=record,
            tool="write_relation",
            args=args,
            ref={
                "kind": "relation",
                "type": item.relation_type,
                "from_entity": item.from_entity.model_dump(mode="json"),
                "to_entity": item.to_entity.model_dump(mode="json"),
            },
            commit=lambda: _put_by(
                agent.relations,
                item,
                key=lambda existing: (
                    existing.from_entity.name,
                    existing.from_entity.entity_type,
                    existing.to_entity.name,
                    existing.to_entity.entity_type,
                ),
            ),
        )

    def event(
        el: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: str,
        evidence: int,
        progress: str | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
    ) -> _ConstructorCall:
        """声明本章一个事件；局部键仅寻址，不以调用顺序推导包含或阶段"""
        record = _record_of(agent, f"event/{el}")
        normalized_el = _normalize_el(el, record=record)
        existing = agent.event_keys().get(normalized_el)
        if isforeshadowing and confidence is None:
            raise _reject(
                "isforeshadowing=True 时 confidence 必填",
                record=record,
                field="confidence",
                code="missing_field",
                expected="high / medium / low",
            )
        item = AgentEvent(
            el=normalized_el,
            isroot=EL_PATH_SEP not in normalized_el,
            description=_require_text(summary, record=record, field_name="summary"),
            title=_require_text(title, record=record, field_name="title"),
            problem=_require_text(problem, record=record, field_name="problem"),
            summary=_require_text(summary, record=record, field_name="summary"),
            event_type=_require_text(event_type, record=record, field_name="event_type"),
            status=_require_enum(status, ("ongoing", "resolved"), record=record, field_name="status"),
            progress=_require_text(progress, record=record, field_name="progress") if progress is not None else None,
            isforeshadowing=isforeshadowing,
            confidence=_require_enum(confidence, CONFIDENCE_VALUES, record=record, field_name="confidence")
            if confidence is not None
            else None,
            participants=list(existing.participants) if existing is not None else [],
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        if existing is not None and existing.to_dict() != item.to_dict():
            raise ValueError(f"event/{normalized_el} 声明内容不可改写")
        return _ConstructorCall(
            record=record,
            tool="write_event",
            args=_event_write_args(book, item),
            ref={"kind": "declaration", "el": item.el},
            commit=lambda: _put_by(agent.events, item, key=lambda current: current.el),
        )

    def participants(el: str, items: list[dict[str, Any]]) -> _ConstructorCall:
        """把一个事件节点的参与者整体设为 items（同一节点重写=整体替换）

        items 每项 {name: 正文名字, entity_type: 大类, role: 主体/客体/接收者/帮助者/
        反对者/见证者/地点, narrative_role: 叙事功能, action: 做了什么, emotion: -2..2 整数}。
        四个描述字段均可省略或写偏：role 缺省按实体登记类型取默认（character→主体、
        location→地点、其余→客体），叙事功能近义词自动归一，emotion 越界按边界收敛。
        地点角色接受 location 与 organization 型端点（机构兼场所按 organization 登记即可当地点）。
        """
        record = _record_of(agent, f"participants/{el}")
        normalized_el = _normalize_el(el, record=record)
        target = agent.event_keys().get(normalized_el)
        if target is None:
            known = "、".join(sorted(agent.event_keys())) or "（本 agent 还没有事件）"
            raise _reject(
                f"participants 引用了本 agent 未构造的事件：{normalized_el}",
                record=record,
                field="el",
                code="unknown_reference",
                expected=f"先用 event(...) 建它，再挂参与者；已构造的 el：{known}",
            )
        normalized_participants = _normalize_participants(items, record=record, book=book)
        characters: list[dict[str, Any]] = []
        for participant in normalized_participants:
            entry: dict[str, Any] = {
                "name": participant.name,
                "entity_type": participant.entity_type,
                "role": participant.role,
            }
            if participant.narrative_role is not None:
                entry["narrative_role"] = participant.narrative_role
            if participant.action is not None:
                entry["action"] = participant.action
            if participant.emotion is not None:
                entry["emotion"] = participant.emotion
            characters.append(entry)

        def commit() -> None:
            """写入成功后才整体换掉该节点的参与者（被拒即整条作废，journal 不动）"""
            target.participants = normalized_participants

        # 参与者按生产口径整体替换该节点参与者列表（同 el 重写=更新语义）：描述与伏笔属性
        # 从已落 journal 的节点记录原样带回，本构造器只改参与者这一项。
        return _ConstructorCall(
            record=record,
            tool="write_event",
            args=_event_write_args(book, target, characters=characters),
            ref={"kind": "participants", "el": target.el, "count": len(normalized_participants)},
            commit=commit,
        )

    def dialogue(
        candidate_index: int,
        verdict: DialogueVerdict,
        evidence: int | None = None,
        speaker: EntityNameRef | None = None,
        tone: Tone | None = None,
    ) -> _ConstructorCall:
        """判定一条对话候选（candidate_index 取候选表编号）

        verdict: dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选
        （题字、描写被引号包裹等，此时只填 candidate_index/verdict）。
        speaker 写 {name: 正文名字, entity_type: character}，运行时自动登记，判不了就省略。
        tone 取闭集，没有贴合的用「其他」。
        evidence 是候选所在段落的段首号：not_dialogue 可省略，其余必须给。
        """
        record = _record_of(agent, f"dialogue/{candidate_index}")
        if (
            isinstance(candidate_index, bool)
            or not isinstance(candidate_index, int)
            or not 1 <= candidate_index <= book.candidate_total
        ):
            raise _reject(
                f"candidate_index 超出候选范围：{candidate_index}",
                record=record,
                field="candidate_index",
                code="out_of_range",
                expected=f"1..{book.candidate_total}（用 <DialogueCandidates> 表里的编号）",
            )
        normalized_verdict = _require_enum(verdict, DIALOGUE_VERDICTS, record=record, field_name="verdict")
        normalized_speaker: EntityNameRef | None = None
        normalized_tone: str | None = None
        if normalized_verdict == "not_dialogue":
            if speaker is not None or tone is not None:
                raise _reject(
                    "not_dialogue 候选只提交 candidate_index/verdict",
                    record=record,
                    field="verdict",
                    code="invalid_value",
                    expected="speaker 与 tone 都省略",
                )
        else:
            if speaker is not None:
                normalized_speaker = _name_ref(speaker, record=record, field_name="speaker")
            if tone is not None:
                normalized_tone = _require_enum(tone, TONE_VALUES, record=record, field_name="tone")
        item = AgentDialogue(
            candidate_index=candidate_index,
            verdict=normalized_verdict,
            speaker=normalized_speaker,
            tone=normalized_tone,
            evidence=normalize_evidence(
                evidence,
                record=record,
                paragraph_text_by_id=book.paragraph_text_by_id,
                required=normalized_verdict != "not_dialogue",
            ),
        )
        args: dict[str, Any] = {"candidate_index": item.candidate_index, "verdict": item.verdict}
        if item.speaker is not None:
            args["speaker"] = item.speaker.model_dump(mode="json")
        if item.tone is not None:
            args["tone"] = item.tone
        return _ConstructorCall(
            record=record,
            tool="write_dialogue",
            args=args,
            ref={"kind": "dialogue", "candidate_index": item.candidate_index, "verdict": item.verdict},
            commit=lambda: _put_by(agent.dialogues, item, key=lambda current: current.candidate_index),
        )

    def label(paragraph_id: int, emotion: int) -> _ConstructorCall:
        """给一个段落打整段情绪标签（段落号本身就是锚点，不需要引文）

        paragraph_id 取正文段首可见号（每段开头的 `N：` 里的 N）；emotion 为 -2..2 整数分值。
        每章自选 2~3 段，优先选情绪表达有代表性、或语气/标点有区分度的段落。
        同段重写=更新语义。
        """
        record = _record_of(agent, f"label/{paragraph_id}")
        normalized_id = _require_paragraph_id(
            paragraph_id, record=record, field_name="paragraph_id", paragraph_text_by_id=book.paragraph_text_by_id
        )
        item = AgentLabel(
            paragraph_id=normalized_id,
            emotion=_require_score(emotion, record=record, field_name="emotion"),
        )
        # 段落标签与章级指标在生产面上同属 write_metrics 一个域（标签是它的 labels 参数），
        # 单独一条标签写不出去，所以这里只落 journal：整章收尾链把三份标签并起来随指标
        # 一次落库（指标缺失时那条兜底记录同样带上标签）。
        return _ConstructorCall(
            record=record,
            ref={"kind": "label", "paragraph_id": item.paragraph_id, "emotion": item.emotion},
            commit=lambda: _put_by(agent.labels, item, key=lambda current: current.paragraph_id),
        )

    def metric(
        summary: str,
        emotional_valence: int,
        narrative_function: NarrativeFunction,
        pivot_moment: bool = False,
        cliffhanger: bool = False,
    ) -> _ConstructorCall:
        """提交本章的摘要与叙事指标（整域一次提交，重复提交按最后一次为准）

        narrative_function 取 冲突/铺垫/转折；emotional_valence 为 -2..2 整数。
        """
        record = _record_of(agent, "metric")
        item = AgentMetric(
            summary=_require_text(summary, record=record, field_name="summary"),
            emotional_valence=_require_score(emotional_valence, record=record, field_name="emotional_valence"),
            narrative_function=_require_enum(
                narrative_function, NARRATIVE_FUNCTIONS, record=record, field_name="narrative_function"
            ),
            pivot_moment=bool(pivot_moment),
            cliffhanger=bool(cliffhanger),
        )

        def commit() -> None:
            """写入成功后才把本域记录挂到 agent 上（被拒即整条作废）"""
            agent.metric = item

        return _ConstructorCall(
            record=record,
            tool="write_metrics",
            args={
                "summary": item.summary,
                "emotional_valence": item.emotional_valence,
                "narrative_function": item.narrative_function,
                "pivot_moment": item.pivot_moment,
                "cliffhanger": item.cliffhanger,
            },
            ref={"kind": "metric", "summary": item.summary},
            commit=commit,
        )

    def pending(case_type: str, description: str) -> _ConstructorCall:
        """登记案例并显式归入人物/关系/对话/事件之一，只有 description 承载文字"""
        from src.case_pool import CASE_TYPES

        record = _record_of(agent, "pending")
        if case_type not in CASE_TYPES:
            raise _reject(
                f"case_type={case_type!r} 不属于案例类型",
                record=record,
                field="case_type",
                code="unknown_case_type",
                expected=f"{list(CASE_TYPES)} 之一",
            )
        item = AgentPending(
            case_type=case_type, description=_require_text(description, record=record, field_name="description")
        )
        if len(item.description) > 100:
            raise _reject(
                f"description={item.description!r} 超过 100 字",
                record=record,
                field="description",
                code="too_long",
                expected="1..100 字普通文字",
            )
        return _ConstructorCall(
            record=record,
            tool="push_case",
            args={"case_type": item.case_type, "description": item.description},
            ref={"kind": "pending"},
            commit=lambda: agent.pending.append(item),
        )

    def plotline(
        subject_title: str,
        description: str,
        after: str,
        evidence: int,
        before: str | None = None,
        subject_id: str | None = None,
        declaration_id: str | None = None,
    ) -> _ConstructorCall:
        """记录有原文依据的问题推进、目标改变或线索揭示

        description 是本次变化的标题（必填）；before/after 是变化前后的状态（不可相同），
        before 未知填 None；主体 ID 可沿用既有回执的 subject_id。
        """
        args = {
            "subject_title": subject_title,
            "description": description,
            "after": after,
            "evidence": evidence,
            "before": before,
            "subject_id": subject_id,
            "declaration_id": declaration_id,
        }
        return _ConstructorCall(
            record=_record_of(agent, "plotline"),
            tool="write_plotline",
            args=args,
            ref={"kind": "plotline"},
            commit=lambda: agent.plotlines.append(args),
        )

    def foreshadow_action(
        source_declaration_id: str, action_type: str, evidence: int, target_declaration_id: str | None = None
    ) -> _ConstructorCall:
        """引用已埋伏笔的 declaration_id 记录强化或回收：先 read_event 读取声明；
        source_declaration_id 须是伏笔树根（isforeshadowing=True 声明的根，
        read_event 回执 is_foreshadow_setup=True），普通事件树根拒收；action_type 写英文常量
        'reinforce'（强化）或 'payoff'（疑似回收）；埋设随声明自动记录"""
        args = {
            "source_declaration_id": source_declaration_id,
            "action_type": action_type,
            "evidence": evidence,
            "target_declaration_id": target_declaration_id,
        }
        return _ConstructorCall(
            record=_record_of(agent, "foreshadow_action"),
            tool="write_foreshadowing_action",
            args=args,
            ref={"kind": "foreshadow_action"},
            commit=lambda: agent.foreshadow_actions.append(args),
        )

    functions = {
        "plotline": (plotline, "保存情节推进及前后状态，evidence为本章段首号"),
        "foreshadow_action": (foreshadow_action, "保存明确强化或疑似回收，照应边不等于动作"),
        "entity": (entity, "登记本章的一个实体（id 为本章实体局部键，name 照抄正文名字）"),
        "relation": (relation, "写一条闭合关系边（两端写正文名字与大类，运行时解析并自动登记）"),
        "event": (event, "写一个事件节点（el 根=树键、子=树键/节点键）"),
        "participants": (participants, "把一个事件节点的参与者整体设为 items（名字与大类由运行时解析并自动登记）"),
        "dialogue": (dialogue, "判定一条对话候选（candidate_index+verdict）"),
        "label": (label, "给一个段落打整段情绪标签（段首号）"),
        "metric": (metric, "提交本章摘要与叙事指标（整域一次提交）"),
        "pending": (pending, "登记一个判不了的疑点（只填 description）"),
    }
    return [(name, functions[name][0], functions[name][1]) for name in _AGENT_CONSTRUCTOR_ORDER]
