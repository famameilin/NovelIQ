"""全书案例池：人物/关系/对话/事件四类问题案例，业务内容含结构化 payload 与描述

- book_cases 承接登记身份、明确目标（实体/关系/对话/声明/完整事件真实 FK）、
  对话候选与诊断失败候选定位、登记原因与独立评审状态
- case_entries 承接 Agent 支持→交付→连接层级（父父子固定深度）、保存告警与
  未发布事件的失败观察；连接的规范身份是 narrative_links.link_id（不读旧边）
- is_write / reads 由固定工具合同与真实交付投影；案例是否解决只认 promise 交付痕迹
  （有承诺即已解决、没有即未解决，不存在中间状态），不落重复列
"""

from __future__ import annotations

import json
import unicodedata
from copy import deepcopy
from typing import Any, cast
from uuid import NAMESPACE_DNS, uuid5

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.case_pool.contributions import CaseContribution
from src.storage.models import (
    BookCase,
    CaseEntry,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    DiagnosisReport,
    DialogueRecord,
    EventDeclaration,
    Execution,
    GraphEntity,
    GraphRelation,
    NarrativeLink,
    WorkItem,
)
from src.utils.identity import stable_digest, stable_uuid

CASE_TYPES = ("character", "relation", "dialogue", "event")
EVENT_CASE_TYPE = "event"

#: 可降级为单案例告警的真实约束冲突（外键/唯一/检查）；结构缺陷必须上抛
_CASE_CONFLICT_SQLSTATES = {"23503", "23505", "23514"}

_REGISTERED_REQUIRED_KEYS: dict[str, set[str]] = {
    "event": {"event_id"},
    "character": {"node_id", "name", "entity_type"},
    "relation": {"node_id"},
    "dialogue": {"candidate_key", "chapter_id"},
}


def _is_write_tool(tool_name: str) -> bool:
    """固定工具合同：标注 write_event 等与诊断 write_entity/write_relation/write_dialogue 同名族"""
    return tool_name.startswith("write_")


