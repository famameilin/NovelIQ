"案例登记、独占领取、提交与正式保存的领域状态"

from __future__ import annotations

import json
import random
import threading
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from functools import wraps
from typing import Any, ClassVar, Concatenate
from weakref import WeakValueDictionary

from src.case_pool.contributions import CaseContribution
from src.storage import Storage, new_id
from src.storage.records.kinds import CASE_TYPES


def _locked[**P, T](method: Callable[Concatenate[CasePool, P], T]) -> Callable[Concatenate[CasePool, P], T]:
    @wraps(method)
    def invoke(self: CasePool, *args: P.args, **kwargs: P.kwargs) -> T:
        with self.lock:
            return method(self, *args, **kwargs)

    return invoke


class CasePool:
    "同进程同 run 共享案例与锁，每件案例由单个执行独占领取"

    _instances: ClassVar[WeakValueDictionary[str, CasePool]] = WeakValueDictionary()
    _instances_lock: ClassVar = threading.RLock()

    def __new__(cls, run_id: str) -> CasePool:
        with cls._instances_lock:
            instance = cls._instances.get(run_id)
            if instance is None:
                instance = super().__new__(cls)
                cls._instances[run_id] = instance
            return instance

    def __init__(self, run_id: str):
        with self._instances_lock:
            if hasattr(self, "run_id"):
                return
            self.lock = threading.RLock()
            self.run_id = run_id
            self.cases: dict[str, dict[str, Any]] = {}
            self.case_runtime: dict[str, dict[str, Any]] = {}
            self.registrations: dict[str, set[str]] = {}
            self.created: dict[str, set[str]] = {}
            self.executions: set[str] = set()
            self.saved: set[str] = set()
            self.save_warnings: dict[str, list[dict[str, Any]]] = {}

    @_locked
    def begin(self, execution_id: str) -> None:
        self.executions.add(execution_id)
        self.registrations.setdefault(execution_id, set())
        self.created.setdefault(execution_id, set())

    def _require(self, author: str) -> None:
        if author not in self.executions:
            raise ValueError("案例操作缺少活动写出者")

    @_locked
    def push(self, case_type: str, description: str, author: str) -> dict[str, Any]:
        "登记普通文字案例，不保存目标或候选元数据"
        self._require(author)
        if case_type not in CASE_TYPES:
            raise ValueError(f"案例类型必须为 {CASE_TYPES}")
        normalized = " ".join(unicodedata.normalize("NFC", description).split())
        if not normalized or len(normalized) > 100:
            raise ValueError("案例描述必须为非空普通文字且不超过 100 字")
        case_id = next(
            (
                key
                for key, item in self.cases.items()
                if item["case_type"] == case_type and item["description"] == normalized
            ),
            None,
        )
        if case_id is None:
            case_id = new_id()
            self.cases[case_id] = {"case_id": case_id, "case_type": case_type, "description": normalized}
            self.case_runtime[case_id] = {"submitted": False, "owner": None}
            self.created[author].add(case_id)
        self.registrations[author].add(case_id)
        return dict(self.cases[case_id])

    def register_case(self, *, case_type: str, description: str, author: str) -> dict[str, Any]:
        "程序登记普通文字案例"
        return self.push(case_type, description, author)

    @_locked
    def merge_committed(self, rows: list[dict[str, Any]]) -> None:
        "增量发布正式提交，保留其他活动执行尚未保存的领取"
        for row in rows:
            identifier = row["case_id"]
            self.cases.setdefault(identifier, {key: row[key] for key in ("case_id", "case_type", "description")})
            runtime = self.case_runtime.setdefault(identifier, {"submitted": False, "owner": None})
            if row["submitted"]:
                runtime.update(submitted=True, owner=row["owner"])

    @_locked
    def claim(self, case_id: str, author: str) -> dict[str, Any]:
        "独占领取指定案例，领取不代表办结"
        self._require(author)
        if case_id not in self.cases:
            raise ValueError("案例不属于当前运行")
        runtime = self.case_runtime[case_id]
        if runtime["owner"] is not None:
            status = "submitted" if runtime["submitted"] else "claimed"
            return {**self.cases[case_id], "status": status if runtime["owner"] == author else "taken"}
        runtime.update(owner=author)
        self.registrations[author].add(case_id)
        return {**self.cases[case_id], "status": "claimed"}

    @_locked
    def claim_random(self, author: str) -> dict[str, Any]:
        "原子随机领取一件尚未被持有的案例，池空返回 empty"
        self._require(author)
        pending = [key for key, runtime in self.case_runtime.items()
                   if not runtime["submitted"] and runtime["owner"] is None]
        return self.claim(random.choice(pending), author) if pending else {"status": "empty"}

    @_locked
    def submit(self, case_id: str, author: str) -> dict[str, Any]:
        "持有者显式提交办结，正式保存前仍可随失败执行撤销"
        self._require(author)
        runtime = self.case_runtime.get(case_id)
        if runtime is None or runtime["owner"] != author:
            raise ValueError("只能提交当前执行已领取的案例")
        runtime["submitted"] = True
        available = [key for key, value in self.case_runtime.items()
                     if not value["submitted"] and value["owner"] is None]
        candidates = [dict(self.cases[key]) for key in random.sample(available, min(10, len(available)))]
        return {**self.cases[case_id], "status": "submitted", "candidates": candidates}

    @_locked
    def counts(self) -> tuple[int, int]:
        "返回可领取与已提交案例数量"
        available = sum(not value["submitted"] and value["owner"] is None for value in self.case_runtime.values())
        submitted = sum(bool(value["submitted"]) for value in self.case_runtime.values())
        return available, submitted

    @_locked
    def unsubmitted_for(self, author: str | None = None) -> list[str]:
        "返回已领取但未提交的案例，作者留空时检查整个案例池"
        return sorted(key for key, value in self.case_runtime.items()
                      if not value["submitted"] and value["owner"] is not None
                      and (author is None or value["owner"] == author))

    @_locked
    def claims_for(self, author: str) -> list[str]:
        "返回当前执行领取的案例，包含已提交但尚未保存的案例"
        return sorted(key for key, value in self.case_runtime.items() if value["owner"] == author)

    @_locked
    def stop(self, author: str) -> None:
        self.executions.discard(author)

    @_locked
    def confirm(self, execution_id: str) -> None:
        for runtime in self.case_runtime.values():
            if runtime["owner"] == execution_id and not runtime["submitted"]:
                runtime.update(owner=None)
        self.saved.add(execution_id)
        self.stop(execution_id)

    @_locked
    def abandon(self, execution_id: str) -> None:
        "保留登记并释放未保存执行的领取与提交"
        if execution_id in self.saved:
            return
        for runtime in self.case_runtime.values():
            if runtime["owner"] == execution_id:
                runtime.update(submitted=False, owner=None)
        self.stop(execution_id)

    @_locked
    def rollback(self, execution_id: str) -> None:
        if execution_id in self.saved:
            return
        self.stop(execution_id)
        self.registrations.pop(execution_id, None)
        created = self.created.pop(execution_id, set())
        retained = set().union(*self.registrations.values()) if self.registrations else set()
        for case_id in created - retained:
            runtime = self.case_runtime.get(case_id)
            if runtime is not None and runtime["owner"] not in (None, execution_id):
                continue
            self.cases.pop(case_id, None)
            self.case_runtime.pop(case_id, None)
        for runtime in self.case_runtime.values():
            if runtime["owner"] == execution_id:
                runtime.update(submitted=False, owner=None)

    @_locked
    def snapshot(self, author: str) -> dict[str, Any]:
        return deepcopy(
            {
                "author": author,
                "active": author in self.executions,
                "cases": self.cases,
                "case_runtime": self.case_runtime,
                "registrations": self.registrations,
                "created": self.created,
            }
        )

    @_locked
    def restore(self, snapshot: dict[str, Any]) -> None:
        "仅恢复当前作者的未保存改动，保留其他执行的登记与领取"
        author = snapshot["author"]
        if author in self.saved:
            return
        prior_created = snapshot["created"].get(author, set())
        other_registrations = set().union(*(v for key, v in self.registrations.items() if key != author))
        for key in self.created.get(author, set()) - prior_created - other_registrations:
            if self.case_runtime[key]["owner"] in (None, author):
                self.cases.pop(key, None)
                self.case_runtime.pop(key, None)
        for key, runtime in self.case_runtime.items():
            prior = snapshot["case_runtime"].get(key, {})
            if runtime["owner"] == author:
                runtime.update(submitted=False, owner=None)
            if prior.get("owner") == author and runtime["owner"] in (None, author):
                runtime.update(prior)
        self.registrations[author] = set(snapshot["registrations"].get(author, set()))
        self.created[author] = set(prior_created)
        if not snapshot["active"]:
            self.stop(author)

    @_locked
    def submissions_for(self, author: str) -> list[str]:
        return sorted(key for key, value in self.case_runtime.items()
                      if value["submitted"] and value["owner"] == author)

    @_locked
    def search(self, case_type: str | None = None) -> list[dict[str, Any]]:
        return [
            {**case, "claimed": self.case_runtime[key]["owner"] is not None,
             "submitted": bool(self.case_runtime[key]["submitted"])}
            for key, case in sorted(self.cases.items())
            if case_type is None or case["case_type"] == case_type
        ]

    @_locked
    def contribution(self, author: str) -> dict[str, Any]:
        "冻结当前执行的登记与显式提交，不保存未提交领取"
        return deepcopy({
            "created_case_ids": sorted(self.created.get(author, set())),
            "registrations": {key: self.cases[key] for key in self.registrations.get(author, set())},
            "submissions": self.submissions_for(author),
        })

    def _case_ids(self, storage: Storage) -> set[str]:
        return storage.cases.ids(self.run_id)

    def save_work(
        self, storage: Storage, contribution: CaseContribution, *, adopted_output_id: str | None = None
    ) -> list[dict[str, Any]]:
        from src.storage.records.cases import CaseSave

        warnings = storage.cases.save(
            CaseSave(contribution.run_id, contribution.author, contribution.snapshot_json),
            adopted_output_id=adopted_output_id,
        )
        self.save_warnings[contribution.author] = warnings
        return warnings

    def save_pending(self, session: Storage, items: list[tuple[str, str]], *, author: str) -> list[str]:
        self.begin(author)
        records = [self.register_case(case_type=kind, description=text, author=author) for kind, text in items]
        contribution = CaseContribution(
            self.run_id,
            author,
            json.dumps(
                {"registrations": {case["case_id"]: case for case in records}, "submissions": []}, ensure_ascii=False
            ),
        )
        from src.storage.records.cases import CaseSave

        warnings = session.cases.save(CaseSave(self.run_id, None, contribution.snapshot_json))
        if warnings:
            raise ValueError(f"案例保存失败: {warnings}")
        return [case["case_id"] for case in records]

    def confirm_pending(self, author: str) -> None:
        self.confirm(author)

    def load_storage(self, session: Storage) -> None:
        rows = session.cases.rows(self.run_id)
        self.merge_committed([
            {"case_id": row.id, "case_type": row.type, "description": row.description,
             "submitted": row.status == "resolved", "owner": row.promised_agent_id}
            for row in rows
        ])

    def restore_storage(self, session: Storage, discard: set[str]) -> None:
        for author in discard:
            self.rollback(author)
        self.load_storage(session)

    def load_saved_work(self, session: Storage, execution_id: str, annotation_id: str) -> dict[str, Any]:
        rows = session.cases.rows(self.run_id)
        records = {
            row.id: {"case_id": row.id, "case_type": row.type, "description": row.description}
            for row in rows
            if row.producer_agent_id == execution_id or row.promised_agent_id == execution_id
        }
        submissions = [row.id for row in rows if row.promised_agent_id == execution_id]
        return {"author": execution_id, "registrations": records, "submissions": submissions}

    @_locked
    def recover_work(self, snapshot: dict[str, Any]) -> None:
        author = snapshot["author"]
        self.begin(author)
        for key, case in snapshot["registrations"].items():
            self.cases[key] = dict(case)
            self.case_runtime.setdefault(key, {"submitted": False, "owner": None})
            self.registrations[author].add(key)
        for key in snapshot.get("submissions", []):
            runtime = self.case_runtime[key]
            if runtime["owner"] not in (None, author):
                raise ValueError("已保存案例提交与当前持有者冲突")
            runtime.update(submitted=True, owner=author)
        self.confirm(author)
