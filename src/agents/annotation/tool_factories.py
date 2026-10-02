"""
章节标注语义写入工具工厂：五个领域写入工具、finish 与 push_case 的闭包构造
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：tools.py 大文件拆分——build_annotation_tools 闭包工厂段迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑、签名与模型可见文案；搜索工具与参数收紧仍由
# tools.build_search_tools/_forbid_undeclared_args 提供，tools.py 对本模块保留 re-export。

from __future__ import annotations

import json
import unicodedata
from typing import Annotated, Any

from langchain_core.tools import tool
from pydantic import Field, JsonValue

from .errors import AnnotationInputError, AnnotationProtocolError, AnnotationStageRejection
from .identity import stable_digest
from .ledger import AnnotationToolLedger
from .schema import (
    CLIFFHANGER_DESCRIPTION,
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ENTITY_TAGS_RULE_TEXT,
    PIVOT_MOMENT_DESCRIPTION,
    ChapterMetricsInput,
    Confidence,
    DialogueVerdict,
    EntityInput,
    EntityRef,
    EntityType,
    EventChildType,
    NarrativeFunction,
    ParagraphLabelInput,
    ParticipantArg,
    PendingCase,
    RelationType,
    Tone,
    relation_catalog_text,
)
from .tools import (
    AnnotationQueryService,
    EntityLocalKey,
    EventLocalKey,
    _forbid_undeclared_args,
    build_search_tools,
)


def build_annotation_tools(
    query_service: AnnotationQueryService,
    ledger: AnnotationToolLedger,
) -> list[Any]:
    """2026-08-07 用于构建语义写入搜索解决和完成工具集"""

    @tool
    def write_metrics(
        summary: str,
        emotional_valence: int,
        narrative_function: NarrativeFunction,
        pivot_moment: Annotated[bool, Field(description=PIVOT_MOMENT_DESCRIPTION)] = False,
        cliffhanger: Annotated[bool, Field(description=CLIFFHANGER_DESCRIPTION)] = False,
        labels: list[ParagraphLabelInput] | None = None,
    ) -> str:
        """写入当前章节摘要、叙事指标与段落情绪标签（整域一次提交，写入即生效）

        emotional_valence 为情绪分值整数 -2..2（-2 强烈负面 / -1 轻微负面 / 0 中性 /
        1 轻微正面 / 2 强烈正面）；summary 为本章摘要。
        labels 为段落情绪标签（每章自选 2-3 段）：paragraph_id 取段首可见号（正文每段
        开头的 `N：`），emotion 同 emotional_valence；优先选情绪表达有代表性、或语气/
        标点有区分度的段落，也允许 0 分段。
        同一章 重复提交整域按最后一次为准（labels 同理，按段号去重后覆盖）。
        回执 content 回显当前整域生效指标。
        """
        payload = ChapterMetricsInput(
            summary=summary,
            emotional_valence=emotional_valence,
            narrative_function=narrative_function,
            pivot_moment=pivot_moment,
            cliffhanger=cliffhanger,
            labels=list(labels or []),
        )
        ledger.apply_metrics(payload)
        return json.dumps(
            {"status": "written", "record": "metrics", "content": ledger.metrics_content()},
            ensure_ascii=False,
        )

    @tool
    def write_entity(
        name: str,
        entity_type: EntityType,
        el: EntityLocalKey,
        tags: Annotated[
            list[Annotated[str, Field(max_length=ENTITY_TAG_MAX_CHARS)]] | None,
            Field(
                max_length=ENTITY_TAG_MAX_COUNT,
                description=f"可空标签，{ENTITY_TAGS_RULE_TEXT}；省略=保留现有标签，提交空列表=清空",
            ),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="一句话简介；省略=保留现值"),
        ] = None,
        attributes: Annotated[
            dict[str, JsonValue | None] | None,
            Field(description="JSON Merge Patch：只写变化的键，值为 null 删除该键；省略=现有属性整体保留"),
        ] = None,
    ) -> str:
        """登记或更新一个实体（一次一个），el 是你自定的章内引用键、绑定即生效

        新实体用本章出现的名称；已登记实体用登记名，只提交本次变化的字段
        （description 一句话简介、tags 见参数说明、attributes 是 JSON Merge Patch）；
        未提交的字段保留现值。
        实体大类一经登记不可变更；同一词条的不同身份用区分性名称
        （如"圣城"是 location、"圣城朝堂"是 organization）。
        事件/关系/对话的实体引用用 el 键（同轮先登记后引用，不等回执）或
        回执/检索 id——write_event 的 characters[].entityid 等字段两者都收。
        回执 content 回显该实体合并后的生效记录（含 run 级 id）。
        """
        # 2026-09-14 删除"提交 write_entity 前必须先 search_graph"硬闸——
        # 首写被检索挡在门外会迫使判定跨回合等待回执；登记序由 el 键承接，闸门删净
        entity = EntityInput(
            name=name,
            entity_type=entity_type,
            tags=tags or [],
            description=description,
            attributes=attributes,
        )
        present = {"name", "entity_type"}
        if tags is not None:
            present.add("tags")
        if description is not None:
            present.add("description")
        if attributes is not None:
            present.add("attributes")
        entity_id = ledger.apply_entity(entity, el=el, present=present)
        bound_el = unicodedata.normalize("NFC", el).strip()
        return json.dumps(
            {
                "status": "written",
                "record": f"entity/{entity.name}",
                "el": bound_el,
                "id": entity_id,
                "content": ledger.entity_content(entity),
            },
            ensure_ascii=False,
        )

    @tool
    def write_dialogue(
        candidate_index: int,
        verdict: DialogueVerdict,
        speaker: EntityRef | None = None,
        tone: Tone | None = None,
    ) -> str:
        """登记本章候选的三态判断，不提供既有对话订正入口

        speaker 只能引用本章登记的实体；归属无法确认时留空
        not_dialogue 表示题字或描写等误判候选，只给编号与 verdict
        """
        record = ledger.apply_dialogue(
            candidate_index=candidate_index, verdict=verdict, speaker_ref=speaker, tone=tone,
        )
        return json.dumps(
            {
                "status": "written", "record": record,
                "content": ledger.dialogue_content(candidate_index),
                "progress": {"written": len(ledger.written_dialogues), "total": len(ledger.dialogue_candidates)},
            },
            ensure_ascii=False,
        )

    @tool
    def write_relation(
        from_entity: EntityRef,
        to_entity: EntityRef,
        relation_type: Annotated[
            RelationType,
            Field(description="闭合关系类型，方向与两端实体类型约束如下：\n" + relation_catalog_text()),
        ],
    ) -> str:
        """登记本章局部关系，两端只能引用本章实体，不修改既有关系状态"""
        record, outcome, content = ledger.apply_relation(
            from_ref=from_entity, to_ref=to_entity, relation_type=relation_type,
        )
        return json.dumps(
            {"status": "written", "record": record, "outcome": outcome, "content": content},
            ensure_ascii=False,
        )

    @tool
    def write_event(
        el: EventLocalKey,
        isroot: bool,
        description: str,
        evidence: int | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        type: EventChildType | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """写入一个事件节点：isroot=true 建事件树根（el=树键如 t1），false 加子事件（el=t1/e2）

        description 是一句话描述（根事件不超过 30 字）。evidence 是该事件所在段的
        段首可见号；多段章节新建事件时必填，单段章节可省略。整棵树可以在一轮里按顺序写完：
        先根后子逐个调用，el 由你指定、写入即生效，同轮后面的调用直接可用（不等回执）；
        树内先后=调用顺序，没有序号参数。子事件 type="main" 顺延主因链（成为新的
        链尾）/"secondary" 挂在当时主链尾；伏笔属性（isforeshadowing/confidence）只属于根：
        isforeshadowing=true 时 confidence 必填（high/medium/low），整棵树成为伏笔树、
        根即埋设事件。
        伏笔建模判据：埋设事件本身就是本章主链事件时，直接给主链根标 isforeshadowing=true，
        不再另立第二棵树重复同一时刻；仅当要埋的悬念不对应主链某个事件时才独立立伏笔树。
        同一悬念的建树选择一次定案，后续回合不再依同一证据复议。
        characters 是该节点的参与者数组（可省）：根节点也直接挂参与者。character 实体
        每条必须带 narrative_role/action/emotion 三态（action 不超过 15 字、emotion
        为 -2..2 整数；同一人物在本章 内的动作不得重复），非 character（item/
        organization/location）条目只填 entityid/role，"地点"角色只用于 location。
        entityid 填本章的 el 键或 write_entity 回执中的 run 级 id。
        同 el 重写按更新处理：根改描述/伏笔属性，子改描述（type 不可改写，要改换键）；
        characters 给出即整体替换该节点参与者列表，省略则保留。
        回执 content 回显该节点落账记录（节点 id/描述/参与者三态，根带伏笔属性现值、子带 type）。
        """
        record = ledger.apply_event(
            el=el,
            isroot=isroot,
            description=description,
            evidence=evidence,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
            node_type=type,
            characters=characters,
        )
        content = ledger.event_content(el=el, isroot=isroot)
        return json.dumps(
            {"status": "written", "record": record, "content": content},
            ensure_ascii=False,
        )

    @tool
    def finish() -> str:
        """声明本章的语义写入已写完：本回合全部调用处理完后系统校验并冻结

        本章的全部内容（含整棵事件树）都可以在同一批调用里按顺序写完，末尾直接跟本工具，
        不必为了"先看回执"再拆一轮：局部键（实体 el、事件树键）由你指定、写入即生效，
        同批后面的调用直接可用。
        本工具可以单独调用，也可以写在 execute_code 的程序末尾——写在程序末尾时在本程序
        全部语句执行完后结算，与单独调用同一条判定。
        写入是实时生效的，本工具只做收尾：唯一会拒绝收尾的是指标（write_metrics）
        尚未提交——那时回执给出 missing_record，先补指标再收尾。
        本回合其他调用有没有失败与收尾无关：失败的那条只回滚它自己（回执已单独说明原因），
        没进图/没进载荷，收尾按已写入内容完成即可，不必为了收尾去重交失败记录。
        没有内容的领域不必造假数据，直接收尾即可（收尾回执给出各域写入条数）。
        收尾判定在本回合全部调用处理完后生效，通过后本章冻结、不再接受写入；
        不调用本工具，本章不会冻结。
        """
        return json.dumps({"status": "pending"}, ensure_ascii=False)

    def _require_chapter_record(
        ledger: AnnotationToolLedger,
        value: str,
        *,
        record: str,
        field: str,
    ) -> str:
        """2026-09-18 用于校验记录键确实是本章已经写出来的记录（案例只指向真实产出）

        记录键就是写入回执里的 record（实体 entity/…、事件 t1 或 t1/e2、关系、对话各自的
        形态；两个面的键空间不同，所以这里给的是"回执里的 record"这条判据而不是样例）。
        可用集合由写入口在每次调用成功时登记（ledger.written_record_keys），这里读同一份。
        未命中按结构化拒绝回，并把本章已写出的键列在 expected 里（模型可当场自纠）。
        """
        normalized = unicodedata.normalize("NFC", str(value)).strip()
        expected = "写入回执里的 record（本章写出来的记录键）"
        if not normalized:
            raise AnnotationStageRejection(
                f"{field} 不能为空",
                record=record,
                field=field,
                code="invalid_value",
                expected=expected,
            )
        if normalized not in ledger.written_record_keys:
            known = "、".join(sorted(ledger.written_record_keys)[:8])
            raise AnnotationStageRejection(
                f"{field} 不是本章已经写出来的记录: {normalized}",
                record=record,
                field=field,
                code="unknown_record",
                expected=f"{expected}；本章已写出：{known or '（还没有任何记录）'}",
            )
        return normalized

    @tool
    def push_case(
        description: str,
        keys: list[str],
        type: str,
        record_id: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> str:
        """把本章分析中发现的未确定内容登记进案例池（回执给出案例 id）

        type 是任意描述字符串（如 "伏笔疑点"）；description 只写人类可读说明且不超过 100 字；
        keys/type/record_id 必须作为独立参数提交，示例：
        push_case(description="玉戒尺在第 5 章异常发光", keys=["玉戒尺"], type="伏笔疑点")。
        record_id 填这条疑点涉及的产出记录键（写入回执里的 record，实体/关系/事件/对话都行），
        没有明确记录就省略。
        未确定项直接进入案例池，不要求另开全书标注或重新分析章节。
        evidence_refs 可引用 read_text 返回的原文定位，保存双方证据。
        """
        if ledger.phase != "chapter_open":
            raise AnnotationProtocolError(f"阶段 {ledger.phase} 不允许 push_case")
        normalized_type = unicodedata.normalize("NFC", type).strip()
        if not normalized_type:
            raise AnnotationInputError("push_case.type 不能为空")
        normalized_description = unicodedata.normalize("NFC", description).strip()
        if not normalized_description:
            raise AnnotationInputError("push_case.description 不能为空")
        if len(normalized_description) > 100:
            raise AnnotationInputError(
                "push_case.description 不能超过 100 字，请精简为人类可读要点"
                "（案例检索载荷有长度上限）"
            )
        json_marker_fields = ('"keys"', '"type"', '"record_id"')
        if any(marker in normalized_description for marker in json_marker_fields):
            raise AnnotationInputError(
                "push_case.description 只接受人类可读说明；keys/type/record_id"
                " 必须作为独立参数提交，不能写入 description 字符串"
            )
        normalized_keys = [unicodedata.normalize("NFC", key).strip() for key in keys]
        if not normalized_keys or any(not key for key in normalized_keys):
            raise AnnotationInputError("push_case.keys 不能为空")
        if len(set(normalized_keys)) != len(normalized_keys):
            raise AnnotationInputError("push_case.keys 不允许重复")
        target_ref: dict[str, Any] = {
            "kind": normalized_type,
            "chapter_id": ledger.current_chapter_id,
            "keys": normalized_keys,
        }
        if evidence_refs:
            if any(reference not in ledger.text_references for reference in evidence_refs):
                raise AnnotationInputError("案例证据必须来自本次 read_text 的回执")
            target_ref["source_refs"] = [
                ledger.text_references[reference].model_dump(mode="json") for reference in sorted(set(evidence_refs))
            ]
        # 2026-09-18 record_id 可为空：留空（省略或纯空白）即不指向记录，不写进 target_ref
        normalized_record_id = None if record_id is None else unicodedata.normalize("NFC", record_id).strip()
        if normalized_record_id:
            target_ref["record_id"] = _require_chapter_record(
                ledger,
                normalized_record_id,
                record=f"case/{normalized_type}",
                field="record_id",
            )
        target_key = stable_digest(ledger.run_scope, normalized_type, target_ref, fold_text=True)
        existing_case = ledger.pending_case_by_id(target_key)
        if existing_case is not None:
            return json.dumps({"accepted": True, "case_id": target_key, "duplicate": True}, ensure_ascii=False)
        pushed = PendingCase(
            type=normalized_type,
            chapter_id=ledger.current_chapter_id,
            keys=normalized_keys,
            description=normalized_description,
            target_key=target_key,
            target_ref=target_ref,
        )
        ledger.pushed_cases.append(pushed)
        response = {
            "accepted": True,
            "case_id": target_key,
            "note": "未确定内容已登记案例池，不作为已确认事实",
        }
        return json.dumps(response, ensure_ascii=False)

    from .links import build_link_tools

    tools = [write_entity, write_metrics, write_event, write_relation, write_dialogue, finish,
             *build_search_tools(query_service, ledger), *build_link_tools(query_service, ledger), push_case]
    for tool_candidate in tools:
        _forbid_undeclared_args(tool_candidate)
    return tools
