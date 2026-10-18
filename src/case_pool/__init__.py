"""全书案例池：人物/关系/对话/事件四类问题案例，业务内容含结构化 payload 与描述

2026-10-16 全库 3NF：旧 book_cases.payload/contributions/state JSON 退场
- book_cases 承接登记身份、明确目标（实体/关系/对话/声明/完整事件真实 FK）、
  对话候选与诊断失败候选定位、登记原因与独立评审状态
- case_entries 承接 Agent 支持→交付→连接层级（父父子固定深度）、保存告警与
  未发布事件的失败观察；连接的规范身份是 narrative_links.link_id（不读旧边）
- is_write / reads / resolved 由固定工具合同与真实采纳交付投影，不落重复列
"""

from __future__ import annotations

import json
import unicodedata
from copy import deepcopy
from typing import Any, cast
from uuid import NAMESPACE_DNS, uuid5

from src.case_pool.contributions import CaseContribution
from src.storage import Storage, new_id
from src.storage.records.models import BookCaseRecord as BookCase
from src.storage.records.models import CaseEntryRecord as CaseEntry
from src.utils.identity import stable_digest

CASE_TYPES = ("character", "relation", "dialogue", "event")
EVENT_CASE_TYPE = "event"
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
    """对话候选键投影：沿用原 UUID5(章号:起止:原文) 算法，不与区间重复存编码"""
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
        self._identifiers: dict[str, str] = {}
        self.cases: dict[str, dict[str, Any]] = {}
        self.case_runtime: dict[str, dict[str, Any]] = {}
        self.registrations: dict[str, set[str]] = {}
        self.created: dict[str, set[str]] = {}
        self.deliveries: dict[str, list[dict[str, Any]]] = {}
        self.saved: set[str] = set()
        self.executions: set[str] = set()
        self._sequence = 0
        self.save_warnings: dict[str, list[dict[str, Any]]] = {}

    def _case_id(self, case_type: str, normalized: str) -> str:
        """描述是登记去重键，数据库身份由 Storage 分配并独立保存"""
        for identifier, record in self.cases.items():
            if (
                record["case_type"] == case_type
                and record["description"] == normalized
                and (not record.get("automatic"))
            ):
                return identifier
        key = stable_digest(self.run_id, case_type, normalized)
        if key not in self._identifiers:
            self._identifiers[key] = new_id()
        return self._identifiers[key]

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
        """案例不可变身份：只比较新库真实保存的定位键与原因

        名字/类型/章号副本由正式目标推导（旧 payload 可推导副本取消），
        不参与身份比较；描述与案例 ID 的身份算法不变。
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
        case_id = self._case_id(case_type, normalized)
        self.cases.setdefault(
            case_id, {"case_id": case_id, "case_type": case_type, "description": normalized, "payload": {}}
        )
        self.case_runtime.setdefault(case_id, {"state": "pending", "owner": None})
        self.registrations[author].add(case_id)
        self.created[author].add(case_id)
        return dict(self.cases[case_id])

    def register_case(
        self, *, case_type: str, description: str, payload: dict[str, Any], author: str
    ) -> dict[str, Any]:
        """程序链登记结构化案例：按类型校验必填定位键，同键同内容幂等"""
        self._require(author)
        validated = _validate_registered_payload(case_type, payload)
        normalized = " ".join(unicodedata.normalize("NFC", description).split())
        if not normalized or len(normalized) > 100:
            raise ValueError(f"register_case.description={description!r}，期望非空普通文字且不超过 100 字")
        record: dict[str, Any] = {
            "case_id": self._case_id(case_type, normalized),
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
            self.case_runtime.setdefault(case_id, {"state": "pending", "owner": None})
        self.registrations[author].add(case_id)
        self.created[author].add(case_id)
        return dict(self.cases[case_id])

    def register_event_case(
        self, *, declaration_id: str, title: str, summary: str, status: str, chapter_id: int, author: str
    ) -> dict[str, Any]:
        """2026-10-15 用户裁定「建一个事件进一个池」：write_event 落地时由程序侧登记

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
        idempotence = (
            next(
                (
                    key
                    for key, item in self.cases.items()
                    if item.get("automatic") and (item.get("payload") or {}).get("event_id") == declaration_id
                ),
                None,
            )
            or new_id()
        )
        record: dict[str, Any] = {
            "case_id": idempotence,
            "automatic": True,
            "case_type": EVENT_CASE_TYPE,
            "description": normalized,
            "payload": payload,
        }
        existing = self.cases.get(idempotence)
        if existing is not None and self.case_identity(existing) != self.case_identity(record):
            raise ValueError(f"case_id={idempotence} 已有另一份不可变说明")
        if existing is None:
            self.cases[idempotence] = record
            self.case_runtime.setdefault(idempotence, {"state": "pending", "owner": None})
        self.registrations[author].add(idempotence)
        self.created[author].add(idempotence)
        return dict(self.cases[idempotence])

    def promise(self, case_id: str, author: str) -> dict[str, Any]:
        self._require(author)
        if case_id not in self.cases:
            raise ValueError(f"promise_case.case_id={case_id!r} 不存在；请取案例列表的真实 ID")
        runtime = self.case_runtime[case_id]
        active = next(
            (key for key, value in self.case_runtime.items() if value["owner"] == author and value.get("active")), None
        )
        if active is not None and active != case_id:
            raise ValueError(f"当前 active case_id={active}，先通过业务工具显式传 caseid 交付")
        if runtime["owner"] is not None and (runtime["owner"] != author or not runtime.get("active")):
            return {**self.cases[case_id], "status": "busy", "state": runtime["state"]}
        if runtime["state"] == "resolved":
            return {**self.cases[case_id], "status": "resolved", "state": "resolved"}
        runtime.update(owner=author, active=True)
        return {**self.cases[case_id], "status": "claimed", "state": runtime["state"]}

    def active(self, author: str) -> str | None:
        return next(
            (key for key, value in self.case_runtime.items() if value["owner"] == author and value.get("active")), None
        )

    def associate(
        self, caseid: Any, author: str, *, tool_name: str, call_id: str, receipt: dict[str, Any], is_write: bool
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
            if self.case_runtime[caseid]["owner"] != author:
                raise ValueError("当前执行尚未 promise 此 caseid，或已被其他执行认领")
            if receipt.get("status") in {"deferred", "rejected", "error", "runtime_error", "partial"}:
                raise ValueError("本次调用未形成有效产物，不登记交付")
            previous = next((item for item in self.deliveries[author] if item["call_id"] == call_id), None)
            if previous is not None and (
                previous["case_id"] != caseid
                or previous["tool_name"] != tool_name
                or previous["receipt"] != receipt
                or (previous["is_write"] != is_write)
            ):
                raise ValueError("同一工具调用 ID 已关联不同案例或产物，不能覆盖原交付")
            if previous is None:
                self._sequence += 1
                self.deliveries[author].append(
                    {
                        "case_id": caseid,
                        "state": "resolved" if is_write else "pending",
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
            if is_write:
                self.case_runtime[caseid]["active"] = False
            return {"status": "success", "caseid": caseid, "delivery": is_write}
        except Exception as exc:
            self.restore(snapshot)
            return {"status": "warning", "code": "case_association_failed", "caseid": caseid, "message": str(exc)}

    def stop(self, author: str) -> None:
        self.executions.discard(author)
        for runtime in self.case_runtime.values():
            if runtime["owner"] == author and runtime.get("active"):
                runtime.update(owner=None, active=False)

    def _saved_state(self, case_id: str) -> str:
        """只有已确认保存的有效写入能解决案例，后续读取不撤销交付"""
        return (
            "resolved"
            if any(
                fact["case_id"] == case_id and fact.get("is_write")
                for author in self.saved
                if case_id not in {item["caseid"] for item in self.save_warnings.get(author, [])}
                for fact in self.deliveries.get(author, [])
            )
            else "pending"
        )

    def confirm(self, execution_id: str) -> None:
        author = execution_id
        self.saved.add(author)
        self.stop(author)
        for runtime in self.case_runtime.values():
            if runtime["owner"] == author:
                runtime.update(owner=None, active=False)
        for caseid, runtime in self.case_runtime.items():
            runtime["state"] = self._saved_state(caseid)

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
                continue
            runtime = self.case_runtime[case_id]
            runtime["state"] = self._saved_state(case_id)
            if runtime["owner"] == author:
                runtime.update(owner=None, active=False)

    def snapshot(self, author: str) -> dict[str, Any]:
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
            {**case, "state": self.case_runtime[key]["state"], "busy": self.case_runtime[key]["owner"] is not None}
            for key, case in sorted(self.cases.items())
            if case_type is None or case.get("case_type") == case_type
        ]

    def _case_ids(self, storage: Storage) -> set[str]:
        """本 run 案例集合：无目标登记按真实运行；正式目标/候选观察按真实生产者身份"""
        return storage.cases.ids(self.run_id)

    def save_work(
        self, storage: Storage, contribution: CaseContribution, *, adopted_output_id: str | None = None
    ) -> list[dict[str, Any]]:
        """登记案例是主体业务；可选交付单独 savepoint，失败不撤销正式产物"""
        from src.storage.records.cases import CaseSave

        warnings = storage.cases.save(
            CaseSave(contribution.run_id, contribution.author, contribution.snapshot_json),
            adopted_output_id=adopted_output_id,
        )
        self.save_warnings[contribution.author] = warnings
        return warnings

    def save_pending(self, session: Storage, items: list[tuple[str, str, dict[str, Any]]], *, author: str) -> list[str]:
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

    def confirm_pending(self, author: str, states: dict[str, str]) -> None:
        """程序只新增登记支持，采用已提交状态，不撤销既有办理结果"""
        self.saved.add(author)
        self.stop(author)
        for case_id, state in states.items():
            self.case_runtime[case_id]["state"] = state

    def _observation_for(self, session: Storage, case: BookCase) -> CaseEntry | None:
        """案例引用的候选观察条目（未发布事件观察形状）"""
        if case.pending_event_entry_id is None:
            return None
        return session.reads.case_pool_pool_observation_for_1(case)

    def _candidate_key_for(self, session: Storage, case: BookCase) -> str | None:
        """对话候选键投影：按真实章节区间与原文重算原 UUID5 算法"""
        if case.dialogue_candidate_chapter_id is None:
            return None
        chapter_text = session.reads.case_pool_pool_candidate_key_for_1(case, self.run_id)
        start = int(case.dialogue_candidate_start or 0)
        end = int(case.dialogue_candidate_end or 0)
        content = chapter_text[start:end] if chapter_text else ""
        return _dialogue_candidate_key(case.dialogue_candidate_chapter_id, start, end, content)

    def _delivery_dict(self, session: Storage, delivery: CaseEntry, support: CaseEntry) -> dict[str, Any]:
        """交付条目读回内存形状：is_write/reads/resolved 由固定工具合同与真实交付投影"""
        connection_ids = [str(link_id) for link_id in session.reads.case_pool_pool_delivery_dict_1(delivery)]
        is_write = _is_write_tool(str(delivery.tool_name or ""))
        receipt = _receipt_dict(delivery.receipt_bytes)
        return {
            "case_id": support.case_id,
            "state": "resolved" if is_write else "pending",
            "call_id": delivery.business_call_id,
            "accepted_order": delivery.accepted_order,
            "connections": connection_ids,
            "reads": [] if is_write else [receipt],
            "tool_name": delivery.tool_name,
            "receipt": receipt,
            "is_write": is_write,
        }

    def _row_record(self, session: Storage, case: BookCase) -> dict[str, Any]:
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
            record = session.reads.case_pool_pool_row_record_1(case)
            if record is not None:
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
            "automatic": case.automatic_declaration_id is not None,
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

    def _load_cases(self, session: Storage, *, discard: set[str] | None = None) -> None:
        """从正式关系重建内存案例域

        discard 为空表示只读加载（诊断启动不改写任何行）；非空表示恢复：
        废弃执行的支持条目连同交付/连接一起删除（承接旧贡献丢失语义），
        连接已失效的交付按规范链路 live 集合过滤，无支持的案例整体退场。
        """
        case_ids = self._case_ids(session)
        if not case_ids:
            return
        cases = sorted(case_ids)
        supports = list(session.reads.case_pool_pool_load_cases_2(cases))
        kept: dict[str, list[CaseEntry]] = {}
        for support in supports:
            kept.setdefault(cast(str, support.case_id), []).append(support)
        for case in session.reads.case_pool_pool_load_cases_1(cases):
            case_supports = kept.get(case.case_id, [])
            if not case_supports and case.pending_event_entry_id is None:
                continue
            self.cases[case.case_id] = self._row_record(session, case)
            resolved = any(bool(support.adopted) for support in case_supports)
            self.case_runtime[case.case_id] = {
                "state": "resolved" if resolved else "pending",
                "owner": None,
                "active": False,
            }
            for support in case_supports:
                author = self._support_author(support)
                self.registrations.setdefault(author, set()).add(case.case_id)
                for delivery in session.reads.case_pool_pool_load_cases_5(support):
                    self.deliveries.setdefault(author, []).append(self._delivery_dict(session, delivery, support))
                    self._sequence = max(self._sequence, int(delivery.accepted_order or 0))
                self.saved.add(author)

    def load_storage(self, session: Storage) -> None:
        """诊断启动仅加载已保存案例，不改写旧贡献或数据"""
        self._clear()
        self._load_cases(session)

    def restore_storage(self, session: Any, discard: set[str]) -> None:
        """启动恢复只保留本次实际存储事实，历史内存贡献和认领不能跨恢复继续使用"""
        self._clear()
        self._load_cases(session, discard=set(discard))

    def load_saved_work(self, session: Any, execution_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外读取当前作者实际保存的登记和交付，不恢复数据库认领"""
        record = session.reads.case_pool_pool_load_saved_work_1(annotation_id)
        if record is None or record.execution_id != execution_id:
            raise ValueError(f"案例保存身份不一致: {execution_id}")
        cases: dict[str, dict[str, str]] = {}
        deliveries: list[dict[str, Any]] = []
        supports = list(session.reads.case_pool_pool_load_saved_work_2(execution_id))
        for support in supports:
            case = session.reads.case_pool_pool_load_saved_work_3(support)
            if case is None:
                continue
            cases[case.case_id] = self._row_record(session, case)
            for delivery in session.reads.case_pool_pool_load_saved_work_4(support):
                deliveries.append(self._delivery_dict(session, delivery, support))
        return {"author": execution_id, "registrations": cases, "deliveries": deliveries}

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内恢复单作者，其他在飞交付与排他占用保持有效"""
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
            self.case_runtime.setdefault(case_id, {"state": "pending", "owner": None, "active": False})
        supported = set().union(*self.registrations.values()) if self.registrations else set()
        for case_id in old_cases | set(snapshot["registrations"]):
            if case_id not in supported:
                self.cases.pop(case_id, None)
                self.case_runtime.pop(case_id, None)
                continue
            facts = [
                (source, item)
                for source, items in self.deliveries.items()
                for item in items
                if item["case_id"] == case_id
            ]
            latest = max(facts, key=lambda pair: pair[1]["accepted_order"], default=None)
            runtime = self.case_runtime[case_id]
            runtime["state"] = self._saved_state(case_id)
            if latest and latest[0] == author and (latest[1]["state"] == "resolved") and (runtime["owner"] is None):
                runtime.update(owner=author, active=False)
            self._sequence = max(self._sequence, max((item["accepted_order"] for _, item in facts), default=0))
