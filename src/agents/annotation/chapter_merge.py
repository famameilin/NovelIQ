"""章内并行 CodeAct：章节代理的合并程序面（绑定即编译、就地执行）

设计（章内并行 CodeAct 方案 §5/§6）：
- 章节代理只补全章层面决策：绑定历史实体、合并重复提及（不按同名自动合并）、
  识别新实体、归并跨块事件、裁决参与者冲突、章节 metrics 与待决项；
- 完备的局部标注留在块运行环境里，章节代理按句柄读取（inspect / 首条消息的
  对象索引），不把块内容整段抄进上下文；
- **绑定即编译、就地执行**：每条合并构造器当场把句柄翻成正式引用，再经生产
  单条事务边界（graph._execute_call）写成正式记录——没有"先攒决策、末尾统一编译"
  的暂存阶段，成功一条就落一条；
- 引用转换是确定性的：块内短键 → 章内 el/编号由系统按已绑定表完成；
  没绑定的提及被拒绝并把待绑定清单交回模型，而不是猜；
- 冲突不许最后写入者覆盖：同一参与者来自多个块事件且字段不一致时编译拒绝，
  要求显式裁决（participants=[...]）；
- 块完成顺序不构成任何顺序：树内先后由后序构造器调用顺序决定，原文先后不自动
  推导因果，块内 link 只是输入线索、不自动拼进主链。

授权足迹：块代理见过正文（检索面）与案例池，其文本/章/事件/案例足迹在章会话
开始前并入章账本；实体名与案例理由的准入复用两段式那条既有硬门槛
（report_entity_name_keys / report_case_quotes），把块 IR 的证据按同一形状喂进去。
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .errors import AnnotationInvariantError, AnnotationStageRejection
from .local_ir import BlockAnnotation
from .program import ProgramRuntime, build_program_tool, constructor_api_text, render_list_signature
from .reader_report import ReaderReport
from .tools import AnnotationToolLedger

if TYPE_CHECKING:
    from .block_program import BlockRunOutcome

# 合并构造器覆盖的块内类别（inspect 与句柄解析共用一张表）
_LOCAL_KINDS = ("mentions", "relations", "dialogues", "events", "links", "metric_notes", "pending")


def build_handle_registry(blocks: list[BlockAnnotation]) -> dict[str, tuple[BlockAnnotation, str, Any]]:
    """用于把所有块内对象登记成 句柄 → (块, 类别, 对象) 的唯一寻址表"""
    registry: dict[str, tuple[BlockAnnotation, str, Any]] = {}
    for block in blocks:
        for kind in _LOCAL_KINDS:
            for item in getattr(block, kind):
                registry[block.handle(item.key)] = (block, kind, item)
        for label in block.labels:
            registry[block.handle(f"label-{label.paragraph_id}")] = (block, "labels", label)
    return registry


def build_block_reports(blocks: list[BlockAnnotation]) -> list[ReaderReport]:
    """用于把块局部标注按既有报告形状喂进写者取证准入（不新增第二套准入实现）

    准入面读的是"本块陈述过哪些实体名/哪些逐字引文"，与报告的来源无关：
    entities/relations/event_trees/dialogues 供 report_entity_name_keys，
    案例线索供 report_case_quotes（引文在块构造时已过 NFC 唯一命中核验）。
    """
    reports: list[ReaderReport] = []
    for block in blocks:
        name_of = {mention.key: mention.name for mention in block.mentions}
        payload: dict[str, Any] = {}
        if block.mentions:
            payload["entities"] = [
                {"name": mention.name, "evidence": [entry.to_dict() for entry in mention.evidence]}
                for mention in block.mentions
            ]
        if block.relations:
            payload["relations"] = [
                {
                    "from_entity": name_of.get(relation.from_ref, ""),
                    "to_entity": name_of.get(relation.to_ref, ""),
                }
                for relation in block.relations
            ]
        if block.events:
            payload["event_trees"] = [
                {"participants": [{"entity": name_of.get(part.entity, "")} for part in event.participants]}
                for event in block.events
            ]
        if block.dialogues:
            payload["dialogues"] = [
                {"speaker": name_of.get(dialogue.speaker, "")}
                for dialogue in block.dialogues
                if dialogue.speaker
            ]
        clues = [item for item in block.pending if item.kind == "case_clue"]
        if clues:
            payload["cases"] = [
                {
                    "entities": [
                        name
                        for name in (
                            name_of.get(handle.partition(":")[2], "") for handle in item.handles
                        )
                        if name
                    ],
                    "evidence": [entry.to_dict() for entry in item.evidence],
                }
                for item in clues
            ]
        if payload:
            reports.append(ReaderReport(block_index=block.block_index, report=payload, warnings=[]))
    return reports


def transfer_authorizations(ledger: AnnotationToolLedger, outcomes: list[BlockRunOutcome]) -> None:
    """用于把各块会话的授权足迹（正文/章/事件/案例）并入章账本

    块是本设计里见过正文与案例池的一方；不并入就会让章代理在自己合法见过的
    证据上被授权面拒绝。案例只传 id，章账本按 id 重新分配自己的运行期编号。
    """
    for outcome in outcomes:
        ledger.authorized_text_paragraph_ids |= outcome.authorized_text_paragraph_ids
        ledger.authorized_chapter_ids |= outcome.authorized_chapter_ids
        ledger.authorized_event_ids |= outcome.authorized_event_ids
        ledger.authorized_tree_ids |= outcome.authorized_tree_ids
        for case_id in sorted(outcome.case_ids):
            ledger.register_case_number(case_id)


@dataclass(slots=True)
class MergeCompiled:
    """一条合并构造器编译出的正式调用计划（绑定即编译的产物）"""

    label: str
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    ref: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    on_success: Callable[[], None] | None = None


def _reject(
    message: str,
    *,
    record: str,
    field: str,
    code: str,
    expected: str,
) -> AnnotationStageRejection:
    """用于构造合并面的记录级结构化拒绝"""
    return AnnotationStageRejection(
        message, record=record, field=field, code=code, expected=expected
    )


def _norm_key(name: str) -> str:
    """用于与 FactGraph 同源的名称归一化（历史实体类型查表用）"""
    return unicodedata.normalize("NFC", name).strip().casefold()


def _participant_fields(body: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """用于参与者冲突检测的字段指纹（角色＋人物三态）"""
    return (body.get("role"), body.get("narrative_role"), body.get("action"), body.get("emotion"))


class ChapterMergeRuntime(ProgramRuntime):
    """章节代理程序面：写者面全套工具 + 合并构造器（绑定即编译、就地执行）

    写者面原有的写入/检索/案例工具一个不少（跨块决策之外的事照旧直接做），
    新增的合并构造器把块局部句柄翻成正式引用后，走同一条 _execute_call 事务边界；
    程序面的语法、限额、压缩回执与写者面共用 RestrictedProgramRuntime 一份实现。
    """

    def __init__(
        self,
        tools: list[Any],
        ledger: AnnotationToolLedger,
        blocks: list[BlockAnnotation],
        *,
        candidate_number_maps: list[dict[int, int | None]],
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """用于绑定章账本、各块局部标注与候选映射表"""
        super().__init__(tools, ledger, observer=observer, stream=stream)
        self.blocks = list(blocks)
        self._candidate_maps = list(candidate_number_maps)
        self._registry = build_handle_registry(self.blocks)
        # 提及句柄 → 章内 el（bind 成功后记录，块内引用靠它翻成正式引用）
        self._bound: dict[str, str] = {}
        # 待决项裁决留痕（不产生正式写入，只进审计与回执）
        self.decisions: list[dict[str, Any]] = []
        self.api_entries = self._api_entries()
        self._constructor_names = frozenset(name for name, _, _ in self.api_entries)
        self.tools.update({name: function for name, function, _ in self.api_entries})

    def build_tool(self) -> Any:
        """用于构造章会话的唯一对外工具 execute_code（合并构造器目录同轮下发）"""
        return build_program_tool(self, extra_api=constructor_api_text(self.api_entries) + "\n\n")

    # ------------------------------------------------------------------
    # 合并构造器（模型面）

    def bind(
        self,
        mention: Any,
        el: str,
        n: int | None = None,
        name: str | None = None,
        entity_type: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> MergeCompiled:
        """把一个或多个块内提及绑定成一个正式实体（编译成 write_entity，就地生效）

        mention 是一个句柄或句柄数组：多个句柄绑到同一个 el 即"合并重复提及"——
        系统绝不按同名自动合并，是否同一个人由你按证据裁决后显式提交。
        绑定历史实体给 n（编号）：姓名与类型默认取图中登记值，只提交本次变化的字段。
        新实体不给 n：姓名与类型默认取该提及自己的值；多个提及名字/类型不一致时
        必须显式给出 name/entity_type。el 是章内引用键，后续 event/relation 用它引用。
        """
        record = f"entity/{name or '?'}"
        handles = self._handles_of(mention, record=record)
        if not isinstance(el, str) or not el.strip():
            raise _reject(
                "bind.el 必须是非空字符串",
                record=record,
                field="el",
                code="invalid_value",
                expected="你自定的章内实体引用键（如 gs），后续 event/relation 用它引用",
            )
        records = [self._resolve(handle, kinds=("mentions",), record=record)[2] for handle in handles]
        write_args: dict[str, Any] = {"el": el.strip()}
        if n is not None:
            resolved_name = self.ledger.resolve_entity_ref(n, record=record, field="n")
            write_args["name"] = name or resolved_name
            write_args["entity_type"] = entity_type or self._registered_type(resolved_name)
            ref_note = {"bound_from": "history", "n": n, "registered_name": resolved_name}
        else:
            names = {item.name for item in records}
            kinds = {item.entity_type for item in records}
            if name is None and len(names) > 1:
                raise _reject(
                    "多个提及的名字不一致，合并必须显式给出 name",
                    record=record,
                    field="name",
                    code="ambiguous_merge",
                    expected="name=合并后采用的登记名（" + "、".join(sorted(names)) + " 里选一个或给新名）",
                )
            if entity_type is None and len(kinds) > 1:
                raise _reject(
                    "多个提及的实体大类不一致，合并必须显式给出 entity_type",
                    record=record,
                    field="entity_type",
                    code="ambiguous_merge",
                    expected="entity_type=character / item / location / organization",
                )
            write_args["name"] = name or next(iter(names))
            write_args["entity_type"] = entity_type or next(iter(kinds))
            ref_note = {"bound_from": "local", "mentions": handles}
        for key in ("tags", "description", "attributes"):
            provided = {"tags": tags, "description": description, "attributes": attributes}[key]
            if provided is not None:
                write_args[key] = provided
        label = f"entity/{write_args['name']}"

        def remember() -> None:
            """用于在正式写入成功后记录句柄→el 的绑定表"""
            for handle in handles:
                self._bound[handle] = write_args["el"]

        return MergeCompiled(
            label=label,
            calls=[("write_entity", write_args)],
            ref={"el": write_args["el"], **ref_note},
            on_success=remember,
        )

    def import_relation(
        self,
        handle: str,
        from_mention: str | None = None,
        to_mention: str | None = None,
        relation_type: str | None = None,
    ) -> MergeCompiled:
        """把一条块内关系编译成正式关系边（两端必须已 bind，编译期完成引用转换）

        handle 是块内关系句柄；默认沿用块内两端与关系类型，用 from_mention/to_mention
        可在合并后改指到别的实体（改指要给出理由的自证责任在裁决者）。
        两端合并成同一实体时该边自动跳过（不再是一条边）。
        """
        record = str(handle)
        block, _kind, item = self._resolve(record, kinds=("relations",), record=record)
        from_el = self._el_of(block, item.from_ref, record=record, override=from_mention)
        to_el = self._el_of(block, item.to_ref, record=record, override=to_mention)
        if from_el == to_el:
            return MergeCompiled(
                label=f"relation/{record}",
                ref={"skipped": "both_ends_merged", "el": from_el},
                notes=[f"{record} 两端已合并为同一实体 {from_el}，该边跳过"],
            )
        return MergeCompiled(
            label=f"relation/{from_el}-{to_el}",
            calls=[
                (
                    "write_relation",
                    {
                        "from_entity": from_el,
                        "to_entity": to_el,
                        "relation_type": relation_type or item.relation_type,
                    },
                )
            ],
            ref={"from": from_el, "to": to_el},
        )

    def merge_dialogues(self) -> MergeCompiled:
        """把各块的对话判定编译成章级对话写入（候选编号按章级候选表对齐）

        候选编号用章级表：块内编号经系统映射；跨块引号截断导致无法对齐的候选不猜、
        记进 skipped 交回给你。说话人所在的提及未绑定时该条跳过（先 bind 再重跑本构造器，
        已写入的判定按更新语义重写，幂等）。
        """
        calls: list[tuple[str, dict[str, Any]]] = []
        skipped: list[dict[str, Any]] = []
        for block in self.blocks:
            candidate_map = self._candidate_maps[block.block_index]
            for dialogue in block.dialogues:
                handle = block.handle(dialogue.key)
                chapter_index = candidate_map.get(dialogue.candidate_index)
                if chapter_index is None:
                    skipped.append(
                        {"handle": handle, "reason": "块内候选跨块引号截断，无法对齐章级候选编号"}
                    )
                    continue
                args: dict[str, Any] = {
                    "candidate_index": chapter_index,
                    "verdict": dialogue.verdict,
                }
                if dialogue.speaker is not None:
                    try:
                        args["speaker"] = self._el_of(block, dialogue.speaker, record=handle)
                    except AnnotationStageRejection as exc:
                        skipped.append({"handle": handle, "reason": str(exc)})
                        continue
                if dialogue.tone is not None:
                    args["tone"] = dialogue.tone
                calls.append(("write_dialogue", args))
        return MergeCompiled(
            label="dialogues",
            calls=calls,
            ref={"merged": len(calls), "skipped": skipped},
        )

    def tree(
        self,
        key: str,
        description: str,
        sources: list[str] | None = None,
        participants: list[dict[str, Any]] | None = None,
        isforeshadowing: bool = False,
        confidence: str | None = None,
    ) -> MergeCompiled:
        """建一棵章级事件树的根（编译成 write_event(isroot=true)，就地生效）

        key 是章内树键（如 t1）。sources 是块内事件句柄数组：它们的参与者会被
        编译进根节点；同一实体在不同来源里字段不一致时编译拒绝，请用
        participants=[{entityid, role, narrative_role, action, emotion}] 显式裁决。
        isforeshadowing=True 时 confidence（high/medium/low）必填。
        树内先后由后续 event(...) 的调用顺序决定，与块完成顺序无关。
        """
        return self._compile_tree_node(
            el=key,
            isroot=True,
            description=description,
            node_type=None,
            sources=sources,
            participants=participants,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
        )

    def event(
        self,
        tree: str,
        key: str,
        description: str,
        type: str = "main",
        sources: list[str] | None = None,
        participants: list[dict[str, Any]] | None = None,
    ) -> MergeCompiled:
        """往章级事件树里加一个子事件（编译成 write_event(isroot=false)）

        type="main" 顺延主因链（成为新链尾）/"secondary" 挂在当时主链尾：
        这是你表达跨块因果的唯一手段——原文先后不自动等于因果，块内 link 只是线索。
        sources 与 participants 的语义同 tree（冲突必须显式裁决）。
        """
        return self._compile_tree_node(
            el=f"{tree}/{key}",
            isroot=False,
            description=description,
            node_type=type,
            sources=sources,
            participants=participants,
            isforeshadowing=False,
            confidence=None,
        )

    def metric(
        self,
        summary: str,
        emotional_valence: int,
        narrative_function: str,
        pivot_moment: bool = False,
        cliffhanger: bool = False,
        labels: list[dict[str, Any]] | None = None,
    ) -> MergeCompiled:
        """提交章级指标与摘要（编译成 write_metrics；省略 labels 即自动并入各块段标签）

        段落标签由各块在正文上打过（每个段落是块自己的锚点，已过证据核验），
        默认全量并入、按段号去重；要改就显式给 labels=[{paragraph_id, emotion}]。
        """
        merged_labels = list(labels) if labels is not None else self._merged_labels()
        return MergeCompiled(
            label="metrics",
            calls=[
                (
                    "write_metrics",
                    {
                        "summary": summary,
                        "emotional_valence": emotional_valence,
                        "narrative_function": narrative_function,
                        "pivot_moment": pivot_moment,
                        "cliffhanger": cliffhanger,
                        "labels": merged_labels,
                    },
                )
            ],
            ref={"labels": len(merged_labels)},
        )

    def inspect(self, handle: str) -> MergeCompiled:
        """按句柄读取一条块内标注的完整明细（正文证据、参与者三态、待决详情）

        你手里只有对象索引；需要看证据原文或完整字段时用本构造器读，不产生写入。
        """
        record = str(handle)
        block, kind, item = self._resolve(record, kinds=_LOCAL_KINDS + ("labels",), record=record)
        return MergeCompiled(
            label=record,
            ref={"kind": kind, "block": block.block_index + 1, **block.expand(kind, item.to_dict())},
        )

    def decide_pending(self, handle: str, decision: str, note: str | None = None) -> MergeCompiled:
        """登记你对一条待决项的裁决（不产生正式写入，只留痕，便于收尾自查）

        decision 写你做了什么处置（如"绑定到 n=12""并入事件 t1/e3""判定不成立"）；
        note 写依据。案例裁决本身仍走 search_pool 与 push_case/resolve_fact_case。
        """
        record = str(handle)
        _block, _kind, item = self._resolve(record, kinds=("pending",), record=record)
        self.decisions.append(
            {
                "handle": record,
                "pending_kind": item.kind,
                "case_id": item.case_id,
                "decision": decision,
                "note": note,
            }
        )
        return MergeCompiled(
            label=record,
            ref={"pending_kind": item.kind, "decided": True, "case_id": item.case_id},
        )

    # ------------------------------------------------------------------
    # 编译支撑（引用转换、冲突检测、自动并入）

    def _api_entries(self) -> list[tuple[str, Any, str]]:
        """用于声明模型可见的合并构造器目录（签名取自绑定方法本身）"""
        return [
            ("bind", self.bind, "把块内提及绑定成正式实体（多个句柄同一 el 即合并重复提及）"),
            ("import_relation", self.import_relation, "把一条块内关系编译成正式关系边"),
            ("merge_dialogues", self.merge_dialogues, "把各块对话判定编译成章级对话写入"),
            ("tree", self.tree, "建章级事件树根（sources 引用块内事件）"),
            ("event", self.event, "往树里加子事件（type 表达主链/挂靠）"),
            ("metric", self.metric, "提交章级指标（省略 labels 即自动并入块内段标签）"),
            ("inspect", self.inspect, "按句柄读取块内标注的完整明细"),
            ("decide_pending", self.decide_pending, "登记对一条待决项的裁决"),
        ]

    def _handles_of(self, value: Any, *, record: str) -> list[str]:
        """用于把 mention 参数归一成句柄数组（单句柄与数组两种写法都收）"""
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, (list, tuple)) and value:
            handles = [str(item).strip() for item in value if str(item).strip()]
            if handles:
                return handles
        raise _reject(
            "mention 需要至少一个块内提及句柄",
            record=record,
            field="mention",
            code="invalid_value",
            expected='单句柄 "B1:m1" 或句柄数组 ["B1:m1", "B2:m3"]',
        )

    def _resolve(
        self,
        handle: str,
        *,
        kinds: tuple[str, ...],
        record: str,
    ) -> tuple[BlockAnnotation, str, Any]:
        """用于按句柄取出块内对象（句柄未知或类别不符一律结构化拒绝）"""
        entry = self._registry.get(str(handle))
        if entry is None:
            known = "、".join(sorted(self._registry)[:12]) or "（各块都没有产出局部标注）"
            raise _reject(
                f"未知句柄：{handle}",
                record=record,
                field="handle",
                code="unknown_handle",
                expected=f"用首条消息 <BlockAnnotations> 里的 handle；已知句柄（前 12 个）：{known}",
            )
        block, kind, item = entry
        if kind not in kinds:
            raise _reject(
                f"句柄类别不符：{handle} 是 {kind}，这里需要 {'/'.join(kinds)}",
                record=record,
                field="handle",
                code="wrong_kind",
                expected=f"该构造器接受：{'/'.join(kinds)}",
            )
        return block, kind, item

    def _registered_type(self, name: str) -> str:
        """用于取历史实体的登记大类（绑定历史实体时默认沿用登记值）"""
        graph = self.ledger.graph
        if graph is None:
            raise AnnotationInvariantError("历史实体绑定需要常驻事实图，graph 缺失")
        registered = graph.entity_types.get(_norm_key(name))
        if registered is None:
            raise _reject(
                f"图里查不到该登记名：{name}",
                record=f"entity/{name}",
                field="n",
                code="unregistered",
                expected="n 取 search_graph 回执里的编号（编号一定对应图中已登记实体）",
            )
        return str(registered)

    def _el_of(
        self,
        block: BlockAnnotation,
        mention_key: str,
        *,
        record: str,
        override: str | None = None,
    ) -> str:
        """用于把块内提及短键翻成章内 el（未绑定即拒绝并把待绑定清单交回模型）"""
        if override:
            text = str(override).strip()
            if ":" in text:
                bound = self._bound.get(text)
                if bound is not None:
                    return bound
                raise _reject(
                    f"该提及尚未绑定：{text}",
                    record=record,
                    field="from_mention",
                    code="unbound_mention",
                    expected="先用 bind(mention=..., el=...) 绑定它，再引用它的 el",
                )
            if text in self.ledger.entity_el_index:
                return text
            raise _reject(
                f"改指目标不是已绑定实体：{text}",
                record=record,
                field="from_mention",
                code="unknown_el",
                expected="已绑定的 el 或块内提及句柄（先 bind）",
            )
        handle = block.handle(mention_key)
        bound = self._bound.get(handle)
        if bound is None:
            pending = sorted(
                item_handle for item_handle in self._registry if item_handle not in self._bound
            )
            raise _reject(
                f"该提及尚未绑定：{handle}",
                record=record,
                field="mention",
                code="unbound_mention",
                expected=(
                    "先 bind 它（句柄→el）再引用；"
                    "当前未绑定句柄（前 12 个）：" + ("、".join(pending[:12]) or "（无）")
                ),
            )
        return bound

    def _compile_participants(
        self,
        *,
        sources: list[str] | None,
        participants: list[dict[str, Any]] | None,
        record: str,
    ) -> list[dict[str, Any]]:
        """用于把块内事件参与者编译成正式参与者数组（冲突拒绝，显式裁决优先）

        同一实体从多个来源取到不一致字段时拒绝编译：把冲突两方原样报给模型，
        由它给 participants=[...] 显式裁决——绝不做最后写入者覆盖。

        顺序很关键：显式裁决**先落地**并把它覆盖到的实体从来源侧摘掉，
        再做来源之间的冲突检测——否则裁决永远改不动冲突（先撞拒绝、够不到裁决）。
        """
        explicit: dict[str, dict[str, Any]] = {}
        for item in participants or []:
            if not isinstance(item, dict):
                raise _reject(
                    "participants 的每一项必须是对象",
                    record=record,
                    field="participants",
                    code="invalid_value",
                    expected="[{entityid, role, narrative_role, action, emotion}]",
                )
            body = dict(item)
            entity_ref = body.get("entityid")
            if isinstance(entity_ref, str) and ":" in entity_ref:
                target = self._registry.get(entity_ref)
                if target is None:
                    raise _reject(
                        f"participants.entityid 引用了未知句柄：{entity_ref}",
                        record=record,
                        field="participants",
                        code="unknown_handle",
                        expected="块内提及句柄或已绑定的 el 键",
                    )
                body["entityid"] = self._el_of(target[0], entity_ref.partition(":")[2], record=record)
            if body.get("entityid") is None or not body.get("role"):
                raise _reject(
                    "participants 每一项都要给 entityid 与 role",
                    record=record,
                    field="participants",
                    code="missing_field",
                    expected="[{entityid, role, narrative_role, action, emotion}]",
                )
            explicit[str(body["entityid"])] = body
        derived: dict[str, dict[str, Any]] = {}
        origin: dict[str, str] = {}
        for raw_handle in sources or []:
            handle = str(raw_handle)
            block, _kind, event = self._resolve(handle, kinds=("events",), record=record)
            for part in event.participants:
                el = self._el_of(block, part.entity, record=record)
                if el in explicit:
                    # 已被显式裁决覆盖的实体不再参与来源冲突检测
                    continue
                derived_body: dict[str, Any] = {"entityid": el, "role": part.role}
                if part.narrative_role is not None:
                    derived_body["narrative_role"] = part.narrative_role
                    derived_body["action"] = part.action
                    derived_body["emotion"] = part.emotion
                existing = derived.get(el)
                if existing is not None and _participant_fields(existing) != _participant_fields(derived_body):
                    raise _reject(
                        f"参与者字段冲突：{el} 在 {origin[el]} 与 {handle} 里不一致"
                        f"（{_participant_fields(existing)} vs {_participant_fields(derived_body)}）",
                        record=record,
                        field="participants",
                        code="participant_conflict",
                        expected="在 participants=[...] 里显式给出你裁决后的字段（三态要齐）",
                    )
                derived[el] = derived_body
                origin[el] = handle
        derived.update(explicit)
        return list(derived.values())

    def _compile_tree_node(
        self,
        *,
        el: str,
        isroot: bool,
        description: str,
        node_type: str | None,
        sources: list[str] | None,
        participants: list[dict[str, Any]] | None,
        isforeshadowing: bool,
        confidence: str | None,
    ) -> MergeCompiled:
        """用于编译一个事件节点的正式 write_event 调用（根/子共用一条路径）"""
        record = el if isroot else el
        write_args: dict[str, Any] = {"el": el, "isroot": isroot, "description": description}
        if isroot:
            if isforeshadowing:
                write_args["isforeshadowing"] = True
                write_args["confidence"] = confidence
        else:
            write_args["type"] = node_type
        characters = self._compile_participants(
            sources=sources, participants=participants, record=record
        )
        if characters:
            write_args["characters"] = characters
        ref: dict[str, Any] = {"el": el, "participants": len(characters)}
        if sources:
            ref["sources"] = [str(handle) for handle in sources]
        return MergeCompiled(
            label=f"event/{el}" + ("/root" if isroot else ""),
            calls=[("write_event", write_args)],
            ref=ref,
        )

    def _merged_labels(self) -> list[dict[str, Any]]:
        """用于把各块段标签按段号去重并入章级指标（同段号后写的块覆盖）"""
        merged: dict[int, int] = {}
        for block in self.blocks:
            for label in block.labels:
                merged[label.paragraph_id] = label.emotion
        return [{"paragraph_id": paragraph_id, "emotion": merged[paragraph_id]} for paragraph_id in sorted(merged)]

    # ------------------------------------------------------------------
    # 程序分发（与写者面共用解释器语义）

    async def _dispatch(self, name: str, args: dict[str, Any], *, line: int | None) -> Any:
        """用于分发一次程序内调用：合并构造器走编译，原生工具走生产事务边界"""
        if name in self._constructor_names:
            return await self._run_constructor(name, args, line=line)
        return await super()._dispatch(name, args, line=line)

    async def _run_constructor(self, name: str, args: dict[str, Any], *, line: int | None) -> dict[str, Any]:
        """用于执行一次合并构造器：编译成功后立刻逐条执行正式调用（绑定即编译）

        编译期失败（未知句柄/未绑定/参与者冲突）记一条失败 op 并把可自纠说明交回；
        编译成功则只由内层正式调用占 op 记录——失败清单里不会出现构造器与内层两条重复。
        """
        compiler = getattr(self, name)
        started_ns = time.perf_counter_ns()
        try:
            compiled: MergeCompiled = compiler(**args)
        except AnnotationInvariantError:
            raise
        except Exception as exc:
            op_index = self._next_op_index(line=line)
            rejected = _call_rejection(name, exc, signature_hint=self._signature_hint(name))
            self._log_op(
                name,
                op_index=op_index,
                line=line,
                status="error",
                receipt=rejected,
                call_args=args,
                error=str(exc),
            )
            self._record_audit(
                name,
                args=args,
                receipt=rejected,
                status="error",
                error=str(exc),
                started_ns=started_ns,
                op_index=op_index,
            )
            return rejected
        written: list[dict[str, Any]] = []
        all_ok = True
        for tool_name, tool_args in compiled.calls:
            result = await self._run_op(name=tool_name, args=tool_args, line=line)
            ok = isinstance(result, dict) and result.get("status") != "rejected"
            all_ok = all_ok and ok
            written.append({"tool": tool_name, "record": result.get("record") if isinstance(result, dict) else None})
        if compiled.on_success is not None and all_ok:
            compiled.on_success()
        # 程序面只有最终回执回到模型眼前：构造器的产出（inspect 明细、merge_dialogues
        # 的 skipped 清单、metric 并入的标签条数）必须进 refs 才看得到；键用构造器
        # 自己给的语义记录名（entity/顾霜、event/t1/root、dialogues、B2:q1 …）
        self.refs[compiled.label] = (
            {**compiled.ref, "notes": list(compiled.notes)} if compiled.notes else compiled.ref
        )
        if not compiled.calls:
            # 不产生正式调用的构造器（inspect/decide_pending/全跳过）在本层留一条成功记录
            op_index = self._next_op_index(line=line)
            self._log_op(
                name,
                op_index=op_index,
                line=line,
                status="success",
                receipt={"record": compiled.label},
                call_args=args,
            )
        receipt: dict[str, Any] = {
            "status": "written" if all_ok else "partial",
            "record": compiled.label,
            "ref": compiled.ref,
        }
        if written:
            receipt["written"] = written
        if compiled.notes:
            receipt["notes"] = list(compiled.notes)
        self._record_audit(
            name, args=args, receipt=receipt, status="success" if all_ok else "error",
            error=None if all_ok else "compiled call failed", started_ns=started_ns,
            op_index=self._ops_in_program,
        )
        return receipt

    def _signature_hint(self, name: str) -> str:
        """用于在参数名写错时把构造器签名原样回给模型（自纠不需要猜）"""
        for entry_name, function, _ in self.api_entries:
            if entry_name == name:
                return render_list_signature(name, function)
        return name

    def _record_audit(
        self,
        name: str,
        *,
        args: dict[str, Any],
        receipt: dict[str, Any],
        status: str,
        error: str | None,
        started_ns: int,
        op_index: int,
    ) -> None:
        """用于把合并构造器调用写进 agent_tool_calls（与写者面同一套字段）"""
        if self.observer is None:
            return
        request_args = dict(args)
        request_args["_program"] = {
            "program_id": self._program_id,
            "op_index": op_index,
            "source_line": None,
            "record": receipt.get("record"),
            "direct_fallback": False,
        }
        self.observer.record_tool_call(
            call_index=self._next_call_index(),
            tool_name=name,
            request_args=request_args,
            raw_args=None,
            response=receipt,
            receipt=receipt,
            status=status,
            error=error,
            tool_duration_ms=max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000)),
            started_ns=started_ns,
        )


def _call_rejection(name: str, exc: Exception, *, signature_hint: str) -> dict[str, Any]:
    """用于把合并构造器的编译期失败渲染成记录级拒绝回执"""
    if isinstance(exc, AnnotationStageRejection):
        return exc.receipt()
    return {
        "status": "rejected",
        "record": name,
        "code": "invalid_call",
        "expected": signature_hint,
        "message": f"{type(exc).__name__}: {exc}",
    }


__all__ = [
    "ChapterMergeRuntime",
    "MergeCompiled",
    "build_block_reports",
    "build_handle_registry",
    "transfer_authorizations",
]