def _receipt_bytes(receipt: Any) -> bytes:
    """不可变回执字节：原样保存当次真实工具回执文档"""
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _receipt_dict(raw: bytes | None) -> Any:
    """回执字节读回原文档；缺失或不可解码时按空对象处理（只用于展示/审计）"""
    if not raw:
        return {}
    try:
        return json.loads(bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _dialogue_candidate_key(chapter_id: int, start: int, end: int, content: str) -> str:
    """对话候选键投影：按 UUID5(章号:起止:原文) 算法计算，不与区间重复存编码"""
    return f"dlg_{uuid5(NAMESPACE_DNS, f'{chapter_id}:{start}:{end}:{content}').hex}"


def _validate_registered_payload(case_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """程序链登记的结构化内容必须带齐该类型的定位键；禁止未声明键导致解析漂移"""
    if case_type not in CASE_TYPES:
        raise ValueError(f"case_type={case_type!r}，必须是 {CASE_TYPES}")
    if not isinstance(payload, dict):
        raise ValueError(f"payload 必须是对象，收到: {payload!r}")
    missing = _REGISTERED_REQUIRED_KEYS[case_type] - set(payload)
    if missing:
        raise ValueError(f"case_type={case_type} 缺少必填 payload 键: {sorted(missing)}")
    return deepcopy(payload)


class CasePool:
    """由 agent 在同一 run 锁内调用；交付接受顺序与数据库保存顺序分离"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.cases: dict[str, dict[str, Any]] = {}
        self.case_runtime: dict[str, dict[str, Any]] = {}
        self.registrations: dict[str, set[str]] = {}
        self.created: dict[str, set[str]] = {}
        self.deliveries: dict[str, list[dict[str, Any]]] = {}
        self.saved: set[str] = set()
        self.executions: set[str] = set()
        self._sequence = 0
        self.save_warnings: dict[str, list[dict[str, Any]]] = {}

    def begin(self, execution_id: str) -> None:
        author = execution_id
        self.executions.add(author)
        self.registrations.setdefault(author, set())
        self.created.setdefault(author, set())
        self.deliveries.setdefault(author, [])

    def _require(self, author: str) -> None:
        if author not in self.executions:
            raise ValueError(f"案例执行已停止: {author}")

    @staticmethod
    def case_identity(record: dict[str, Any]) -> tuple[Any, ...]:
        """案例不可变身份：只比较真实保存的定位键与原因

        名字/类型/章号副本由正式目标推导，不参与身份比较；描述与案例 ID 的身份算法不变。
        """
        payload = record.get("payload") or {}
        return (
            record.get("case_type"),
            record.get("description"),
            payload.get("node_id"),
            payload.get("event_id"),
            payload.get("candidate_key"),
            payload.get("reason"),
        )

    def push(self, case_type: str, description: str, author: str) -> dict[str, Any]:
        """模型侧登记类型化案例：必须归入四类之一，结构化 payload 留空"""
        self._require(author)
        if case_type not in CASE_TYPES:
            raise ValueError(f"case_type={case_type!r}，必须显式归入 {CASE_TYPES}")
        normalized = " ".join(unicodedata.normalize("NFC", description).split())
        if not normalized or len(normalized) > 100:
            raise ValueError(f"push_case.description={description!r}，期望非空普通文字且不超过 100 字")
        case_id = stable_digest(self.run_id, case_type, normalized)
        self.cases.setdefault(
            case_id,
            {"case_id": case_id, "case_type": case_type, "description": normalized, "payload": {}},
        )
        self.case_runtime.setdefault(case_id, {"promised": False, "owner": None})
        self.registrations[author].add(case_id)
        self.created[author].add(case_id)
        return dict(self.cases[case_id])

    def register_case(
        self,
        *,
        case_type: str,
        description: str,
        payload: dict[str, Any],
        author: str,
    ) -> dict[str, Any]:
        """程序链登记结构化案例：按类型校验必填定位键，同键同内容幂等"""
        self._require(author)
        validated = _validate_registered_payload(case_type, payload)
        normalized = " ".join(unicodedata.normalize("NFC", description).split())
        if not normalized or len(normalized) > 100:
            raise ValueError(
                f"register_case.description={description!r}，期望非空普通文字且不超过 100 字"
            )
        record: dict[str, Any] = {
            "case_id": stable_digest(self.run_id, case_type, normalized),
            "case_type": case_type,
            "description": normalized,
            "payload": validated,
        }
        return self._register(record, author)

    def _register(self, record: dict[str, Any], author: str) -> dict[str, Any]:
        case_id = record["case_id"]
        existing = self.cases.get(case_id)
        if existing is not None and self.case_identity(existing) != self.case_identity(record):
            raise ValueError(f"case_id={case_id} 已有另一份不可变说明")
        if existing is None:
            self.cases[case_id] = record
            self.case_runtime.setdefault(case_id, {"promised": False, "owner": None})
        self.registrations[author].add(case_id)
        self.created[author].add(case_id)
        return dict(self.cases[case_id])

    def register_event_case(
        self,
        *,
        declaration_id: str,
        title: str,
        summary: str,
        status: str,
        chapter_id: int,
        author: str,
    ) -> dict[str, Any]:
        """write_event 落地时由程序侧登记案例

        同一事件按声明 id 幂等登记一次；声明内容不可改写由事件声明侧保证，重复登记
        返回既有案例，不改写业务字段。不走模型可见工具。
        """
        payload = {
            "event_id": declaration_id,
            "title": title,
            "summary": summary,
            "status": status,
            "chapter_id": int(chapter_id),
        }
        normalized = " ".join(unicodedata.normalize("NFC", str(title)).split())[:100]
        idempotence = stable_digest(self.run_id, "event_case", declaration_id)
        record: dict[str, Any] = {
            "case_id": idempotence,
            "case_type": EVENT_CASE_TYPE,
            "description": normalized,
            "payload": payload,
        }
        existing = self.cases.get(idempotence)
        if existing is not None and self.case_identity(existing) != self.case_identity(record):
            raise ValueError(f"case_id={idempotence} 已有另一份不可变说明")
        if existing is None:
            self.cases[idempotence] = record
            self.case_runtime.setdefault(idempotence, {"promised": False, "owner": None})
        self.registrations[author].add(idempotence)
        self.created[author].add(idempotence)
        return dict(self.cases[idempotence])

    def promise(self, case_id: str, author: str) -> dict[str, Any]:
        """接手承诺：承诺即视为解决，系统不做完成度核对；已被接手返回 taken

        承诺落一条非写入交付（tool_name=promise_case）作为持久化痕迹，
        读取重建时「有承诺交付」即已解决，没有即未解决，不存在中间状态。
        """
        self._require(author)
        if case_id not in self.cases:
            raise ValueError(f"promise_case.case_id={case_id!r} 不存在；请取案例列表的真实 ID")
        runtime = self.case_runtime[case_id]
        if runtime["promised"]:
            return {**self.cases[case_id], "status": "taken"}
        runtime["promised"] = True
        runtime["owner"] = author
        self.registrations[author].add(case_id)
        self._sequence += 1
        self.deliveries[author].append(
            {
                "case_id": case_id,
                "call_id": f"promise-{author}-{case_id}",
                "accepted_order": self._sequence,
                "connections": [],
                "reads": [],
                "tool_name": "promise_case",
                "receipt": {"status": "promised"},
                "is_write": False,
            }
        )
        return {**self.cases[case_id], "status": "promised"}

    def associate(
        self,
        caseid: Any,
        author: str,
        *,
        tool_name: str,
        call_id: str,
        receipt: dict[str, Any],
        is_write: bool,
    ) -> dict[str, Any]:
        """业务已成功后登记真实调用凭据；任何关联错误只撤销案例域自身"""
        snapshot = self.snapshot(author)
        try:
            self._require(author)
            if not call_id:
                raise ValueError("案例关联缺少真实工具调用 ID")
            if not isinstance(caseid, str) or not caseid:
                raise ValueError("caseid 必须是非空案例 ID")
            if caseid not in self.cases:
                raise ValueError("caseid 不属于当前 run")
            runtime = self.case_runtime[caseid]
            if not runtime.get("promised") or runtime.get("owner") != author:
                raise ValueError("该案例尚未由本执行承诺；先 promise_case 接手，再带 caseid 调用")
            if receipt.get("status") in {"deferred", "rejected", "error", "runtime_error", "partial"}:
                raise ValueError("本次调用未形成有效产物，不登记交付")
            previous = next((item for item in self.deliveries[author] if item["call_id"] == call_id), None)
            if previous is not None and (
                previous["case_id"] != caseid
                or previous["tool_name"] != tool_name
                or previous["receipt"] != receipt
                or previous["is_write"] != is_write
            ):
                raise ValueError("同一工具调用 ID 已关联不同案例或产物，不能覆盖原交付")
            if previous is None:
                self._sequence += 1
                self.deliveries[author].append(
                    {
                        "case_id": caseid,
                        "call_id": call_id,
                        "accepted_order": self._sequence,
                        "connections": [],
                        "reads": [] if is_write else [deepcopy(receipt)],
                        "tool_name": tool_name,
                        "receipt": deepcopy(receipt),
                        "is_write": is_write,
                    }
                )
            self.registrations[author].add(caseid)
            return {"status": "success", "caseid": caseid, "delivery": is_write}
        except Exception as exc:
            self.restore(snapshot)
            return {"status": "warning", "code": "case_association_failed", "caseid": caseid, "message": str(exc)}

    def stop(self, author: str) -> None:
        self.executions.discard(author)

    def confirm(self, execution_id: str) -> None:
        author = execution_id
        self.saved.add(author)
        self.stop(author)

    def rollback(self, execution_id: str) -> None:
        author = execution_id
        if author in self.saved:
            return
        self.stop(author)
        self.registrations.pop(author, None)
        self.created.pop(author, None)
        self.deliveries.pop(author, None)
        supported = set().union(*self.registrations.values()) if self.registrations else set()
        for case_id in list(self.cases):
            if case_id not in supported:
                self.cases.pop(case_id)
                self.case_runtime.pop(case_id)

    def snapshot(self, author: str) -> dict[str, Any]:
        # 单条操作由 agent 持锁，快照只覆盖本操作可能改动的案例域
        return deepcopy(
            {
                "cases": self.cases,
                "case_runtime": self.case_runtime,
                "registrations": self.registrations,
                "created": self.created,
                "deliveries": self.deliveries,
                "sequence": self._sequence,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.cases = snapshot["cases"]
        self.case_runtime = snapshot["case_runtime"]
        self.registrations = snapshot["registrations"]
        self.created = snapshot["created"]
        self.deliveries = snapshot["deliveries"]
        self._sequence = snapshot["sequence"]

    def search(self, case_type: str | None = None) -> list[dict[str, Any]]:
        return [
            {**case, "promised": bool(self.case_runtime[key]["promised"])}
            for key, case in sorted(self.cases.items())
            if case_type is None or case.get("case_type") == case_type
        ]

    # ------------------------------------------------------------------
    # 数据库读写：book_cases 具名列 + case_entries 六种有限形状
    # ------------------------------------------------------------------

    def _run_execution_ids(self, session: Session) -> set[str]:
        """本运行的真实执行：执行行直接携带运行归属（调用形状或整轮会话形状）"""
        return set(
            session.scalars(
                select(Execution.execution_id).where(
                    or_(Execution.run_id == self.run_id, Execution.session_run_id == self.run_id)
                )
            )
        )

    def _case_ids(self, session: Session) -> set[str]:
        """本 run 案例集合：无目标登记按真实运行；正式目标/候选观察按真实生产者身份"""
        case_ids = set(
            session.scalars(select(BookCase.case_id).where(BookCase.registration_run_id == self.run_id))
        )
        execution_ids = self._run_execution_ids(session)
        if execution_ids:
            case_ids |= set(
                session.scalars(
                    select(CaseEntry.case_id).where(
                        CaseEntry.case_id.is_not(None), CaseEntry.producer_execution_id.in_(execution_ids)
                    )
                )
            )
            case_ids |= set(
                session.scalars(
                    select(BookCase.case_id)
                    .join(CaseEntry, BookCase.pending_event_entry_id == CaseEntry.entry_id)
                    .where(CaseEntry.candidate_producer_execution_id.in_(execution_ids))
                )
            )
        case_ids |= set(
            session.scalars(
                select(CaseEntry.case_id).where(
                    CaseEntry.case_id.is_not(None),
                    CaseEntry.program_work_id.in_(self._run_program_work_ids()),
                )
            )
        )
        return case_ids

    def _run_program_work_ids(self):
        """本 run 的程序形状 work：章末核对按运行归属、诊断失败保留按整轮会话归属"""
        return select(WorkItem.work_id).where(
            or_(
                WorkItem.program_run_id == self.run_id,
                WorkItem.diagnosis_session_id.in_(
                    select(Execution.execution_id).where(Execution.session_run_id == self.run_id)
                ),
            )
        )

    def _case_belongs(self, session: Session, case: BookCase) -> bool:
        """案例归属校验：登记运行或真实生产者执行必须属于本 run"""
        if case.registration_run_id is not None:
            return case.registration_run_id == self.run_id
        execution_ids = self._run_execution_ids(session)
        if case.pending_event_entry_id is not None:
            producer = session.scalar(
                select(CaseEntry.candidate_producer_execution_id).where(
                    CaseEntry.entry_id == case.pending_event_entry_id
                )
            )
            return producer in execution_ids
        return (
            session.scalar(
                select(CaseEntry.entry_id).where(
                    CaseEntry.case_id == case.case_id,
                    or_(
                        CaseEntry.producer_execution_id.in_(execution_ids),
                        CaseEntry.program_work_id.in_(self._run_program_work_ids()),
                    ),
                )
            )
            is not None
        )

    def _pending_observation(self, session: Session, contribution: CaseContribution, payload: dict[str, Any]) -> str:
        """诊断失败候选观察：同一 (真实执行, 候选标识) 只存一次，多个案例共同引用"""
        reference = str(payload.get("event_id") or payload.get("node_id") or "")
        if not reference:
            raise ValueError("未发布事件候选缺少候选标识")
        chapter_id = payload.get("chapter_id")
        if chapter_id is None:
            raise ValueError("未发布事件候选缺少来源章")
        existing = session.scalar(
            select(CaseEntry.entry_id).where(
                CaseEntry.candidate_producer_execution_id == contribution.author,
                CaseEntry.pending_event_reference == reference,
            )
        )
        if existing is not None:
            return str(existing)
        title = str(payload.get("name") or payload.get("title") or reference)[:255]
        entry = CaseEntry(
            entry_id=stable_uuid("case_pending_observation", contribution.author, reference),
            candidate_producer_execution_id=contribution.author,
            pending_event_reference=reference,
            pending_event_title=title,
            pending_event_chapter_id=int(chapter_id),
        )
        session.add(entry)
        session.flush()
        return entry.entry_id

    def _formal_target_columns(
        self, session: Session, case: dict[str, Any], contribution: CaseContribution
    ) -> dict[str, Any]:
        """payload 定位键 → book_cases 正式目标/候选列；不能落库的目标明确报错"""
        payload = case.get("payload") or {}
        case_type = case["case_type"]
        values: dict[str, Any] = {}
        if case_type == "character" and payload.get("node_id"):
            entity = session.get(GraphEntity, str(payload["node_id"]))
            if entity is None:
                raise ValueError(f"人物案例目标实体不存在: {payload['node_id']}")
            values["entity_target_id"] = entity.entity_id
        elif case_type == "relation" and payload.get("node_id"):
            relation = session.get(GraphRelation, str(payload["node_id"]))
            if relation is None:
                raise ValueError(f"关系案例目标不存在: {payload['node_id']}")
            values["relation_target_id"] = relation.relation_id
        elif case_type == "dialogue":
            candidate_key = payload.get("candidate_key")
            chapter_id = payload.get("chapter_id")
            if candidate_key and chapter_id is not None:
                record = session.scalar(
                    select(DialogueRecord).where(
                        DialogueRecord.candidate_key == str(candidate_key),
                        DialogueRecord.creation_execution_id.in_(self._run_execution_ids(session)),
                    )
                )
                if record is not None:
                    values["dialogue_target_id"] = record.dialogue_id
                else:
                    start, end = payload.get("start"), payload.get("end")
                    if not isinstance(start, int) or not isinstance(end, int):
                        raise ValueError("对话候选缺少正式记录与真实章节区间 start/end")
                    values["dialogue_candidate_chapter_id"] = int(chapter_id)
                    values["dialogue_candidate_start"] = start
                    values["dialogue_candidate_end"] = end
        elif case_type == "event":
            event_id = str(payload.get("event_id") or payload.get("node_id") or "")
            if event_id:
                if session.get(CompleteEvent, event_id) is not None:
                    values["complete_event_target_id"] = event_id
                elif session.get(EventDeclaration, event_id) is not None:
                    # 按声明自动登记（write_event 落地）与普通描述登记的声明目标分列承接
                    if case["case_id"] == stable_digest(self.run_id, "event_case", event_id):
                        values["automatic_declaration_id"] = event_id
                    else:
                        values["declaration_target_id"] = event_id
                else:
                    values["pending_event_entry_id"] = self._pending_observation(
                        session, contribution, payload
                    )
        return values

    def _ensure_case_row(self, session: Session, case: dict[str, Any], contribution: CaseContribution) -> BookCase:
        """幂等登记案例行；已存在时只校验归属，不改写既有业务字段"""
        existing = session.get(BookCase, case["case_id"])
        if existing is not None:
            if not self._case_belongs(session, existing):
                raise ValueError(f"case_id={case['case_id']} 不属于当前 run")
            return existing
        payload = case.get("payload") or {}
        values: dict[str, Any] = {
            "case_id": case["case_id"],
            "case_type": case["case_type"],
            "description": case["description"],
            "registration_run_id": self.run_id,
        }
        reason = payload.get("reason")
        if isinstance(reason, str) and reason:
            values["registration_reason"] = reason
        paragraph_id = payload.get("paragraph_id")
        if isinstance(paragraph_id, int):
            values["registration_paragraph_id"] = paragraph_id
        values.update(self._formal_target_columns(session, case, contribution))
        if any(
            values.get(name) is not None
            for name in (
                "automatic_declaration_id",
                "entity_target_id",
                "relation_target_id",
                "dialogue_target_id",
                "declaration_target_id",
                "complete_event_target_id",
                "pending_event_entry_id",
            )
        ):
            # 正式目标或候选观察可决定运行时，登记运行必须为空
            values["registration_run_id"] = None
        row = BookCase(**values)
        session.add(row)
        session.flush()
        return row

    def _support_entry(
        self, session: Session, case_id: str, contribution: CaseContribution, adopted: bool
    ) -> CaseEntry:
        """Agent 支持/贡献：每 (case, producer execution) 一行，不伪造第二份支持

        程序形状（章末核对/诊断失败保留）按 work_items 登记的程序身份区分：
        支持条目引用程序 work，adopted 恒 NULL，程序身份不能冒充 producer 执行。
        """
        work = session.get(WorkItem, contribution.author)
        if work is not None:
            existing = session.scalar(
                select(CaseEntry).where(
                    CaseEntry.case_id == case_id, CaseEntry.program_work_id == contribution.author
                )
            )
            if existing is not None:
                return existing
            entry = CaseEntry(
                entry_id=stable_uuid("case_program_support", case_id, contribution.author),
                case_id=case_id,
                program_work_id=contribution.author,
            )
            session.add(entry)
            session.flush()
            return entry
        existing = session.scalar(
            select(CaseEntry).where(
                CaseEntry.case_id == case_id,
                CaseEntry.producer_execution_id == contribution.author,
            )
        )
        if existing is not None:
            existing.adopted = bool(existing.adopted) or adopted
            return existing
        entry = CaseEntry(
            entry_id=stable_uuid("case_support", case_id, contribution.author),
            case_id=case_id,
            producer_execution_id=contribution.author,
            adopted=adopted,
        )
        session.add(entry)
        session.flush()
        return entry

    def _save_support(
        self, session: Session, case: BookCase, contribution: CaseContribution, facts: list[dict[str, Any]]
    ) -> None:
        """支持→交付→连接：只引用直接父条目，业务 call_id 全局唯一"""
        adopted = any(bool(fact.get("is_write")) for fact in facts)
        support = self._support_entry(session, case.case_id, contribution, adopted)
        for fact in facts:
            delivery = session.scalar(
                select(CaseEntry).where(CaseEntry.business_call_id == str(fact["call_id"]))
            )
            if delivery is None:
                delivery = CaseEntry(
                    entry_id=stable_uuid("case_delivery_entry", case.case_id, str(fact["call_id"])),
                    parent_entry_id=support.entry_id,
                    business_call_id=str(fact["call_id"]),
                    accepted_order=int(fact["accepted_order"]),
                    tool_name=str(fact["tool_name"]),
                    receipt_bytes=_receipt_bytes(fact.get("receipt")),
                )
                session.add(delivery)
                session.flush()
            elif delivery.parent_entry_id != support.entry_id:
                raise ValueError(f"业务调用 ID 已属于其他交付: {fact['call_id']}")
            for link_id in fact.get("connections") or []:
                exists = session.scalar(
                    select(CaseEntry.entry_id).where(
                        CaseEntry.parent_entry_id == delivery.entry_id,
                        CaseEntry.narrative_link_id == str(link_id),
                    )
                )
                if exists is None:
                    session.add(
                        CaseEntry(
                            entry_id=stable_uuid("case_connection_entry", delivery.entry_id, str(link_id)),
                            parent_entry_id=delivery.entry_id,
                            narrative_link_id=str(link_id),
                        )
                    )

    def _formal_owner(
        self, session: Session, contribution: CaseContribution, adopted_output_id: str | None
    ) -> tuple[str | None, str | None]:
        """正式产物 owner：标注尝试记录或诊断发布报告（告警行归属不伪造）"""
        record_id = session.scalar(
            select(ChapterAnnotation.record_id).where(
                ChapterAnnotation.execution_id == contribution.author
            )
        )
        if record_id is not None:
            return str(record_id), None
        report_statement = (
            select(DiagnosisReport.report_id)
            .join(Execution, Execution.execution_id == DiagnosisReport.session_id)
            .where(Execution.session_run_id == self.run_id)
        )
        if adopted_output_id:
            report_id = session.scalar(
                report_statement.where(DiagnosisReport.report_id == adopted_output_id)
            )
            if report_id is not None:
                return None, str(report_id)
        report_id = session.scalar(
            report_statement.where(DiagnosisReport.session_id == contribution.author)
        )
        if report_id is not None:
            return None, str(report_id)
        return None, None

    def _save_warnings(
        self,
        session: Session,
        record_id: str | None,
        report_id: str | None,
        warnings: list[dict[str, Any]],
    ) -> None:
        """真实保存告警逐条落 case_entries 的告警形状；无正式 owner 时只返回给调用方"""
        for ordinal, item in enumerate(warnings):
            reference = str(item.get("caseid") or item.get("code") or "unknown")[:255]
            message = str(item.get("message") or item)
            if record_id is not None:
                session.add(
                    CaseEntry(
                        entry_id=stable_uuid("case_save_warning", record_id, str(ordinal)),
                        warning_record_id=record_id,
                        warning_ordinal=ordinal,
                        attempted_case_reference=reference,
                        warning_message=message,
                    )
                )
            elif report_id is not None:
                session.add(
                    CaseEntry(
                        entry_id=stable_uuid("case_save_warning", report_id, str(ordinal)),
                        warning_report_id=report_id,
                        warning_ordinal=ordinal,
                        attempted_case_reference=reference,
                        warning_message=message,
                    )
                )
        session.flush()

    def save_work(
        self, session: Session, contribution: CaseContribution, *, adopted_output_id: str | None = None
    ) -> list[dict[str, Any]]:
        """登记案例是主体业务；可选交付单独 savepoint，失败不撤销正式产物"""
        from sqlalchemy.exc import DBAPIError

        frozen = contribution.snapshot()
        warnings: list[dict[str, Any]] = []
        failed_ids: set[str] = set()
        created_ids = set(frozen["created_case_ids"])
        record_id, report_id = self._formal_owner(session, contribution, adopted_output_id)

        def failed(case_id: str, exc: Exception) -> None:
            # 同一案例先失败者为准：登记失败不再由后续交付补一条误导性告警
            if case_id in failed_ids:
                return
            failed_ids.add(case_id)
            warnings.append({"code": "case_save_failed", "caseid": case_id, "message": str(exc)})

        for case_id in sorted(frozen["created_case_ids"]):
            case = frozen["registrations"][case_id]
            try:
                with session.begin_nested():
                    self._ensure_case_row(session, case, contribution)
            except (OSError, TimeoutError):
                raise
            except DBAPIError as exc:
                if (
                    exc.connection_invalidated
                    or str(getattr(exc.orig, "sqlstate", "")) not in _CASE_CONFLICT_SQLSTATES
                ):
                    raise
                failed(case_id, exc)
            except ValueError as exc:
                failed(case_id, exc)
        for case_id in sorted(frozen["registrations"]):
            facts = deepcopy([item for item in frozen["deliveries"] if item["case_id"] == case_id])
            try:
                with session.begin_nested():
                    state = session.get(BookCase, case_id, with_for_update=True)
                    # 本贡献新建案例的归属已由登记层校验；仅对既有案例要求真实支持证据
                    if state is None or (
                        case_id not in created_ids and not self._case_belongs(session, state)
                    ):
                        raise ValueError(f"case_id={case_id} 不属于当前 run")
                    self._save_support(session, state, contribution, facts)
            except (OSError, TimeoutError):
                raise
            except DBAPIError as exc:
                if (
                    exc.connection_invalidated
                    or str(getattr(exc.orig, "sqlstate", "")) not in _CASE_CONFLICT_SQLSTATES
                ):
                    raise
                failed(case_id, exc)
            except ValueError as exc:
                failed(case_id, exc)
        if warnings:
            self._save_warnings(session, record_id, report_id, warnings)
        self.save_warnings[contribution.author] = warnings
        return warnings

    def save_pending(
        self, session: Session, items: list[tuple[str, str, dict[str, Any]]], *, author: str
    ) -> list[str]:
        """章末程序登记结构化案例（case_type, description, payload）；事务由 Agent 提交，失败不能降成 warning

        调用方持 run 锁，并负责成功后的 confirm 和失败后的内存恢复
        """
        self.begin(author)
        cases = [
            self.register_case(case_type=case_type, description=description, payload=payload, author=author)
            for case_type, description, payload in items
        ]
        contribution = CaseContribution(
            run_id=self.run_id,
            author=author,
            snapshot_json=json.dumps(
                {
                    "created_case_ids": [case["case_id"] for case in cases],
                    "registrations": {case["case_id"]: case for case in cases},
                    "deliveries": [],
                },
                ensure_ascii=False,
            ),
        )
        warnings = self.save_work(session, contribution)
        if warnings:
            raise ValueError(f"章末案例未成功保存: {warnings}")
        return [case["case_id"] for case in cases]

    def confirm_pending(self, author: str) -> None:
        """程序登记案例已随事务保存：只标记作者保存完成，不改动承诺痕迹"""
        self.saved.add(author)
        self.stop(author)

    def _observation_for(self, session: Session, case: BookCase) -> CaseEntry | None:
        """案例引用的候选观察条目（未发布事件观察形状）"""
        if case.pending_event_entry_id is None:
            return None
        return session.get(CaseEntry, case.pending_event_entry_id)

    def _candidate_key_for(self, session: Session, case: BookCase) -> str | None:
        """对话候选键投影：按真实章节区间与原文重算 UUID5 算法"""
        if case.dialogue_candidate_chapter_id is None:
            return None
        chapter_text = session.scalar(
            select(Chapter.text).where(
                Chapter.run_id == self.run_id, Chapter.chapter_id == case.dialogue_candidate_chapter_id
            )
        )
        start = int(case.dialogue_candidate_start or 0)
        end = int(case.dialogue_candidate_end or 0)
        content = chapter_text[start:end] if chapter_text else ""
        return _dialogue_candidate_key(case.dialogue_candidate_chapter_id, start, end, content)

    def _delivery_dict(self, session: Session, delivery: CaseEntry, support: CaseEntry) -> dict[str, Any]:
        """交付条目读回内存形状：is_write/reads 由固定工具合同与真实交付投影"""
        connection_ids = [
            str(link_id)
            for link_id in session.scalars(
                select(CaseEntry.narrative_link_id).where(CaseEntry.parent_entry_id == delivery.entry_id)
            )
        ]
        is_write = _is_write_tool(str(delivery.tool_name or ""))
        receipt = _receipt_dict(delivery.receipt_bytes)
        return {
            "case_id": support.case_id,
            "call_id": delivery.business_call_id,
            "accepted_order": delivery.accepted_order,
            "connections": connection_ids,
            "reads": [] if is_write else [receipt],
            "tool_name": delivery.tool_name,
            "receipt": receipt,
            "is_write": is_write,
        }

    def _row_record(self, session: Session, case: BookCase) -> dict[str, Any]:
        """把 book_cases 行转成内存案例记录；payload 为具名列的确定性投影"""
        payload: dict[str, Any] = {}
        if case.entity_target_id is not None:
            payload["node_id"] = case.entity_target_id
        elif case.relation_target_id is not None:
            payload["node_id"] = case.relation_target_id
        elif case.automatic_declaration_id is not None:
            payload["event_id"] = case.automatic_declaration_id
        elif case.declaration_target_id is not None:
            payload["event_id"] = case.declaration_target_id
        elif case.complete_event_target_id is not None:
            payload["event_id"] = case.complete_event_target_id
        elif case.pending_event_entry_id is not None:
            observation = self._observation_for(session, case)
            if observation is not None:
                payload["event_id"] = observation.pending_event_reference
                payload["name"] = observation.pending_event_title
                payload["chapter_id"] = observation.pending_event_chapter_id
        elif case.dialogue_target_id is not None:
            payload["dialogue_id"] = case.dialogue_target_id
            record = session.get(DialogueRecord, case.dialogue_target_id)
            if record is not None:
                # 候选键存于正式对话记录，投影回来保证重载身份一致
                payload["candidate_key"] = record.candidate_key
        elif case.dialogue_candidate_chapter_id is not None:
            payload["chapter_id"] = case.dialogue_candidate_chapter_id
            payload["start"] = case.dialogue_candidate_start
            payload["end"] = case.dialogue_candidate_end
            candidate_key = self._candidate_key_for(session, case)
            if candidate_key is not None:
                payload["candidate_key"] = candidate_key
        if case.registration_reason:
            payload["reason"] = case.registration_reason
        if case.registration_paragraph_id is not None:
            payload["paragraph_id"] = case.registration_paragraph_id
        return {
            "case_id": case.case_id,
            "case_type": case.case_type,
            "description": case.description,
            "payload": payload,
        }

    def _clear(self) -> None:
        self.cases.clear()
        self.case_runtime.clear()
        self.registrations.clear()
        self.created.clear()
        self.deliveries.clear()
        self.saved.clear()
        self.executions.clear()
        self.save_warnings.clear()
        self._sequence = 0

    def _support_author(self, support: CaseEntry) -> str:
        """支持作者身份：程序形状是程序 work 身份，Agent 形状是真实执行号（单一字符串）"""
        if support.program_work_id is not None:
            return str(support.program_work_id)
        return str(support.producer_execution_id)

    def _load_cases(
        self, session: Session, *, discard: set[str] | None = None
    ) -> None:
        """从正式关系重建内存案例域

        discard 为空表示只读加载（诊断启动不改写任何行）；非空表示恢复：
        废弃执行的支持条目连同交付/连接一起删除，
        连接已失效的交付按规范链路 live 集合过滤，无支持的案例整体退场。
        """
        discard_executions = set(discard or ())
        case_ids = self._case_ids(session)
        if not case_ids:
            return
        cases = sorted(case_ids)
        supports = list(
            session.scalars(
                select(CaseEntry).where(
                    CaseEntry.case_id.in_(cases),
                    or_(
                        CaseEntry.producer_execution_id.is_not(None),
                        CaseEntry.program_work_id.is_not(None),
                    ),
                )
            )
        )
        pruned_supports: set[str] = set()
        if discard is not None:
            # 候选观察同样属于被废弃执行：先删引用它的案例行（RESTRICT），
            # 案例行级联带走其支持条目，再删观察条目
            observation_ids: set[str] = set()
            cascade_case_ids: set[str] = set()
            if discard_executions:
                observation_ids = set(
                    session.scalars(
                        select(CaseEntry.entry_id).where(
                            CaseEntry.candidate_producer_execution_id.in_(sorted(discard_executions))
                        )
                    )
                )
            if observation_ids:
                for case in session.scalars(
                    select(BookCase).where(BookCase.pending_event_entry_id.in_(sorted(observation_ids)))
                ):
                    cascade_case_ids.add(case.case_id)
                    session.delete(case)
                session.flush()
                for entry_id in sorted(observation_ids):
                    session.delete(session.get(CaseEntry, entry_id))
            live_links = (
                set(
                    session.scalars(
                        select(NarrativeLink.link_id).where(
                            NarrativeLink.producer_execution_id.in_(self._run_execution_ids(session))
                        )
                    )
                )
                if self._run_execution_ids(session)
                else set()
            )
            for support in supports:
                if support.case_id in cascade_case_ids:
                    # 已随案例行级联删除，不能再发第二次 DELETE
                    pruned_supports.add(support.entry_id)
                    continue
                if support.producer_execution_id in discard_executions:
                    session.delete(support)
                    pruned_supports.add(support.entry_id)
                    continue
                for delivery in session.scalars(
                    select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id)
                ):
                    connection_ids = set(
                        session.scalars(
                            select(CaseEntry.narrative_link_id).where(
                                CaseEntry.parent_entry_id == delivery.entry_id
                            )
                        )
                    )
                    if connection_ids and not connection_ids <= live_links:
                        session.delete(delivery)
            session.flush()
        kept: dict[str, list[CaseEntry]] = {}
        for support in supports:
            if support.entry_id in pruned_supports:
                continue
            # 支持条目必然属于某个案例（ck_case_entries_shape 支持形状 case_id 非空），
            # 且查询已按 case_id.in_(cases) 过滤
            kept.setdefault(cast(str, support.case_id), []).append(support)
        for case in session.scalars(select(BookCase).where(BookCase.case_id.in_(cases))):
            case_supports = kept.get(case.case_id, [])
            if not case_supports and case.pending_event_entry_id is None:
                if discard is not None:
                    session.delete(case)
                continue
            self.cases[case.case_id] = self._row_record(session, case)
            self.case_runtime[case.case_id] = {"promised": False, "owner": None}
            for support in case_supports:
                author = self._support_author(support)
                self.registrations.setdefault(author, set()).add(case.case_id)
                for delivery in session.scalars(
                    select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id)
                ):
                    self.deliveries.setdefault(author, []).append(
                        self._delivery_dict(session, delivery, support)
                    )
                    if str(delivery.tool_name or "") == "promise_case":
                        # 承诺痕迹：有承诺交付即已解决，没有即未解决
                        self.case_runtime[case.case_id]["promised"] = True
                    self._sequence = max(self._sequence, int(delivery.accepted_order or 0))
                self.saved.add(author)
        if discard is not None:
            session.flush()

    def load_storage(self, session: Session) -> None:
        """诊断启动仅加载已保存案例，不改写旧贡献或数据"""
        self._clear()
        self._load_cases(session)

    def restore_storage(self, session: Any, discard: set[str]) -> None:
        """启动恢复只保留本次实际存储事实，历史内存贡献和认领不能跨恢复继续使用"""
        self._clear()
        self._load_cases(session, discard=set(discard))

    def load_saved_work(self, session: Any, execution_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外读取当前作者实际保存的登记和交付，不恢复数据库认领"""
        record = session.get(ChapterAnnotation, annotation_id)
        if record is None or record.execution_id != execution_id:
            raise ValueError(f"案例保存身份不一致: {execution_id}")
        cases: dict[str, dict[str, str]] = {}
        deliveries: list[dict[str, Any]] = []
        supports = list(
            session.scalars(
                select(CaseEntry).where(
                    CaseEntry.producer_execution_id == execution_id, CaseEntry.case_id.is_not(None)
                )
            )
        )
        for support in supports:
            case = session.get(BookCase, support.case_id)
            if case is None:
                continue
            cases[case.case_id] = self._row_record(session, case)
            for delivery in session.scalars(
                select(CaseEntry).where(CaseEntry.parent_entry_id == support.entry_id)
            ):
                deliveries.append(self._delivery_dict(session, delivery, support))
        return {"author": execution_id, "registrations": cases, "deliveries": deliveries}

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内恢复单作者，其他在飞交付保持有效；承诺痕迹随交付重建"""
        author = str(snapshot["author"])
        old_cases = set(self.registrations.get(author, set()))
        self.registrations[author] = set(snapshot["registrations"])
        self.deliveries[author] = deepcopy(snapshot["deliveries"])
        self.saved.add(author)
        self.stop(author)
        for case_id, case in snapshot["registrations"].items():
            existing = self.cases.get(case_id)
            if existing is not None and self.case_identity(existing) != self.case_identity(case):
                raise ValueError(f"case_id={case_id} 已有另一份不可变说明")
            self.cases[case_id] = dict(case)
            self.case_runtime.setdefault(case_id, {"promised": False, "owner": None})
        promised_ids = {
            str(item["case_id"])
            for items in self.deliveries.values()
            for item in items
            if item.get("tool_name") == "promise_case"
        }
        for case_id in snapshot["registrations"]:
            if case_id in promised_ids:
                self.case_runtime[case_id]["promised"] = True
        supported = set().union(*self.registrations.values()) if self.registrations else set()
        for case_id in old_cases | set(snapshot["registrations"]):
            if case_id not in supported:
                self.cases.pop(case_id, None)
                self.case_runtime.pop(case_id, None)
                continue
            self._sequence = max(
                self._sequence,
                max(
                    (
                        int(item["accepted_order"])
                        for items in self.deliveries.values()
                        for item in items
                        if item["case_id"] == case_id
                    ),
                    default=0,
                ),
            )
