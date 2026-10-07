"""全书描述式案例与当前认领，业务内容只含案例 ID 和说明"""

from __future__ import annotations

import unicodedata
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from src.case_pool.contributions import CaseContribution
from src.utils.identity import stable_digest


class CasePool:
    """由 agent 在同一 run 锁内调用；交付接受顺序与数据库保存顺序分离"""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.cases: dict[str, dict[str, str]] = {}
        self.case_runtime: dict[str, dict[str, Any]] = {}
        self.registrations: dict[tuple[str, str], set[str]] = {}
        self.deliveries: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.saved: set[tuple[str, str]] = set()
        self.executions: set[tuple[str, str]] = set()
        self._sequence = 0

    def begin(self, work_id: str, invocation_id: str) -> None:
        author = (work_id, invocation_id)
        self.executions.add(author)
        self.registrations.setdefault(author, set())
        self.deliveries.setdefault(author, [])

    def _require(self, author: tuple[str, str]) -> None:
        if author not in self.executions:
            raise ValueError(f"案例执行已停止: {author}")

    def push(self, description: str, author: tuple[str, str]) -> dict[str, str]:
        self._require(author)
        normalized = " ".join(unicodedata.normalize("NFC", description).split())
        if not normalized or len(normalized) > 100:
            raise ValueError(f"push_case.description={description!r}，期望非空普通文字且不超过 100 字")
        case_id = stable_digest(self.run_id, normalized)
        self.cases.setdefault(case_id, {"case_id": case_id, "description": normalized})
        self.case_runtime.setdefault(case_id, {"state": "pending", "owner": None})
        self.registrations[author].add(case_id)
        return dict(self.cases[case_id])

    def promise(self, case_id: str, author: tuple[str, str]) -> dict[str, Any]:
        self._require(author)
        if case_id not in self.cases:
            raise ValueError(f"promise_case.case_id={case_id!r} 不存在；请取案例列表的真实 ID")
        runtime = self.case_runtime[case_id]
        active = next(
            (key for key, value in self.case_runtime.items() if value["owner"] == author and value.get("active")), None
        )
        if active is not None and active != case_id:
            raise ValueError(f"当前 active case_id={active}，先 finish(case_delivery=..., complete=False)")
        if runtime["owner"] is not None and (runtime["owner"] != author or not runtime.get("active")):
            return {**self.cases[case_id], "status": "busy", "state": runtime["state"]}
        if runtime["state"] == "resolved":
            return {**self.cases[case_id], "status": "resolved", "state": "resolved"}
        runtime.update(owner=author, active=True)
        return {**self.cases[case_id], "status": "claimed", "state": runtime["state"]}

    def active(self, author: tuple[str, str]) -> str | None:
        return next(
            (key for key, value in self.case_runtime.items() if value["owner"] == author and value.get("active")), None
        )

    def deliver(
        self,
        delivery: dict[str, Any],
        author: tuple[str, str],
        *,
        call_id: str,
        connections: list[str],
        reads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._require(author)
        previous = next((item for item in self.deliveries[author] if item["call_id"] == call_id), None)
        if previous is not None:
            return deepcopy(previous)
        if set(delivery) != {"case_id", "state", "reason"}:
            raise ValueError("case_delivery 只接受 case_id/state/reason")
        case_id, state, reason = delivery["case_id"], delivery["state"], delivery["reason"]
        if (
            state not in {"pending", "resolved", "deferred", "contested"}
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError(f"case_delivery state={state!r} reason={reason!r}，期望合法状态与非空办理结论")
        if self.active(author) != case_id:
            raise ValueError(f"case_delivery.case_id={case_id!r}，当前实际 active={self.active(author)!r}")
        if state == "resolved" and not connections and not reads:
            raise ValueError(f"case_id={case_id} resolved 缺少实际有效连接或当前执行的实际读取")
        self._sequence += 1
        # 此为案例域的办理事实，既不是案例内容，也不是隐藏的待执行意图
        accepted = {
            "case_id": case_id,
            "state": state,
            "call_id": call_id,
            "accepted_order": self._sequence,
            "connections": list(connections),
            "reads": deepcopy(reads),
            "reason": reason,
        }
        self.deliveries[author].append(accepted)
        self.registrations[author].add(case_id)
        self.case_runtime[case_id].update(state=state, active=False, owner=author if state == "resolved" else None)
        return deepcopy(accepted)

    def stop(self, author: tuple[str, str]) -> None:
        self.executions.discard(author)

    def confirm(self, work_id: str, invocation_id: str) -> None:
        author = (work_id, invocation_id)
        self.saved.add(author)
        self.stop(author)
        for runtime in self.case_runtime.values():
            if runtime["owner"] == author:
                runtime.update(owner=None, active=False)

    def rollback(self, work_id: str, invocation_id: str) -> None:
        author = (work_id, invocation_id)
        if author in self.saved:
            return
        self.stop(author)
        self.registrations.pop(author, None)
        self.deliveries.pop(author, None)
        supported = set().union(*self.registrations.values()) if self.registrations else set()
        for case_id in list(self.cases):
            if case_id not in supported:
                self.cases.pop(case_id)
                self.case_runtime.pop(case_id)
                continue
            facts = [item for items in self.deliveries.values() for item in items if item["case_id"] == case_id]
            latest = max(facts, key=lambda item: item["accepted_order"], default=None)
            runtime = self.case_runtime[case_id]
            runtime["state"] = latest["state"] if latest else "pending"
            if runtime["owner"] == author:
                runtime.update(owner=None, active=False)

    def snapshot(self, author: tuple[str, str]) -> dict[str, Any]:
        # 单条操作由 agent 持锁，快照只覆盖本操作可能改动的案例域
        return deepcopy(
            {
                "cases": self.cases,
                "case_runtime": self.case_runtime,
                "registrations": self.registrations,
                "deliveries": self.deliveries,
                "sequence": self._sequence,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.cases = snapshot["cases"]
        self.case_runtime = snapshot["case_runtime"]
        self.registrations = snapshot["registrations"]
        self.deliveries = snapshot["deliveries"]
        self._sequence = snapshot["sequence"]

    def search(self) -> list[dict[str, Any]]:
        return [
            {**case, "state": self.case_runtime[key]["state"], "busy": self.case_runtime[key]["owner"] is not None}
            for key, case in sorted(self.cases.items())
        ]

    def save_work(self, session: Session, contribution: CaseContribution) -> None:
        from sqlalchemy.dialects.postgresql import insert

        from src.storage.models import BookCase, EventEdge

        frozen = contribution.snapshot()
        for case_id, case in sorted(frozen["registrations"].items()):
            session.execute(insert(BookCase).values(run_id=self.run_id, **case).on_conflict_do_nothing())
            session.flush()
            state = session.get(BookCase, case_id, with_for_update=True)
            if state is None:
                raise ValueError(f"case_id={case_id} 案例行插入未生效")
            facts = deepcopy([item for item in frozen["deliveries"] if item["case_id"] == case_id])
            for fact in facts:
                if fact["state"] == "resolved" and any(
                    session.get(EventEdge, key) is None for key in fact["connections"]
                ):
                    raise ValueError(f"case_id={case_id} resolved 的连接尚未成功保存")
            contributions = dict(state.contributions)
            contributions.setdefault(
                contribution.work_id, {"invocation_id": contribution.invocation_id, "deliveries": facts}
            )
            state.contributions = contributions
            all_facts = [item for source in contributions.values() for item in source["deliveries"]]
            latest = max(all_facts, key=lambda item: item["accepted_order"], default=None)
            state.state = latest["state"] if latest else "pending"

    def restore_storage(self, session: Any, discard: set[str]) -> None:
        from sqlalchemy import select

        from src.storage.models import BookCase, EventEdge

        # 启动恢复只保留本次实际存储事实，历史内存贡献和认领不能跨恢复继续使用
        self.cases.clear()
        self.case_runtime.clear()
        self.registrations.clear()
        self.deliveries.clear()
        self.saved.clear()
        self.executions.clear()
        self._sequence = 0
        live_edges = set(session.execute(select(EventEdge.edge_id).where(EventEdge.run_id == self.run_id)).scalars())
        for case in session.execute(select(BookCase).where(BookCase.run_id == self.run_id)).scalars().all():
            contributions = {key: deepcopy(value) for key, value in case.contributions.items() if key not in discard}
            if not contributions:
                session.delete(case)
                continue
            for value in contributions.values():
                value["deliveries"] = [
                    fact
                    for fact in value["deliveries"]
                    if not fact["connections"] or set(fact["connections"]) <= live_edges
                ]
            case.contributions = contributions
            facts = [fact for value in contributions.values() for fact in value["deliveries"]]
            latest = max(facts, key=lambda item: item["accepted_order"], default=None)
            case.state = latest["state"] if latest else "pending"
            self.cases[case.case_id] = {"case_id": case.case_id, "description": case.description}
            self.case_runtime[case.case_id] = {"state": case.state, "owner": None, "active": False}
            for work_id, value in contributions.items():
                author = (work_id, value["invocation_id"])
                self.registrations.setdefault(author, set()).add(case.case_id)
                self.deliveries.setdefault(author, []).extend(value["deliveries"])
                self.saved.add(author)
            self._sequence = max(self._sequence, max((item["accepted_order"] for item in facts), default=0))
        session.flush()

    def load_saved_work(self, session: Any, work_id: str, invocation_id: str, annotation_id: str) -> dict[str, Any]:
        """锁外读取当前作者实际保存的登记和交付，不恢复数据库认领"""
        from sqlalchemy import select

        from src.storage.models import AnalysisOutput, BookCase

        record = session.get(AnalysisOutput, annotation_id)
        if record is None or record.work_id != work_id or record.invocation_id != invocation_id:
            raise ValueError(f"案例保存身份不一致: {work_id}/{invocation_id}")
        cases: dict[str, dict[str, str]] = {}
        deliveries: list[dict[str, Any]] = []
        for case in session.execute(select(BookCase).where(BookCase.run_id == self.run_id)).scalars():
            contribution = case.contributions.get(work_id)
            if contribution is None:
                continue
            if contribution["invocation_id"] != invocation_id:
                raise ValueError(f"case_id={case.case_id} 保存 invocation 不一致: {contribution['invocation_id']}")
            cases[case.case_id] = {"case_id": case.case_id, "description": case.description}
            deliveries.extend(deepcopy(contribution["deliveries"]))
        return {"author": (work_id, invocation_id), "registrations": cases, "deliveries": deliveries}

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        """同 run 锁内恢复单作者，其他在飞交付与排他占用保持有效"""
        author = tuple(snapshot["author"])
        old_cases = set(self.registrations.get(author, set()))
        self.registrations[author] = set(snapshot["registrations"])
        self.deliveries[author] = deepcopy(snapshot["deliveries"])
        self.saved.add(author)
        self.stop(author)
        for case_id, case in snapshot["registrations"].items():
            existing = self.cases.get(case_id)
            if existing is not None and existing != case:
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
            runtime["state"] = latest[1]["state"] if latest else "pending"
            # 部分确认可能先释放了本作者占用，重建到再次确认；不能覆盖别人的认领
            if latest and latest[0] == author and latest[1]["state"] == "resolved" and runtime["owner"] is None:
                runtime.update(owner=author, active=False)
            self._sequence = max(self._sequence, max((item["accepted_order"] for _, item in facts), default=0))
