"""章内三代理并发：单个 subagent 的程序面（八类构造器 + 完整工具面 + subagent 会话运行器）

设计（《章内多代理重设计-三代理并发版》§3/§3.1/§4）：

- **三个 subagent 的模型可见面完全相同（不按域裁剪）**：只有 `execute_code` 与 `finish`
  两项（八类构造器、检索四项、案例五项全装在 execute_code 的 description 里）。
  域分工只写在职责文案里，不通过拿掉工具或构造器实现——依据是 run c80105cc 的实测
  （工具按域渐进解锁时，模型在多个回合反复确认能力缺口，67% 思考落在锁定轮，
  锁定轮只发 14% 调用）。
- **构造器写入生效**（2026-09-18）：构造器只做校验与写参构造，运行时立即把这笔写入交给
  生产单条事务边界（`graph._execute_call`，与写者面同一个实现）——成功才落 journal、
  才回 `{status:"written", record, ref}`；被拒的那一条只作废自己（journal 不动，
  模型拿到 record/field/code/expected 当场自纠，程序继续跑后面的语句）。
  实体/事件的落库 el 按角色命名空间化（`角色:局部键`，见 namespace_el），
  所以三个 subagent 各自的 a1/t1 互不占用；同名实体由生产写入自己会合。
- **subagent 之间共享章级账本**（同一个 AnnotationToolLedger、同一份工具表）：
  案例 id 全章唯一、检索工具当轮即可看到别的 subagent 刚落库的实体与案例，
  授权足迹也不再需要落库相位搬运。
- 收束 = 模型不再提交程序；`finish` 只声明本 subagent 完毕并回显还缺什么，
  撞轮次上限按同一收束处理。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from loguru import logger

from .errors import AnnotationInvariantError, AnnotationRetryableError
from .graph import _execute_call
from .program import (
    _READ_TOOL_NAMES,
    PROGRAM_TOOL_NAME,
    SUBAGENT_CONTRACT_TEXT,
    RestrictedProgramRuntime,
    _call_rejection,
    _dedent_catalog_text,
    build_program_tool,
    build_program_tools,
    call_parameters,
    constructor_call_entries,
    render_list_signature,
)
from .prompts import SUBAGENT_ROLE_SCOPES, SUBAGENT_SYSTEM_PROMPT, build_subagent_gap_message, build_subagent_message
from .schema import (
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    FORESHADOWING_ACTIONS,
    RELATION_CHANGE_KIND_LABELS,
    Confidence,
    DialogueVerdict,
    EntityRef,
    EntityType,
    EventChildType,
    NarrativeFunction,
    RelationChangeKindArg,
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
    PARTICIPANT_ROLES,
    PENDING_CASE_TYPES,
    PENDING_KINDS,
    RELATION_TYPES,
    RESERVED_ROOT_KEY,
    RUNTIME_ROLES,
    SUBAGENT_ROLES,
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
from .tools import FINISH_TOOL_NAME, AnnotationToolLedger, _forbid_undeclared_args

if TYPE_CHECKING:
    pass

# 三个 subagent 的名字（多块章三条并发；单块章走 runner 的 agent 路径）：单源在
# subagent_ir（prompts 的职责范围文案按同一份角色名建表），本模块只转出
# subagent 的展示名（职责文案与日志共用）
SUBAGENT_ROLE_LABELS: dict[str, str] = {
    "structure": "实体与关系",
    "event": "事件与参与者",
    "evidence": "对话与章级证据",
}

# 三个 subagent 在 execute_code 程序面里的工具目录（检索 4 + 案例 3）。顺序与分组只影响
# 模型可见目录的排列，三个 subagent 拿到的是同一份；正式写入工具与章级 finish 都不在其中
# （subagent 写不出去任何正式记录）。
SUBAGENT_TOOL_NAMES: tuple[str, ...] = (
    "search_graph",
    "search_text",
    "search_event",
    "search_pool",
    "push_case",
    "promise_case",
    "close_case",
)

# 2026-09-18 subagent 的模型可见面（绑定面）：只有程序入口与收尾两件，与写者面逐字同名。
SUBAGENT_BOUND_TOOL_NAMES: tuple[str, ...] = (PROGRAM_TOOL_NAME, FINISH_TOOL_NAME)

# 2026-09-18 本面的引用与证据口径（渲染在构造器目录之前，全局定义一次）。
# 为什么必须有这一块：构造器的实体引用走 _require_known_entity_id，只认"本 subagent 登记过的
# id"；而正式工具的 docstring 教的是"填 run 级 id 或本章 的 el 键"（写者面真的收这两者）。
# 两面共用一份 tools.py 文案，subagent 程序面若照抄就会教错——模型按外部 id 写
# relation(from_id=<id>) 只会连吃 unknown_reference 拒绝。
_SUBAGENT_REFERENCE_SCOPE_TEXT: str = (
    "引用与证据口径：\n"
    "- 实体引用（relation 的 from_id/to_id、participants 的 entity_id、dialogue 的 speaker_id、"
    "pending 的 keys）写你在本 subagent 用 entity() 登记过的 id；别名、称号分别登记成不同 id。\n"
    "- 证据（evidence、paragraph_id）写正文段首可见号：每段开头的 `N：` 里的 N，一个整数即可，"
    "服务端按号取段、不需要抄原文；号码越界会被拒并回报合法号范围。\n"
    "- 案例调用指向的是产出记录：push_case(record_id=...) 与 promise_case(result_id=...) 都写"
    "写入回执里的 record 原值（照抄，不要自己拼）：实体形如 structure/entity/a1、事件形如 "
    "event/t1、对话形如 evidence/dialogue/…，且必须是本章已经写出来的记录——"
    "语义改动由那条记录自己承担，案例只记账。\n\n"
)

# 2026-09-18 本面目录说明覆盖表：只列 native docstring 在本面会教错的工具。
# search_graph 教"实体引用一律填 run 级 id 或 el 键"（本面构造器只收
# 本 subagent 登记的 id，案例工具收的是产出记录键，run 级 id/el 在本面没有参数收）；
# search_event 教"因果前驱填 tree_id"（本面没有因果前驱参数：伏笔续接/回收由 event() 的
# foreshadowing_action + root_event_id 表达）。未列出的工具仍以工具对象为单一事实源。

SUBAGENT_TOOL_COPY: dict[str, str] = {
    "search_graph": (
        "按实体名查询图节点及其一跳邻域（相连的边与邻居节点）\n\n"
        "matches 是命中的实体，neighbors 是它们的邻居，relations 是两端都在结果里的边；"
        "matches/neighbors 都带 run 级 id，供你对照检索结果读，"
        "但本面没有任何参数收外部 id：实体引用一律写你在本 subagent 登记过的 id"
        "（见上方的引用与证据口径）。"
    ),
    "search_event": (
        "按关键词检索已完成章节的事件树，树根直接按回执里的 id 引用\n\n"
        "检索范围为树内任意节点的描述与参与者；查询支持多关键词（空格/标点分隔，任一命中即返回）"
        "与通配符（% 匹配任意长度、_ 匹配单个字符），如「伯安 偷%」。\n\n"
        "树根视图带 id、is_foreshadow_setup 与 foreshadowing_status，"
        "活跃伏笔树据此发现（根视图的 is_foreshadow_setup 即埋设事件）："
        "本章事件续接或回收它时，写事件的调用带 foreshadowing_action 与 root_event_id。"
    ),
}

# 八类构造器（§3.1 的目录就是模型知道"能交什么、怎么交"的全部依据）。
# 收尾不是构造器：subagent 的 finish 是面上一等工具（见 build_subagent_finish_tool）。
_SUBAGENT_CONSTRUCTOR_ORDER: tuple[str, ...] = (
    "entity",
    "relation",
    "event",
    "participants",
    "dialogue",
    "label",
    "metric",
    "pending",
)

# subagent 关键产出缺失时的续跑上限：attempt_number 到本值即放行（缺口在章收尾面上可见降级），
# subagent 级重试有界（1 次续跑），不做无限修
_SUBAGENT_GATE_ATTEMPTS = 2


def subagent_gap(subagent: SubagentAnnotation, *, candidate_total: int) -> dict[str, Any]:
    """用于判一个 subagent "交完了没有"：没声明收尾、候选缺判定、指标缺提交

    写入在构造器里就生效，subagent 自己的遗漏在章收尾相位没有模型通道可补，所以缺口只能
    在这里判出来：不完整即续跑一次（同一个会话，产出记录与轮次预算都还在），仍不完整才
    放行并把缺口交给章收尾面的可见降级（指标中性兜底、未判候选按 not_dialogue 默认——
    与单 agent 收尾的 `_default_undecided_dialogues` 同口径）。
    """
    if subagent.role != "evidence":
        # 结构 subagent 与事件 subagent 的完整性口径只有"声明了收尾"；候选与指标不属于它们
        return {"finished": subagent.finished, "missing_candidates": [], "missing_metric": False}
    judged = {item.candidate_index for item in subagent.dialogues}
    return {
        "finished": subagent.finished,
        "missing_candidates": sorted(set(range(1, candidate_total + 1)) - judged),
        "missing_metric": subagent.metric is None,
    }


def subagent_gap_is_clean(gap: dict[str, Any]) -> bool:
    """用于判缺口是否已经消掉（续跑一次后仍不完整即放行）"""
    return bool(gap.get("finished")) and not gap.get("missing_candidates") and not gap.get("missing_metric")


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
    """用于校验参与者清单的形状（entity_id 是本 subagent 已登记 id、character 三态齐）

    2026-09-17 §3.1：这里只判形状——"是不是 character"由生产面按**落库后的实体大类**
    判定（write_event 自己查图），所以三态齐否按"给了三态就是 character 语义"处理：
    三态要么一起给、要么一个都不给（与大类无关）。
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
        role = _require_enum(
            entry.get("role"), PARTICIPANT_ROLES, record=record, field_name=f"participants[{index}].role"
        )
        narrative_role = entry.get("narrative_role")
        action = entry.get("action")
        emotion = entry.get("emotion")
        given = [value is not None for value in (narrative_role, action, emotion)]
        if any(given) and not all(given):
            raise _reject(
                f"participants[{index}]（{entity_id}）的 narrative_role/action/emotion 要么一起给、要么都不给",
                record=record,
                field=f"participants[{index}].narrative_role",
                code="missing_field",
                expected="narrative_role（主体/客体/发送者/接收者/帮助者/反对者/见证者）"
                "＋ action（一句话动作）＋ emotion（-2..2 整数）",
            )
        normalized.append(
            SubagentParticipant(
                entity_id=entity_id,
                role=role,
                narrative_role=(
                    _require_enum(
                        narrative_role, RUNTIME_ROLES, record=record, field_name=f"participants[{index}].narrative_role"
                    )
                    if narrative_role is not None
                    else None
                ),
                action=(
                    _require_text(action, record=record, field_name=f"participants[{index}].action")
                    if action is not None
                    else None
                ),
                emotion=(
                    _require_score(emotion, record=record, field_name=f"participants[{index}].emotion")
                    if emotion is not None
                    else None
                ),
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
    known_case_ids: set[str]
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


def _foreshadowing_attach_args(
    book: _ConstructorBook,
    *,
    record: str,
    foreshadowing_action: str | None,
    root_event_id: str | None,
    payoff_likelihood: str | None = None,
    strength: str | None = None,
) -> dict[str, Any] | None:
    """用于校验"挂进既有伏笔树"的参数并翻成 write_event 入参（省略=不挂）

    root_event_id 两种写法：本 subagent 已写出的树键（在本面的引用键空间里，落库前按角色
    命名空间化）或 search_event 树根视图里的 id（历史树的节点 id，原样透传）。
    2026-09-19 payoff_likelihood/strength：顺手把树根的回收可能性与强度更新成本章现值，
    只在挂边时接受（没挂边就给了即拒绝——它们改的是树根，不是本节点）。
    """
    root_updates: dict[str, str] = {}
    for field_name, value in (("payoff_likelihood", payoff_likelihood), ("strength", strength)):
        if value is None:
            continue
        root_updates[field_name] = _require_enum(
            value, CONFIDENCE_VALUES, record=record, field_name=field_name
        )
    if foreshadowing_action is None and root_event_id is None:
        if root_updates:
            raise _reject(
                "payoff_likelihood/strength 只用于挂进既有伏笔树",
                record=record,
                field=next(iter(root_updates)),
                code="not_on_attach",
                expected=(
                    "要更新树根属性就同时给 foreshadowing_action 与 root_event_id（挂边）；"
                    "本章新建伏笔树的回收可能性用 isforeshadowing=True + confidence"
                ),
            )
        return None
    if foreshadowing_action is None or root_event_id is None:
        raise _reject(
            "foreshadowing_action 与 root_event_id 必须同时给",
            record=record,
            field="foreshadowing_action",
            code="invalid_call",
            expected=(
                '同时给 foreshadowing_action（"reinforce"=续接 / "payoff"=回收）'
                "与 root_event_id（本 subagent 已写出的树键，或 search_event 树根视图里的 id）"
            ),
        )
    action = _require_enum(
        foreshadowing_action, FORESHADOWING_ACTIONS, record=record, field_name="foreshadowing_action"
    )
    normalized_root = _require_text(root_event_id, record=record, field_name="root_event_id")
    if normalized_root in book.subagent.event_keys():
        normalized_root = namespace_event_el(book.role, normalized_root)
    return {"foreshadowing_action": action, "root_event_id": normalized_root, **root_updates}


def _dialogue_update_call(
    book: _ConstructorBook,
    *,
    candidate_key: str,
    candidate_index: int | None,
    verdict: str | None,
    evidence: int | None,
    speaker_id: str | None,
    tone: str | None,
    description: str | None,
    is_inner_monologue: bool | None,
) -> _ConstructorCall:
    """用于按对话记录键构造一次"订正既有记录"的调用（判本章候选是另一条用法）

    这个键就是候选表里那条候选的 candidate_key：本章候选判过就有记录，既有记录同样按它订正。
    订正只消费 candidate_key 与 speaker_id/tone/description/is_inner_monologue；模型常顺手
    复读判候选路径的 candidate_index/verdict/evidence，误带时忽略、不作废整笔。
    """
    normalized_id = _require_text(candidate_key, record="dialogue", field_name="candidate_key")
    record = _record_of(book.subagent, f"dialogue/{normalized_id}")
    if is_inner_monologue is not None and not isinstance(is_inner_monologue, bool):
        raise _reject(
            f"is_inner_monologue 必须是 True/False：{is_inner_monologue!r}",
            record=record,
            field="is_inner_monologue",
            code="invalid_value",
            expected="True=内心独白 / False=人物之间说出口的话",
        )
    args: dict[str, Any] = {"candidate_key": normalized_id}
    updated: list[str] = []
    if speaker_id is not None:
        args["speaker"] = namespace_el(
            book.role,
            _require_known_entity_id(book, speaker_id, record=record, field_name="speaker_id"),
        )
        updated.append("speaker_id")
    if tone is not None:
        args["tone"] = _require_enum(tone, TONE_VALUES, record=record, field_name="tone")
        updated.append("tone")
    if description is not None:
        args["description"] = _require_text(description, record=record, field_name="description")
        updated.append("description")
    if is_inner_monologue is not None:
        args["is_inner_monologue"] = is_inner_monologue
        updated.append("is_inner_monologue")
    if not updated:
        raise _reject(
            "没有要订正的字段",
            record=record,
            field="candidate_key",
            code="no_update",
            expected="speaker_id/tone/description/is_inner_monologue 至少给一个",
        )
    return _ConstructorCall(
        record=record,
        tool="write_dialogue",
        args=args,
        ref={"kind": "dialogue_update", "candidate_key": normalized_id, "fields": updated},
        # 订正不改候选账本（候选判定是另一条用法）：本条只让记录行更新，别无产出
        commit=lambda: None,
    )


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
    known_case_ids: set[str],
    candidate_total: int,
) -> list[tuple[str, Any, str]]:
    """用于构造 subagent 命名空间里的记录构造器（返回 (名字, 可调用, 一句话说明) 列表）

    每个构造器当场校验、当场给出要写的那一笔：成功时运行时立即经生产单条事务边界
    落库（写入生效），失败抛 AnnotationStageRejection（只废这一条，程序继续跑后面的
    语句）。三个 subagent 拿到的是同一份构造器清单（§3），引用键按角色命名空间化
    落库（namespace_el），所以三个 subagent 的同名局部键互不占用。
    """
    book = _ConstructorBook(
        subagent=subagent,
        role=subagent.role,
        paragraph_text_by_id=paragraph_text_by_id,
        known_case_ids=known_case_ids,
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
        change_kind: RelationChangeKindArg | None = None,
    ) -> _ConstructorCall:
        """写一条闭合关系边（两端写本 subagent 已登记的实体 id，不判身份、不判别名）

        relation_type 取闭合关系类型表；方向与两端类型约束在参数说明里。
        change_kind 省略（或填"新增"）=建边；填其余取值=对这条既有边提交一次变化
        （端点仍是本 subagent 已登记的实体 id，解除这类变化要求该边当前还在）。
        变化落在哪一段用 evidence 给段首号（整数）；建边不带 evidence。
        正文只说见面/对峙这类没有闭合关系可表达的，宁缺勿滥——用 pending 登记。
        """
        record = _record_of(subagent, f"relation/{from_id}-{to_id}")
        source = _require_known_entity_id(book, from_id, record=record, field_name="from_id")
        target = _require_known_entity_id(book, to_id, record=record, field_name="to_id")
        normalized_change = (
            _require_enum(change_kind, RELATION_CHANGE_KIND_LABELS, record=record, field_name="change_kind")
            if change_kind is not None
            else None
        )
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
            change_kind=normalized_change,
        )
        args: dict[str, Any] = {
            "from_entity": namespace_el(book.role, item.from_id),
            "to_entity": namespace_el(book.role, item.to_id),
            "relation_type": item.relation_type,
        }
        if item.change_kind is not None:
            args["change_kind"] = item.change_kind
            # 变化落在哪一段，随变更进图域操作日志；建边（含显式"新增"）不消费 evidence、
            # 元组为空，只有真带段号时才透传（生产面建边路径本就忽略它）
            if item.evidence:
                args["evidence"] = item.evidence[0].paragraph_id
        return _ConstructorCall(
            record=record,
            tool="write_relation",
            args=args,
            ref={
                "kind": "relation",
                "type": item.relation_type,
                "from_id": item.from_id,
                "to_id": item.to_id,
                "change_kind": item.change_kind,
            },
            commit=lambda: _put_by(
                subagent.relations,
                item,
                key=lambda existing: (existing.from_id, existing.to_id, existing.change_kind),
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
        foreshadowing_action: str | None = None,
        root_event_id: str | None = None,
        payoff_likelihood: str | None = None,
        strength: str | None = None,
    ) -> _ConstructorCall:
        """写一个事件节点（el 根=树键 t1、子=树键/节点键 t1/e2；树内先后=调用顺序）

        type=main 顺延主因链 / secondary 挂当时主链尾（子事件必填，根事件不填）。
        伏笔属性只属于根：isforeshadowing=True 时 confidence 必填（high/medium/low）。
        参与者用 participants(el=本键, items=[...]) 追加。同 el 重写=更新语义。
        foreshadowing_action 与 root_event_id 同时给=把这个节点挂进一棵已存在的伏笔树
        （续接/回收，节点本身照常写进本章事件树）；payoff_likelihood/strength 只在挂边时给，
        用来把树根上的回收可能性/强度更新成本章判断出的现值。
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
        attach = _foreshadowing_attach_args(
            book,
            record=record,
            foreshadowing_action=foreshadowing_action,
            root_event_id=root_event_id,
            payoff_likelihood=payoff_likelihood,
            strength=strength,
        )
        ref: dict[str, Any] = {
            "kind": "event",
            "el": item.el,
            "isroot": item.isroot,
            "participants": len(item.participants),
        }
        if attach is not None:
            ref["foreshadowing"] = dict(attach)
        return _ConstructorCall(
            record=record,
            tool="write_event",
            args={**_event_write_args(book, item), **({} if attach is None else attach)},
            ref=ref,
            commit=lambda: _put_by(subagent.events, item, key=lambda current: current.el),
        )

    def participants(el: str, items: list[dict[str, Any]]) -> _ConstructorCall:
        """把一个事件节点的参与者整体设为 items（同一节点重写=整体替换）

        items 每项 {entity_id: 本 subagent 已登记的实体 id, role: 主体/客体/接收者/帮助者/
        反对者/见证者/地点, narrative_role: 叙事功能, action: 做了什么, emotion: -2..2 整数}。
        character 的三态（narrative_role/action/emotion）要么一起给、要么都不给。
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
        candidate_index: int | None = None,
        verdict: DialogueVerdict | None = None,
        evidence: int | None = None,
        speaker_id: EntityRef | None = None,
        tone: Tone | None = None,
        candidate_key: str | None = None,
        description: str | None = None,
        is_inner_monologue: bool | None = None,
    ) -> _ConstructorCall:
        """判定一条对话候选（candidate_index 取候选表编号），或按 candidate_key 订正既有记录

        verdict: dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选
        （题字、描写被引号包裹等，此时只填 candidate_index/verdict）。
        speaker_id 写本 subagent 已登记的实体 id，判不了就省略；tone 取闭集，没有贴合的用「其他」。
        evidence 是候选所在段落的段首号：not_dialogue 可省略，其余必须给。
        给 candidate_key（候选表里那条候选的键）时按更新语义改那条既有记录：speaker_id/tone/
        description/is_inner_monologue 至少给一个；candidate_index/verdict/evidence 只属于
        判候选用法，订正时误带会被忽略。
        """
        if candidate_key is not None:
            return _dialogue_update_call(
                book,
                candidate_key=candidate_key,
                candidate_index=candidate_index,
                verdict=verdict,
                evidence=evidence,
                speaker_id=speaker_id,
                tone=tone,
                description=description,
                is_inner_monologue=is_inner_monologue,
            )
        record = _record_of(subagent, f"dialogue/{candidate_index}")
        if candidate_index is None or verdict is None:
            raise _reject(
                "缺少 candidate_index 与 verdict",
                record=_record_of(subagent, "dialogue"),
                field="candidate_index",
                code="invalid_call",
                expected=(
                    "两种用法二选一：判本章候选给 candidate_index 与 verdict；"
                    "订正既有记录给 candidate_key 与要改的字段"
                ),
            )
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
        case_id: str | None = None,
    ) -> _ConstructorCall:
        """登记一个你判不了的疑点（keys 写本 subagent 已登记的实体 id 逐条列表）

        kind: unresolved_reference=引用无法解析 / event_continuation=事件疑似与既有事件树
        延续 / case_clue=疑似案例线索 / other。
        case_clue 必须带 evidence（候选/线索所在段落的段首号），可用 case_id
        带上 search_pool 命中的案例 id。
        """
        normalized_kind = _require_enum(kind, PENDING_KINDS, record=_record_of(subagent, "pending"), field_name="kind")
        record = _record_of(subagent, f"pending/{normalized_kind}")
        normalized_keys: list[str] = []
        for raw_key in keys or []:
            normalized_keys.append(
                _require_known_entity_id(book, raw_key, record=record, field_name="keys")
            )
        resolved_case_id: str | None = None
        if case_id is not None:
            if not isinstance(case_id, str) or not case_id.strip():
                raise _reject(
                    "case_id 必须是 search_pool 回执里的案例 id",
                    record=record,
                    field="case_id",
                    code="invalid_value",
                    expected="search_pool 回执的案例 id；没用过检索就省略",
                )
            if case_id not in book.known_case_ids:
                raise _reject(
                    f"case_id 未由本 subagent 的 search_pool 授权：{case_id}",
                    record=record,
                    field="case_id",
                    code="unauthorized_case",
                    expected="先用 search_pool 检索拿案例 id，再原样填回执里的 id",
                )
            resolved_case_id = case_id
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
            case_id=resolved_case_id,
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
        if item.case_id is not None:
            description = f"疑似命中既有案例 {item.case_id}：{item.detail}"

        def commit() -> None:
            """写入成功后才登记这条待决项（被拒即整条作废，与案例池里那条保持一致）"""
            subagent.pending.append(item)

        return _ConstructorCall(
            record=record,
            tool="push_case",
            args={
                "description": truncate_case_description(description),
                # 案例池的 keys 是与实体名匹配的人类可读字符串（search_pool 的命中口径），
                # 这里把本 subagent 的局部引用键翻成登记名；没有 keys 的疑点用它自己的种类
                "keys": [entities[key].name for key in item.keys if key in entities] or [item.kind],
                "type": PENDING_CASE_TYPES.get(item.kind, "其他疑点"),
            },
            ref={"kind": "pending", "pending_kind": item.kind, "case_id": resolved_case_id},
            commit=commit,
        )

    functions = {
        "entity": (entity, "登记本章的一个实体（id=本 subagent 引用键，name 照抄正文写法仅展示）"),
        "relation": (
            relation,
            "写一条闭合关系边，或对既有边提交一次变化（change_kind；两端写本 subagent 已登记的实体 id）",
        ),
        "event": (
            event,
            "写一个事件节点（el 根=树键、子=树键/节点键；可同时挂进既有伏笔树并更新树根属性）",
        ),
        "participants": (participants, "把一个事件节点的参与者整体设为 items（entity_id 用本 subagent 实体 id）"),
        "dialogue": (
            dialogue,
            "判定一条对话候选（candidate_index+verdict），或按 candidate_key 订正既有对话记录",
        ),
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
        judged = {item.candidate_index for item in subagent.dialogues}
        missing = sorted(set(range(1, candidate_total + 1)) - judged)
        return json.dumps(
            {
                "status": "written",
                "record": _record_of(subagent, "finish"),
                "ref": {
                    "role": subagent.role,
                    "finished": True,
                    "counts": subagent.counts(),
                    "unjudged_candidates": missing,
                    "candidate_total": candidate_total,
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


class SubagentProgramRuntime(RestrictedProgramRuntime):
    """一个 subagent 的程序面：八类构造器 + 检索/案例 + 收尾（绑定面只有 execute_code 与 finish）

    生命周期：一个 subagent 建一次、跨回合复用（变量与逐 op 记录随之保留）。
    程序目录三个 subagent 完全相同（SUBAGENT_TOOL_NAMES + finish），域分工只写在职责文案里。
    """

    contract_text = SUBAGENT_CONTRACT_TEXT

    def __init__(
        self,
        tool_map: dict[str, Any],
        ledger: AnnotationToolLedger,
        subagent: SubagentAnnotation,
        *,
        write_lock: asyncio.Lock | None = None,
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """用于绑定共享章级账本、生产工具表与本 subagent 的产出记录

        模型可见面（绑定面）= [execute_code, finish]；execute_code 的程序目录 =
        SUBAGENT_TOOL_NAMES（检索/案例）+ 八类构造器 + finish。执行面（execution_tools）
        是完整生产工具表——构造器编译出的那笔写入要经它落地，而正式写入工具不在模型可见面。

        write_lock：三个 subagent 共享一个章级账本与一张事实图，账本快照/按条回滚
        与图写入都假定串行，所以内层调用按锁执行（模型生成期间不占锁）。
        """
        paragraph_info = ledger.paragraph_info
        if paragraph_info is None:
            raise AnnotationInvariantError("subagent 程序面需要段落坐标映射，paragraph_info 缺失")
        paragraph_text_by_id = paragraph_info.text_by_visible_id()
        candidate_total = len(ledger.dialogue_candidates)
        entries = build_subagent_constructors(
            subagent,
            paragraph_text_by_id=paragraph_text_by_id,
            known_case_ids=ledger.known_case_ids,
            candidate_total=candidate_total,
        )
        self.finish_tool = build_subagent_finish_tool(subagent, candidate_total=candidate_total)
        program_tools = build_program_tools(list(tool_map.values()))
        by_name = {str(tool.name): tool for tool in program_tools}
        # 可见面按 SUBAGENT_TOOL_NAMES 的顺序取（那是模型目录的排列依据），不跟随工具表顺序
        visible_tools = [by_name[name] for name in SUBAGENT_TOOL_NAMES if name in by_name]
        namespace: dict[str, Any] = {str(tool.name): tool for tool in [*visible_tools, self.finish_tool]}
        namespace.update({name: function for name, function, _ in entries})
        super().__init__(
            [*visible_tools, self.finish_tool],
            namespace,
            observer=observer,
            stream=stream,
            execution_tools={
                **{str(tool.name): tool for tool in program_tools},
                # 生产面也有一个同名 finish（章级收尾），本面必须用自己的那个
                FINISH_TOOL_NAME: self.finish_tool,
            },
        )
        self.ledger = ledger
        self.subagent = subagent
        self.api_entries = entries
        self._constructor_names = frozenset(name for name, _, _ in entries)
        self._paragraph_text_by_id = paragraph_text_by_id
        self._write_lock = write_lock if write_lock is not None else asyncio.Lock()

    def build_tool(self) -> Any:
        """用于构造 subagent 的对外程序入口 execute_code（构造器与检索/案例/finish 同一份目录）"""
        return build_program_tool(
            self,
            extra_api=_SUBAGENT_REFERENCE_SCOPE_TEXT,
            tool_descriptions=SUBAGENT_TOOL_COPY,
            call_entries=constructor_call_entries(self.api_entries),
        )

    def _progress(self) -> dict[str, int]:
        """用于回执 progress（本 subagent 已构造的记录计数）"""
        return self.subagent.counts()

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """用于执行程序里的一次调用（构造器与工具同一条路径、同一套回执与审计）

        每个名字走同样的步骤：寻址换算 → （构造器）当场校验成待写记录 → 经生产单条事务
        边界执行 → 落产出记录 → 收尾（op 记录 + 审计行各写一次）。回执只有三种：
        写成了 {status:"written", record, ref}、读到了数据本身（检索）、被拒
        {status:"rejected", record, field, code, expected, message}——不因为"这次调的是
        构造器还是工具"而换一套形状。
        """
        op_index = self._next_op_index(line=line)
        started_ns = time.perf_counter_ns()
        # 模型写的那一次调用：op 记录与审计行都记它，执行用构造器编译出的生产入参
        call_args = dict(args)
        plan: _ConstructorCall | None = None
        if name in self._constructor_names:
            try:
                plan = self.tools[name](**call_args)
            except AnnotationInvariantError:
                self._close_turn()
                raise
            except Exception as exc:
                return self._finish_call(
                    name,
                    op_index=op_index,
                    line=line,
                    status="error",
                    receipt=_call_rejection(name, exc, signature_hint=self._signature_hint(name)),
                    call_args=call_args,
                    error=str(exc),
                    started_ns=started_ns,
                )
        target = name if plan is None else plan.tool
        exec_args = call_args if plan is None else plan.args
        if plan is not None and target is None:
            # 只落产出记录的构造器（label）：标签与章级指标同属一个域，单独一条写不出去
            plan.commit()
            self.ledger.written_record_keys.add(plan.record)
            return self._finish_call(
                name,
                op_index=op_index,
                line=line,
                status="success",
                receipt=_written_receipt(plan.record, plan.ref),
                call_args=call_args,
                error=None,
                started_ns=started_ns,
            )
        try:
            async with self._write_lock:
                entry = await _execute_call(
                    {"name": target, "args": exec_args, "id": f"{self._program_id}-op{op_index}"},
                    tool_map=self.execution_tools,
                    ledger=self.ledger,
                    # 审计行由本面的 _record_audit 统一写（构造器名=模型这一次动作），
                    # 内层写入不另开审计行：一个调用一行，两个面同一份字段。
                    observer=None,
                    stream=self.stream,
                    call_index=self._next_call_index(),
                    # 2026-09-18 subagent 与写者面的收尾工具同名：本面的 finish 不是章级收尾
                    chapter_finish_name=None,
                )
        except AnnotationInvariantError:
            self._close_turn()
            raise
        ok = str(entry.get("status") or "error") == "success"
        if ok and plan is not None:
            plan.commit()
            # 模型看到的记录键就是这次回执里的 record：登记进章级账本，push_case(record_id=...)
            # 与 promise_case(result_id=...) 按它校验"指向的是本章真实写出来的记录"
            self.ledger.written_record_keys.add(plan.record)
        receipt: Any
        if not ok:
            receipt = _refused_receipt(name, None if plan is None else plan.record, entry.get("receipt"))
        elif plan is None:
            receipt = _tool_receipt(name, entry.get("receipt"))
        else:
            _sync_entity_ref(plan.ref, entry.get("receipt"))
            receipt = _written_receipt(plan.record, plan.ref)
        return self._finish_call(
            name,
            op_index=op_index,
            line=line,
            status="success" if ok else "error",
            receipt=receipt,
            call_args=call_args,
            error=None if ok else str(entry.get("error") or _receipt_message(receipt) or "调用被拒"),
            started_ns=started_ns,
        )

    def _finish_call(
        self,
        name: str,
        *,
        op_index: int,
        line: int | None,
        status: str,
        receipt: Any,
        call_args: dict[str, Any],
        error: str | None,
        started_ns: int,
    ) -> Any:
        """用于一次调用的收尾：逐 op 记录与审计行各写一次（构造器与工具共用同一份实现）"""
        self._log_op(
            name,
            op_index=op_index,
            line=line,
            status=status,
            receipt=receipt,
            call_args=call_args,
            error=error,
        )
        self._record_audit(
            name,
            args=call_args,
            receipt=receipt,
            status=status,
            error=error,
            started_ns=started_ns,
            op_index=op_index,
            line=line,
        )
        return receipt

    def _close_turn(self) -> None:
        """用于合同违反时先闭合回合审计计时（否则 agent_turns 的耗时字段留空）"""
        observer = self.audit_observer
        if observer is not None:
            observer.close_turn()

    def _signature_hint(self, name: str) -> str:
        """用于在参数名写错时把构造器签名原样回给模型（自纠不需要猜）"""
        for entry_name, function, _ in self.api_entries:
            if entry_name == name:
                return render_list_signature(name, call_parameters(name, function))
        return name

    def _record_audit(
        self,
        name: str,
        *,
        args: dict[str, Any],
        receipt: Any,
        status: str,
        error: str | None,
        started_ns: int,
        op_index: int,
        line: int | None,
    ) -> None:
        """用于把一个调用写进 agent_tool_calls（构造器与工具同一份字段）

        记录键与错误码取自回执（生产拒绝的 code、构造器校验的 code 或工具的载荷），
        source_line 来自模型程序里的源码行——构造器与工具都有，质量统计按
        (tool_name, error_code) 分桶。检索类回执就是数据本身（数组/对象），取字段前先按
        对象判形态。
        """
        if self.observer is None:
            return
        body: dict[str, Any] = receipt if isinstance(receipt, dict) else {}
        request_args = dict(args)
        request_args["_program"] = {
            "program_id": self._program_id,
            "op_index": op_index,
            "source_line": line,
            "record": body.get("record"),
            "direct_fallback": False,
        }
        if body.get("code"):
            request_args["_program"]["error_code"] = body["code"]
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
class SubagentRunOutcome:
    """一个 subagent 会话的产出（本 subagent 的产出记录 + 末条消息，供日志与离线对照）

    2026-09-18 写入生效后这里不再搬运授权足迹与案例记录：它们落在三个 subagent 共享的
    章级账本上，调用方拿到的账本本身就是终态（没有落库相位的状态搬运）。
    """

    subagent: SubagentAnnotation
    final_messages: list[BaseMessage]


async def run_subagent_agent(
    *,
    run_id: str,
    chapter_id: int,
    role: str,
    ledger: AnnotationToolLedger,
    tool_map: dict[str, Any],
    write_lock: asyncio.Lock,
    subagent: SubagentAnnotation,
    llm: Any,
    session_factory: Any,
    graph_state: Any | None = None,
    stream: Any | None = None,
    audit_recorder: Any | None = None,
    novel_id: str = "default",
    attempt_number: int = 1,
) -> SubagentRunOutcome:
    """用于运行一个 subagent 的 CodeAct 会话（写入直接落共享章级账本）

    subagent 绝不触碰 FactGraph 的章节生命周期（begin/reset/drain 全归派发方），
    但它的每一笔构造都经生产单条事务边界即时落库（写入生效）。
    模型可见面 = [execute_code, finish]；会话收束 = 模型不再提交程序，
    撞轮次上限按同一收束处理。
    """
    from src.agents.annotation.graph import build_subagent_graph
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
        task_type="annotation_subagent",
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
        task_type="annotation_subagent",
        call_type="agent",
        model_name=model_name or "unknown",
        model_provider=model_provider,
    )
    try:
        paragraph_info = ledger.paragraph_info
        if paragraph_info is None:
            raise AnnotationInvariantError("subagent 会话需要段落坐标映射，paragraph_info 缺失")
        runtime = SubagentProgramRuntime(
            tool_map,
            ledger,
            subagent,
            write_lock=write_lock,
            observer=observer,
            stream=stream,
        )
        program_tool = runtime.build_tool()
        graph = build_subagent_graph(
            llm,
            program_tool,
            runtime.finish_tool,
            ledger=ledger,
            max_iterations=max(1, settings.models.annotation.max_iterations),
            stream=stream,
            observer=observer,
            retries=settings.models.annotation.total_attempts,
        )
        first_messages: list[BaseMessage] = [
            SystemMessage(content=SUBAGENT_SYSTEM_PROMPT),
            HumanMessage(
                content=build_subagent_message(
                    role=role,
                    paragraph_info=paragraph_info,
                    candidates=ledger.dialogue_candidates,
                    role_scope=SUBAGENT_ROLE_SCOPES[role],
                )
            ),
        ]
        result_state = await graph.ainvoke(
            {
                "messages": first_messages,
                "phase": "chapter_open",
                "iterations": 0,
                "error": None,
            }
        )
        # 2026-09-17 缺口闸门 + subagent 级有界续跑：subagent 内的遗漏在落库相位没有模型
        # 通道可修（写入即生效，缺口就是缺口），所以这里必须判"交完了没有"。缺口清单直接作为
        # 一条用户消息交回**同一个会话**（产出记录、变量与轮次预算都还在，不是新起会话）；
        # 续跑一次仍不完整就放行，缺口在章级收尾面上可见降级。
        candidate_total = len(ledger.dialogue_candidates)
        gap = subagent_gap(subagent, candidate_total=candidate_total)
        if not subagent_gap_is_clean(gap) and attempt_number < _SUBAGENT_GATE_ATTEMPTS:
            logger.info(
                "subagent gate retry run_id={} chapter_id={} role={} missing_candidates={} missing_metric={}",
                run_id,
                chapter_id,
                role,
                len(gap["missing_candidates"]),
                gap["missing_metric"],
            )
            result_state = await graph.ainvoke(
                {
                    "messages": [*result_state["messages"], HumanMessage(content=build_subagent_gap_message(gap))],
                    "phase": "chapter_open",
                    "iterations": 0,
                    "error": None,
                }
            )
            gap = subagent_gap(subagent, candidate_total=candidate_total)
        if not subagent_gap_is_clean(gap):
            logger.warning(
                "subagent incomplete run_id={} chapter_id={} role={} gap={}",
                run_id,
                chapter_id,
                role,
                gap,
            )
    except asyncio.CancelledError:
        # 兄弟 subagent 失败会把在飞的这一条取消（BaseException，不走下面的 Exception 分支）：
        # 取消同样要收口审计行，否则 agent_invocations 留下没有终态的悬挂行
        recorder.finish_invocation(invocation_id, status="error", final_error="cancelled")
        raise
    except Exception as exc:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        if isinstance(exc, AnnotationRetryableError):
            raise
        raise AnnotationRetryableError(f"subagent 会话失败（{SUBAGENT_ROLE_LABELS.get(role, role)}）: {exc}") from exc
    error = result_state.get("error")
    if error:
        recorder.finish_invocation(invocation_id, status="error", final_error=str(error))
        raise AnnotationRetryableError(f"subagent 会话失败（{SUBAGENT_ROLE_LABELS.get(role, role)}）: {error}")
    recorder.finish_invocation(invocation_id, status="success")
    return SubagentRunOutcome(
        subagent=subagent,
        final_messages=list(result_state["messages"]),
    )


__all__ = [
    "SUBAGENT_BOUND_TOOL_NAMES",
    "SUBAGENT_ROLES",
    "SUBAGENT_ROLE_LABELS",
    "SUBAGENT_TOOL_NAMES",
    "SubagentProgramRuntime",
    "SubagentRunOutcome",
    "build_subagent_constructors",
    "build_subagent_finish_tool",
    "subagent_gap",
    "subagent_gap_is_clean",
    "run_subagent_agent",
]
