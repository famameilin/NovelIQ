"""事件与参与者的结构化提交，引用换算与正式写入由引擎完成"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Annotated, Any, Self

from langchain_core.tools import StructuredTool
from pydantic import Field, StrictInt, ValidationError, WithJsonSchema, field_validator, model_validator

from src.event_trees.program_contract import (
    PROGRAM_MAX_CODE_CHARS,
    ProgramFault,
    ProgramRuntimeSurface,
)
from src.event_trees.vocabulary import (
    _EVENT_ONLY_ROLE_WORDS,
    EventChildType,
    EventParticipantRole,
    normalize_event_participant_role,
)
from src.fact_graph.schema import (
    Confidence,
    EntityType,
    RoleFunction,
    StrictModel,
    normalize_semantic_text,
)
from src.fact_graph.vocabulary import (
    _TONE_CHINESE_WORDS,
    clamp_emotion_score,
    normalize_role_function,
)

SUBMIT_EVENTS_TOOL_NAME = "submit_events"


class EvidencePosition(StrictModel):
    """本章原文位置，提交段首可见号与可选逐字引文，不提交全局 ID、哈希或 source_ref"""

    paragraph_id: StrictInt = Field(description="本章正文段首可见号")
    quote: str | None = Field(default=None, min_length=1, description="逐字原文；省略时引用整段")
    occurrence: StrictInt = Field(default=1, ge=1, description="同段相同引文第几次出现，从 1 开始")


class ParticipantSubmission(StrictModel):
    """按正文名称提交参与者；2026-10-04 合同放开：字段可省略或写偏，非 character 只填 role

    与正式参与者校验同一口径：role/narrative_role/emotion 缺省或写偏由引擎归一
    （role 未知词交写入点按实体登记类型给默认、叙事功能近义词归一、情绪分值钳制），
    拒绝面只留字段误用（非 character 携带三态、地点角色配非 location 实体、
    事件角色词写进叙事功能、语气词写进情绪分值）。
    """

    name: str = Field(min_length=1, description="正文实体名称，不归并别名，不填写实体 ID")
    entity_type: EntityType
    role: EventParticipantRole | None = Field(
        default=None,
        description=(
            "参与角色：主体/客体/接收者/帮助者/反对者/见证者/地点（地点作为参与者角色）；"
            "可省略，缺省按实体登记类型取（character→主体、location→地点、其余→客体）；"
            "地点只用于 location，organization 作为群体按行动填主体/客体等，不填地点"
        ),
    )
    narrative_role: RoleFunction | None = Field(
        default=None,
        description="character 参与者的人物叙事功能：主体/客体/发送者/接收者/帮助者/反对者/见证者；"
        "可省略，近义词自动归一；非 character 必须省略本字段",
    )
    action: str | None = Field(
        default=None, min_length=1,
        description="character 参与者的一句话动作概括（不超过 15 字）；可省略；非 character 必须省略",
    )
    emotion: int | None = Field(
        default=None,
        ge=-2,
        le=2,
        description="character 参与者动作伴随的情绪分值 -2..2；可省略，越界按边界收敛；非 character 必须省略",
    )
    evidence: EvidencePosition | None = Field(default=None, description="实体原文位置，省略时沿用事件证据")

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> object:
        """用于把参与角色词归一到闭集（未收录交写入点按实体登记类型给默认）"""
        return normalize_event_participant_role(value)

    @field_validator("narrative_role", mode="before")
    @classmethod
    def _normalize_narrative_role(cls, value: object) -> object:
        """用于阻止事件专属角色词进入人物功能字段，其余近义词归一（未收录收敛为主体）"""
        if isinstance(value, str) and value.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise ValueError(
                "narrative_role 不接受 "
                f"{value.strip()}：地点、行动者等只用于 role 字段；"
                "人物功能使用 主体/客体/发送者/接收者/帮助者/反对者/见证者"
            )
        return normalize_role_function(value)

    @field_validator("emotion", mode="before")
    @classmethod
    def _normalize_emotion(cls, value: object) -> object:
        """用于阻止对话语气词进入人物情绪分值字段，数值越界按边界钳制"""
        if isinstance(value, str) and value.strip() in _TONE_CHINESE_WORDS:
            raise ValueError(
                f"emotion 不接受 {value.strip()}：该字段是整数分值 -2..2"
                "（-2 强烈负面 … 2 强烈正面），语气词是对话 tone 字段的取值"
            )
        return clamp_emotion_score(value)

    @model_validator(mode="after")
    def validate_states(self) -> Self:
        """与正式参与者校验保持同一口径：字段误用仍拒，缺省/写偏交给写入点缺省与归一"""
        self.name = normalize_semantic_text(self.name, label="participant.name")
        given = [value is not None for value in (self.narrative_role, self.action, self.emotion)]
        if self.entity_type != "character" and any(given):
            fields = {key: getattr(self, key) for key in ("narrative_role", "action", "emotion")
                      if getattr(self, key) is not None}
            raise ValueError(
                f"参与者 {self.name} entity_type={self.entity_type}，实际人物字段={fields}；"
                "narrative_role/action/emotion 只属于 character，删除这些字段，保留 name/entity_type/role"
            )
        if self.role == EventParticipantRole.LOCATION and self.entity_type != "location":
            raise ValueError(
                f"参与者 {self.name} entity_type={self.entity_type}，实际 role=地点；"
                "地点角色必须使用 location 实体；保持真实实体类型，按行动改填主体/客体/接收者/帮助者/反对者/见证者"
            )
        return self


class EventSubmission(StrictModel):
    """根事件省略 root_id/type；子事件填树根 id 与 main/secondary，树内先后按数组顺序"""

    id: str = Field(min_length=1, max_length=64, description="自定稳定键，修复时沿用；无需拼树路径")
    root_id: str | None = Field(
        default=None, min_length=1,
        description="子事件所属树根的自定 id；根事件省略，不能填写 batch_* 生产记录键",
    )
    type: EventChildType | None = Field(default=None, description="子事件必填 main/secondary，根事件不填")
    description: str = Field(min_length=1)
    evidence: EvidencePosition
    participants: list[ParticipantSubmission] | None = Field(
        default=None, min_length=1, max_length=30, description="提供时为完整非空集合；省略时保留已有参与者",
    )
    isforeshadowing: bool = False
    confidence: Confidence | None = None

    @field_validator("root_id")
    @classmethod
    def validate_root_reference(cls, value: str | None) -> str | None:
        """生产键已完成哈希换算，不能再次当作提交 id 哈希成一个永远等不到根的桶"""
        if value is not None and re.match(r"^(?:[a-z_]+/event/|[a-z_]+:)?batch_", value.strip()):
            raise ValueError(f"root_id={value!r} 是 batch_* 生产记录键；root_id 只接受根事件的自定 id")
        return value

    @model_validator(mode="after")
    def validate_tree_fields(self) -> Self:
        """结构化入口保留根与子节点的业务约束"""
        if self.root_id is None:
            if self.type is not None:
                raise ValueError("根事件不填 type")
            if self.isforeshadowing and self.confidence is None:
                raise ValueError("伏笔根事件必须提供 confidence")
        else:
            if self.root_id == self.id:
                raise ValueError("子事件的 root_id 不能指向自身")
            if self.type is None:
                raise ValueError("子事件必须提供 type=main/secondary")
            if self.isforeshadowing or self.confidence is not None:
                raise ValueError("伏笔属性只属于根事件")
        participants = self.participants or []
        if len({participant.name for participant in participants}) != len(participants):
            raise ValueError("同一事件的参与者名称不能重复")
        return self


def _event_item_schema() -> dict[str, Any]:
    """从正式提交模型生成目录，展开引用后交给逐项校验入口"""
    schema = EventSubmission.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].removeprefix("#/$defs/")])
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return expand(schema)


EventBatchItem = Annotated[Any, WithJsonSchema(_event_item_schema())]


class EventBatchInput(StrictModel):
    """逐项校验事件，坏项不阻止同批其他事件写入"""

    # schema 仍展示完整字段，校验移到逐项边界，避免一个坏项拒绝整个数组
    events: list[EventBatchItem] = Field(min_length=1, max_length=50)


def _local_key(value: str) -> str:
    return "batch_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class EventSubmissionEngine:
    """复用现有单条写入、回滚与审计，不另建正式数据写入链"""

    def __init__(self, runtime: ProgramRuntimeSurface) -> None:
        self.runtime = runtime
        self.ledger = runtime.ledger
        self.subagent = getattr(runtime, "subagent", None)
        self.results: dict[int, dict[str, Any]] = {}
        self._references: dict[tuple[int, str | None, int], dict[str, Any]] = {}

    async def _call(self, name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
        self.runtime._guard()
        receipt = await self.runtime._dispatch(name, args, line=None)
        if self.runtime.ops[-1]["status"] != "success":
            result.setdefault("failed", []).append({
                key: receipt[key] for key in ("record", "field", "actual", "code", "expected", "message", "error")
                if key in receipt
            })
            result["status"] = "failed"
            return None
        return receipt

    def _reject(
        self, result: dict[str, Any], *, field: str, message: str, code: str = "invalid_value", actual: Any = None,
    ) -> None:
        started_ns = time.perf_counter_ns()
        op = self.runtime._next_op_index(line=None)
        receipt = {
            "status": "rejected", "record": f"submission/{result['id']}", "field": field,
            "code": code, "actual": actual, "expected": message, "message": message,
        }
        self.runtime._log_op(SUBMIT_EVENTS_TOOL_NAME, op_index=op, line=None, status="error", receipt=receipt)
        self.ledger.errors.append(message)
        # 逐项拒绝也进入内层审计，不能让外层批提交成功掩盖错误率
        if self.runtime.observer is not None:
            self.runtime.observer.record_tool_call(
                call_index=self.runtime._next_call_index(),
                tool_name=SUBMIT_EVENTS_TOOL_NAME,
                request_args={"id": result["id"], "_program": {
                    "program_id": self.runtime._program_id, "op_index": op, "source_line": None,
                    "record": receipt["record"], "direct_fallback": False,
                }},
                response=receipt,
                receipt=receipt,
                status="error",
                error=message,
                tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
                started_ns=started_ns,
            )
        result.setdefault("failed", []).append(receipt)
        result["status"] = "failed"

    async def _read(self, position: EvidencePosition, result: dict[str, Any]) -> dict[str, Any] | None:
        key = (position.paragraph_id, position.quote, position.occurrence)
        if key not in self._references:
            receipt = await self._call("read_chapter_text", position.model_dump(), result)
            if receipt is None:
                return None
            self._references[key] = receipt
        return self._references[key]

    async def _anchor(self, record: str, reference: dict[str, Any], result: dict[str, Any]) -> bool:
        return await self._call("anchor_record", {
            "record_id": record, "source_ref": reference["source_ref"],
        }, result) is not None

    async def _participant(
        self, participant: ParticipantSubmission, evidence: EvidencePosition, result: dict[str, Any],
    ) -> dict[str, Any] | None:
        reference = await self._read(participant.evidence or evidence, result)
        if reference is None:
            return None
        known = self.ledger.written_entities.get(participant.name)
        if known is not None and str(known.entity_type) != str(participant.entity_type):
            self._reject(
                result, field="participants.entity_type", message=f"{participant.name} 已登记为 {known.entity_type}",
            )
            return None
        key = _local_key("entity:" + participant.name)
        args: dict[str, Any] = {"name": participant.name, "entity_type": participant.entity_type}
        if self.subagent is not None:
            existing = next((item for item in self.subagent.entities if item.name == participant.name), None)
            if existing is not None:
                key = existing.id
            args.update(id=key, evidence=(participant.evidence or evidence).paragraph_id)
            tool_name = "entity"
        else:
            args["el"] = key
            tool_name = "write_entity"
        receipt = await self._call(tool_name, args, result)
        if receipt is None or not await self._anchor(receipt["record"], reference, result):
            return None
        item: dict[str, Any] = {"entity_id" if self.subagent is not None else "entityid": key, "role": participant.role}
        # 2026-10-04 合同放开：三态字段给了才携带（缺省交写入点按空处理），不再按类型整组搬运
        for field_name in ("narrative_role", "action", "emotion"):
            value = getattr(participant, field_name)
            if value is not None:
                item[field_name] = value
        return item

    async def _event(self, event: EventSubmission, result: dict[str, Any]) -> None:
        reference = await self._read(event.evidence, result)
        if reference is None:
            return
        participants = []
        for participant in event.participants or []:
            item = await self._participant(participant, event.evidence, result)
            if item is None:
                return
            participants.append(item)
        key = _local_key("event:" + event.id)
        if event.root_id is not None:
            key = _local_key("event:" + event.root_id) + "/" + key
        args: dict[str, Any] = {
            "el": key, "isroot": event.root_id is None, "description": event.description,
            "evidence": event.evidence.paragraph_id,
        }
        if event.root_id is None:
            args.update(isforeshadowing=event.isforeshadowing, confidence=event.confidence)
        else:
            args["type"] = event.type
        if self.subagent is None and event.participants is not None:
            args["characters"] = participants
        receipt = await self._call("event" if self.subagent is not None else "write_event", args, result)
        if receipt is None:
            return
        result["record"] = receipt["record"]
        # 2026-10-04 树键校验下沉：子事件先于树根提交时账本挂起（根建好后按到达序冲账），
        # 不再整项判拒；participants/anchor 留给建根后的重提（waiting 项按工具说明可重提）。
        # 判据用账本挂起缓冲：solo 面回执本就是生产键；lane 面回执是 IR 键，先翻译再比对
        production_record = self.ledger.production_record_key(str(receipt["record"]))
        if event.root_id is not None and self.ledger.is_pending_child(production_record):
            result["status"] = "waiting"
            result["note"] = f"树根 {event.root_id} 尚未写入：该子事件已挂起，根建好后自动生效，重提亦可"
            return
        if self.subagent is not None and participants:
            if await self._call("participants", {"el": key, "items": participants}, result) is None:
                return
        if await self._anchor(receipt["record"], reference, result):
            result["status"] = "written"

    async def execute(self, items: list[Any]) -> None:
        """先建立树根，再按提交顺序写子事件；每项保留自己的失败路径"""

        encoded = json.dumps([
            item.model_dump(mode="json") if isinstance(item, EventSubmission) else item for item in items
        ], ensure_ascii=False)
        if len(encoded) > PROGRAM_MAX_CODE_CHARS:
            raise ProgramFault("结构化提交超过程序字符上限", code="program_too_large")
        proposals: list[tuple[int, EventSubmission]] = []
        roots: dict[str, list[int]] = {}
        seen: set[str] = set()
        for index, raw in enumerate(items):
            self.results[index] = {"id": raw.id if isinstance(raw, EventSubmission) else (
                str(raw.get("id") or f"#{index + 1}") if isinstance(raw, dict) else f"#{index + 1}"
            ), "status": "waiting"}
            if (isinstance(raw, EventSubmission) and raw.root_id is None) or (
                isinstance(raw, dict) and raw.get("root_id") is None
            ):
                roots.setdefault(self.results[index]["id"], []).append(index)
        for index, raw in enumerate(items):
            self.runtime._guard()
            result = self.results[index]
            try:
                event = EventSubmission.model_validate(raw)
            except ValidationError as exc:
                issue = exc.errors(include_url=False, include_context=False)[0]
                path = ".".join(str(part) for part in issue["loc"])
                self._reject(
                    result, field=f"events[{index}]" + (f".{path}" if path else ""),
                    message=issue["msg"], actual=issue.get("input"),
                )
                continue
            if event.id in seen:
                self._reject(result, field=f"events[{index}].id", message="同批事件 id 不能重复", actual=event.id)
                continue
            seen.add(event.id)
            proposals.append((index, event))
        for index, event in [item for item in proposals if item[1].root_id is None] + [
            item for item in proposals if item[1].root_id is not None
        ]:
            if event.root_id in roots and not any(
                self.results[root_index]["status"] == "written" for root_index in roots[event.root_id]
            ):
                # 同批根失败不能转成合法暂挂；阻断依赖项也不能登记实体或污染待补根缓冲
                self._reject(
                    self.results[index], field=f"events[{index}].root_id", code="dependency_failed",
                    actual=event.root_id,
                    message=f"同批树根 submission/{event.root_id} 写入失败；先修复树根，再重提该子事件",
                )
                continue
            await self._event(event, self.results[index])


def build_event_submission_tool(runtime: ProgramRuntimeSurface) -> Any:
    """为章级与子代理提供同一结构化入口，减少模型手写引用和调用程序"""
    async def submit_events(events: list[Any]) -> str:
        engine = EventSubmissionEngine(runtime)
        body = json.loads(await runtime._execute_program(lambda: engine.execute(events)))
        body["items"] = list(engine.results.values())
        return json.dumps(body, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=submit_events,
        name=SUBMIT_EVENTS_TOOL_NAME,
        args_schema=EventBatchInput,
        description=(
            "直接调用本工具批量提交事件与参与者的数据，不能在 execute_code 程序里调用。"
            "优先使用本工具完成事件域：提交正文位置、实体名称与人物三态（三态与 role 均可省略或写偏，"
            "引擎按实体登记类型给缺省、近义词归一、情绪分值钳制）；"
            "非 character 省略 narrative_role/action/emotion，只有 location 可以填 role=地点，"
            "organization 按群体行动填主体/客体等，不能因活动发生在组织驻地就填地点。"
            "引擎建立局部键、先建树根、换算原文坐标、登记参与者并绑定证据，不需要编写程序或构造 source_ref。"
            "树内先后按数组顺序；同 id 重提按现有写入规则更新。items 只回成功键和失败/等待项："
            "等待=子事件先于树根提交，已挂起待建根自动生效，重提亦可；同批根失败的子事件直接报告 dependency_failed。"
            "失败项修复取值后仅重提失败或等待的 id，"
            "成功项不用重写；其余标注域使用 execute_code。"
        ),
    )
