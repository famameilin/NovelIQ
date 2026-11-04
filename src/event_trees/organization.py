"完整事件组织草稿、原文绑定与正式产出保存"

from __future__ import annotations

import threading
from typing import Any, Literal

from pydantic import BaseModel

from src.event_trees import storage_map as smap
from src.event_trees.organization_models import (
    BoundOrganizationEvidence,
    CompleteEventDraft,
    EventOutcomeDraft,
    EventQueueDraft,
    NarrativeOrganization,
    OrganizationEvidence,
    QueueReferenceDraft,
    RelationDraft,
    record_payloads,
    snapshot_digest,
    validate_event_line_names,
)
from src.event_trees.organization_queries import (
    _execution_in_run,
    _global_positions,
    _paragraph_rows,
    _run_event_dicts,
)
from src.event_trees.organization_rules import validate_organization as validate_organization_rules
from src.event_trees.queues import QueueGraph
from src.storage import Storage, new_id
from src.utils.event_references import referenced_event_ids
from src.utils.identity import text_digest


class CandidateConflict(ValueError):
    """可定位的候选冲突只返回真实生产者，不能重开无关会话"""

    def __init__(self, message: str, producer_agent_ids: list[str]) -> None:
        self.producer_agent_ids = tuple(sorted(set(producer_agent_ids)))
        super().__init__(message)


def _page_size(limit: int, maximum: int = 100) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit 必须在 1 到 {maximum} 之间")


