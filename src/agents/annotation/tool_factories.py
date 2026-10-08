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

from src.event_trees.models import ParticipantArg
from src.event_trees.vocabulary import EventChildType
from src.fact_graph.inputs import ChapterMetricsInput, EntityInput, ParagraphLabelInput
from src.fact_graph.schema import (
    CLIFFHANGER_DESCRIPTION,
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ENTITY_TAGS_RULE_TEXT,
    PIVOT_MOMENT_DESCRIPTION,
    EntityRef,
)
from src.fact_graph.vocabulary import (
    Confidence,
    DialogueVerdict,
    EntityType,
    NarrativeFunction,
    RelationType,
    Tone,
    relation_catalog_text,
)

from .ledger import AnnotationToolLedger
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
            candidate_index=candidate_index,
            verdict=verdict,
            speaker_ref=speaker,
            tone=tone,
        )
        return json.dumps(
            {
                "status": "written",
                "record": record,
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
            from_ref=from_entity,
            to_ref=to_entity,
            relation_type=relation_type,
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
        建议先根后子逐个调用，el 由你指定、写入即生效，同轮后面的调用直接可用（不等回执）；
        子事件先于根提交也可以：会挂起，根建好后按提交顺序自动生效（回执 content 带 deferred 提示）。
        树内先后=调用顺序，没有序号参数。子事件 type="main" 顺延主因链（成为新的
        链尾）/"secondary" 挂在当时主链尾；伏笔属性（isforeshadowing/confidence）只属于根：
        isforeshadowing=true 时 confidence 必填（high/medium/low），整棵树成为伏笔树、
        根即埋设事件。
        伏笔建模判据：埋设事件本身就是本章主链事件时，直接给主链根标 isforeshadowing=true，
        不再另立第二棵树重复同一时刻；仅当要埋的悬念不对应主链某个事件时才独立立伏笔树。
        同一悬念的建树选择一次定案，后续回合不再依同一证据复议。
        characters 是该节点的参与者数组（可省）：根节点也直接挂参与者。character 实体的
        role/narrative_role/action/emotion 建议都给，也允许省略或写偏：role 缺省按实体登记
        类型取（character→主体、location→地点、其余→客体），叙事功能近义词自动归一，
        emotion 越界按边界收敛；action 不超过 15 字，同一人物在本章内的动作不得重复。
        非 character（item/organization/location）条目只填 entityid/role，
        "地点"角色只用于 location。
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




    from .links import build_link_tools

    tools = [
        write_entity,
        write_metrics,
        write_event,
        write_relation,
        write_dialogue,
        *build_search_tools(query_service, ledger),
        *build_link_tools(query_service, ledger),
    ]
    for tool_candidate in tools:
        _forbid_undeclared_args(tool_candidate)
    return tools
