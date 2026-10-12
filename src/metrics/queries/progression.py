"""按正文披露章归并独立变化；窗口和分页只裁剪记录，不裁剪历史状态"""

from __future__ import annotations

import base64
import json
from collections import Counter
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.event_trees.action_order import action_order
from src.storage.models import AnalysisOutput, Chapter, EntityState, EventNode, ForeshadowingAction, GraphFact
from src.utils.identity import stable_uuid

DIMENSIONS = ("plot", "character", "relationship", "foreshadowing")


class ProgressionQuery:
    """只消费已保存事实，调用方复用整个任务 completed 的访问规则"""

    def __init__(self, session: Session, run_id: str) -> None:
        self.session, self.run_id = session, run_id
        rows = session.scalars(
            select(Chapter)
            .where(Chapter.run_id == run_id, Chapter.text.is_not(None))
            .order_by(Chapter.sequence, Chapter.chapter_id)
        ).all()
        self.chapters: list[dict[str, Any]] = [
            {"chapter_id": row.chapter_id, "order": index + 1, "title": row.display_title or row.title}
            for index, row in enumerate(rows)
        ]
        self.orders: dict[int, int] = {row["chapter_id"]: row["order"] for row in self.chapters}

    def _cutoff(self, chapter_id: int | None) -> int:
        if chapter_id is None:
            return 1 if self.chapters else 0
        if chapter_id not in self.orders:
            raise ValueError(f"正文阅读章节不存在: {chapter_id}")
        return self.orders[chapter_id]

    def _changes(self, cutoff: int, *, display_order: bool = True) -> list[dict[str, Any]]:
        chapter_ids = [key for key, order in self.orders.items() if order <= cutoff]
        # 时间轴请求的主要开销是整行水合数千条 GraphFact ORM 实体，只取构建变化所需的列
        facts = self.session.execute(
            select(
                GraphFact.fact_id,
                GraphFact.fact_type,
                GraphFact.chapter_id,
                GraphFact.subject_entity_id,
                GraphFact.author_work_id,
                GraphFact.annotation_id,
                GraphFact.event_id,
                GraphFact.content,
                GraphFact.evidence,
            ).where(
                GraphFact.run_id == self.run_id,
                GraphFact.chapter_id.in_(chapter_ids),
                GraphFact.fact_type.in_(["entity", "character_observation", "relation", "plot_progression"]),
            )
        ).mappings().all()
        facts = list(facts)
        outputs = {
            row.output_id: row.role
            for row in self.session.execute(
                select(AnalysisOutput.output_id, AnalysisOutput.role).where(
                    AnalysisOutput.run_id == self.run_id, AnalysisOutput.kind == "chapter_annotation"
                )
            )
        }
        roles = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}
        facts.sort(
            key=lambda row: (
                self.orders[row["chapter_id"]],
                roles[outputs[row["annotation_id"]]],
                row["author_work_id"],
                row["content"].get("operation_order", 0),
                row["fact_id"],
            )
        )
        deltas: dict[str, list[dict[str, Any]]] = {}
        for row in self.session.scalars(
            select(EntityState).where(
                EntityState.run_id == self.run_id,
                EntityState.chapter_id.in_(chapter_ids),
            )
        ):
            for change in row.changes:
                field = change["field"]
                # 首次登记的标签、说明和程序计数不是情节变化
                if field in {"entity_type", "support_count", "is_main_character", "is_representative"}:
                    continue
                if change["before"] == change["after"]:
                    continue
                if change["before"] is None and field not in {"action", "emotion", "role_function"}:
                    continue
                deltas.setdefault(change["fact_id"], []).append(
                    {
                        "field": field,
                        "before": change["before"],
                        "after": change["after"],
                    }
                )
        changes: list[dict[str, Any]] = []
        relation_states: dict[str, dict[str, Any]] = {}
        for fact in facts:
            op = fact["content"]["operation"]
            fields: list[dict[str, Any]] = []
            action: str | None = None
            # before/after 跨维度形态不同（dict/str），循环内统一按 Any 传递
            before: Any = None
            after: Any = None
            if fact["fact_type"] in {"entity", "character_observation"}:
                fields = deltas.get(fact["fact_id"], [])
                if not fields:
                    continue
                dimension, subject = "character", fact["subject_entity_id"]
                name = op.get("character") or op.get("name")
                before = {item["field"]: item["before"] for item in fields}
                after = {item["field"]: item["after"] for item in fields}
                title = str(
                    after.get("action")
                    or "、".join(
                        {"emotion": "情绪", "role_function": "叙事作用"}.get(item["field"], item["field"])
                        for item in fields
                    )
                )
            elif fact["fact_type"] == "relation":
                dimension, subject = "relationship", fact["content"]["relation_id"]
                name = f"{op['from_entity']} · {op['to_entity']}"
                action = op.get("change_kind", "assert")
                prior = relation_states.get(subject)
                before = deepcopy(prior) if prior is not None else None
                after = {"relation_type": op["relation_type"], "active": action not in {"break", "retract"}}
                relation_states[subject] = deepcopy(after)
                if before == after and action == "assert":
                    continue
                if action != "assert":
                    after["change"] = action
                    after["reason"] = op.get("reason")
                title = op.get("reason") or f"{op['relation_type']}：{'首次记录' if before is None else action}"
            else:
                dimension, subject = "plot", op["subject_id"]
                name, title = op["subject_title"], op["description"]
                before, after = op["before"], op["after"]
                if before == after:
                    continue
            evidence = fact["evidence"]
            scope = "paragraph" if fact["fact_type"] == "plot_progression" else "chapter"
            changes.append(
                self._change(
                    fact["fact_id"],
                    dimension,
                    str(subject),
                    str(name),
                    str(title),
                    fact["chapter_id"],
                    before,
                    after,
                    fields,
                    action,
                    evidence,
                    scope,
                    [fact["event_id"]] if fact["event_id"] else [],
                    [fact["fact_id"]],
                )
            )
        actions = sorted(
            self.session.scalars(
                select(ForeshadowingAction).where(
                    ForeshadowingAction.run_id == self.run_id,
                    ForeshadowingAction.chapter_id.in_(chapter_ids),
                )
            ),
            key=action_order,
        )
        roots = {
            row.event_id: row
            for row in self.session.scalars(
                select(EventNode).where(
                    EventNode.run_id == self.run_id,
                    EventNode.is_foreshadowing_root.is_(True),
                    EventNode.chapter_id.in_(chapter_ids),
                )
            )
        }
        visible_events = set(
            self.session.scalars(
                select(EventNode.event_id).where(EventNode.run_id == self.run_id, EventNode.chapter_id.in_(chapter_ids))
            )
        )
        previous: dict[str, str] = {}
        for action_row in actions:
            root = roots.get(action_row.root_event_id)
            if root is None or (action_row.target_event_id and action_row.target_event_id not in visible_events):
                raise ValueError(f"伏笔动作 {action_row.action_id} 的来源或目标不在阅读截点内")
            before = previous.get(root.event_id)
            after = {"setup": "已埋设", "reinforce": "已强化", "payoff": "疑似回收"}[action_row.action_type]
            previous[root.event_id] = after
            changes.append(
                self._change(
                    action_row.action_id,
                    "foreshadowing",
                    root.event_id,
                    root.description,
                    after,
                    action_row.chapter_id,
                    before,
                    after,
                    [],
                    action_row.action_type,
                    action_row.evidence,
                    action_row.evidence_scope,
                    list(
                        dict.fromkeys(
                            [root.event_id, *([action_row.target_event_id] if action_row.target_event_id else [])]
                        )
                    ),
                    [],
                )
            )
        # 稳定排序保留同位置动作的归并顺序；章级项仍并列，不生成虚构的章内时间
        if display_order:
            changes.sort(
                key=lambda item: (
                    item["chapter_order"],
                    min(item["anchor_paragraph_ids"], default=2**31),
                )
            )
        return changes

    def _change(
        self,
        source: str,
        dimension: str,
        subject: str,
        name: str,
        title: str,
        chapter: int,
        before: Any,
        after: Any,
        deltas: list[dict[str, Any]],
        action: str | None,
        evidence: list[dict[str, Any]],
        scope: str,
        events: list[str],
        facts: list[str],
    ) -> dict[str, Any]:
        return {
            "progression_change_id": stable_uuid("progression", self.run_id, dimension, subject, source),
            "dimension": dimension,
            "subject_id": subject,
            "subject_title": name,
            "title": title,
            "chapter_id": chapter,
            "chapter_order": self.orders[chapter],
            "before": before,
            "after": after,
            "deltas": deltas,
            "action": action,
            "evidence_scope": scope,
            "evidence": evidence,
            "anchor_paragraph_ids": sorted({item["paragraph_id"] for item in evidence if "paragraph_id" in item})
            if scope == "paragraph"
            else [],
            "source_event_ids": events,
            "source_fact_ids": facts,
        }

    def fetch(
        self,
        *,
        through_chapter_id: int | None = None,
        window_start_chapter_id: int | None = None,
        window_end_chapter_id: int | None = None,
        subject_id: str | None = None,
        dimension: str | None = None,
        q: str = "",
        cursor: str | None = None,
        limit: int = 100,
        source_fact_id: str | None = None,
    ) -> dict[str, Any]:
        cutoff = self._cutoff(through_chapter_id)
        start = self._cutoff(window_start_chapter_id)
        end = self._cutoff(window_end_chapter_id) if window_end_chapter_id is not None else cutoff
        if start > end or not 1 <= limit <= 500 or (dimension is not None and dimension not in DIMENSIONS):
            raise ValueError("时间轴窗口、维度或分页大小无效")
        all_changes = self._changes(cutoff, display_order=False)
        states: dict[tuple[str, str], dict[str, Any]] = {}
        for change in all_changes:
            key = (change["dimension"], change["subject_id"])
            old = states.get(key, {}).get("state")
            value = deepcopy(change["after"])
            if change["dimension"] == "character":
                value = {**(old or {}), **value}
            states[key] = {
                **{
                    field: change[field]
                    for field in ("subject_id", "subject_title", "dimension", "chapter_id", "chapter_order")
                },
                "state": value,
            }
        selected = [
            item
            for item in all_changes
            if (not subject_id or item["subject_id"] == subject_id)
            and (not dimension or item["dimension"] == dimension)
            and (
                not q
                or q.casefold()
                in json.dumps(
                    [item["subject_title"], item["title"], item["before"], item["after"]], ensure_ascii=False
                ).casefold()
            )
            and (not source_fact_id or source_fact_id in item["source_fact_ids"])
        ]
        counts = Counter((item["chapter_id"], item["chapter_order"], item["dimension"]) for item in selected)
        selected = [item for item in selected if start <= item["chapter_order"] <= end]
        selected.sort(
            key=lambda item: (
                item["chapter_order"],
                min(item["anchor_paragraph_ids"], default=2**31),
            )
        )
        context = [self.run_id, cutoff, start, end, subject_id, dimension, q, source_fact_id]
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if decoded["query"] != context or not isinstance(decoded["offset"], int) or decoded["offset"] < 0:
                    raise ValueError
                offset = decoded["offset"]
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError("分页游标与当前时间轴条件不匹配") from exc
        next_offset = offset + limit
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"query": context, "offset": next_offset}, ensure_ascii=False).encode()
        ).decode()
        return {
            "run_id": self.run_id,
            "chapters": [
                {**chapter, "title": chapter["title"] if chapter["order"] <= cutoff else f"第 {chapter['order']} 章"}
                for chapter in self.chapters
            ],
            "through_chapter_id": next((c["chapter_id"] for c in self.chapters if c["order"] == cutoff), None),
            "changes": selected[offset:next_offset],
            "states": list(states.values()),
            "subjects": [
                {k: value[k] for k in ("dimension", "subject_id", "subject_title")} for value in states.values()
            ],
            "total": len(selected),
            "next_cursor": next_cursor if next_offset < len(selected) else None,
            "distribution": [
                {"chapter_id": key[0], "chapter_order": key[1], "dimension": key[2], "count": count}
                for key, count in sorted(counts.items())
            ],
        }

    def detail(self, change_id: str, through_chapter_id: int) -> dict[str, Any]:
        cutoff = self._cutoff(through_chapter_id)
        for item in self._changes(cutoff):
            if item["progression_change_id"] == change_id:
                return item
        if any(item["progression_change_id"] == change_id for item in self._changes(len(self.chapters))):
            raise LookupError("CHANGE_NOT_VISIBLE")
        raise LookupError("CHANGE_NOT_FOUND")

    def export(self) -> dict[str, Any]:
        last = self.chapters[-1]["chapter_id"] if self.chapters else None
        result = self.fetch(through_chapter_id=last)
        result["changes"] = self._changes(len(self.chapters))
        result["next_cursor"] = None
        return result
