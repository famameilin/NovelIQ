"""
章节标注语义写入系统账本：单章领域写入与系统绑定状态
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：tools.py 大文件拆分——AnnotationToolLedger 整类迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；_ROOT_NODE_KEY/_EL_PATH_SEP 改为直接使用
# schema 的权威常量（RESERVED_ROOT_KEY/EL_PATH_SEP，原变量即其别名，行为不变）；
# tools.py 对 AnnotationToolLedger 保留 re-export，既有导入方零改动。

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import ValidationError

from .candidates import extract_dialogue_candidates
from .errors import (
    AnnotationInputError,
    AnnotationInvariantError,
    AnnotationProtocolError,
    AnnotationStageRejection,
)
from .fact_graph import FactGraph
from .identity import stable_uuid
from .schema import (
    EL_PATH_SEP,
    RELATION_DEFINITIONS,
    RESERVED_ROOT_KEY,
    BoundChapterAnnotation,
    BoundCharacterObservation,
    BoundDialogue,
    BoundEvent,
    BoundParagraphLabel,
    ChapterMetricsInput,
    ChapterParagraphInfo,
    Confidence,
    DialogueCandidate,
    DialogueInput,
    DialogueVerdict,
    EntityDirectoryInput,
    EntityInput,
    EntityType,
    EventCauseRole,
    EventChildType,
    EventParticipantInput,
    EventParticipantRole,
    ParticipantArg,
    PendingCase,
    RelationInput,
    RelationType,
    Tone,
)
from .subagent_ir import ROLE_NAMESPACE_SEP
from .tools import _norm_entity_key, _norm_graph_name
from .validation_errors import _translate_record_validation

# 2026-09-07 监督标签冻结软下限（每章 2-3 段定稿）：低于 2 留痕覆盖告警，不阻断冻结
_PARAGRAPH_LABEL_MIN_PER_CHAPTER = 2

# 引用被拒时回执里列几个本章已登记实体（"el=名字"对照）；超出部分只报总数，
# 拒绝回执要能一眼读完（全章几十个实体时不铺开）
_ENTITY_REF_HINT_LIMIT = 12


@dataclass(slots=True)
class AnnotationToolLedger:
    """2026-08-07 用于保存单章领域写入和系统绑定状态

    2026-09-13 实时写入：模型面的每个小调用即时落到目标结构（written_*），
    全部写完后由唯一 finish 收尾冻结，没有暂存区也没有逐域结束声明。
    2026-09-19 章即块：原 章级字段退役，账本只认章（current_chapter_id/text）。
    """

    run_scope: str
    current_chapter_id: int
    current_chapter_text: str
    allow_future_context: bool
    phase: str = "chapter_open"
    dialogue_candidates: list[DialogueCandidate] = field(default_factory=list)
    domain_payloads: dict[str, Any] = field(default_factory=dict)
    bound_payloads: dict[str, Any] = field(default_factory=dict)
    write_records: list[dict[str, Any]] = field(default_factory=list)
    completed_chapters: list[BoundChapterAnnotation] = field(default_factory=list)
    ready_chapter: BoundChapterAnnotation | None = None
    pushed_cases: list[PendingCase] = field(default_factory=list)
    # 2026-08-30：search_text 返回正文时登记真实 SQL 命中段落
    authorized_text_paragraph_ids: set[int] = field(default_factory=set)
    text_references: dict[str, Any] = field(default_factory=dict)
    source_anchors: dict[str, list[Any]] = field(default_factory=dict)
    cross_chapter_links: list[Any] = field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（仅留痕不阻断），随章持久化
    coverage_warnings: list[str] = field(default_factory=list)
    annotation: BoundChapterAnnotation | None = None
    errors: list[str] = field(default_factory=list)
    search_log: list[dict[str, Any]] = field(default_factory=list)
    graph: FactGraph | None = None
    # 2026-08-18 事件森林/DAG：本章 的段落坐标映射，用于事件锚点校验和证据派生
    paragraph_info: ChapterParagraphInfo | None = None
    # 只登记本章已写出的事件节点
    authorized_event_ids: set[str] = field(default_factory=set)
    # 2026-08-19 当前章节序号（写章指标与上下文摘要展示用）
    current_chapter_order: int | None = None
    # 本章事件树状态，跨章引用只授权精确原文
    event_trees: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 2026-09-13 实时写入（取消暂存）：每次小调用即时落到目标结构，回执即当前真相。
    # 全部进 snapshot/restore——单次调用失败只回滚该调用，之前写入的记录必须保留
    written_entities: dict[str, EntityInput] = field(default_factory=dict)
    metrics_payload: ChapterMetricsInput | None = None
    written_dialogues: dict[int, DialogueInput] = field(default_factory=dict)
    # 有序对 → 关系记录（同一对端点换类型即整体替换，保持"本章关系=完整集合"语义）
    written_relations: dict[tuple[str, str], RelationInput] = field(default_factory=dict)
    # 人物动态状态按记录键持有（重写同一参与者即更新，键给回执定位用）
    observation_by_record: dict[str, BoundCharacterObservation] = field(default_factory=dict)
    # tree_key → tree_id：章内局部键是模型侧寻址面，真实 uuid 不外露
    tree_key_index: dict[str, str] = field(default_factory=dict)
    # 2026-10-04 树键校验下沉：tree_key → 暂挂子事件（先于根到达时缓存，建根按到达序
    # 冲账；finish 时仍有暂挂即拒，防止静默丢数据）
    pending_child_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # 2026-09-14 实体局部键索引：el → 归一化登记名（模型自定、写入即绑定、同轮可用）
    entity_el_index: dict[str, str] = field(default_factory=dict)
    # 2026-09-18 本章已经写出来的记录键集合（程序面每次调用成功即登记）：
    # push_case 的 record_id 按它校验，模型只能指向真实产出
    written_record_keys: set[str] = field(default_factory=set)
    # 2026-09-13 收尾声明：唯一 finish 置位后由系统冻结当前章
    chapter_finished: bool = False

    def __post_init__(self) -> None:
        """2026-08-07 用于初始化唯一章的对话候选"""
        if not self.current_chapter_text.strip():
            raise AnnotationInputError("current_chapter_text 不能为空")
        self.dialogue_candidates = extract_dialogue_candidates(
            self.current_chapter_id,
            self.current_chapter_text,
        )

    def pending_case_by_id(self, case_id: str) -> PendingCase | None:
        """按稳定目标合并本章已登记的未确定案例"""
        return next((case for case in self.pushed_cases if case.target_key == case_id), None)

    def set_phase(self, phase: str) -> None:
        """2026-08-07 用于同步 LangGraph 和工具账本阶段"""
        self.phase = phase

    def snapshot(self) -> dict[str, Any]:
        """2026-08-10 用于在单个工具调用执行前保存可回滚账本状态

        2026-09-13 实时写入结构同进快照：单条小调用失败只回滚该调用，
        之前已写入的记录必须原样保留（失败不丢已写入记录）。
        """
        return deepcopy(
            {
                "phase": self.phase,
                "domain_payloads": self.domain_payloads,
                "bound_payloads": self.bound_payloads,
                "chapter_finished": self.chapter_finished,
                "write_records": self.write_records,
                "completed_chapters": self.completed_chapters,
                "ready_chapter": self.ready_chapter,
                "pushed_cases": self.pushed_cases,
                "authorized_text_paragraph_ids": self.authorized_text_paragraph_ids,
                "text_references": self.text_references,
                "source_anchors": self.source_anchors,
                "cross_chapter_links": self.cross_chapter_links,
                "authorized_event_ids": self.authorized_event_ids,
                "event_trees": self.event_trees,
                # 重提与建根会核销挂起项，后续字段失败时必须随该调用一起恢复
                "pending_child_events": self.pending_child_events,
                "annotation": self.annotation,
                "search_log": self.search_log,
                "written_entities": self.written_entities,
                "metrics_payload": self.metrics_payload,
                "written_dialogues": self.written_dialogues,
                "written_relations": self.written_relations,
                "observation_by_record": self.observation_by_record,
                "tree_key_index": self.tree_key_index,
                "entity_el_index": self.entity_el_index,
                "written_record_keys": self.written_record_keys,
            }
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        """2026-08-10 用于在单个工具调用失败时恢复该调用开始前的账本状态"""
        for field_name, value in snapshot.items():
            setattr(self, field_name, value)

    def resolve_entity_ref(self, ref: str, *, record: str, field: str) -> str:
        """2026-09-14 用于把模型面实体引用（run 级 uuid id / 自定 el）解析成登记名

        两种键空间同一条解析路径：字符串先查本章 的 el 索引，未命中再按
        uuid 反查图登记（uuid5 确定性 id）；未知的 id/el 结构化拒绝并列出已知键。
        """
        if self.graph is None:
            raise AnnotationInvariantError("实体引用解析需要常驻事实图，graph 缺失")
        key = self.entity_el_index.get(str(ref).strip())
        if key is not None:
            display_name = self.graph.entity_names.get(key)
            if display_name is None:
                raise AnnotationStageRejection(
                    f"el 指向的实体尚未入图: {ref}",
                    record=record,
                    field=field,
                    code="unregistered",
                    expected="先用 write_entity 登记该实体（el 在登记当场绑定）",
                )
            return display_name
        try:
            return self.graph.resolve_entity_id(str(ref).strip(), label=f"{record}.{field}")
        except ValueError as exc:
            raise AnnotationStageRejection(
                str(exc),
                record=record,
                field=field,
                code="unknown_entity_id",
                expected=(
                    "本章已登记实体的 run 级 id（write_entity 回执）或本章自定的 el 键；"
                    f"本章已登记：{self._registered_el_pairs()}"
                ),
            ) from None

    def _registered_el_pairs(self) -> str:
        """2026-09-20 用于把本章已登记的 el=名字 对渲染成一行（引用被拒时的就地自纠材料）

        run 54a72932：135 次把实体名称当引用填，而拒绝回执只给 uuid 示例——名称到 uuid
        要跨一层翻译，模型干脆照原样重试。这里给的是"名字 ↔ 可直接填的 el 键"的对照。
        """
        rows = self.entity_ledger()
        rendered = "、".join(f"{row['el']}={row['name']}" for row in rows[:_ENTITY_REF_HINT_LIMIT])
        if len(rows) > _ENTITY_REF_HINT_LIMIT:
            rendered += f" 等 {len(rows)} 个"
        return rendered or "（本章还没有登记实体）"

    def _tree_id(self, tree_key: str) -> str:
        """树身份绑定章与局部键，重试和乱序执行都得到同一 id"""
        return stable_uuid(self.run_scope, self.current_chapter_id, "event_tree", tree_key)

    def _node_id(self, tree_key: str, node_key: str) -> str:
        """节点身份绑定局部键，避免重投递产生另一组事件 id"""
        return stable_uuid(self.run_scope, self.current_chapter_id, "event_node", tree_key, node_key)

    # ------------------------------------------------------------------
    # 实时写入：每个小调用即时落到目标结构，回执即当前真相（2026-09-13 取消暂存区）
    # ------------------------------------------------------------------

    def _require_writable(self, record: str) -> None:
        """用于在每个写入入口统一校验阶段（章冻结后不再接受写入）"""
        if self.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许写入正式标注")

    def _tree_by_key(self, tree_key: str, record: str) -> dict[str, Any]:
        """用于按章内局部键读取已落账的事件树，未建树时给出可自纠报错"""
        tree = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if tree is None:
            raise AnnotationStageRejection(
                f"树键未建: {tree_key}",
                record=record,
                field="el",
                code="unknown_tree",
                expected='先用 write_event(isroot=true, el="t1") 建树，子事件再用 t1/节点键（同轮先根后子即可）',
            )
        return tree

    def _bound_event(self, node_id: str) -> BoundEvent:
        """用于在已落账事件里按节点 id 取节点对象（参与者挂在它上面）"""
        for event in self.bound_payloads.get("events") or []:
            if event.node_id == node_id:
                return event
        raise AnnotationInvariantError(f"事件节点未落账: {node_id}")

    # ------------------------------------------------------------------
    # 实体域：登记即入图并绑定 run 级 uuid id；el 局部键当场绑定，同轮可用

    def apply_entity(self, entity: EntityInput, *, el: str, present: set[str] | None = None) -> str:
        """用于登记或更新一个实体、绑定 el 局部键并即时返回 run 级 id（同键同内容重放幂等）

        present（本次实际提交的字段集合）给定时按部分更新合并：未提交字段保留现值，
        兑现 write_entity 合同"只提交本次变化的字段"；不传=整条记录语义（直连调用）。
        """
        record = f"entity/{entity.name}"
        self._require_writable(record)
        normalized_el = unicodedata.normalize("NFC", el).strip()
        bound_key = self.entity_el_index.get(normalized_el)
        if bound_key is not None and bound_key != _norm_entity_key(entity.name):
            raise AnnotationStageRejection(
                f"el 键已被另一实体占用: {normalized_el}",
                record=record,
                field="el",
                code="duplicate_el",
                expected="换一个 el 键（el 在 章内一对一绑定实体）",
            )
        key = _norm_entity_key(entity.name)
        existing = self.written_entities.get(key)
        if existing is not None and present is not None:
            # 部分更新：先合并成生效记录，再落图（闸门看到的永远是完整记录）
            entity = self._merge_partial_entity(existing, entity, present)
            record = f"entity/{entity.name}"
        if self.graph is None:
            raise AnnotationInvariantError("write_entity 需要常驻事实图，graph 缺失")
        registered = self.graph.entity_types.get(key)
        if registered is not None and registered != entity.entity_type:
            raise AnnotationStageRejection(
                f"已登记实体不允许变更大类: {entity.name}",
                record=record,
                field="entity_type",
                code="type_conflict",
                expected=f"{registered}（同一词条的不同身份请用区分性名称）",
            )
        if existing is None or existing != entity:
            # 同键不同内容=更新语义；同键同内容直接跳过，避免重复操作日志
            self.graph.register_entities([entity])
            self.graph.record_entity_ops([entity], chapter_id=self.current_chapter_id)
            self.written_entities[key] = entity
            self._rebuild_entity_payload()
        self.entity_el_index[normalized_el] = key
        entity_id = self.graph.entity_id(entity.name)
        if entity_id is None:
            raise AnnotationInvariantError(f"实体 id 登记失败: {entity.name}")
        return entity_id

    @staticmethod
    def _merge_partial_entity(existing: EntityInput, incoming: EntityInput, present: set[str]) -> EntityInput:
        """用于已登记实体的部分更新合并（2026-09-14 兑现"只提交本次变化的字段"合同）

        未提交字段保留现值；tags 提交空列表=清空、省略=保留；
        attributes 提交即 JSON Merge Patch（值覆盖、null 删键、省略=整域保留）。
        """
        updates: dict[str, Any] = {}
        if "tags" in present:
            updates["tags"] = incoming.tags
        if "description" in present:
            updates["description"] = incoming.description
        merged = existing.model_copy(update=updates)
        if "attributes" in present:
            patched = dict(existing.attributes or {})
            for attr_key, attr_value in (incoming.attributes or {}).items():
                if attr_value is None:
                    patched.pop(attr_key, None)
                else:
                    patched[attr_key] = attr_value
            merged.attributes = patched
        return merged

    def _rebuild_entity_payload(self) -> None:
        """用于按写入顺序重建当前章 的实体目录载荷"""
        self.domain_payloads["entities"] = EntityDirectoryInput(entities=list(self.written_entities.values()))

    # ------------------------------------------------------------------
    # 指标域：整域一次提交，重复提交按最后一次为准；段落级监督标签随本域提交

    def apply_metrics(self, payload: ChapterMetricsInput) -> None:
        """用于写入当前章 摘要、叙事指标与段落情绪标签（重复提交整域覆盖）

        labels 的 paragraph_id 是段首可见号（正文每段开头的 `N：`），必须属于本章；
        越界段号整次提交拒绝并指明是哪一条标签。落库前按段落坐标映射
        换回全局 paragraph_id（绑定载荷与持久化口径不变）。
        """
        self._require_writable("metrics")
        if payload.labels:
            visible_to_global = dict(self._visible_global_pairs()) if self.paragraph_info is not None else {}
            for label in payload.labels:
                if label.paragraph_id not in visible_to_global:
                    preview = ", ".join(str(pid) for pid in sorted(visible_to_global)[:12]) or "（无）"
                    raise AnnotationStageRejection(
                        f"paragraph_id 不属于本章: {label.paragraph_id}",
                        record="metrics",
                        field="paragraph_id",
                        code="out_of_range",
                        expected=f"本章 可标注的段号（正文段首 `N：`）: {preview}"
                        f"{'…' if len(visible_to_global) > 12 else ''}",
                    )
            self.bound_payloads["paragraph_labels"] = [
                BoundParagraphLabel(
                    paragraph_id=visible_to_global[label.paragraph_id],
                    emotion=label.emotion,
                )
                for label in payload.labels
            ]
        else:
            self.bound_payloads["paragraph_labels"] = []
        self.metrics_payload = payload
        self.domain_payloads["metrics"] = payload

    def _visible_global_pairs(self) -> list[tuple[int, int]]:
        """用于把段首可见号与全局 paragraph_id 配成对（落库映射的单一来源）"""
        assert self.paragraph_info is not None
        return list(zip(self.paragraph_info.visible_ids(), self.paragraph_info.paragraph_ids, strict=True))

    # ------------------------------------------------------------------
    # 对话域：按候选序号即时落账三态判定

    def apply_dialogue(
        self,
        *,
        candidate_index: int,
        verdict: DialogueVerdict,
        speaker_ref: str | None,
        tone: Tone | None,
    ) -> str:
        """用于按候选序号写入一条对话三态判断（同序号重写按更新语义）"""
        record = f"dialogue/{candidate_index}"
        self._require_writable(record)
        candidate_by_index = dict(enumerate(self.dialogue_candidates, start=1))
        if candidate_index not in candidate_by_index:
            raise AnnotationStageRejection(
                f"candidate_index 超出系统候选范围: {candidate_index}",
                record=record,
                field="candidate_index",
                code="out_of_range",
                expected=f"1..{len(self.dialogue_candidates)}（见正文后的 DialogueCandidates 表）",
            )
        speaker_name: str | None = None
        if speaker_ref is not None:
            speaker_name = self.resolve_entity_ref(speaker_ref, record=record, field="speaker")
            if self.graph is not None and self.graph.entity_type(speaker_name) != "character":
                raise AnnotationStageRejection(
                    f"说话人必须是 character: {speaker_name}",
                    record=record,
                    field="speaker",
                    code="not_character",
                    expected="character 类型的实体（run 级 id 或 el 键）",
                )
        try:
            item = DialogueInput(
                candidate_index=candidate_index,
                verdict=verdict,
                speaker=speaker_name,
                tone=tone,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_dialogue") from None
        self.written_dialogues[candidate_index] = item
        self._rebuild_dialogue_payload()
        return record

    def _rebuild_dialogue_payload(self) -> None:
        """用于按候选序重建对话载荷（判定表 + 仅含真对话/独白的落账视图）"""
        candidate_by_index = dict(enumerate(self.dialogue_candidates, start=1))
        items = [self.written_dialogues[index] for index in sorted(self.written_dialogues)]
        bound: list[BoundDialogue] = []
        for item in items:
            if item.verdict == DialogueVerdict.NOT_DIALOGUE:
                continue
            candidate = candidate_by_index[item.candidate_index]
            bound.append(
                BoundDialogue(
                    candidate_index=item.candidate_index,
                    candidate_key=candidate.candidate_key,
                    content=candidate.content,
                    start=candidate.start,
                    end=candidate.end,
                    speaker=item.speaker,
                    tone=item.tone,
                    is_inner_monologue=item.verdict == DialogueVerdict.INNER_MONOLOGUE,
                )
            )
        self.domain_payloads["dialogues"] = items
        self.bound_payloads["dialogues"] = bound

    # ------------------------------------------------------------------
    # 关系域：即时入图，同一对端点重写即整体替换

    def apply_relation(
        self,
        *,
        from_ref: str,
        to_ref: str,
        relation_type: RelationType,
    ) -> tuple[str, str, dict[str, Any]]:
        """用于写入一条本章确认存在的闭合关系边（同一对端点换类型即整体替换）

        返回 (记录键, 本条边的入图结果, 本次写入内容)：assert=新边入图 /
        skipped_existing=已在图上 /
        skipped_self_loop=两端解析到同一实体且非"同一人物"语义（不入图）。
        """
        provisional = f"relation/{from_ref}-{to_ref}/{relation_type}"
        self._require_writable(provisional)
        if self.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        from_name = self.resolve_entity_ref(from_ref, record=provisional, field="from_entity")
        to_name = self.resolve_entity_ref(to_ref, record=provisional, field="to_entity")
        record = f"relation/{from_name}-{to_name}/{relation_type}"
        definition = RELATION_DEFINITIONS[str(relation_type)]
        entity_types = self._fact_entity_catalog()
        for field_name, name, expected_types in (
            ("from_entity", from_name, definition["from_types"]),
            ("to_entity", to_name, definition["to_types"]),
        ):
            try:
                self._require_entity(
                    name,
                    entity_types=entity_types,
                    expected_types=expected_types,
                    label=f"write_relation.{field_name}",
                )
            except ValueError as exc:
                raise AnnotationStageRejection(
                    f"{record}({field_name}={name!r})：{exc}",
                    record=record,
                    field=field_name,
                    code="endpoint_invalid",
                    expected=f"端点类型必须属于 {list(expected_types)}",
                ) from None
        try:
            item = RelationInput(
                from_entity=from_name,
                to_entity=to_name,
                relation_type=relation_type,
            )
        except ValidationError as exc:
            raise _translate_record_validation(record, exc, tool_name="write_relation") from None
        self.written_relations[(item.from_entity, item.to_entity)] = item
        outcomes = self._flush_relations()
        resolution = (self.graph.resolve_name(item.from_entity), self.graph.resolve_name(item.to_entity))
        outcome = next(
            (
                entry["outcome"]
                for entry in outcomes
                if (entry["from"], entry["to"]) == resolution and entry["relation_type"] == str(item.relation_type)
            ),
            "assert",
        )
        return record, outcome, item.model_dump(mode="json")

    def _flush_relations(self) -> list[dict[str, Any]]:
        """用于把本章关系完整集合重放到事实图（先清空本章 assert 再按序重放）

        与旧的"领域结算整体替换"语义一致：同一对端点重写换类型即为替换，
        重放保证图终态与本章关系集合同源。
        """
        if self.graph is None:
            raise AnnotationInvariantError("write_relation 需要常驻事实图，graph 缺失")
        self.graph.reset_chapter_relations()
        outcomes: list[dict[str, Any]] = []
        resolved_items: list[RelationInput] = []
        for item in self.written_relations.values():
            resolved_from = self.graph.resolve_name(item.from_entity)
            resolved_to = self.graph.resolve_name(item.to_entity)
            if _norm_graph_name(resolved_from) == _norm_graph_name(resolved_to):
                # 两端沿同一人物分量解析到同一实体：
                # "同一人物"边（含同批双向重申、跨章重申、传递归并）= 归并已
                # 成立，按合同接受为 skipped_existing；普通关系类型塌成自环
                # 才是退化输入，标 skipped_self_loop。两者照常入图都会在持久化
                # 插入 from_entity_id=to_entity_id 的自环行，违反
                # graph_relations 端点互异约束炸掉完成事务（run a83fae3d
                # 第9章实锤），一律跳过不入图不入操作日志
                is_same_character = RELATION_DEFINITIONS[str(item.relation_type)]["semantics"] == "same_character"
                outcomes.append(
                    {
                        "from": resolved_from,
                        "to": resolved_to,
                        "relation_type": str(item.relation_type),
                        "outcome": "skipped_existing" if is_same_character else "skipped_self_loop",
                    }
                )
                continue
            dumped = item.model_dump(mode="python")
            dumped["from_entity"] = resolved_from
            dumped["to_entity"] = resolved_to
            resolved_item = RelationInput(**dumped)
            resolved_items.append(resolved_item)
            added = self.graph.apply_relation(resolved_item)
            outcomes.append(
                {
                    "from": resolved_from,
                    "to": resolved_to,
                    "relation_type": str(item.relation_type),
                    "outcome": "assert" if added else "skipped_existing",
                }
            )
        self.graph.record_relation_asserts(resolved_items, chapter_id=self.current_chapter_id)
        self.domain_payloads["relations"] = list(self.written_relations.values())
        return outcomes

    # ------------------------------------------------------------------
    # 事件域：建树/加子事件/挂参与者一个调用写完（真实 id 服务端内部持有）

    def apply_event(
        self,
        *,
        el: str,
        isroot: bool,
        description: str,
        evidence: int | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        node_type: EventChildType | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """用于写入一个事件节点：isroot 建根（el=树键），子事件 el=树键/节点键

        根节点键固定 root；子节点父=当时主链尾，main 推进链尾；树内先后=调用顺序。
        伏笔属性（isforeshadowing/confidence）只属于根，isforeshadowing=true 时
        confidence 必填；characters=None 保留该节点已有参与者，给出列表即整体替换。
        """
        record = self._event_record(el, isroot=isroot)
        self._require_writable(record)
        tree_key, _, node_key = el.partition(EL_PATH_SEP)
        tree_key = tree_key.strip()
        node_key = node_key.strip()
        if isroot:
            if not tree_key or node_key:
                raise AnnotationStageRejection(
                    f"根事件的 el 必须是树键（不带路径）: {el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected="根事件 el=树键（如 t1）；子事件才是 树键/节点键（如 t1/e2）",
                )
            if node_type is not None:
                raise AnnotationStageRejection(
                    "type 只属于子事件（根事件由 isroot=true 表达）",
                    record=record,
                    field="type",
                    code="not_on_root",
                    expected="根事件不填 type",
                )
            if isforeshadowing and confidence is None:
                raise AnnotationStageRejection(
                    "isforeshadowing=true 时必须提供 confidence",
                    record=record,
                    field="confidence",
                    code="missing",
                    expected="confidence=high / medium / low（伏笔回收可能性三档）",
                )
            node_id = self._apply_event_root(
                record=record,
                tree_key=tree_key,
                description=description,
                evidence=evidence,
                isforeshadowing=isforeshadowing,
                confidence=confidence,
            )
            # 2026-10-04 树键校验下沉：建根（或根重写）时把先到的暂挂子事件按到达序冲账
            self._flush_pending_children(tree_key)
        else:
            if not tree_key or not node_key:
                raise AnnotationStageRejection(
                    f"子事件的 el 必须是 树键/节点键: {el}",
                    record=record,
                    field="el",
                    code="bad_el",
                    expected='形如 t1/e2（节点键不得占用 root）；建树请用 write_event(isroot=true, el="t1")',
                )
            if node_key == RESERVED_ROOT_KEY:
                raise AnnotationStageRejection(
                    f"子事件不得占用节点键 {RESERVED_ROOT_KEY}",
                    record=record,
                    field="el",
                    code="reserved",
                    expected="换一个节点键（root 固定指根事件）",
                )
            if isforeshadowing or confidence is not None:
                raise AnnotationStageRejection(
                    "伏笔属性（isforeshadowing/confidence）只属于根事件",
                    record=record,
                    field="isforeshadowing",
                    code="not_on_child",
                    expected="子事件只填 el/type/description/characters",
                )
            if node_type is None:
                raise AnnotationStageRejection(
                    "子事件必须提供 type",
                    record=record,
                    field="type",
                    code="missing",
                    expected='type="main"（顺延主因链）或 "secondary"（挂在当时主链尾）',
                )
            if self.tree_key_index.get(tree_key) is None:
                # 2026-10-04 树键校验下沉：根未建时子事件不再即时拒绝，挂起等建根冲账
                #（写面本来就是纯内存账本、整章成功才单事务落库，调用期因果校验只制造返工）
                self.pending_child_events.setdefault(tree_key, []).append(
                    {
                        "record": record,
                        "node_key": node_key,
                        "node_type": node_type,
                        "description": description,
                        "evidence": evidence,
                        "characters": characters,
                    }
                )
                return record
            node_id = self._apply_event_child(
                record=record,
                tree_key=tree_key,
                node_key=node_key,
                node_type=node_type,
                description=description,
                evidence=evidence,
            )
        if characters is not None:
            self._apply_participants(
                node_record=record,
                node_id=node_id,
                characters=characters,
            )
        return record

    def _event_record(self, el: str, *, isroot: bool) -> str:
        """用于把模型面 el 归一成记录键（根记录 = 树键/root）"""
        cleaned = unicodedata.normalize("NFC", el).strip()
        if isroot or EL_PATH_SEP not in cleaned:
            return f"{cleaned}/{RESERVED_ROOT_KEY}"
        return cleaned

    _IR_RECORD_RE = re.compile(r"([a-z_]+)/(entity|dialogue|relation|event)/(.+)")

    def production_record_key(self, key: str) -> str:
        """用于把模型面 IR 记录键规范成生产记录键（已是生产键的原样返回）

        2026-09-20 起 subagent 路径的 written_record_keys 混装两种键：构造器 plan 的
        IR 键（structure/entity/a1、event/t1、evidence/dialogue/3）与生产写入面的
        生产键（entity/{name}、event:t1/root、dialogue/3）。push_case/anchor_record 按
        written 集合校验后原样存进 target_ref/source_anchors，而正式提交的
        bind_record_target 只认生产键——IR 键落库必炸"原文锚点不是本章正式产出"。
        这里在工具入口统一翻译成生产键，两类消费点共用这一份规范。
        """
        # 2026-10-04 裸树键补全：模型按自然形态拿树键当记录键（run 4cb054dc 18 次
        # anchor 被拒），树键在索引里时唯一指到它的根记录，统一补 /root
        if key in self.tree_key_index:
            return f"{key}/{RESERVED_ROOT_KEY}"
        match = self._IR_RECORD_RE.fullmatch(key)
        if match is not None:
            role, domain, body = match.groups()
            if domain == "entity":
                name = self.resolve_entity_ref(f"{role}:{body}", record=key, field="record_id")
                return f"entity/{name}"
            if domain == "dialogue":
                return f"dialogue/{body}"
            if domain == "event":
                # 2026-10-03 非事件角色写树时的 IR 键（structure/event/t1）：树键按
                # 角色命名空间化落库（namespace_event_el → structure:t1）
                namespaced = f"{role}{ROLE_NAMESPACE_SEP}{body}"
                return namespaced if EL_PATH_SEP in body else f"{namespaced}/{RESERVED_ROOT_KEY}"
            if domain == "relation":
                return self._production_relation_key(key, role, body)
            return key
        if key.startswith("event/"):
            # 2026-10-03 修正事件键翻译：子代理事件树落库时树键按角色命名空间化
            # （namespace_event_el：t1 → event:t1），节点 id 以命名空间树键参与
            # stable_uuid——IR 前缀 "event/" 恰是事件角色自己的前缀（_record_of 去重），
            # 翻译必须保留命名空间。此前翻成 t1/root、t1/e12，提交期 bind_record_target
            # 按无命名空间树键算 node_id 永不匹配，案例指向事件的章必炸"原文锚点的
            # 事件不是本章正式产出"（run 4a6c268c ch21 三连炸实证）。written 集合里的
            # "event/..." 只来自子代理构造器日志（solo 面 write_event 回执本就是生产键
            # event:t1/root 或 t1/root 原样登记），无条件翻译不影响 solo 路径。
            el = key.removeprefix("event/")
            namespaced = f"event{ROLE_NAMESPACE_SEP}{el}"
            return namespaced if EL_PATH_SEP in el else f"{namespaced}/{RESERVED_ROOT_KEY}"
        return key

    def _production_relation_key(self, key: str, role: str, body: str) -> str:
        """用于把 IR 关系键翻译成生产键；消解不了当场拒绝（毒键入库必炸提交期 bind）

        2026-10-03 角色命名空间修复：IR 关系键的端点 el 是 subagent 局部键，落库时按
        角色命名空间化（namespace_el → structure:qianjin），解析必须带角色前缀——此前用
        裸 el 查索引永不命中，翻译原样返回 "structure/relation/a-b"，提交期
        bind_record_target 前缀不匹配 entity/relation/dialogue，落进事件分支按
        tree_key="structure" 算 node_id 永不匹配，整章炸"原文锚点的事件不是本章正式产出"
        （run 4a6c268c ch21 attempt 14/15 实证）。原样返回等价于埋毒键，改为当场拒绝：
        模型拿结构化回执换一条可消解的记录或省略 record_id，不再连烧 3 个 attempt。
        """
        from_el, sep, to_el = body.rpartition("-")
        if not sep:
            raise AnnotationStageRejection(
                f"{key} 不是可消解的关系记录键（缺少 from-to 端点形态）",
                record=key,
                field="record_id",
                code="unknown_record",
                expected="关系 IR 键形如 structure/relation/from_el-to_el（端点 el 是你登记实体时的 id）",
            )
        if self.graph is None:
            raise AnnotationInvariantError("关系键消解需要常驻事实图，graph 缺失")
        names: list[str] = []
        for el in (from_el, to_el):
            names.append(self.resolve_entity_ref(f"{role}{ROLE_NAMESPACE_SEP}{el}", record=key, field="record_id"))
        types = {
            str(op["relation_type"])
            for op in self.graph.relation_assert_ops
            if op["from_entity"] == names[0] and op["to_entity"] == names[1]
        }
        if len(types) != 1:
            raise AnnotationStageRejection(
                f"{key} 无法唯一消解成一条已写出的关系边（两端间存在 {len(types)} 种关系类型）",
                record=key,
                field="record_id",
                code="unknown_record",
                expected="两端之间恰好写出过一条关系边时才能作为案例目标；请换可消解的记录或省略 record_id",
            )
        return f"relation/{names[0]}-{names[1]}/{types.pop()}"

    def _event_evidence_paragraph_id(
        self, evidence: int | None, *, record: str, existing: BoundEvent | None = None
    ) -> int | None:
        """将段首可见号绑定到本章段落；重写未给证据时保留原锚点。"""
        if evidence is None and existing is not None and existing.evidence_paragraph_id is not None:
            return existing.evidence_paragraph_id
        if self.paragraph_info is None:
            return None
        visible_to_global = dict(self._visible_global_pairs())
        if evidence is None and len(visible_to_global) == 1:
            return next(iter(visible_to_global.values()))
        if evidence is None:
            raise AnnotationStageRejection(
                "事件缺少所在段证据",
                record=record,
                field="evidence",
                code="missing_evidence",
                expected="填写本章正文段首的可见号（单个整数）",
            )
        if isinstance(evidence, bool) or not isinstance(evidence, int) or evidence not in visible_to_global:
            preview = ", ".join(str(number) for number in sorted(visible_to_global)[:12])
            raise AnnotationStageRejection(
                f"事件 evidence 不属于本章: {evidence}",
                record=record,
                field="evidence",
                code="out_of_range",
                expected=f"本章可用段首号: {preview}{'…' if len(visible_to_global) > 12 else ''}",
            )
        return visible_to_global[evidence]

    def _apply_event_root(
        self,
        *,
        record: str,
        tree_key: str,
        description: str,
        evidence: int | None,
        isforeshadowing: bool,
        confidence: Confidence | None,
    ) -> str:
        """用于建树并即时落账根事件（同树键重写按更新语义），返回根节点 id"""
        existing = self.event_trees.get(self.tree_key_index.get(tree_key, ""))
        if existing is not None:
            root_event = self._bound_event(existing["root_node_id"])
            root_event.evidence_paragraph_id = self._event_evidence_paragraph_id(
                evidence, record=record, existing=root_event
            )
            root_event.description = description
            root_event.is_foreshadow_setup = isforeshadowing
            root_event.payoff_likelihood = confidence
            existing["isforeshadowing"] = isforeshadowing
            return str(existing["root_node_id"])
        tree_id = self._tree_id(tree_key)
        root_node_id = self._node_id(tree_key, RESERVED_ROOT_KEY)
        evidence_paragraph_id = self._event_evidence_paragraph_id(evidence, record=record)
        root_event = BoundEvent(
            node_id=root_node_id,
            tree_id=tree_id,
            parent_node_id=None,
            cause_role="root",
            description=description,
            evidence_paragraph_id=evidence_paragraph_id,
            participants=[],
            is_foreshadow_setup=isforeshadowing,
            payoff_likelihood=confidence,
        )
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.append(root_event)
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["events"] = events_bound
        self.event_trees[tree_id] = {
            "tree_id": tree_id,
            "chapter_id": self.current_chapter_id,
            "chapter_order": self.current_chapter_order,
            "root_node_id": root_node_id,
            "trunk_tail": root_node_id,
            "isforeshadowing": isforeshadowing,
            # node_key → node_id：模型侧只用章内局部键寻址（根键固定 root）
            "nodes": {RESERVED_ROOT_KEY: root_node_id},
        }
        self.tree_key_index[tree_key] = tree_id
        self.authorized_event_ids.add(root_node_id)
        return root_node_id

    def _apply_event_child(
        self,
        *,
        record: str,
        tree_key: str,
        node_key: str,
        node_type: EventChildType,
        description: str,
        evidence: int | None,
    ) -> str:
        """用于在已建的树上追加/更新一个子事件，返回节点 id

        "main" 顺延主因链（成为新的链尾）/"secondary" 挂在当时主链尾；
        树内先后=调用顺序（order 参数已下线，无任何下游消费）。
        """
        tree = self._tree_by_key(tree_key, record)
        existing_node_id = tree["nodes"].get(node_key)
        if existing_node_id is not None:
            event = self._bound_event(str(existing_node_id))
            if str(event.cause_role) != str(node_type):
                raise AnnotationStageRejection(
                    f"节点已建，type 不允许改写: {tree_key}/{node_key}",
                    record=record,
                    field="type",
                    code="immutable",
                    expected="删除重写需换节点键（该节点 type=已定的 main/secondary）",
                )
            event.evidence_paragraph_id = self._event_evidence_paragraph_id(evidence, record=record, existing=event)
            event.description = description
            self._discard_resubmitted_pending({(node_key, description)}, exclude_tree=tree_key)
            return str(existing_node_id)
        parent_node_id = str(tree["trunk_tail"])
        node_id = self._node_id(tree_key, node_key)
        evidence_paragraph_id = self._event_evidence_paragraph_id(evidence, record=record)
        event = BoundEvent(
            node_id=node_id,
            tree_id=str(tree["tree_id"]),
            parent_node_id=parent_node_id,
            cause_role=cast("EventCauseRole", str(node_type)),
            description=description,
            evidence_paragraph_id=evidence_paragraph_id,
            participants=[],
        )
        events_bound = list(self.bound_payloads.get("events") or [])
        events_bound.append(event)
        self.bound_payloads["events"] = events_bound
        self.domain_payloads["events"] = events_bound
        tree["nodes"][node_key] = node_id
        if str(node_type) == "main":
            tree["trunk_tail"] = node_id
        self.authorized_event_ids.add(node_id)
        self._discard_resubmitted_pending({(node_key, description)}, exclude_tree=tree_key)
        return node_id

    def _discard_resubmitted_pending(
        self, written: set[tuple[str, str]], *, exclude_tree: str | None = None,
    ) -> None:
        """只核销节点键与描述完全一致的重提项，保留未写入项及其原有到达顺序"""
        for tree_key, items in list(self.pending_child_events.items()):
            if tree_key == exclude_tree:
                continue
            remaining = [item for item in items if (str(item["node_key"]), str(item["description"])) not in written]
            if remaining:
                self.pending_child_events[tree_key] = remaining
            else:
                del self.pending_child_events[tree_key]

    def _reconcile_pending_children(self) -> None:
        """收尾前核对实际已落账的子节点，清理早前错误桶中已被正确重提的挂起项"""
        event_by_id = {str(event.node_id): event for event in self.bound_payloads.get("events") or []}
        written = {
            (str(node_key), event_by_id[str(node_id)].description)
            for tree in self.event_trees.values()
            for node_key, node_id in tree.get("nodes", {}).items()
            if node_key != RESERVED_ROOT_KEY and str(node_id) in event_by_id
        }
        self._discard_resubmitted_pending(written)

    def _flush_pending_children(self, tree_key: str) -> None:
        """用于建根时按到达顺序冲账先于根提交的暂挂子事件（含各自参与者）"""
        pending = self.pending_child_events.pop(tree_key, None)
        if not pending:
            return
        for item in pending:
            node_id = self._apply_event_child(
                record=str(item["record"]),
                tree_key=tree_key,
                node_key=str(item["node_key"]),
                node_type=cast("EventChildType", item["node_type"]),
                description=str(item["description"]),
                evidence=item.get("evidence"),
            )
            characters = item.get("characters")
            if characters is not None:
                self._apply_participants(
                    node_record=str(item["record"]),
                    node_id=node_id,
                    characters=characters,
                )

    def is_pending_child(self, record: str) -> bool:
        """用于判断该生产记录键是否仍在暂挂子事件缓冲里（树根未建，调用期未落账）"""
        return any(
            str(item.get("record")) == record for items in self.pending_child_events.values() for item in items
        )

    def _apply_participants(
        self,
        *,
        node_record: str,
        node_id: str,
        characters: list[ParticipantArg],
    ) -> None:
        """用于把 characters 数组整体替换到指定节点的参与者列表

        按登记类型分流：character 三态可空、给了就派生人物动态状态
        （人物榜/Greimas/实体状态注入的唯一数据源），role 缺省按登记类型取默认；
        非 character 不接受三态；同一实体在数组内只允许出现一次；
        旧记录键下的动态状态先清后建（替换语义）。
        """
        if self.graph is None:
            raise AnnotationInvariantError("参与者解析需要常驻事实图，graph 缺失")
        event = self._bound_event(node_id)
        for stale in [key for key in self.observation_by_record if key.startswith(f"{node_record}/participant/")]:
            del self.observation_by_record[stale]
        seen: set[str] = set()
        participants: list[EventParticipantInput] = []
        for arg in characters:
            participant_record = f"{node_record}/participant/{arg.entityid}"
            entity_name = self.resolve_entity_ref(arg.entityid, record=participant_record, field="entityid")
            key = _norm_entity_key(entity_name)
            if key in seen:
                raise AnnotationStageRejection(
                    f"同一实体在 characters 数组内重复出现: {entity_name}",
                    record=participant_record,
                    field="entityid",
                    code="duplicate_participant",
                    expected="每个实体一次提交只出现一次（本数组即该节点参与者的完整集合）",
                )
            seen.add(key)
            actual_type = self.graph.entity_type(entity_name)
            if actual_type is None:
                raise AnnotationStageRejection(
                    f"参与者实体未登记: {entity_name}",
                    record=participant_record,
                    field="entityid",
                    code="unregistered",
                    expected="先用 write_entity 登记本章实体",
                )
            # 2026-10-04 合同放开：role 可省略，按实体登记类型给缺省
            # （character→主体、location→地点、其余→客体）；显式写错仍拒
            effective_role = arg.role or (
                EventParticipantRole.LOCATION
                if actual_type == EntityType.LOCATION.value
                else EventParticipantRole.SUBJECT
                if actual_type == EntityType.CHARACTER.value
                else EventParticipantRole.OBJECT
            )
            if effective_role == EventParticipantRole.LOCATION and actual_type != EntityType.LOCATION.value:
                raise AnnotationStageRejection(
                    f"地点角色端点必须是 location: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="role",
                    code="role_type_mismatch",
                    expected="地点角色只用于 location 实体",
                )
            has_observation = any(value is not None for value in (arg.narrative_role, arg.action, arg.emotion))
            if actual_type == EntityType.CHARACTER.value:
                # 2026-10-04 合同放开：三态字段可空落账（不再要求必填），缺省由消费方按空处理
                if arg.action is not None:
                    self._reject_duplicate_observation(participant_record, entity_name, arg.action)
                # 2026-10-04 三态全空不产动态状态行：同一人物在多个事件上无动作参与是放开后的
                # 正常形态，全空行既无信息量又会在收尾校验撞 (character, action=None) 重复语义；
                # 参与者本身仍随事件落账，只是不进 character_observations
                if has_observation:
                    self.observation_by_record[participant_record] = BoundCharacterObservation(
                        character=entity_name,
                        role_function=arg.narrative_role,
                        action=arg.action,
                        emotion=arg.emotion,
                    )
            elif has_observation:
                raise AnnotationStageRejection(
                    f"narrative_role/action/emotion 只属于 character 参与者: {entity_name}（登记类型 {actual_type}）",
                    record=participant_record,
                    field="narrative_role",
                    code="observation_on_noncharacter",
                    expected="非 character 条目只填 entityid/role",
                )
            try:
                participants.append(
                    EventParticipantInput(
                        entity=entity_name,
                        role=effective_role,
                        narrative_role=arg.narrative_role,
                        action=arg.action,
                        emotion=arg.emotion,
                    )
                )
            except ValidationError as exc:
                raise _translate_record_validation(participant_record, exc, tool_name="write_event") from None
        event.participants = participants
        self._rebuild_observation_payload()

    def _rebuild_observation_payload(self) -> None:
        """用于按写入顺序重建人物动态状态载荷"""
        observations = list(self.observation_by_record.values())
        self.domain_payloads["character_observations"] = observations
        self.bound_payloads["character_observations"] = observations

    def _reject_duplicate_observation(
        self,
        record: str,
        entity_name: str,
        action: str,
    ) -> None:
        """用于挡住同一人物的重复动态状态（人物,动作 在本章 内唯一）

        写入点校验：触发时只拒绝这一条，已写入的记录与其他节点不受影响。
        """
        for other_record, observation in self.observation_by_record.items():
            if other_record == record:
                continue
            if (observation.character, observation.action) != (entity_name, action):
                continue
            raise AnnotationStageRejection(
                f"人物动态状态重复：{other_record}(character={observation.character}, action={observation.action})"
                f" 与 {record}(character={entity_name}, action={action}) 相撞",
                record=record,
                field="action",
                code="duplicate_observation",
                expected="本章非空的 (character, action) 组合唯一",
            )

    # ------------------------------------------------------------------
    # 2026-09-14 回执返回写入内容（所有 write 回执回显写入内容）；2026-09-19 id 纪律：
    # content=本次写入的生效终值（服务端归一/端点解析已完成），带 run 级 uuid id

    def entity_content(self, entity: EntityInput) -> dict[str, Any]:
        """用于回显 write_entity 登记/更新后该实体生效记录（含 run 级 id）"""
        stored = self.written_entities.get(_norm_entity_key(entity.name), entity)
        content = stored.model_dump(mode="json")
        content["id"] = self.graph.entity_id(stored.name) if self.graph is not None else None
        return content

    def metrics_content(self) -> dict[str, Any]:
        """用于回显 write_metrics 提交后的整域生效指标（整域覆盖，以最新回执为准）"""
        if self.metrics_payload is None:
            raise AnnotationInvariantError("write_metrics 回显需要 metrics_payload 已落账")
        return self.metrics_payload.model_dump(mode="json")

    def dialogue_content(self, candidate_index: int) -> dict[str, Any]:
        """用于回显 write_dialogue 后该候选的生效判定（speaker 已解析为登记名，带 candidate_key）"""
        content = self.written_dialogues[candidate_index].model_dump(mode="json")
        content["candidate_key"] = self.dialogue_candidates[candidate_index - 1].candidate_key
        return content

    def event_content(self, *, el: str, isroot: bool) -> dict[str, Any]:
        """用于回显 write_event 后该节点的服务端终值（节点 id/描述/伏笔属性/参与者三态）

        el 与 isroot 是模型侧提交别名、树上不存储，因此不进 content；id 纪律下
        content 带 run 级 uuid 节点 id（=落库 event_id），树级 uuid 不外露。
        """
        cleaned = unicodedata.normalize("NFC", el).strip()
        tree_key, _, node_key = cleaned.partition(EL_PATH_SEP)
        tree_key_clean = tree_key.strip()
        tree = self.event_trees.get(self.tree_key_index.get(tree_key_clean, ""))
        if tree is None:
            if tree_key_clean in self.pending_child_events:
                # 2026-10-04 树键校验下沉：暂挂子事件的回显即挂起状态本身
                return {
                    "deferred": True,
                    "note": f"树 {tree_key_clean} 尚未建根：该子事件已挂起，根建好后自动生效",
                }
            raise AnnotationInvariantError(f"write_event 回显需要账本内事件树: {tree_key}")
        if isroot or not node_key.strip():
            event = self._bound_event(str(tree["root_node_id"]))
        else:
            event = self._bound_event(str(tree["nodes"][node_key.strip()]))
        content: dict[str, Any] = {
            "id": str(event.node_id),
            "description": event.description,
        }
        if isroot:
            content["isforeshadowing"] = bool(tree["isforeshadowing"])
            confidence = event.payoff_likelihood
            content["confidence"] = str(confidence) if confidence is not None else None
        else:
            content["type"] = str(event.cause_role)
        content["characters"] = [p.model_dump(mode="json") for p in event.participants]
        return content

    # ------------------------------------------------------------------
    # 2026-09-14 进度账本数据源（每回合注入最新进展，不走回执 rollup）：
    # 服务端不把思考重放给模型，"已写到哪、还欠哪些"由系统逐回合直给——四个
    # *_ledger() 供 graph 侧渲染写者面【进度账本】注入块（局部键面，不露 uuid）。

    def entity_ledger(self) -> list[dict[str, Any]]:
        """用于列举本章已写入实体的账本（el 绑定序）：{el, name, id, entity_type}，带 tags 与同一人物别名

        别名列（alias）与标签列直接对抗"外号没接上登记名→重复注册实体"（run b7477080
        ch3 把猴子当新人物又建一套登记）。
        2026-09-20 entity_type：大类一经登记不可变更，账本行带上它，省得模型凭记忆重写
        时写错大类（run 54a72932：10 次"实体大类已登记为 X"的拒绝）。
        """
        rows: list[dict[str, Any]] = []
        for el, key in self.entity_el_index.items():
            stored = self.written_entities.get(key)
            if stored is None:
                continue
            row: dict[str, Any] = {
                "el": el,
                "name": stored.name,
                "id": self.graph.entity_id(stored.name) if self.graph is not None else None,
                "entity_type": str(stored.entity_type),
            }
            if stored.tags:
                row["tags"] = list(stored.tags)
            if self.graph is not None:
                aliases = self.graph.alias_group(stored.name)
                if aliases:
                    row["aliases"] = aliases
            rows.append(row)
        return rows

    def relation_ledger(self) -> list[str]:
        """用于列举本章当前生效关系边的账本："起-止/类型"（登记名）"""
        return [f"{item.from_entity}-{item.to_entity}/{item.relation_type}" for item in self.written_relations.values()]

    def event_ledger(self) -> dict[str, dict[str, Any]]:
        """用于本章事件树的快照账本：树键 → 根描述/伏笔标记（含置信现值）/子键与类型/主链尾

        键是模型侧的局部键（树键与子事件键），不露 uuid；trunk_tail=root 表示主链还没有子节点。
        """
        view: dict[str, dict[str, Any]] = {}
        for tree_key, tree_id in self.tree_key_index.items():
            tree = self.event_trees.get(tree_id) or {}
            nodes: dict[str, str] = dict(tree.get("nodes") or {})
            root_id = str(tree.get("root_node_id", ""))
            root_event = self._bound_event(root_id)
            children: dict[str, str] = {}
            for node_key, node_id in nodes.items():
                if node_key == RESERVED_ROOT_KEY:
                    continue
                children[node_key] = str(self._bound_event(str(node_id)).cause_role)
            entry: dict[str, Any] = {
                "root": root_event.description,
                "foreshadowing": bool(tree.get("isforeshadowing")),
                "children": children,
                "trunk_tail": next(
                    (k for k, v in nodes.items() if str(v) == str(tree.get("trunk_tail"))), RESERVED_ROOT_KEY
                ),
            }
            if entry["foreshadowing"] and root_event.payoff_likelihood is not None:
                entry["confidence"] = str(root_event.payoff_likelihood)
            view[tree_key] = entry
        return view

    def dialogue_ledger(self) -> dict[str, Any]:
        """用于对话域账本：候选总数/已判定写入数/未写入编号 + 已判条目的判定值

        judged 带值是对抗整册重推的关键：只报"已判 N/M"时模型把未判清单读成
        "一切从零重推"，写完的条目也要回文核对（run b7477080 ch1 全册过 6 遍）。
        """
        judged: dict[str, str] = {}
        for index, item in sorted(self.written_dialogues.items()):
            if str(item.verdict) != "dialogue":
                judged[str(index)] = str(item.verdict)
            else:
                judged[str(index)] = f"{item.speaker or 'null'}/{item.tone or 'null'}"
        pending = sorted(set(range(1, len(self.dialogue_candidates) + 1)) - set(self.written_dialogues))
        return {
            "total": len(self.dialogue_candidates),
            "written": len(self.written_dialogues),
            "pending": pending,
            "judged": judged,
        }

    # ------------------------------------------------------------------
    # 收尾声明：唯一 finish，系统据此校验并冻结当前章（冻结单位=整章）

    def finish_chapter(self) -> dict[str, Any]:
        """校验本章必需产物及逐条对话判定后组装结果，不补造未判内容

        构造失败整体回滚，已写入记录原样保留；结构校验不等于语义正确性证明
        """
        if self.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish")
        # 核销只依赖已接受事实，后续收尾拒绝也不把已过期的挂起项恢复回来
        self._reconcile_pending_children()
        if self.metrics_payload is None:
            raise AnnotationStageRejection(
                "本章指标尚未提交，不予收尾",
                record="finish",
                field="metrics",
                code="missing_record",
                expected="先 write_metrics 提交摘要与叙事指标",
            )
        snapshot = self.snapshot()
        try:
            if self.pending_child_events:
                # 2026-10-04 树键校验下沉的兜底：根始终没建时暂挂子事件不许静默丢弃；
                # 点名各树挂起的节点键（只有 "t1×3" 数量时模型无从判断挂的是哪些子事件）
                detail = "、".join(
                    f"{tree_key}({', '.join(str(item['node_key']) for item in items)})"
                    for tree_key, items in self.pending_child_events.items()
                )
                raise AnnotationStageRejection(
                    f"子事件仍挂起等待建根: {detail}",
                    record="finish",
                    field="events",
                    code="missing_record",
                    expected="先 write_event(isroot=true, el=树键) 建根（挂起的子事件自动生效），或换树键重写",
                )
            pending = self.dialogue_ledger()["pending"]
            if pending:
                raise AnnotationStageRejection(
                    f"对话候选尚未判定: {pending}",
                    record="finish",
                    field="dialogues",
                    code="missing_record",
                    expected="逐条判定候选后再 finish，未确定内容登记案例池",
                )
            self._ensure_domain_payloads()
            self.ready_chapter = self._build_ready_chapter()
        except Exception as exc:
            self.restore(snapshot)
            if isinstance(exc, AnnotationStageRejection):
                raise
            raise AnnotationStageRejection(
                f"章节收尾校验失败: {exc}",
                record="finish",
                code="assembly_failed",
                expected="按报错核对已写入的记录后重新 finish",
            ) from None
        self.write_records.extend(self._chapter_write_records())
        self.chapter_finished = True
        return {
            "status": "completed",
            "chapter_id": self.current_chapter_id,
            "records": self._written_counts(),
        }

    def _ensure_domain_payloads(self) -> None:
        """用于收尾时补齐空域载荷（零实体/零关系/零事件都是合法终态）"""
        self.domain_payloads.setdefault(
            "entities",
            EntityDirectoryInput(entities=list(self.written_entities.values())),
        )
        self.domain_payloads.setdefault("relations", list(self.written_relations.values()))
        self.domain_payloads.setdefault("dialogues", list(self.written_dialogues.values()))
        self.domain_payloads.setdefault("events", list(self.bound_payloads.get("events") or []))
        self.domain_payloads.setdefault(
            "character_observations",
            list(self.observation_by_record.values()),
        )
        self.bound_payloads.setdefault("events", list(self.domain_payloads["events"]))
        self.bound_payloads.setdefault(
            "character_observations",
            list(self.domain_payloads["character_observations"]),
        )
        self.bound_payloads.setdefault("dialogues", [])
        self.bound_payloads.setdefault("paragraph_labels", [])

    def _chapter_write_records(self) -> list[dict[str, Any]]:
        """用于收尾时把本章 的写入汇总成领域级审计记录（形状与此前一致）"""
        records: list[dict[str, Any]] = [
            {
                "chapter_id": self.current_chapter_id,
                "domain": "entities",
                "payload": EntityDirectoryInput(entities=list(self.written_entities.values())).model_dump(mode="json"),
            }
        ]
        if self.metrics_payload is not None:
            records.append(
                {
                    "chapter_id": self.current_chapter_id,
                    "domain": "metrics",
                    "payload": self.metrics_payload.model_dump(mode="json"),
                }
            )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
                "domain": "events",
                "payload": {
                    "tool": "write_event",
                    "trees": self._event_tree_records(),
                    "character_observation_count": len(self.observation_by_record),
                    "finalized": True,
                },
            }
        )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
                "domain": "relations",
                "payload": [item.model_dump(mode="json") for item in self.written_relations.values()],
            }
        )
        records.append(
            {
                "chapter_id": self.current_chapter_id,
                "domain": "dialogues",
                "payload": [item.model_dump(mode="json") for item in (self.domain_payloads.get("dialogues") or [])],
            }
        )
        return records

    def _event_tree_records(self) -> list[dict[str, Any]]:
        """用于按建树顺序汇总每棵树的结构（节点键与父子关系，不含真实 id）"""
        trees: list[dict[str, Any]] = []
        for tree_key, tree_id in self.tree_key_index.items():
            tree = self.event_trees.get(tree_id) or {}
            children: list[dict[str, Any]] = []
            for node_key, node_id in tree.get("nodes", {}).items():
                if node_key == RESERVED_ROOT_KEY:
                    continue
                event = self._bound_event(str(node_id))
                children.append(
                    {
                        "node_key": node_key,
                        "type": str(event.cause_role),
                        "parent_node_key": self._node_key_of(tree, str(event.parent_node_id or "")),
                    }
                )
            root_event = self._bound_event(str(tree.get("root_node_id") or ""))
            trees.append(
                {
                    "tree_key": tree_key,
                    "description": root_event.description,
                    "isforeshadowing": bool(tree.get("isforeshadowing")),
                    "children": children,
                }
            )
        return trees

    def _node_key_of(self, tree: dict[str, Any], node_id: str) -> str | None:
        """用于按节点 id 反查章内节点键（审计记录不暴露真实 id）"""
        for node_key, candidate in tree.get("nodes", {}).items():
            if str(candidate) == node_id:
                return str(node_key)
        return None

    def _written_counts(self) -> dict[str, int]:
        """用于收尾回执给出各域写入条数（模型面只需知道写了多少）"""
        return {
            "entities": len(self.written_entities),
            "metrics": 1 if self.metrics_payload is not None else 0,
            "events": len(self.bound_payloads.get("events") or []),
            "relations": len(self.written_relations),
            "dialogues": len(self.written_dialogues),
            "character_observations": len(self.observation_by_record),
            "paragraph_labels": len(self.bound_payloads.get("paragraph_labels") or []),
        }

    def _entity_catalog(
        self,
        directory: EntityDirectoryInput,
    ) -> tuple[dict[str, EntityType], dict[str, str]]:
        """2026-08-08 用于建立当前章 唯一实体名称和类型目录"""
        types: dict[str, EntityType] = {}
        names: dict[str, str] = {}
        for entity in directory.entities:
            normalized = unicodedata.normalize("NFC", entity.name).strip()
            key = normalized.casefold()
            if key in types:
                raise ValueError(f"本章 实体名称重复: {normalized}")
            types[key] = entity.entity_type
            names[key] = normalized
        return types, names

    def _fact_entity_catalog(self) -> dict[str, EntityType]:
        """2026-08-10 用于合并内存图已登记实体与当前章 已声明实体作为事实端点目录"""
        catalog = dict(self.graph.entity_types) if self.graph is not None else {}
        entities_payload = self.domain_payloads.get("entities")
        if entities_payload is not None:
            types, _names = self._entity_catalog(entities_payload)
            catalog.update(types)
        return catalog

    def _require_entity(
        self,
        name: str,
        *,
        entity_types: dict[str, EntityType],
        expected_types: tuple[EntityType, ...] | None = None,
        label: str,
    ) -> str:
        """2026-08-11 用于校验事实端点已由当前章 实体目录或已登记实体声明（别名解析后）"""
        key = unicodedata.normalize("NFC", name).strip().casefold()
        resolved_key = key
        if self.graph is not None:
            resolved_key = _norm_graph_name(self.graph.resolve_name(name))
        actual_type = entity_types.get(resolved_key) or entity_types.get(key)
        if actual_type is None:
            raise ValueError(f"{label} 未在当前章 登记: {name}（请先用 write_entity 登记该实体，或改用已登记实体名）")
        if expected_types is not None and actual_type not in expected_types:
            raise ValueError(
                f"{label} 端点类型必须属于 {[str(t) for t in expected_types]}，实际为 {actual_type}"
                f"（该名称在图上的登记类型是 {actual_type}，"
                "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
            )
        return key

    # ------------------------------------------------------------------
    # 事件锚点与证据派生（2026-08-18 事件森林/DAG）
    # ------------------------------------------------------------------
    # 2026-08-22 重构：证据升为章级单份，由持久化层统一盖章，
    # 账本侧不再持有任何锚点/哈希派生逻辑

    def _validate_domain_duplicates(self, payloads: dict[str, Any]) -> None:
        """2026-08-07 用于拒绝当前章 各领域的重复语义事实

        2026-10-04 回执点名违规记录：拒绝消息列出相撞各条的生产记录键与字段值，不再只报
        下标+域名——run 4cb054dc ch12 自愈回合烧 60%+ 思考逆向解读拒绝合同，直接诱因就是
        "[3, 7] character_observations 重复语义项"这种无法定位的形态。
        """
        # 2026-10-04 三态放开后判重只在写入点做（_reject_duplicate_observation，动作非空才查）：
        # 同一人物在多个事件上无动作出场是合法形态，(人物, None) 相撞不是重复语义
        errors: list[str] = []
        for domain, entries in self._duplicate_entries(payloads).items():
            seen: dict[tuple[Any, ...], list[str]] = {}
            for key, label in entries:
                seen.setdefault(key, []).append(label)
            for labels in seen.values():
                if len(labels) > 1:
                    errors.append(f"{domain} 重复语义项: {' 与 '.join(labels)}")
        if errors:
            raise ValueError("；".join(errors))

    def _duplicate_entries(self, payloads: dict[str, Any]) -> dict[str, list[tuple[tuple[Any, ...], str]]]:
        """用于为判重载荷生成 (语义键, 记录点名标签) 对（标签与键同源同序）

        character_observations 的载荷顺序与 observation_by_record 一致（同一 dict 的
        values/keys），逐条能反查回生产记录键；events 用树内节点反查模型面局部键
        （不露 uuid）。键/序失配时退回下标标签，点名失败不改变判重语义。
        """
        node_labels = {
            str(node_id): f"{tree_key}/{node_key}"
            for tree_key, tree_id in self.tree_key_index.items()
            for node_key, node_id in (self.event_trees.get(tree_id) or {}).get("nodes", {}).items()
        }
        observation_keys = list(self.observation_by_record)
        return {
            "character_observations": [
                (
                    (item.character, item.action),
                    f"{observation_keys[index] if index < len(observation_keys) else index}"
                    f"(character={item.character}, action={item.action})",
                )
                for index, item in enumerate(payloads["character_observations"])
                if item.action is not None
            ],
            "events": [
                ((str(item.node_id),), node_labels.get(str(item.node_id), str(item.node_id)))
                for item in payloads.get("events") or []
            ],
            "relations": [
                (
                    (item.from_entity, item.to_entity, str(item.relation_type)),
                    f"relation/{item.from_entity}-{item.to_entity}/{item.relation_type}",
                )
                for item in payloads["relations"]
            ],
        }

    # ------------------------------------------------------------------
    # ready_chapter 构造与冻结
    # ------------------------------------------------------------------

    def _build_ready_chapter(self) -> BoundChapterAnnotation:
        """2026-08-20 用于从全部已接受领域校验并构造完整 BoundChapterAnnotation（优化：内联验证逻辑）"""
        payloads = self.domain_payloads
        entity_types, _entity_names = self._entity_catalog(payloads["entities"])
        resolved_entity_types = {
            **(self.graph.entity_types if self.graph is not None else {}),
            **entity_types,
        }

        # 2026-08-20 内联全量端点校验，合并 _validate_fact_endpoints 和 _validate_domain_endpoints
        # 2026-10-04 错误点名生产记录键（原 "[下标] 域.字段" 模型无法映射回具体记录）
        errors: list[str] = []

        def check_entity(
            name: str,
            expected_types: tuple[EntityType, ...] | None,
            label: str,
            record_label: str,
        ) -> None:
            key = unicodedata.normalize("NFC", name).strip().casefold()
            resolved_key = key
            if self.graph is not None:
                resolved_key = _norm_graph_name(self.graph.resolve_name(name))
            actual_type = resolved_entity_types.get(resolved_key) or resolved_entity_types.get(key)
            if actual_type is None:
                errors.append(
                    f"{record_label} {label} 未在当前章 登记: {name}"
                    "（请先用 write_entity 登记该实体，或改用已登记实体名）"
                )
                return
            if expected_types is not None and actual_type not in expected_types:
                errors.append(
                    f"{record_label} {label}={name!r} 端点类型必须属于 {[str(t) for t in expected_types]}，"
                    f"实际为 {actual_type}（该名称在图上的登记类型是 {actual_type}，"
                    "请按登记类型使用，或对同一词条的不同身份使用区分性名称）"
                )

        # character_observations 端点校验（载荷顺序与 observation_by_record 一致，可反查记录键）
        observation_keys = list(self.observation_by_record)
        for index, item in enumerate(payloads["character_observations"]):
            record_label = str(observation_keys[index]) if index < len(observation_keys) else str(index)
            check_entity(item.character, (EntityType.CHARACTER,), "character_observation.character", record_label)

        # dialogues 端点校验
        for item in payloads["dialogues"]:
            if item.verdict != DialogueVerdict.NOT_DIALOGUE and item.speaker is not None:
                check_entity(
                    item.speaker,
                    (EntityType.CHARACTER,),
                    "dialogue.speaker",
                    f"dialogue/{item.candidate_index}",
                )

        # 2026-08-22 事件契约：write_event 已在写入时内联校验参与者端点，此处不再重查

        # relations 端点校验
        for item in payloads["relations"]:
            definition = RELATION_DEFINITIONS[str(item.relation_type)]
            record_label = f"relation/{item.from_entity}-{item.to_entity}/{item.relation_type}"
            check_entity(item.from_entity, definition["from_types"], "relation.from_entity", record_label)
            check_entity(item.to_entity, definition["to_types"], "relation.to_entity", record_label)

        if errors:
            raise ValueError("端点校验失败: " + "；".join(errors))

        self._validate_domain_duplicates(payloads)
        bound_dialogues = list(self.bound_payloads["dialogues"])
        # 2026-09-04 单一写面：entities/relations 不进 ready_chapter，
        # 图域真相源是 FactGraph 操作日志，持久化从其派生
        return BoundChapterAnnotation(
            metrics=payloads["metrics"],
            character_observations=list(self.bound_payloads["character_observations"]),
            dialogues=bound_dialogues,
            events=list(self.bound_payloads["events"]),
            paragraph_labels=list(self.bound_payloads.get("paragraph_labels") or []),
        )

    def _paragraph_label_coverage_warnings(self) -> list[str]:
        """2026-09-07 用于在冻结前确定性登记段落级监督覆盖缺口（仅告警不阻断冻结）

        每章 2-3 段为定稿密度（2026-09-14 由句级改段级）；低于 2 段（含空载荷）
        随章留痕，供 linguistic 阶段边界拟合的样本量判断与报告附录展示。
        """
        labels = self.bound_payloads.get("paragraph_labels") or []
        if len(labels) >= _PARAGRAPH_LABEL_MIN_PER_CHAPTER:
            return []
        return [f"情绪标签覆盖: 仅标注 {len(labels)} 段（每章应自选 2-3 段）"]

    def complete_active_chapter(self) -> BoundChapterAnnotation:
        """用于在收尾声明后冻结当前章（覆盖率告警随章留痕）"""
        if self.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 complete_chapter")
        if not self.chapter_finished:
            raise ValueError("本章 尚未收尾：先调用 finish")
        if self.ready_chapter is None:
            raise AnnotationInvariantError("已收尾但 ready_chapter 缺失，系统不变量被破坏")
        warnings = self._paragraph_label_coverage_warnings()
        chapter = (
            self.ready_chapter.model_copy(update={"coverage_warnings": warnings}) if warnings else self.ready_chapter
        )
        self.completed_chapters.append(chapter)
        # 2026-08-14 M6：当前章隐式授权（_resolve_case_details 按 current_chapter_id
        # 相等校验），不再登记文本授权集合
        # 2026-08-14 D1：不再有 continuity_open 阶段，冻结章 后直接进入终态
        self.phase = "completed"
        return chapter

    def finish(self) -> BoundChapterAnnotation:
        """2026-08-11 用于在章冻结后由系统产出章节正式标注

        2026-09-19 章即块拍平：章节标注就是冻结的那一份（原"各 chunk summary
        拼章节摘要"随两级结构退役，摘要在 metrics.summary）。
        """
        if self.phase != "completed":
            raise AnnotationProtocolError(f"阶段 {self.phase} 不允许 finish")
        if not self.completed_chapters:
            raise AnnotationInvariantError("已冻结但 completed_chapters 为空，系统不变量被破坏")
        annotation = self.completed_chapters[-1]
        self.annotation = annotation
        self.phase = "completed"
        return annotation

    # ------------------------------------------------------------------
    # 确定性上下文摘要与搜索压缩

    def _domain_fact_views(self) -> dict[str, Any]:
        """2026-08-10 用于生成当前候选各领域的事实语义键视图"""
        payloads = self.domain_payloads
        views: dict[str, Any] = {}
        if "metrics" in payloads:
            views["metrics"] = {
                "summary": payloads["metrics"].summary,
                "emotional_valence": str(payloads["metrics"].emotional_valence),
                "narrative_function": str(payloads["metrics"].narrative_function),
            }
        if "entities" in payloads:
            views["entities"] = {
                "items": len(payloads["entities"].entities),
                "names": [entity.name for entity in payloads["entities"].entities],
            }
        if "character_observations" in payloads:
            views["character_observations"] = [
                {
                    "character": item.character,
                    "action": item.action,
                }
                for item in payloads["character_observations"]
            ]
        if "dialogues" in payloads:
            views["dialogues"] = [
                {
                    "candidate_index": item.candidate_index,
                    "verdict": str(item.verdict),
                    "speaker": item.speaker,
                }
                for item in payloads["dialogues"]
            ]
        if "events" in payloads:
            views["events"] = [
                {
                    "node_id": item.node_id,
                    "tree_id": item.tree_id,
                    "parent_node_id": item.parent_node_id,
                    "cause_role": item.cause_role,
                    "description": item.description,
                    "participants": [
                        {
                            "id": (self.graph.entity_id(participant.entity) if self.graph is not None else None),
                            "entity": participant.entity,
                            "role": str(participant.role),
                        }
                        for participant in item.participants
                    ],
                }
                for item in payloads["events"]
            ]
        if "relations" in payloads:
            views["relations"] = [
                {
                    "from": item.from_entity,
                    "to": item.to_entity,
                    "relation_type": str(item.relation_type),
                }
                for item in payloads["relations"]
            ]
        return views

    def context_summary(self) -> dict[str, Any]:
        """2026-08-10 用于从账本确定性生成当前模型请求的上下文摘要"""
        return {
            "phase": self.phase,
            "chapter_id": self.current_chapter_id,
            "chapter_finished": self.chapter_finished,
            # 2026-09-13 实时写入进度（仅供审计：模型看到的只有各小调用的回执）
            "written": self._written_counts(),
            "missing_content": self.missing_content_domains(),
            "entities": {
                "declared": [
                    {
                        "id": (self.graph.entity_id(entity.name) if self.graph is not None else None),
                        "name": entity.name,
                        "entity_type": entity.entity_type,
                    }
                    for entity in self.domain_payloads.get("entities", EntityDirectoryInput()).entities
                ],
                "registered": (
                    [
                        {
                            "id": self.graph.entity_id(display_name),
                            "name": display_name,
                            "entity_type": self.graph.entity_types[key],
                        }
                        for key, display_name in sorted(self.graph.entity_names.items())
                    ]
                    if self.graph is not None
                    else []
                ),
            },
            "facts": self._domain_fact_views(),
            "errors": list(self.errors),
            "cases": {"seeds": len(self.pushed_cases)},
            "search_log": list(self.search_log[-8:]),
        }

    def append_search_log(self, entry: dict[str, Any]) -> None:
        """2026-08-10 用于登记搜索结果压缩条目（查询、命中编号与 digest）"""
        self.search_log.append(entry)

    def missing_content_domains(self) -> list[str]:
        """2026-09-13 用于列出当前章 尚无写入的领域（收尾提醒与审计共用）

        空域是合法终态（某些块确实没有关系/对话/事件），这里只作为提醒清单，
        不阻断收尾——模型看到清单后可自行判断"确实为空，直接收尾"。
        """
        missing: list[str] = []
        if not self.written_entities:
            missing.append("entities")
        if self.metrics_payload is None:
            missing.append("metrics")
        if not self.bound_payloads.get("events"):
            missing.append("events")
        if not self.written_relations:
            missing.append("relations")
        if not self.written_dialogues:
            missing.append("dialogues")
        return missing
