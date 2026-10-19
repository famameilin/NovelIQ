"案例登记、承诺与正式保存的领域状态"

from __future__ import annotations

import json
import unicodedata
from copy import deepcopy
from typing import Any

from src.case_pool.contributions import CaseContribution
from src.storage import Storage, new_id
from src.storage.records.kinds import CASE_TYPES


class CasePool:
    "每个案例一条记录，承诺即视为解决"

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.cases: dict[str, dict[str, Any]] = {}
        self.case_runtime: dict[str, dict[str, Any]] = {}
        self.registrations: dict[str, set[str]] = {}
        self.created: dict[str, set[str]] = {}
        self.executions: set[str] = set()
        self.saved: set[str] = set()
        self.save_warnings: dict[str, list[dict[str, Any]]] = {}

    def begin(self, execution_id: str) -> None:
        self.executions.add(execution_id)
        self.registrations.setdefault(execution_id, set())
        self.created.setdefault(execution_id, set())

    def _require(self, author: str) -> None:
        if author not in self.executions:
            raise ValueError("案例操作缺少活动写出者")

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
            self.case_runtime[case_id] = {"promised": False, "owner": None}
            self.created[author].add(case_id)
        self.registrations[author].add(case_id)
        return dict(self.cases[case_id])

    def register_case(self, *, case_type: str, description: str, author: str) -> dict[str, Any]:
        "程序登记普通文字案例"
        return self.push(case_type, description, author)

    def register_event_case(self, *, title: str, summary: str, author: str) -> dict[str, Any]:
        "正式事件生成链登记待办理案例"
        return self.push("event", f"{title.strip()}：{summary.strip()}"[:100], author)

    def promise(self, case_id: str, author: str) -> dict[str, Any]:
        "承诺即视为解决，不执行额外完成度核对"
        self._require(author)
        if case_id not in self.cases:
            raise ValueError("案例不属于当前运行")
        runtime = self.case_runtime[case_id]
        if runtime["promised"]:
            return {**self.cases[case_id], "status": "taken"}
        runtime.update(promised=True, owner=author)
        self.registrations[author].add(case_id)
        return {**self.cases[case_id], "status": "promised"}

    def stop(self, author: str) -> None:
        self.executions.discard(author)

    def confirm(self, execution_id: str) -> None:
        self.saved.add(execution_id)
        self.stop(execution_id)

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
                runtime.update(promised=False, owner=None)

    def snapshot(self, author: str) -> dict[str, Any]:
        return deepcopy(
            {
                "cases": self.cases,
                "case_runtime": self.case_runtime,
                "registrations": self.registrations,
                "created": self.created,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.cases = snapshot["cases"]
        self.case_runtime = snapshot["case_runtime"]
        self.registrations = snapshot["registrations"]
        self.created = snapshot["created"]

    def promises_for(self, author: str) -> list[str]:
        return sorted(key for key, value in self.case_runtime.items() if value["promised"] and value["owner"] == author)

    def search(self, case_type: str | None = None) -> list[dict[str, Any]]:
        return [
            {**case, "promised": bool(self.case_runtime[key]["promised"])}
            for key, case in sorted(self.cases.items())
            if case_type is None or case["case_type"] == case_type
        ]

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
                {"registrations": {case["case_id"]: case for case in records}, "promises": []}, ensure_ascii=False
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
        self.cases.clear()
        self.case_runtime.clear()
        for row in session.cases.rows(self.run_id):
            self.cases[row.id] = {"case_id": row.id, "case_type": row.type, "description": row.description}
            self.case_runtime[row.id] = {"promised": row.status == "resolved", "owner": row.promised_agent_id}

    def restore_storage(self, session: Storage, discard: set[str]) -> None:
        self.load_storage(session)

    def load_saved_work(self, session: Storage, execution_id: str, annotation_id: str) -> dict[str, Any]:
        rows = session.cases.rows(self.run_id)
        records = {
            row.id: {"case_id": row.id, "case_type": row.type, "description": row.description}
            for row in rows
            if row.producer_agent_id == execution_id or row.promised_agent_id == execution_id
        }
        promises = [row.id for row in rows if row.promised_agent_id == execution_id]
        return {"author": execution_id, "registrations": records, "promises": promises}

    def recover_work(self, snapshot: dict[str, Any]) -> None:
        author = snapshot["author"]
        self.begin(author)
        for key, case in snapshot["registrations"].items():
            self.cases[key] = dict(case)
            self.case_runtime.setdefault(key, {"promised": False, "owner": None})
            self.registrations[author].add(key)
        for key in snapshot.get("promises", []):
            runtime = self.case_runtime[key]
            if runtime["owner"] not in (None, author):
                raise ValueError("已保存案例承诺与当前持有者冲突")
            runtime.update(promised=True, owner=author)
        self.confirm(author)
