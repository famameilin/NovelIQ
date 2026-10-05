"""
章内 subagent 构造器：八类记录构造器、收尾工具与程序面回执 helper
"""

# ruff: noqa: E402 —— 文件末尾的 re-export 导入为有意的延迟导入（大文件拆分聚合面）。

# 创建时间：2026-10-02　创建者：Trae
# 任务：subagent_program.py 大文件拆分——回执 helpers + 规范化 + 构造器账本 +
# build_subagent_constructors（八类构造器闭包）+ build_subagent_finish_tool 迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑、签名与模型可见文案；_SUBAGENT_CONSTRUCTOR_ORDER
# 等常量保留在 subagent_program.py，由本模块末尾反向引用（双向均定义先于引用，
# 任意导入顺序安全）；subagent_program.py 对本模块符号保留 re-export。

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool

from .program import _READ_TOOL_NAMES, _dedent_catalog_text
from .schema import (
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    Confidence,
    DialogueVerdict,
    EntityRef,
    EntityType,
    EventChildType,
    NarrativeFunction,
    RelationType,
    Tone,
)
from .subagent_ir import (
    CONFIDENCE_VALUES,
    DIALOGUE_VERDICTS,
    EL_PATH_SEP,
    ENTITY_TYPES,
    EVENT_CHILD_TYPES,
    NARRATIVE_FUNCTIONS,
    PENDING_CASE_TYPES,
    PENDING_KINDS,
    RELATION_TYPES,
    RESERVED_ROOT_KEY,
    RUNTIME_ROLES,
    TONE_VALUES,
    SubagentAnnotation,
    SubagentDialogue,
    SubagentEntity,
    SubagentEvent,
    SubagentLabel,
    SubagentMetric,
    SubagentParticipant,
    SubagentPending,
    SubagentRelation,
    _reject,
    _require_enum,
    _require_local_key,
    _require_name,
    _require_paragraph_id,
    _require_score,
    _require_text,
    namespace_el,
    namespace_event_el,
    normalize_evidence,
    truncate_case_description,
)
from .tools import FINISH_TOOL_NAME, _forbid_undeclared_args
from .vocabulary import (
    _EVENT_ONLY_ROLE_WORDS,
    clamp_emotion_score,
    normalize_event_participant_role,
    normalize_role_function,
)


def _record_of(subagent: SubagentAnnotation, field: str) -> str:
    """用于在记录键里带上职责名（三个 subagent 的审计行按它分流）

    2026-09-20 去重前缀：事件 subagent 的字段本就以 event/ 开头，再套职责名渲染成
    event/event/t1——跨 lane 引用产出记录时（案例的 result_id/record_id 要"照抄回执里的
    record"），模型按自然形态 event/t1 猜，13+13 次全被 unknown_record 拒。职责名与域同名
    时不再叠加（structure/entity/…、evidence/dialogue/… 这类前缀照旧）。
    """
    prefix = f"{subagent.role}/"
    return field if field.startswith(prefix) else f"{prefix}{field}"


def _written_receipt(record: str, ref: dict[str, Any]) -> dict[str, Any]:
    """用于构造一次写入成功的程序面回执（构造器与工具同一封信）"""
    return {"status": "written", "record": record, "ref": dict(ref)}


def _sync_entity_ref(ref: dict[str, Any], production_receipt: Any) -> None:
    """用于把实体 ref 的大类对齐生产层的生效记录

    同章内另一条 lane 先登记过同名实体时，生产层按部分更新合并保留登记大类、
    丢弃本次入参的 entity_type；ref 若照抄输入，模型看到的大类与现实不符
    （run faff5efe ch14 实测：event lane 提交 location、生效 organization）。
    """
    if ref.get("kind") != "entity" or not isinstance(production_receipt, dict):
        return
    content = production_receipt.get("content")
    if isinstance(content, dict) and "entity_type" in content:
        ref["entity_type"] = content["entity_type"]