class EventOrganizationDraft:
    """只更新本轮内存；程序检查完整性后由诊断保存点一次提交"""

    def _identifier(self, *key):
        if key not in self._identifiers:
            self._identifiers[key] = new_id()
        return self._identifiers[key]

    def __init__(self, session: Storage, run_id: str, agent_id: str | None = None) -> None:
        # agent_id 是诊断整轮的会话身份（executions 的 session 形状），不是单个案例的调用
        self.session = session
        self.lock = threading.RLock()
        self.publication_lock = threading.RLock()
        self.cache_reads = False
        self._stored_view: tuple[dict[str, dict[str, Any]], QueueGraph] | None = None
        self.run_id = run_id
        self._identifiers: dict[tuple, str] = {}
        self.agent_id = agent_id
        self.producer_agent_id: str | None = None
        self.content_snapshot: str | None = None
        self.structure_snapshot: str | None = None
        self.queue_references: dict[tuple[str, str], QueueReferenceDraft] = {}
        self.events: dict[str, CompleteEventDraft] = {}
        self.relations: dict[str, RelationDraft] = {}
        self.saved_relation_ids: set[str] = set()
        self.outcomes: dict[str, EventOutcomeDraft] = {}
        self.queues: dict[str, EventQueueDraft] = {}
        self.event_line_ids: set[str] = set()
        self.event_line_marks: dict[str, set[str]] = {}
        self.line_names: dict[str, str] = {}

    def set_event_line(self, event_id: str, is_event_line: bool, *, author: str) -> bool:
        "按执行记录事件线标记，返回标记是否改变"
        changed = (event_id in self.event_line_ids) != is_event_line
        if is_event_line:
            self.event_line_ids.add(event_id)
            self.event_line_marks.setdefault(author, set()).add(event_id)
        else:
            self.event_line_ids.discard(event_id)
            self.event_line_marks.get(author, set()).discard(event_id)
            self.line_names.pop(event_id, None)
        return changed

    def name_event_lines(self, names: dict[str, str]) -> bool:
        "为全部选定事件线命名并返回是否改变"
        validate_event_line_names(names, self.event_line_ids)
        changed = self.line_names != names
        self.line_names = dict(names)
        return changed

    def discard_event_line_marks(self, author: str) -> None:
        "移除该执行本次新增的事件线标记"
        discarded = self.event_line_marks.pop(author, set())
        self.event_line_ids.difference_update(discarded)
        for tree_id in discarded:
            self.line_names.pop(tree_id, None)

    def _all_events(self) -> dict[str, dict[str, Any]]:
        return self.read_view()[0]

    def refresh_read_cache(self) -> None:
        "正式提交后重新读取已保存贡献"
        self._stored_view = None

    def queue_graph(self, *, require_complete: bool = False, producers: set[str] | None = None) -> QueueGraph:
        stored, formal = self._formal_view()
        return self._queue_graph(stored, formal, require_complete=require_complete, producers=producers)

    def _queue_graph(
        self,
        stored: dict[str, dict[str, Any]],
        formal: QueueGraph,
        *,
        require_complete: bool = False,
        producers: set[str] | None = None,
    ) -> QueueGraph:
        """合并同一次读取的正式状态与当前可见草稿"""
        visible_producers = (
            producers
            if producers is not None
            else ({self.producer_agent_id} if self.producer_agent_id is not None else set())
        )
        queues = dict(formal.queues)
        references = [(parent, child) for parent, children in formal.children.items() for child in children]
        visible = dict(stored)
        visible.update(
            {
                key: item.model_dump(mode="json")
                for key, item in self.events.items()
                if item.producer_agent_id in visible_producers
            }
        )
        for key, item in self.queues.items():
            if key in queues:
                if tuple(item.event_ids) != queues[key]:
                    raise ValueError("已保存事件树成员或顺序不能改写")
            elif item.producer_agent_id in visible_producers:
                queues[key] = tuple(item.event_ids)
        for reference in self.queue_references.values():
            pair = (reference.parent_tree_id, reference.child_tree_id)
            if reference.producer_agent_id in visible_producers and pair not in references:
                references.append(pair)
        if require_complete:
            child_counts: dict[str, int] = {}
            for parent, _child in references:
                child_counts[parent] = child_counts.get(parent, 0) + 1
            for key, item in self.queues.items():
                if (
                    item.producer_agent_id in visible_producers
                    and key not in formal.queues
                    and not item.event_ids
                    and child_counts.get(key, 0) < 2
                ):
                    raise ValueError(
                        "新建的空事件树必须连接至少两棵子树：只有多棵事件树同属一棵尚不存在的事件树时才允许新建"
                    )
        return QueueGraph(
            queues,
            references,
            visible,
            require_complete=require_complete,
            event_line_ids=self.event_line_ids,
        )

    def _formal_view(self) -> tuple[dict[str, dict[str, Any]], QueueGraph]:
        if self.cache_reads and self._stored_view is not None:
            return self._stored_view
        events = _run_event_dicts(self.session, self.run_id)
        links = self.session.reads.events.list_queue_links(self.run_id)
        executions = self.session.reads.events.list_execution_trees(
            smap.run_execution_ids(self.session, self.run_id)
        )
        graph = QueueGraph.from_rows(
            links,
            events,
            [row.group_id for row in executions],
            require_complete=False,
            event_line_ids=self.event_line_ids,
        )
        view = events, graph
        if self.cache_reads:
            self._stored_view = view
        return view

    def read_view(self) -> tuple[dict[str, dict[str, Any]], QueueGraph]:
        with self.publication_lock:
            events, _formal = self._formal_view()
            events = {key: {**value, "saved": True} for key, value in events.items()}
            events.update(
                {
                    key: item.model_dump(mode="json")
                    for key, item in self.events.items()
                    if item.producer_agent_id == self.producer_agent_id and key not in events
                }
            )
            graph = self._queue_graph(events, _formal)
            events = {
                **{
                    key: {**value, "is_event_line": graph.event_tree.get(key) in self.event_line_ids}
                    for key, value in events.items()
                }
            }
            return events, graph

    def referenced_event_ids(self, producers: set[str] | None = None) -> set[str]:
        """本生产者的包含、关系与证据引用到的事件身份"""
        owned = producers if producers is not None else ({self.producer_agent_id} if self.producer_agent_id else set())
        return referenced_event_ids(self, owned)

    def unpublished_references(self, producers: set[str] | None = None) -> list[str]:
        """引用到其他生产者尚未正式保存的事件身份"""
        owned = producers if producers is not None else ({self.producer_agent_id} if self.producer_agent_id else set())
        owned_events = {item.event_id for item in self.events.values() if item.producer_agent_id in owned}
        referenced = referenced_event_ids(self, owned) - owned_events
        if not referenced:
            return []
        return sorted(referenced - set(self.session.narrative.run_events(self.run_id)))

    def progress(self) -> dict[str, int]:
        """用于写入回执里的轻量进度"""
        graph = self.queue_graph()
        return {
            "unparented_trees": len(graph.unparented),
            "unassigned": len(self.events) - len(graph.event_tree),
            "outcomes": len(self.outcomes),
            "event_lines": len(self.event_line_ids),
            "event_lines_named": len(self.line_names),
        }

    @staticmethod
    def _event_hierarchy(event_id: str, graph: QueueGraph) -> dict[str, Any]:
        if event_id not in graph.event_tree:
            return {"tree_id": None, "parent_event_ids": [], "event_line_ids": [], "is_top_level": False}
        tree_id = graph.event_tree[event_id]
        position = graph.positions[event_id]
        return {
            "tree_id": tree_id,
            "tree_position": position,
            "tree_event_ids": list(graph.queues[tree_id]),
            "parent_event_ids": graph.event_parents(event_id),
            "event_line_ids": graph.event_lines(event_id),
            "is_top_level": position == 0 and not graph.parents[tree_id],
        }

    def search_events(
        self,
        query: str = "",
        *,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """分页返回本次草稿与正式事件，零事件时也可从过程读取开始"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        by_id, parents = self.read_view()
        rows = [
            {**item, **self._event_hierarchy(key, parents)}
            for key, item in by_id.items()
            if (not top_level_only or self._event_hierarchy(key, parents)["is_top_level"])
            and (
                not query
                or query.casefold()
                in " ".join(str(item[field]) for field in ("title", "problem", "summary")).casefold()
            )
        ]
        rows.sort(key=lambda item: (item["first_text_position"] or 0, item["event_id"]))
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }

    def read_events(self, event_ids: list[str]) -> list[dict[str, Any]]:
        _page_size(len(event_ids))
        by_id, parents = self.read_view()
        missing = sorted(set(event_ids) - set(by_id))
        if missing:
            raise ValueError(f"本任务事件不存在: {missing}")
        return [
            {
                **by_id[key],
                **self._event_hierarchy(key, parents),
                "direct_child_event_ids": parents.event_children(key) if key in parents.event_tree else [],
            }
            for key in event_ids
        ]

    def _source(self) -> dict[str, Any]:
        if not self.producer_agent_id:
            raise ValueError("诊断贡献缺少真实生产者")
        return {"producer_agent_id": self.producer_agent_id}

    def _require_free_key(self, key: str, event_id: str) -> None:
        """局部键在同一执行内唯一：被其他事件占用时拒收，同一事件重发放行"""
        holder = next(
            (
                item
                for item in self.events.values()
                if item.producer_agent_id == self.producer_agent_id and item.local_key == key
            ),
            None,
        )
        if holder is not None and holder.event_id != event_id:
            raise ValueError(
                f"局部键已被本执行的其他事件占用: key={key} event_id={holder.event_id} title={holder.title}；"
                "同一执行内局部键必须唯一且不随章节、批次重置；请换用未占用的键（建议由事件 id 派生），"
                "或复用、撤回占用的候选后重新提交"
            )

    def _tree_by_key(self, key: str) -> str | None:
        "按运行内树键定位当前草稿或正式树"
        for item in self.queues.values():
            if item.tree_key == key:
                return item.tree_id
        for row in self.session.reads.events.list_execution_trees(smap.run_execution_ids(self.session, self.run_id)):
            if row.tree_key == key:
                return row.group_id
        return None

    def retract(
        self,
        *,
        kind: Literal["queue", "reference", "relation"],
        identifier: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        "撤回当前生产者尚未保存的事件树、父子引用或语义关系"
        if kind not in {"queue", "reference", "relation"}:
            raise ValueError("只允许撤回事件树、父子引用或语义关系")
        if not reason.strip():
            raise ValueError("撤回须明确理由")
        self.bind_evidence(evidence)
        if kind == "queue":
            item = self.queues.get(identifier)
            if item is None or item.producer_agent_id != self.producer_agent_id:
                raise ValueError("只能撤回本执行未保存事件树")
            if identifier in self._formal_view()[1].queues:
                raise ValueError("正式事件树不可撤回")
            if any(identifier in pair for pair in self.queue_references):
                raise ValueError("请先撤回本执行指向该草稿事件树的父子引用")
            del self.queues[identifier]
            try:
                self.queue_graph()
            except Exception:
                self.queues[identifier] = item
                raise
            return
        records: Any = {"reference": self.queue_references, "relation": self.relations}[kind]
        key: Any = tuple(identifier.split("/", 1)) if kind == "reference" else identifier
        item = records.get(key)
        if item is None or item.producer_agent_id != self.producer_agent_id:
            raise ValueError("只能撤回当前生产者的实际候选")
        saved = self.session.reads.events.list_queue_references(self.run_id) if kind == "reference" else []
        if any((row.parent_tree_id, row.child_tree_id) == key for row in saved):
            raise ValueError("已保存的父子引用不可撤回")
        if kind == "relation" and identifier in self.saved_relation_ids:
            raise ValueError("已保存的事件关系不可撤回")
        del records[key]
        if kind == "reference":
            try:
                self.queue_graph()
            except Exception:
                records[key] = item
                raise

    def event(
        self,
        *,
        key: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: Literal["ongoing", "resolved"],
        reason: str,
        from_chapter_id: int,
        to_chapter_id: int,
        evidence: list[OrganizationEvidence],
        progress: str | None = None,
    ) -> dict[str, Any]:
        """依据正文创建不可变事件，起止章节独立于包含结构"""
        if not key.strip() or not reason.strip():
            raise ValueError("事件局部键和理由不能为空")
        self.session.narrative.validate_event_range(self.run_id, from_chapter_id, to_chapter_id)
        bound = self.bind_evidence(evidence)
        holder = next(
            (
                item
                for item in self.events.values()
                if item.producer_agent_id == self.producer_agent_id and item.local_key == key
            ),
            None,
        )
        event_id = (
            holder.event_id
            if holder is not None
            else self._identifier("event", self.run_id, self.producer_agent_id, key)
        )
        candidate = CompleteEventDraft(
            event_id=event_id,
            local_key=key,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            progress=progress,
            reason=reason,
            from_chapter_id=from_chapter_id,
            to_chapter_id=to_chapter_id,
            first_text_position=self._first_position(bound),
            evidence=bound,
            **self._source(),
        )
        self._require_free_key(key, event_id)
        if event_id in self.events and self.events[event_id] != candidate:
            raise ValueError("已接受事件不能被其他操作覆盖")
        self.events[event_id] = candidate
        return {"status": "accepted_candidate", "event_id": event_id}

    def queue(
        self,
        *,
        event_ids: list[str],
        reason: str = "",
        evidence: list[OrganizationEvidence] | None = None,
        tree_id: str | None = None,
        tree_key: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        "提交本执行事件树；空树只建树，未保存树只能在队尾追加成员"
        evidence = evidence or []
        if not event_ids and not (tree_key and title):
            raise ValueError("空事件树必须给 tree_key 和 title")
        if event_ids:
            self.read_events(event_ids)
        previous = self.queues.get(tree_id) if tree_id is not None else None
        if previous is None and tree_key is not None:
            previous = self.queues.get(self._tree_by_key(tree_key) or "")
        if previous is None and event_ids:
            previous = next((item for item in self.queues.values() if event_ids[0] in item.event_ids), None)
        if previous is not None and previous.producer_agent_id != self.producer_agent_id:
            raise ValueError(
                f"事件树 {previous.tree_id} 属于其他执行，不能追加或改写；请用 write_link 挂到该树"
            )
        if previous is not None:
            if tree_id is not None and previous.tree_id != tree_id:
                raise ValueError("tree_id 与 tree_key 指向不同事件树")
            if not event_ids:
                return previous.tree_id
            members = list(previous.event_ids)
            extended = members + [value for value in event_ids if value not in members]
            if extended[: len(members)] != members:
                raise ValueError("事件树成员顺序不能改写，只能在队尾追加")
            # 空树先建后追加时补上首个成员的树理由，已理由不改写
            update: dict[str, Any] = {"event_ids": extended}
            if not previous.reason.strip() and reason.strip():
                update["reason"] = reason
            if not previous.evidence and evidence:
                update["evidence"] = self.bind_evidence(evidence)
            item = previous.model_copy(update=update)
        else:
            graph = self.queue_graph()
            if tree_id is not None and tree_id in graph.queues:
                raise ValueError("已保存事件树不能追加成员")
            belongs = set(graph.event_tree)
            if any(value in belongs for value in event_ids):
                raise ValueError("该事件已属于已保存事件树，不能另建树")
            if tree_key is not None and self._tree_by_key(tree_key) is not None:
                raise ValueError(
                    f"tree_key={tree_key} 已被运行内事件树 {self._tree_by_key(tree_key)} 使用；"
                    "请用 write_link 挂到该树，不要另建"
                )
            first = self.read_events([event_ids[0]])[0] if event_ids else None
            item = EventQueueDraft(
                tree_id=tree_id or self._identifier(
                    "event_tree",
                    self.run_id,
                    self.producer_agent_id,
                    tree_key or (event_ids[0] if event_ids else title),
                ),
                tree_key=tree_key,
                title=title or (first["title"] if first else ""),
                description=description or (first["summary"] if first else title or ""),
                event_ids=event_ids,
                reason=reason,
                evidence=self.bind_evidence(evidence),
                **self._source(),
            )
        self.queues[item.tree_id] = item
        try:
            self.queue_graph()
        except Exception:
            if previous is None:
                self.queues.pop(item.tree_id, None)
            else:
                self.queues[item.tree_id] = previous
            raise
        return item.tree_id

    def reference(
        self, *, parent_tree_id: str, child_tree_id: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        "父树尾连接子树首，允许多父并拒绝未保存的其他执行树"
        graph = self.queue_graph()
        for key in (parent_tree_id, child_tree_id):
            if key not in graph.queues:
                raise ValueError("端点必须是已读取的完整事件树")
        item = QueueReferenceDraft(
            parent_tree_id=parent_tree_id,
            child_tree_id=child_tree_id,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        pair = (parent_tree_id, child_tree_id)
        previous = self.queue_references.get(pair)
        if previous is not None and previous != item:
            raise ValueError(
                f"父子引用 {parent_tree_id}→{child_tree_id} 已由 {previous.producer_agent_id} "
                f"以不同理由或证据提交：{previous.reason}；引用原判断，或撤回本执行草稿后重试"
            )
        self.queue_references[pair] = item
        try:
            self.queue_graph()
        except Exception:
            if previous is None:
                self.queue_references.pop(pair)
            raise

    def validate_events(self, events: dict[str, CompleteEventDraft] | None = None) -> None:
        self.queue_graph(require_complete=True)

    def relate_events(
        self,
        *,
        key: str,
        source_kind: Literal["event"],
        source_id: str,
        target_kind: Literal["event"],
        target_id: str,
        relation_type: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> str:
        self.read_events([source_id, target_id])
        if relation_type in {"main", "secondary", "contains", "containment", "same_identity"}:
            raise ValueError("身份、包含及旧主链标记不能伪装为普通事件关系")
        relation_id = self._identifier("event_relation", self.run_id, self.producer_agent_id, key)
        self.relations[relation_id] = RelationDraft(
            relation_id=relation_id,
            source_kind=source_kind,
            source_id=source_id,
            target_kind=target_kind,
            target_id=target_id,
            relation_type=relation_type,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            source_operation_id=key,
            **self._source(),
        )
        return relation_id

    def read_passages(self, paragraph_ids: list[int], offset: int = 0, limit: int = 10) -> dict[str, Any]:
        """有界读取真实原文；段号从工具回执获得，长段落按字符续读"""
        _page_size(len(paragraph_ids), 20)
        _page_size(limit, 20)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        rows = self.session.reads.text.list_passages(paragraph_ids, self.run_id)
        if set(paragraph_ids) - {row.paragraph_id for row in rows}:
            raise ValueError("本任务原文段落不存在")
        return {
            "items": [
                {
                    "paragraph_id": row.paragraph_id,
                    "chapter_id": row.chapter_id,
                    "text": row.text[offset : offset + 2000],
                    "next_offset": offset + 2000 if len(row.text) > offset + 2000 else None,
                }
                for row in rows[:limit]
            ]
        }

    def bind_evidence(self, evidence: list[OrganizationEvidence]) -> list[BoundOrganizationEvidence]:
        """沿用原文锚点的逐字绑定规则，不接受模型提交坐标或哈希"""
        if not evidence:
            return []
        _page_size(len(evidence))
        event_ids = list({item.event_id for item in evidence if item.event_id is not None})
        if event_ids:
            self.read_events(event_ids)
        paragraph_ids = {item.paragraph_id for item in evidence}
        paragraphs = _paragraph_rows(self.session, self.run_id, paragraph_ids)
        bound = []
        for item in evidence:
            row = paragraphs.get(item.paragraph_id)
            if row is None:
                raise ValueError(f"本任务原文段落不存在: {item.paragraph_id}")
            start, end = 0, len(row.text)
            if item.quote is not None:
                start = -1
                for _ in range(item.occurrence):
                    start = row.text.find(item.quote, start + 1)
                if start < 0:
                    raise ValueError(
                        f"quote 或 occurrence 不匹配原文（paragraph_id={item.paragraph_id}，"
                        f"occurrence={item.occurrence}）；先 read_text 读取该段，原样复制其中的连续文本"
                    )
                end = start + len(item.quote)
            elif item.occurrence != 1:
                raise ValueError("完整段落引用 occurrence 必须为 1")
            bound.append(
                BoundOrganizationEvidence(
                    event_id=item.event_id,
                    paragraph_id=row.paragraph_id,
                    chapter_id=row.chapter_id,
                    char_start=start,
                    char_end=end,
                    text_hash=text_digest(row.text[start:end]),
                )
            )
        return bound

    def _first_position(self, evidence: list[BoundOrganizationEvidence]) -> int:
        positions = _global_positions(self.session, self.run_id, {ref.paragraph_id for ref in evidence})
        return min(positions[ref.paragraph_id] + ref.char_start for ref in evidence)

    def register_outcome(self, *, key: str, title: str, description: str, evidence: list[OrganizationEvidence]) -> str:
        """结果身份由本轮稳定键派生，不包含任何来源事件身份"""
        if not key.strip():
            raise ValueError("结果稳定键不能为空")
        outcome_id = self._identifier("event_outcome", self.run_id, self.producer_agent_id, key)
        bound = self.bind_evidence(evidence)
        self.outcomes[outcome_id] = EventOutcomeDraft(
            outcome_id=outcome_id,
            title=title,
            description=description,
            evidence=bound,
            first_text_position=self._first_position(bound),
            **self._source(),
        )
        return outcome_id

    def _validate_subject(self, kind: str, subject_id: str) -> None:
        if kind == "event":
            self.read_events([subject_id])
        elif kind == "fact":
            try:
                fact_id = str(subject_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("冲突事实主体必须是正式图谱事实流水号") from exc
            row = self.session.reads.graph.get_fact(fact_id)
            producer_agent_id = None if row is None else row.direct_producer_agent_id
            if producer_agent_id is None or not _execution_in_run(self.session, producer_agent_id, self.run_id):
                raise ValueError("冲突事实主体不存在或不属于本 run")
        else:
            raise ValueError("冲突主体类型无效")

    def read_draft(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """分页读取事件、关系及结果"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        groups: dict[str, list[BaseModel]] = {
            "events": list(self.events.values()),
            "relations": list(self.relations.values()),
            "outcomes": list(self.outcomes.values()),
            "queues": list(self.queues.values()),
        }
        return {
            **{
                name: [item.model_dump(mode="json") for item in values[offset : offset + limit]]
                for name, values in groups.items()
            },
            "totals": {name: len(values) for name, values in groups.items()},
        }

    def content_digest(self) -> str:
        """按事件正文和章节范围计算保存快照"""
        return snapshot_digest(record_payloads(self.events.values()))

    def structure_digest(self) -> str:
        """结构摘要：按当前事件、包含与关系实时计算，用于报告绑定与保存快照"""
        return snapshot_digest(
            {
                "events": record_payloads(self.events.values()),
                "queue_references": record_payloads(self.queue_references.values()),
                "queues": record_payloads(self.queues.values()),
                "relations": record_payloads(self.relations.values()),
                "event_line_ids": sorted(self.event_line_ids),
                "event_line_names": dict(sorted(self.line_names.items())),
            }
        )

    def finish(self) -> NarrativeOrganization:
        self.validate_events()
        self.queue_graph(require_complete=True).require_event_lines(sorted(self.event_line_ids))
        missing = sorted(self.event_line_ids - set(self.line_names))
        if missing:
            raise ValueError(f"事件线尚未命名：{missing}；请用 name_event_lines 一次提交全部事件线名称")
        validate_event_line_names(self.line_names, self.event_line_ids)
        self.content_snapshot = self.content_digest()
        self.structure_snapshot = self.structure_digest()
        result = NarrativeOrganization(
            source_agent_id=self.agent_id,
            event_line_ids=sorted(self.event_line_ids),
            event_line_names=dict(sorted(self.line_names.items())),
            events=list(self.events.values()),
            relations=list(self.relations.values()),
            outcomes=list(self.outcomes.values()),
            queues=list(self.queues.values()),
            queue_references=list(self.queue_references.values()),
            content_snapshot=self.content_snapshot,
            structure_snapshot=self.structure_snapshot,
        )
        validate_organization(self.session, self.run_id, result)
        return result


def validate_organization(session: Storage, run_id: str, organization: NarrativeOrganization) -> None:
    "构造独立校验状态，拒绝改变当前会话草稿"
    validate_organization_rules(session, run_id, organization, EventOrganizationDraft(session, run_id))
