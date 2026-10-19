"七字段案例的登记与承诺保存"

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import Agent, Case


class CaseWritesRepository:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def _case_ids(self, session) -> set[str]:
        return set(session.scalars(select(Case.id).where(Case.run_id == self.run_id)))

    def rows(self, session):
        return list(session.scalars(select(Case).where(Case.run_id == self.run_id).order_by(Case.id)))

    def save_work(self, session, contribution, *, adopted_output_id: str | None = None) -> list[dict[str, Any]]:
        "案例与承诺随调用方正式保存事务提交"
        if contribution.run_id != self.run_id:
            raise ValueError("案例贡献不属于当前运行")
        producer = session.get(Agent, contribution.author) if contribution.author else None
        if contribution.author and producer is None:
            raise ValueError("案例写出者 Agent 不存在")
        if producer is not None and producer.run_id != self.run_id:
            raise ValueError("案例写出者不属于当前运行")
        snapshot = contribution.snapshot()
        for case_id, case in snapshot.get("registrations", {}).items():
            session.execute(
                insert(Case)
                .values(
                    id=case_id,
                    run_id=self.run_id,
                    type=case["case_type"],
                    description=case["description"],
                    status="pending",
                    producer_agent_id=contribution.author if producer is not None else None,
                )
                .on_conflict_do_nothing(index_elements=[Case.id])
            )
            row = session.get(Case, case_id)
            if (
                row is None
                or row.run_id != self.run_id
                or row.type != case["case_type"]
                or row.description != case["description"]
            ):
                raise ValueError("案例身份与已保存的案例内容或运行不一致")
        promises = snapshot.get("promises", [])
        if promises and producer is None:
            raise ValueError("承诺案例必须有本运行的真实 Agent")
        for case_id in promises:
            result = session.execute(
                update(Case)
                .where(Case.id == case_id, Case.run_id == self.run_id, Case.status == "pending")
                .values(status="resolved", promised_agent_id=contribution.author)
            )
            if result.rowcount == 0:
                row = session.get(Case, case_id, populate_existing=True)
                if row is None or row.run_id != self.run_id or row.promised_agent_id != contribution.author:
                    raise ValueError("案例已由其他 Agent 承诺或不属于当前运行")
        session.flush()
        return []