def _tool_receipt(name: str, payload: Any) -> Any:
    """用于把一次工具调用的产出收敛成程序面回执

    检索类的产出就是数据本身（程序要拿它绑变量、遍历、取长度），套信封会毁掉读的语义，
    所以原样返回；其余工具（案例/finish）统一成 {status, record, ref}——工具自己那套
    {"accepted": ...} 是生产层的回执，不再漏到程序面。
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


def _normalize_participants(raw: Any, *, record: str, book: _ConstructorBook) -> list[SubagentParticipant]:
    """用于校验参与者清单的形状（entity_id 是本 subagent 已登记 id），并归一角色取值

    2026-10-04 合同放开：role/narrative_role/emotion 缺省或写偏不再拒绝——role 未知词
    交生产面按实体登记类型给默认，叙事功能近义词归一（未收录收敛为主体），
    情绪分值越界按边界钳制；地点等事件专属角色词写进叙事功能仍当场拒（字段误用）。
    """
    if raw is None:
        raise _reject(
            "participants 需要参与者数组",
            record=record,
            field="participants",
            code="missing_field",
            expected='[{"entity_id": 本 subagent 实体 id, "role": ..., "narrative_role": ..., '
            '"action": ..., "emotion": ...}]',
        )
    if not isinstance(raw, (list, tuple)) or not raw:
        raise _reject(
            "participants 必须是非空数组",
            record=record,
            field="participants",
            code="invalid_value",
            expected='[{"entity_id": 本 subagent 实体 id, "role": ...}]，至少一个参与者',
        )
    normalized: list[SubagentParticipant] = []
    for index, item in enumerate(raw):
        entry = item if isinstance(item, dict) else {}
        entity_id = _require_known_entity_id(
            book, entry.get("entity_id"), record=record, field_name=f"participants[{index}].entity_id"
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
            SubagentParticipant(
                entity_id=entity_id,
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

    2026-09-18 写入生效：构造器是纯校验器（当场可拒绝、不碰 journal），运行时拿本对象
    经生产单条事务边界把 `args` 写进正式账本，**写入成功才**调 `commit()` 落 journal。
    因此 subagent 的列表恒等于"已经落库的记录"：模型引用一个键，就一定有一条已生效的
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
    """构造器闭包共用的 subagent 态与取值边界"""

    subagent: SubagentAnnotation
    role: str
    paragraph_text_by_id: dict[int, str]
    candidate_total: int


def _event_write_args(
    book: _ConstructorBook,
    item: SubagentEvent,
    *,
    characters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """用于把一条事件记录翻成 write_event 入参（el 按角色命名空间化）

    characters 省略=不动该节点已有参与者（生产口径：给出即整体替换、省略即保留），
    所以 event 与 participants 两个构造器共用本函数。
    """
    args: dict[str, Any] = {
        "el": namespace_event_el(book.role, item.el),
        "isroot": item.isroot,
        "description": item.description,
        "evidence": item.evidence[0].paragraph_id,
    }
    if item.isroot:
        args["isforeshadowing"] = item.isforeshadowing
        if item.confidence is not None:
            args["confidence"] = item.confidence
    else:
        args["type"] = item.node_type
    if characters is not None:
        args["characters"] = characters
    return args


def _require_known_entity_id(book: _ConstructorBook, value: Any, *, record: str, field_name: str) -> str:
    """用于校验实体引用是"本 subagent 已登记的 id"（未登记即结构化拒绝并列出已知 id）"""
    normalized = _require_local_key(value, record=record, field_name=field_name)
    known = book.subagent.entity_ids()
    if normalized not in known:
        available = "、".join(known) or "（本 subagent 还没有实体）"
        raise _reject(
            f"{field_name} 引用了本 subagent 未登记的实体 id：{normalized}",
            record=record,
            field=field_name,
            code="unknown_reference",
            expected=f"先用 entity(id=..., name=...) 在本 subagent 登记它，再用 id 引用；已登记 id：{available}",
        )
    return normalized


def build_subagent_constructors(
    subagent: SubagentAnnotation,
    *,
    paragraph_text_by_id: dict[int, str],
    candidate_total: int,
) -> list[tuple[str, Any, str]]:
    """用于构造 subagent 命名空间里的记录构造器（返回 (名字, 可调用, 一句话说明) 列表）

    每个构造器当场校验、当场给出要写的那一笔：成功时运行时立即经生产单条事务边界
    落库（写入生效），失败抛 AnnotationStageRejection（只废这一条，程序继续跑后面的
    语句）。三个 subagent 拿到的是同一份构造器清单（§3），引用键按角色命名空间化
    落库（namespace_el），所以三个 subagent 的同名局部键互不占用。
    """
    # 聚合模块会反向导入构造器，运行时再读取目录顺序以避免首次导入环
    from .subagent_program import _SUBAGENT_CONSTRUCTOR_ORDER

    book = _ConstructorBook(
        subagent=subagent,
        role=subagent.role,
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
        attributes: dict[str, Any] | None = None,
    ) -> _ConstructorCall:
        """登记本章的一个实体（id 是你自定的本 subagent 引用键，name 照抄正文写法只作展示）

        id 形如 a1/a2…，relation/participants/dialogue/pending 都用它引用本实体。
        entity_type 取闭集 character/item/location/organization（有生命就是 character）。
        evidence 写该名字出现段落的段首号（正文每段开头的 `N：` 里的 N）。同 id 重写=更新语义。
        """
        record = _record_of(subagent, f"entity/{id}")
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
        normalized_attributes: dict[str, Any] | None = None
        if attributes is not None:
            if not isinstance(attributes, dict):
                raise _reject(
                    "attributes 必须是对象（键=属性名，值=属性值）",
                    record=record,
                    field="attributes",
                    code="invalid_value",
                    expected="{属性名: 值}；不确定就省略",
                )
            normalized_attributes = {
                _require_text(item_key, record=record, field_name="attributes"): item_value
                for item_key, item_value in attributes.items()
            }
        item = SubagentEntity(
            id=normalized_id,
            name=normalized_name,
            entity_type=kind,
            tags=normalized_tags,
            description=(
                _require_text(description, record=record, field_name="description")
                if description is not None
                else None
            ),
            attributes=normalized_attributes,
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        args: dict[str, Any] = {
            "name": item.name,
            "entity_type": item.entity_type,
            "el": namespace_el(book.role, item.id),
        }
        if item.tags:
            args["tags"] = list(item.tags)
        if item.description is not None:
            args["description"] = item.description
        if item.attributes is not None:
            args["attributes"] = dict(item.attributes)
        return _ConstructorCall(
            record=record,
            tool="write_entity",
            args=args,
            ref={"kind": "entity", "id": item.id, "name": item.name, "entity_type": item.entity_type},
            commit=lambda: _put_by(subagent.entities, item, key=lambda existing: existing.id),
        )

    def relation(
        from_id: EntityRef,
        to_id: EntityRef,
        relation_type: RelationType,
        evidence: int | None = None,
    ) -> _ConstructorCall:
        """写一条闭合关系边（两端写本 subagent 已登记的实体 id，不判身份、不判别名）

        relation_type 取闭合关系类型表；方向与两端类型约束在参数说明里。
        2026-10-02 对齐 0.2.0 写面：本章只确认局部关系（建边），不带 change_kind 关系变化
        ——跨章关系变化由 write_link 关联工具承担。
        正文只说见面/对峙这类没有闭合关系可表达的，宁缺勿滥——用 pending 登记。
        """
        record = _record_of(subagent, f"relation/{from_id}-{to_id}")
        source = _require_known_entity_id(book, from_id, record=record, field_name="from_id")
        target = _require_known_entity_id(book, to_id, record=record, field_name="to_id")
        # 建边不消费 evidence（同生产面的口径）：给了也不报错，只不落进这条记录
        item = SubagentRelation(
            from_id=source,
            to_id=target,
            relation_type=_require_enum(relation_type, RELATION_TYPES, record=record, field_name="relation_type"),
            evidence=(
                normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id)
                if evidence is not None
                else ()
            ),
        )
        args: dict[str, Any] = {
            "from_entity": namespace_el(book.role, item.from_id),
            "to_entity": namespace_el(book.role, item.to_id),
            "relation_type": item.relation_type,
        }
        return _ConstructorCall(
            record=record,
            tool="write_relation",
            args=args,
            ref={
                "kind": "relation",
                "type": item.relation_type,
                "from_id": item.from_id,
                "to_id": item.to_id,
            },
            commit=lambda: _put_by(
                subagent.relations,
                item,
                key=lambda existing: (existing.from_id, existing.to_id),
            ),
        )

    def event(
        el: str,
        isroot: bool,
        description: str,
        evidence: int,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        type: EventChildType | None = None,
    ) -> _ConstructorCall:
        """写一个事件节点（el 根=树键 t1、子=树键/节点键 t1/e2；树内先后=调用顺序）

        type=main 顺延主因链 / secondary 挂当时主链尾（子事件必填，根事件不填）。
        伏笔属性只属于根：isforeshadowing=True 时 confidence 必填（high/medium/low）。
        参与者用 participants(el=本键, items=[...]) 追加。同 el 重写=更新语义。
        2026-10-02 对齐 0.2.0 写面：伏笔挂树参数（foreshadowing_action/root_event_id 等）
        已随案例裁决机器退役——跨章伏笔照应由 write_link 关联工具承担。
        """
        record = _record_of(subagent, f"event/{el}")
        normalized_el = _normalize_el(el, record=record)
        tree_key, _, node_key = normalized_el.partition(EL_PATH_SEP)
        if not isinstance(isroot, bool):
            raise _reject(
                "isroot 必须是 True/False",
                record=record,
                field="isroot",
                code="invalid_value",
                expected="True 建树根（el=树键）/ False 加子事件（el=树键/节点键）",
            )
        existing = subagent.event_keys().get(normalized_el)
        if isroot:
            if node_key:
                raise _reject(
                    f"根事件的 el 必须是树键（不带路径）：{normalized_el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected="根事件 el=树键（如 t1）；子事件才是 树键/节点键（如 t1/e2）",
                )
            if type is not None:
                raise _reject(
                    "type 只属于子事件（根事件由 isroot=True 表达）",
                    record=record,
                    field="type",
                    code="not_on_root",
                    expected="根事件不填 type",
                )
            if isforeshadowing and confidence is None:
                raise _reject(
                    "isforeshadowing=True 时 confidence 必填",
                    record=record,
                    field="confidence",
                    code="missing_field",
                    expected="high / medium / low（伏笔回收可能性三档）",
                )
            normalized_confidence = (
                _require_enum(confidence, CONFIDENCE_VALUES, record=record, field_name="confidence")
                if confidence is not None
                else None
            )
            normalized_type: str | None = None
        else:
            if not tree_key or not node_key:
                raise _reject(
                    f"子事件的 el 必须是 树键/节点键：{normalized_el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected="形如 t1/e2；建树请用 event(el=\"t1\", isroot=True, ...)",
                )
            if node_key == RESERVED_ROOT_KEY:
                raise _reject(
                    f"子事件的节点键不得占用 {RESERVED_ROOT_KEY}",
                    record=record,
                    field="el",
                    code="reserved",
                    expected="换一个节点键（root 固定指根事件）",
                )
            if isforeshadowing or confidence is not None:
                raise _reject(
                    "伏笔属性（isforeshadowing/confidence）只属于根事件",
                    record=record,
                    field="isforeshadowing",
                    code="not_on_child",
                    expected="子事件只填 el/type/description",
                )
            if type is None:
                raise _reject(
                    "子事件必须提供 type",
                    record=record,
                    field="type",
                    code="missing_field",
                    expected="main（顺延主因链）/ secondary（挂在当时主链尾）",
                )
            normalized_type = _require_enum(type, EVENT_CHILD_TYPES, record=record, field_name="type")
            normalized_confidence = None
        item = SubagentEvent(
            el=normalized_el,
            isroot=isroot,
            description=_require_text(description, record=record, field_name="description"),
            isforeshadowing=isforeshadowing,
            confidence=normalized_confidence,
            node_type=normalized_type,
            participants=list(existing.participants) if existing is not None else [],
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        ref: dict[str, Any] = {
            "kind": "event",
            "el": item.el,
            "isroot": item.isroot,
            "participants": len(item.participants),
        }
        return _ConstructorCall(
            record=record,
            tool="write_event",
            args=_event_write_args(book, item),
            ref=ref,
            commit=lambda: _put_by(subagent.events, item, key=lambda current: current.el),
        )

    def participants(el: str, items: list[dict[str, Any]]) -> _ConstructorCall:
        """把一个事件节点的参与者整体设为 items（同一节点重写=整体替换）

        items 每项 {entity_id: 本 subagent 已登记的实体 id, role: 主体/客体/接收者/帮助者/
        反对者/见证者/地点, narrative_role: 叙事功能, action: 做了什么, emotion: -2..2 整数}。
        四个描述字段均可省略或写偏：role 缺省按实体登记类型取默认（character→主体、
        location→地点、其余→客体），叙事功能近义词自动归一，emotion 越界按边界收敛。
        """
        record = _record_of(subagent, f"participants/{el}")
        normalized_el = _normalize_el(el, record=record)
        target = subagent.event_keys().get(normalized_el)
        if target is None:
            known = "、".join(sorted(subagent.event_keys())) or "（本 subagent 还没有事件）"
            raise _reject(
                f"participants 引用了本 subagent 未构造的事件：{normalized_el}",
                record=record,
                field="el",
                code="unknown_reference",
                expected=f"先用 event(...) 建它，再挂参与者；已构造的 el：{known}",
            )
        normalized_participants = _normalize_participants(items, record=record, book=book)
        characters: list[dict[str, Any]] = []
        for participant in normalized_participants:
            entry: dict[str, Any] = {
                "entityid": namespace_el(book.role, participant.entity_id),
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
        speaker_id: EntityRef | None = None,
        tone: Tone | None = None,
    ) -> _ConstructorCall:
        """判定一条对话候选（candidate_index 取候选表编号）

        verdict: dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选
        （题字、描写被引号包裹等，此时只填 candidate_index/verdict）。
        speaker_id 写本 subagent 已登记的实体 id，判不了就省略；tone 取闭集，没有贴合的用「其他」。
        evidence 是候选所在段落的段首号：not_dialogue 可省略，其余必须给。
        2026-10-02 对齐 0.2.0 写面：candidate_key 订正路径已随订正入口退役。
        """
        record = _record_of(subagent, f"dialogue/{candidate_index}")
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
        normalized_speaker: str | None = None
        normalized_tone: str | None = None
        if normalized_verdict == "not_dialogue":
            if speaker_id is not None or tone is not None:
                raise _reject(
                    "not_dialogue 候选只提交 candidate_index/verdict",
                    record=record,
                    field="verdict",
                    code="invalid_value",
                    expected="speaker_id 与 tone 都省略",
                )
        else:
            if speaker_id is not None:
                normalized_speaker = _require_known_entity_id(
                    book, speaker_id, record=record, field_name="speaker_id"
                )
            if tone is not None:
                normalized_tone = _require_enum(tone, TONE_VALUES, record=record, field_name="tone")
        item = SubagentDialogue(
            candidate_index=candidate_index,
            verdict=normalized_verdict,
            speaker_id=normalized_speaker,
            tone=normalized_tone,
            evidence=normalize_evidence(
                evidence,
                record=record,
                paragraph_text_by_id=book.paragraph_text_by_id,
                required=normalized_verdict != "not_dialogue",
            ),
        )
        args: dict[str, Any] = {"candidate_index": item.candidate_index, "verdict": item.verdict}
        if item.speaker_id is not None:
            args["speaker"] = namespace_el(book.role, item.speaker_id)
        if item.tone is not None:
            args["tone"] = item.tone
        return _ConstructorCall(
            record=record,
            tool="write_dialogue",
            args=args,
            ref={"kind": "dialogue", "candidate_index": item.candidate_index, "verdict": item.verdict},
            commit=lambda: _put_by(
                subagent.dialogues, item, key=lambda current: current.candidate_index
            ),
        )

    def label(paragraph_id: int, emotion: int) -> _ConstructorCall:
        """给一个段落打整段情绪标签（段落号本身就是锚点，不需要引文）

        paragraph_id 取正文段首可见号（每段开头的 `N：` 里的 N）；emotion 为 -2..2 整数分值。
        每章自选 2~3 段，优先选情绪表达有代表性、或语气/标点有区分度的段落。
        同段重写=更新语义。
        """
        record = _record_of(subagent, f"label/{paragraph_id}")
        normalized_id = _require_paragraph_id(
            paragraph_id, record=record, field_name="paragraph_id", paragraph_text_by_id=book.paragraph_text_by_id
        )
        item = SubagentLabel(
            paragraph_id=normalized_id,
            emotion=_require_score(emotion, record=record, field_name="emotion"),
        )
        # 段落标签与章级指标在生产面上同属 write_metrics 一个域（标签是它的 labels 参数），
        # 单独一条标签写不出去，所以这里只落 journal：整章收尾链把三份标签并起来随指标
        # 一次落库（指标缺失时那条兜底记录同样带上标签）。
        return _ConstructorCall(
            record=record,
            ref={"kind": "label", "paragraph_id": item.paragraph_id, "emotion": item.emotion},
            commit=lambda: _put_by(subagent.labels, item, key=lambda current: current.paragraph_id),
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
        record = _record_of(subagent, "metric")
        item = SubagentMetric(
            summary=_require_text(summary, record=record, field_name="summary"),
            emotional_valence=_require_score(emotional_valence, record=record, field_name="emotional_valence"),
            narrative_function=_require_enum(
                narrative_function, NARRATIVE_FUNCTIONS, record=record, field_name="narrative_function"
            ),
            pivot_moment=bool(pivot_moment),
            cliffhanger=bool(cliffhanger),
        )

        def commit() -> None:
            """写入成功后才把本域记录挂到 subagent 上（被拒即整条作废）"""
            subagent.metric = item

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

    def pending(
        kind: str,
        detail: str,
        evidence: int | None = None,
        keys: list[str] | None = None,
    ) -> _ConstructorCall:
        """登记一个你判不了的疑点（keys 写本 subagent 已登记的实体 id 逐条列表）

        kind: unresolved_reference=引用无法解析 / event_continuation=事件疑似与既有事件树
        延续 / case_clue=疑似案例线索 / other。
        case_clue 必须带 evidence（候选/线索所在段落的段首号）。
        2026-10-02 对齐 0.2.0 案例面：case_id 授权随 search_pool 退役，疑点只登记不指向既有案例。
        """
        normalized_kind = _require_enum(kind, PENDING_KINDS, record=_record_of(subagent, "pending"), field_name="kind")
        record = _record_of(subagent, f"pending/{normalized_kind}")
        normalized_keys: list[str] = []
        for raw_key in keys or []:
            normalized_keys.append(
                _require_known_entity_id(book, raw_key, record=record, field_name="keys")
            )
        item = SubagentPending(
            kind=normalized_kind,
            detail=_require_text(detail, record=record, field_name="detail"),
            keys=normalized_keys,
            evidence=normalize_evidence(
                evidence,
                record=record,
                paragraph_text_by_id=book.paragraph_text_by_id,
                required=False,
            ),
        )
        if item.kind == "case_clue" and not item.evidence:
            raise _reject(
                "case_clue 必须带证据段号",
                record=record,
                field="evidence",
                code="missing_evidence",
                expected=f"单个段首可见号整数（正文每段开头的 `N：`，范围 1..{len(book.paragraph_text_by_id)}）",
            )
        entities = subagent.entity_ids()
        description = item.detail

        def commit() -> None:
            """写入成功后才登记这条待决项（被拒即整条作废，与案例池里那条保持一致）"""
            subagent.pending.append(item)

        return _ConstructorCall(
            record=record,
            tool="push_case",
            args={
                "description": truncate_case_description(description),
                # 案例池的 keys 是与实体名匹配的人类可读字符串，这里把本 subagent 的
                # 局部引用键翻成登记名；没有 keys 的疑点用它自己的种类
                "keys": [entities[key].name for key in item.keys if key in entities] or [item.kind],
                "type": PENDING_CASE_TYPES.get(item.kind, "其他疑点"),
            },
            ref={"kind": "pending", "pending_kind": item.kind},
            commit=commit,
        )

    functions = {
        "entity": (entity, "登记本章的一个实体（id=本 subagent 引用键，name 照抄正文写法仅展示）"),
        "relation": (relation, "写一条闭合关系边（两端写本 subagent 已登记的实体 id）"),
        "event": (event, "写一个事件节点（el 根=树键、子=树键/节点键）"),
        "participants": (participants, "把一个事件节点的参与者整体设为 items（entity_id 用本 subagent 实体 id）"),
        "dialogue": (dialogue, "判定一条对话候选（candidate_index+verdict）"),
        "label": (label, "给一个段落打整段情绪标签（段首号）"),
        "metric": (metric, "提交本章摘要与叙事指标（整域一次提交）"),
        "pending": (pending, "登记一个判不了的疑点（keys 写本 subagent 实体 id）"),
    }
    return [(name, functions[name][0], functions[name][1]) for name in _SUBAGENT_CONSTRUCTOR_ORDER]


def build_subagent_finish_tool(subagent: SubagentAnnotation, *, candidate_total: int) -> Any:
    """2026-09-18 用于构造 subagent 面唯一的收尾工具 finish（面上一等工具，不是构造器）

    三个 subagent 的产出由系统在三个 subagent 齐之后统一落库，所以本工具是 subagent 完整性的
    唯一凭据：它只置位与回报，不做校验、不冻结整章（章级冻结由系统在本章收束后做）。
    本工具同时出现在绑定面与 execute_code 的程序目录里——两处同一个对象，
    名字与语义只有一份。
    """

    def _finish() -> str:
        """声明本 subagent 的标注已写完：回执列出各类记录条数、还缺哪些候选判定与指标

        判不了的疑点先用 pending 或 push_case 登记再收尾，别为了收尾去补假数据；
        构造器的写入是即时生效的（收尾不减损已写入的记录），收尾后仍可继续写入。
        """
        subagent.finished = True
        from .subagent_program import subagent_gap

        gap = subagent_gap(subagent, candidate_total=candidate_total)
        return json.dumps(
            {
                "status": "written",
                "record": _record_of(subagent, "finish"),
                "ref": {
                    "role": subagent.role,
                    "finished": True,
                    "counts": subagent.counts(),
                    "unjudged_candidates": gap["missing_candidates"],
                    "candidate_total": candidate_total if subagent.role == "evidence" else 0,
                    "missing_metric": gap["missing_metric"],
                },
            },
            ensure_ascii=False,
        )

    # 说明文本在构造时就去掉源码缩进：本工具既进 execute_code 的目录、又是绑定面的
    # 一等工具，两处读同一份 description（否则同一段话在目录里左对齐、在绑定的
    # schema 里带 8 空格缩进）。
    tool_candidate = StructuredTool.from_function(
        func=_finish,
        name=FINISH_TOOL_NAME,
        description=_dedent_catalog_text(inspect.getdoc(_finish) or ""),
    )
    _forbid_undeclared_args(tool_candidate)
    return tool_candidate
