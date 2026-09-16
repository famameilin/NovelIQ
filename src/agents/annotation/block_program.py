"""章内并行 CodeAct：块代理程序面（局部标注构造器 + 块会话运行器）

设计（章内并行 CodeAct 方案 §3/§4/§8）：
- 块代理对外只有一条工具 execute_code；程序里的"工具"是本模块的局部标注构造器，
  由系统在块自己的命名空间里提供（mention/relation/dialogue/local_event/participant/
  link/label/metric/pending），外加四个只读检索工具（检索绑定块自己的账本）；
- 构造器当场校验并当场生效（写入即生效的块内版本）：evidence 走 NFC 唯一命中核验，
  闭集词表越界、引用未构造的键、缺必填三态，一律记录级结构化拒绝，程序继续跑后面的
  语句——模型在自己会话的轮次内自修，不新增任何升级分支；
- 产出全部落在内存对象（BlockAnnotation）上：块代理**不碰正式账本、不碰事实图写入、
  不碰案例裁决**，因此没有并发写冲突，块完成顺序也不构成任何语义顺序；
- 会话收束 = 模型不再提交程序（没有收尾工具）；撞轮次上限按同一收束处理。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .errors import AnnotationInvariantError, AnnotationRetryableError, AnnotationStageRejection
from .graph import _execute_call
from .local_ir import (
    DIALOGUE_VERDICTS,
    ENTITY_TYPES,
    LINK_KINDS,
    NARRATIVE_FUNCTIONS,
    PARTICIPANT_ROLES,
    PENDING_KINDS,
    RELATION_TYPES,
    RUNTIME_ROLES,
    TONE_VALUES,
    BlockAnnotation,
    LocalDialogue,
    LocalEvent,
    LocalLabel,
    LocalLink,
    LocalMention,
    LocalMetricNote,
    LocalParticipant,
    LocalPending,
    LocalRelation,
    _reject,
    _require_enum,
    _require_key,
    _require_score,
    _require_text,
    normalize_evidence,
)
from .program import (
    BLOCK_CONTRACT_TEXT,
    RestrictedProgramRuntime,
    _call_rejection,
    build_program_tool,
    build_program_tools,
    constructor_api_text,
    render_list_signature,
)
from .prompts import BLOCK_SYSTEM_PROMPT, build_block_program_message
from .schema import ENTITY_TAG_MAX_CHARS, ENTITY_TAG_MAX_COUNT, ChunkParagraphInfo, Confidence
from .tools import AnnotationToolLedger, build_search_tools

if TYPE_CHECKING:
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.agents.stream import AgentStream

# 块内事件的伏笔置信度与正式写入同源（Confidence 三档）
_CONFIDENCE_VALUES: tuple[str, ...] = tuple(member.value for member in Confidence)


@dataclass(slots=True)
class BlockContext:
    """单个块代理会话的输入上下文（annotate 工作流构建一次，重试复用）

    与读者块上下文同构，多带相邻完整段落作为只读边界上下文（判跨块延续用，
    不能作为本块证据锚点）。
    """

    # 0 基块序号（句柄前缀 B{n+1}）
    block_index: int
    block_count: int
    # 运行时子块负 ID（审计与候选提取身份）
    block_chunk_id: int
    block_text: str
    paragraph_info: ChunkParagraphInfo
    # 块内候选序号（1 基）→ 章级候选表序号（1 基；跨块引号无法对齐时为 None）
    candidate_number_map: dict[int, int | None]
    boundary_before: tuple[int, str] | None = None
    boundary_after: tuple[int, str] | None = None


def _record_of(block: BlockAnnotation, key: Any) -> str:
    """用于在校验前先给出记录定位（key 本身可能是非法值）"""
    return f"{block.handle_prefix}:{key}"


def _put(items: list[Any], item: Any) -> None:
    """用于按块内键写入或整体替换（同键重写=更新语义，与正式写入同口径）"""
    for index, existing in enumerate(items):
        if existing.key == item.key:
            items[index] = item
            return
    items.append(item)


def _require_known(value: Any, known: dict[str, Any], *, record: str, field_name: str, label: str) -> str:
    """用于校验引用的是本块已构造的键（未知键给出已知键清单，一次自纠）"""
    text = value if isinstance(value, str) else str(value)
    if text not in known:
        known_list = "、".join(sorted(known)) or "（本块还没有可引用的对象）"
        raise _reject(
            f"{field_name} 引用了本块未构造的{label}：{text}",
            record=record,
            field=field_name,
            code="unknown_reference",
            expected=f"先用构造器建它，再引用它的键；已知键：{known_list}",
        )
    return text


@dataclass(slots=True)
class _ConstructorBook:
    """构造器闭包共用的块态与取值边界（避免每个构造器各自解包一遍）"""

    block: BlockAnnotation
    paragraph_text_by_id: dict[int, str]
    case_number_registry: dict[int, str]
    candidate_total: int

    def mention_keys(self) -> dict[str, LocalMention]:
        """用于取本块已构造的提及表"""
        return self.block.keys_of("mentions")

    def event_keys(self) -> dict[str, LocalEvent]:
        """用于取本块已构造的事件表"""
        return self.block.keys_of("events")


def build_block_constructors(
    block: BlockAnnotation,
    *,
    paragraph_text_by_id: dict[int, str],
    case_number_registry: dict[int, str],
    candidate_total: int,
) -> list[tuple[str, Any, str]]:
    """用于构造块命名空间里的局部标注构造器（返回 (名字, 可调用, 一句话说明) 列表）

    每个构造器当场校验、当场生效，成功返回回执 {status, record, ref}，
    失败抛 AnnotationStageRejection（由运行时翻成记录级拒绝、只废这一条）。
    """
    book = _ConstructorBook(
        block=block,
        paragraph_text_by_id=paragraph_text_by_id,
        case_number_registry=case_number_registry,
        candidate_total=candidate_total,
    )

    def mention(
        key: str,
        name: str,
        entity_type: str,
        evidence: list[dict[str, Any]],
        tags: list[str] | None = None,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造本块的一次实体提及（只是一个提及：没有编号、没有图节点）

        name 用正文里出现的名字；entity_type 是 character/item/location/organization
        （有生命就是 character）。evidence 是本块段落内的逐字引文。同键重写=更新。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
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
        item = LocalMention(
            key=normalized_key,
            name=_require_text(name, record=record, field_name="name"),
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
        _put(block.mentions, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {"kind": "mention", "name": item.name, "entity_type": item.entity_type},
        }

    def relation(
        key: str,
        from_mention: str,
        to_mention: str,
        relation_type: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """构造本块两个提及之间的一条关系（两端都必须是本块已构造的 mention 键）

        relation_type 取闭合关系类型注册表里的值（方向与端点类型约束与正式写入同一张表）。
        正文只说"见面/对峙"这类没有闭合关系可表达的内容，用 link 记事件联系或 pending。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
        known = book.mention_keys()
        normalized_from = _require_known(
            from_mention, known, record=record, field_name="from_mention", label="提及"
        )
        normalized_to = _require_known(to_mention, known, record=record, field_name="to_mention", label="提及")
        item = LocalRelation(
            key=normalized_key,
            from_ref=normalized_from,
            to_ref=normalized_to,
            relation_type=_require_enum(relation_type, RELATION_TYPES, record=record, field_name="relation_type"),
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        _put(block.relations, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {"kind": "relation", "type": item.relation_type},
        }

    def dialogue(
        key: str,
        candidate_index: int,
        verdict: str,
        evidence: list[dict[str, Any]] | None = None,
        speaker: str | None = None,
        tone: str | None = None,
    ) -> dict[str, Any]:
        """判定本块一条对话候选（candidate_index 用本块 <DialogueCandidates> 表里的编号）

        verdict: dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选
        （题字、描写被引号包裹等，此时只填 key/candidate_index/verdict）。
        speaker 是本块已构造的 mention 键，无法确认时省略；tone 取闭合枚举，没有贴合的用「其他」。
        evidence 是候选所在段落的逐字引文：not_dialogue 可省略（候选本身就是锚点），
        真实对话与内心独白必须给（说话人归属要有正文依据）。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
        if (
            isinstance(candidate_index, bool)
            or not isinstance(candidate_index, int)
            or not 1 <= candidate_index <= candidate_total
        ):
            raise _reject(
                f"candidate_index 超出本块候选范围：{candidate_index}",
                record=record,
                field="candidate_index",
                code="out_of_range",
                expected=f"本块候选编号 1..{candidate_total}（用 <DialogueCandidates> 表里的编号）",
            )
        normalized_verdict = _require_enum(
            verdict, DIALOGUE_VERDICTS, record=record, field_name="verdict"
        )
        normalized_speaker: str | None = None
        normalized_tone: str | None = None
        if normalized_verdict == "not_dialogue":
            if speaker is not None or tone is not None:
                raise _reject(
                    "not_dialogue 候选只提交 key/candidate_index/verdict",
                    record=record,
                    field="verdict",
                    code="invalid_value",
                    expected="speaker 与 tone 都省略",
                )
        else:
            if speaker is not None:
                normalized_speaker = _require_known(
                    speaker, book.mention_keys(), record=record, field_name="speaker", label="提及"
                )
            if tone is not None:
                normalized_tone = _require_enum(tone, TONE_VALUES, record=record, field_name="tone")
        item = LocalDialogue(
            key=normalized_key,
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
        _put(block.dialogues, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {"kind": "dialogue", "candidate_index": item.candidate_index, "verdict": item.verdict},
        }

    def local_event(
        key: str,
        description: str,
        evidence: list[dict[str, Any]],
        is_foreshadowing: bool = False,
        confidence: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """构造本块的一个局部事件（扁平：树形结构与跨块归并由章节代理裁决）

        description 是一句话描述。is_foreshadowing=true 表示本块正文把这里写成埋设
        （此时 confidence 必填 high/medium/low）；note 写你对跨块延续的判断线索。
        参与者用 participant(event=本键, ...) 追加。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
        if not isinstance(is_foreshadowing, bool):
            raise _reject(
                "is_foreshadowing 必须是 True/False",
                record=record,
                field="is_foreshadowing",
                code="invalid_value",
                expected="True 或 False",
            )
        normalized_confidence: str | None = None
        if is_foreshadowing:
            if confidence is None:
                raise _reject(
                    "is_foreshadowing=True 时 confidence 必填",
                    record=record,
                    field="confidence",
                    code="missing_field",
                    expected="high / medium / low",
                )
            normalized_confidence = _require_enum(
                confidence, _CONFIDENCE_VALUES, record=record, field_name="confidence"
            )
        elif confidence is not None:
            raise _reject(
                "confidence 只属于伏笔事件（is_foreshadowing=True）",
                record=record,
                field="confidence",
                code="invalid_value",
                expected="非伏笔事件省略 confidence",
            )
        existing = book.event_keys().get(normalized_key)
        item = LocalEvent(
            key=normalized_key,
            description=_require_text(description, record=record, field_name="description"),
            participants=list(existing.participants) if existing is not None else [],
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
            is_foreshadowing=is_foreshadowing,
            confidence=normalized_confidence,
            note=(_require_text(note, record=record, field_name="note") if note is not None else None),
        )
        _put(block.events, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {
                "kind": "event",
                "description": item.description,
                "is_foreshadowing": item.is_foreshadowing,
                "participants": len(item.participants),
            },
        }

    def participant(
        event: str,
        entity: str,
        role: str,
        evidence: list[dict[str, Any]],
        narrative_role: str | None = None,
        action: str | None = None,
        emotion: int | None = None,
    ) -> dict[str, Any]:
        """把一个提及挂成本块某事件的参与者（character 三态必填，非 character 只填 role）

        role 取 主体/客体/接收者/帮助者/反对者/见证者/地点；character 的
        narrative_role/action/emotion 必须同时给出（emotion 为 -2..2 整数）。
        同一事件里同一提及重写=整体替换该条参与者。
        """
        normalized_event = str(event) if not isinstance(event, str) else event
        record = f"{block.handle_prefix}:{normalized_event}"
        known_events = book.event_keys()
        event_key = _require_known(event, known_events, record=record, field_name="event", label="事件")
        known_mentions = book.mention_keys()
        entity_key = _require_known(entity, known_mentions, record=record, field_name="entity", label="提及")
        mention_item = known_mentions[entity_key]
        normalized_role = _require_enum(role, PARTICIPANT_ROLES, record=record, field_name="role")
        is_character = mention_item.entity_type == "character"
        observations = (narrative_role, action, emotion)
        if is_character and not all(value is not None for value in observations):
            raise _reject(
                f"character 参与者 {mention_item.name} 的 narrative_role/action/emotion 必须同时给出",
                record=record,
                field="narrative_role",
                code="missing_field",
                expected="narrative_role（主体/客体/发送者/接收者/帮助者/反对者/见证者）"
                "＋ action（一句话动作）＋ emotion（-2..2 整数）",
            )
        if not is_character and any(value is not None for value in observations):
            raise _reject(
                f"{mention_item.entity_type} 参与者 {mention_item.name} 只填 entity 与 role",
                record=record,
                field="narrative_role",
                code="invalid_value",
                expected="非 character 实体不填 narrative_role/action/emotion",
            )
        participant_item = LocalParticipant(
            entity=entity_key,
            role=normalized_role,
            narrative_role=(
                _require_enum(narrative_role, RUNTIME_ROLES, record=record, field_name="narrative_role")
                if narrative_role is not None
                else None
            ),
            action=(_require_text(action, record=record, field_name="action") if action is not None else None),
            emotion=(_require_score(emotion, record=record, field_name="emotion") if emotion is not None else None),
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        target = known_events[event_key]
        target.participants = [
            existing for existing in target.participants if existing.entity != entity_key
        ] + [participant_item]
        return {
            "status": "written",
            "record": block.handle(event_key),
            "ref": {"kind": "participant", "event": block.handle(event_key), "entity": block.handle(entity_key)},
        }

    def link(
        key: str,
        from_event: str,
        to_event: str,
        kind: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """构造本块两个局部事件之间的一条有正文依据的联系（不自动推导因果）

        kind: succession=顺承 / causality=因果（正文明确说了因为前者所以后者）/
        same_scene=同一场 / parallel=并行。跨块联系不在本块下结论，用 pending 上报。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
        known_events = book.event_keys()
        normalized_from = _require_known(
            from_event, known_events, record=record, field_name="from_event", label="事件"
        )
        normalized_to = _require_known(
            to_event, known_events, record=record, field_name="to_event", label="事件"
        )
        item = LocalLink(
            key=normalized_key,
            from_event=normalized_from,
            to_event=normalized_to,
            kind=_require_enum(kind, LINK_KINDS, record=record, field_name="kind"),
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        _put(block.links, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {"kind": "link", "link_kind": item.kind},
        }

    def label(paragraph_id: int, emotion: int) -> dict[str, Any]:
        """给本块一个段落打整段情绪标签（段落本身就是锚点，不需要 evidence）

        paragraph_id 取 <CurrentBlock> 里 <paragraph id="…"> 的号；emotion 为 -2..2 整数分值。
        本块内值得打标的段落都可以打，最终提交哪几段由章节代理决定。
        """
        record = f"{block.handle_prefix}:label/{paragraph_id}"
        if (
            isinstance(paragraph_id, bool)
            or not isinstance(paragraph_id, int)
            or paragraph_id not in book.paragraph_text_by_id
        ):
            raise _reject(
                f"paragraph_id 不属于本块：{paragraph_id!r}",
                record=record,
                field="paragraph_id",
                code="out_of_range",
                expected="本块段落号：" + "、".join(str(item) for item in sorted(book.paragraph_text_by_id)),
            )
        item = LocalLabel(
            paragraph_id=paragraph_id,
            emotion=_require_score(emotion, record=record, field_name="emotion"),
            evidence=(),
        )
        for index, existing in enumerate(block.labels):
            if existing.paragraph_id == paragraph_id:
                block.labels[index] = item
                break
        else:
            block.labels.append(item)
        return {
            "status": "written",
            "record": block.handle(f"label-{paragraph_id}"),
            "ref": {"kind": "label", "paragraph_id": paragraph_id, "emotion": item.emotion},
        }

    def metric(
        key: str,
        evidence: list[dict[str, Any]],
        summary: str | None = None,
        emotional_valence: int | None = None,
        narrative_function: str | None = None,
        pivot_moment: bool = False,
        cliffhanger: bool = False,
    ) -> dict[str, Any]:
        """给出章级指标的局部依据（本块的摘要要点与情绪基调）

        summary 是本章摘要里属于本块的一句话；emotional_valence 为 -2..2 整数；
        narrative_function 取 冲突/铺垫/转折。至少给 summary 或 emotional_valence 之一。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
        if summary is None and emotional_valence is None and narrative_function is None:
            raise _reject(
                "metric 至少给出 summary 或 emotional_valence 之一",
                record=record,
                field="summary",
                code="missing_field",
                expected="summary（本块摘要）或 emotional_valence（-2..2 整数）",
            )
        item = LocalMetricNote(
            key=normalized_key,
            summary=(_require_text(summary, record=record, field_name="summary") if summary is not None else None),
            emotional_valence=(
                _require_score(emotional_valence, record=record, field_name="emotional_valence")
                if emotional_valence is not None
                else None
            ),
            narrative_function=(
                _require_enum(narrative_function, NARRATIVE_FUNCTIONS, record=record, field_name="narrative_function")
                if narrative_function is not None
                else None
            ),
            pivot_moment=bool(pivot_moment),
            cliffhanger=bool(cliffhanger),
            evidence=normalize_evidence(evidence, record=record, paragraph_text_by_id=book.paragraph_text_by_id),
        )
        _put(block.metric_notes, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {"kind": "metric_note", "summary": item.summary},
        }

    def pending(
        key: str,
        kind: str,
        detail: str,
        evidence: list[dict[str, Any]] | None = None,
        handles: list[str] | None = None,
        case_number: int | None = None,
    ) -> dict[str, Any]:
        """登记一个你判不了、要交给章节代理裁决的待决项

        kind: unresolved_reference=引用无法解析 / event_continuation=事件疑似跨块延续 /
        case_clue=疑似案例线索 / other。
        detail 写清"你在正文里看到什么、为什么判不了"；handles 填相关的块内句柄
        （可写短键，也可写 B2:m1 形态）；case_clue 可用 case_number 带上 search_pool 命中的编号。
        """
        record = _record_of(block, key)
        normalized_key = _require_key(key, record=record)
        normalized_kind = _require_enum(kind, PENDING_KINDS, record=record, field_name="kind")
        normalized_handles: list[str] = []
        for raw_handle in handles or []:
            text = str(raw_handle).strip()
            if not text:
                continue
            normalized_handles.append(text if ":" in text else block.handle(text))
        case_id: str | None = None
        if case_number is not None:
            if isinstance(case_number, bool) or not isinstance(case_number, int):
                raise _reject(
                    "case_number 必须是 search_pool 回执里的整数编号",
                    record=record,
                    field="case_number",
                    code="invalid_value",
                    expected="search_pool 回执的 case_number；没用过检索就省略",
                )
            case_id = book.case_number_registry.get(case_number)
            if case_id is None:
                raise _reject(
                    f"case_number 未由本块 search_pool 授权：{case_number}",
                    record=record,
                    field="case_number",
                    code="unauthorized_case",
                    expected="先用 search_pool 检索拿编号，再原样填回执里的 case_number",
                )
        item = LocalPending(
            key=normalized_key,
            kind=normalized_kind,
            detail=_require_text(detail, record=record, field_name="detail"),
            evidence=normalize_evidence(
                evidence,
                record=record,
                paragraph_text_by_id=book.paragraph_text_by_id,
                required=False,
            ),
            handles=normalized_handles,
            case_id=case_id,
        )
        _put(block.pending, item)
        return {
            "status": "written",
            "record": block.handle(item.key),
            "ref": {"kind": "pending", "pending_kind": item.kind, "case_id": case_id},
        }

    return [
        (
            "mention",
            mention,
            "构造本块的一次实体提及（同名不同身份请用不同 key，绑定由章节代理裁决）",
        ),
        (
            "relation",
            relation,
            "构造两个提及之间的一条闭合关系（两端是已构造的 mention 键）",
        ),
        (
            "dialogue",
            dialogue,
            "判定一条对话候选（candidate_index 用本块候选表编号）",
        ),
        (
            "local_event",
            local_event,
            "构造本块的一个局部事件（扁平；参与者用 participant 追加）",
        ),
        (
            "participant",
            participant,
            "把一个提及挂成本块某事件的参与者（character 三态必填）",
        ),
        (
            "link",
            link,
            "构造本块两个事件之间的一条有正文依据的联系",
        ),
        (
            "label",
            label,
            "给本块一个段落打整段情绪标签",
        ),
        (
            "metric",
            metric,
            "给出章级指标的本块局部依据（摘要要点/情绪基调/叙事功能）",
        ),
        (
            "pending",
            pending,
            "登记你判不了、交给章节代理裁决的待决项",
        ),
    ]


class BlockProgramRuntime(RestrictedProgramRuntime):
    """块代理程序面：局部标注构造器 + 块自己的只读检索（写不出去任何正式记录）

    生命周期：一个块会话建一次、跨回合复用（变量、句柄引用与逐 op 记录随之保留）。
    检索调用与写者面走同一条单条事务边界（_execute_call），构造器调用走同一份逐 op
    记录口径，因此块面审计与写者面同一套字段。
    """

    contract_text = BLOCK_CONTRACT_TEXT

    def __init__(
        self,
        query_service: Any,
        ledger: AnnotationToolLedger,
        block: BlockAnnotation,
        *,
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """用于绑定块账本、块内中间表示与审计/事件出口"""
        paragraph_info = ledger.paragraph_info
        if paragraph_info is None:
            raise AnnotationInvariantError("块程序面需要段落坐标映射，paragraph_info 缺失")
        paragraph_text_by_id = dict(zip(paragraph_info.paragraph_ids, paragraph_info.texts, strict=True))
        entries = build_block_constructors(
            block,
            paragraph_text_by_id=paragraph_text_by_id,
            case_number_registry=ledger.case_number_registry,
            candidate_total=len(ledger.dialogue_candidates),
        )
        search_tools = build_program_tools(build_search_tools(query_service, ledger))
        namespace: dict[str, Any] = {str(tool.name): tool for tool in search_tools}
        namespace.update({name: function for name, function, _ in entries})
        super().__init__(search_tools, namespace, observer=observer, stream=stream)
        self.ledger = ledger
        self.block = block
        self.api_entries = entries
        self._constructor_names = frozenset(name for name, _, _ in entries)
        self._paragraph_text_by_id = paragraph_text_by_id
        # 候选总数给 dialogue 构造器做越界校验（块内切片的口径与读者面一致）
        self._candidate_total = len(ledger.dialogue_candidates)

    def build_tool(self) -> Any:
        """用于构造本块的唯一对外工具 execute_code（构造器目录 + 检索目录同轮下发）"""
        return build_program_tool(self, extra_api=constructor_api_text(self.api_entries) + "\n\n")

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """用于分发一次程序内调用：构造器走记录级校验，检索走单条事务边界"""
        if name in self._constructor_names:
            return await self._run_constructor(name, args, line=line)
        return await self._run_search(name, args, line=line)

    async def _run_constructor(self, name: str, args: dict[str, Any], *, line: int | None) -> dict[str, Any]:
        """用于执行一次构造器调用（业务失败只登记该条，程序继续跑后面的语句）"""
        op_index = self._next_op_index(line=line)
        started_ns = time.perf_counter_ns()
        status = "success"
        error: str | None = None
        try:
            receipt = self.tools[name](**args)
        except AnnotationInvariantError:
            raise
        except Exception as exc:
            receipt = _call_rejection(name, exc, signature_hint=self._signature_hint(name))
            status = "error"
            error = str(exc)
        else:
            self.refs[str(receipt["record"])] = receipt.get("ref") or {}
        self._log_op(
            name,
            op_index=op_index,
            line=line,
            status=status,
            receipt=receipt,
            call_args=args,
            error=error,
        )
        self._record_audit(
            name,
            args=args,
            receipt=receipt,
            status=status,
            error=error,
            started_ns=started_ns,
            op_index=op_index,
        )
        return receipt

    async def _run_search(self, name: str, args: dict[str, Any], *, line: int | None) -> dict[str, Any]:
        """用于把一次检索调用交给生产单条事务边界（与写者面同一份实现与审计）"""
        op_index = self._next_op_index(line=line)
        entry = await _execute_call(
            {"name": name, "args": args, "id": f"{self._program_id}-op{op_index}"},
            tool_map=self.execution_tools,
            ledger=self.ledger,
            observer=self.observer,
            stream=self.stream,
            call_index=self._next_call_index(),
            program_meta={
                "program_id": self._program_id,
                "op_index": op_index,
                "source_line": line,
                "record": None,
                "direct_fallback": False,
            },
        )
        raw_call = entry.get("call")
        call_args: dict[str, Any] = dict(raw_call.get("args") or {}) if isinstance(raw_call, dict) else {}
        self._log_op(
            name,
            op_index=op_index,
            line=line,
            status=str(entry.get("status") or "error"),
            receipt=entry.get("receipt"),
            call_args=call_args,
        )
        return entry.get("receipt") or {}

    def _signature_hint(self, name: str) -> str:
        """用于在参数名写错时把构造器签名原样回给模型（自纠不需要猜）"""
        for entry_name, function, _ in self.api_entries:
            if entry_name == name:
                return render_list_signature(name, function)
        return name

    def _record_audit(
        self,
        name: str,
        *,
        args: dict[str, Any],
        receipt: dict[str, Any],
        status: str,
        error: str | None,
        started_ns: int,
        op_index: int,
    ) -> None:
        """用于把构造器调用写进 agent_tool_calls（与写者面同一套字段）"""
        if self.observer is None:
            return
        request_args = dict(args)
        request_args["_program"] = {
            "program_id": self._program_id,
            "op_index": op_index,
            "source_line": None,
            "record": receipt.get("record"),
            "direct_fallback": False,
        }
        self.observer.record_tool_call(
            call_index=self._next_call_index(),
            tool_name=name,
            request_args=request_args,
            raw_args=None,
            response=receipt,
            receipt=receipt,
            status=status,
            error=error,
            tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
            started_ns=started_ns,
        )


@dataclass(slots=True)
class BlockRunOutcome:
    """一次块会话的产出（局部标注 + 授权足迹，后者必须并入章级审计）"""

    block: BlockAnnotation
    final_messages: list[BaseMessage]
    authorized_text_paragraph_ids: set[int]
    authorized_chapter_ids: set[int]
    authorized_event_ids: set[str]
    authorized_tree_ids: set[str]
    # 块内 search_pool 命中过的案例 id（编号是会话局部的，跨面只传 id）
    case_ids: set[str]


async def run_block_agent(
    *,
    run_id: str,
    chapter_id: int,
    context: BlockContext,
    query_service_factory: Any,
    session_factory: Any,
    llm: Any,
    graph_state: Any | None = None,
    stream: AgentStream | None = None,
    audit_recorder: AgentAuditRecorder | None = None,
    chapter_label: str | None = None,
    novel_id: str = "default",
    attempt_number: int = 1,
) -> BlockRunOutcome:
    """用于运行单个块的 CodeAct 会话（产出局部标注，不写正式账本）

    块代理绝不触碰 FactGraph 的章节生命周期（begin/reset/drain 全归章节会话调用链），
    也绝不产生任何正式写入：它的全部产出是内存里的 BlockAnnotation。
    会话收束 = 模型不再提交程序；撞轮次上限按同一收束处理。
    会话结束时复核块内引用闭合，悬空引用即块失败（整章走既有失败路径）。
    """
    from src.agents.annotation.graph import build_block_graph
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
        task_type="annotation_block",
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
        task_type="annotation_block",
        call_type="agent",
        model_name=model_name or "unknown",
        model_provider=model_provider,
    )
    block = BlockAnnotation(
        block_index=context.block_index,
        block_chunk_id=context.block_chunk_id,
        block_text=context.block_text,
    )
    try:
        # 2026-09-16 连接粒度：块会话不再自开只读会话，查询服务按单次工具调用取还连接
        query_service = query_service_factory(session_factory)
        ledger = AnnotationToolLedger(
            run_scope=run_id,
            current_chapter_id=chapter_id,
            current_chunk_id=context.block_chunk_id,
            current_chunk_text=context.block_text,
            allow_future_context=settings.models.annotation.allow_future_context,
            graph=graph_state,
            paragraph_info=context.paragraph_info,
            current_chapter_order=getattr(query_service, "current_chapter_order", None),
        )
        runtime = BlockProgramRuntime(query_service, ledger, block, observer=observer, stream=stream)
        program_tool = runtime.build_tool()
        graph = build_block_graph(
            llm,
            program_tool,
            ledger=ledger,
            max_iterations=max(1, settings.models.annotation.max_iterations),
            stream=stream,
            observer=observer,
            retries=settings.models.annotation.total_attempts,
        )
        first_messages: list[BaseMessage] = [
            SystemMessage(content=BLOCK_SYSTEM_PROMPT),
            HumanMessage(
                content=build_block_program_message(
                    block_number=context.block_index + 1,
                    block_total=context.block_count,
                    paragraph_info=context.paragraph_info,
                    boundary_before=context.boundary_before,
                    boundary_after=context.boundary_after,
                    candidates=ledger.dialogue_candidates,
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
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        if isinstance(exc, AnnotationRetryableError):
            raise
        raise AnnotationRetryableError(f"块会话失败（块 {context.block_index + 1}）: {exc}") from exc
    error = result_state.get("error")
    if error:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(error))
        raise AnnotationRetryableError(f"块会话失败（块 {context.block_index + 1}）: {error}")
    try:
        block.validate()
    except AnnotationStageRejection as exc:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        raise AnnotationRetryableError(f"块局部标注非法（块 {context.block_index + 1}）: {exc}") from exc
    recorder.finish_invocation(invocation_id, status="success")
    return BlockRunOutcome(
        block=block,
        final_messages=list(result_state["messages"]),
        authorized_text_paragraph_ids=set(ledger.authorized_text_paragraph_ids),
        authorized_chapter_ids=set(ledger.authorized_chapter_ids),
        authorized_event_ids=set(ledger.authorized_event_ids),
        authorized_tree_ids=set(ledger.authorized_tree_ids),
        case_ids=set(ledger.case_number_registry.values()),
    )


def render_block_index(blocks: list[BlockAnnotation]) -> str:
    """用于把各块的紧凑对象索引渲染成章节代理首条请求里的 <BlockAnnotations> 区块"""
    sections: list[str] = []
    for block in blocks:
        sections.append(
            f'<BlockAnnotation block="{block.block_index + 1}">\n'
            f"{json.dumps(block.index(), ensure_ascii=False, indent=1)}\n"
            "</BlockAnnotation>"
        )
    return "\n".join(sections)


__all__ = [
    "BlockContext",
    "BlockProgramRuntime",
    "BlockRunOutcome",
    "build_block_constructors",
    "render_block_index",
    "run_block_agent",
]
