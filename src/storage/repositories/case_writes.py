"七字段案例的登记与提交保存"

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from src.storage.models import Agent, Case


class CaseWritesRepository:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def _case_ids(self, session) -> set[str]:
        return set(session.scalars(select(Case.id).where(Case.run_id == self.run_id)))

    def rows(self, session):
        return list(session.scalars(select(Case).where(Case.run_id == self.run_id).order_by(Case.id)))

    def register_unparented_trees(self, session) -> list[dict[str, Any]]:
        "没有父树的事件树保存后，在同一事务登记未归并案例"
        from sqlalchemy.orm import aliased

        from src.storage.ids import new_id
        from src.storage.models import NarrativeGroup, NarrativeLink
        from src.storage.records.cases import event_tree_case_description
        from src.storage.repositories.narrative_records import run_execution_ids

        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"fact_graph:{self.run_id}"}
        )
        session.flush()
        incoming = aliased(NarrativeLink)
        trees = list(
            session.scalars(
                select(NarrativeGroup).where(
                    NarrativeGroup.producer_agent_id.in_(run_execution_ids(self.run_id)),
                    NarrativeGroup.kind == "tree",
                    ~select(incoming.link_id).where(incoming.child_tree_id == NarrativeGroup.group_id).exists(),
                )
            )
        )
        # 每棵悬空树最多登记两次：首次保存一次，办结仍未归并时补登一次
        rows = self.rows(session)
        existing = {(row.type, row.description) for row in rows if row.status == "pending"}
        totals: dict[tuple[str, str], int] = {}
        for row in rows:
            key = (row.type, row.description)
            totals[key] = totals.get(key, 0) + 1
        for tree in trees:
            description = event_tree_case_description(tree.group_id)
            key = ("event", description)
            if key in existing or totals.get(key, 0) >= 2:
                continue
            session.add(
                Case(
                    id=new_id(),
                    run_id=self.run_id,
                    type="event",
                    description=description,
                    status="pending",
                    producer_agent_id=tree.producer_agent_id,
                )
            )
            existing.add(key)
            totals[key] = totals.get(key, 0) + 1
        session.flush()
        return [
            {
                "case_id": row.id,
                "case_type": row.type,
                "description": row.description,
                "submitted": row.status == "resolved",
                "owner": row.promised_agent_id,
            }
            for row in self.rows(session)
        ]

    def save_work(self, session, contribution, *, adopted_output_id: str | None = None) -> list[dict[str, Any]]:
        "案例登记与办结随调用方正式保存事务提交"
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
        submissions = snapshot.get("submissions", [])
        if submissions and producer is None:
            raise ValueError("提交案例必须有本运行的真实 Agent")
        for case_id in submissions:
            result = session.execute(
                update(Case)
                .where(Case.id == case_id, Case.run_id == self.run_id, Case.status == "pending")
                .values(status="resolved", promised_agent_id=contribution.author)
            )
            if result.rowcount == 0:
                row = session.get(Case, case_id, populate_existing=True)
                if row is None or row.run_id != self.run_id or row.promised_agent_id != contribution.author:
                    raise ValueError("案例已由其他 Agent 提交或不属于当前运行")
        session.flush()
        return []
