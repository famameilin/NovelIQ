"""
章节标注语义写入工具工厂：五个领域写入工具、finish 与 push_case 的闭包构造
"""

from __future__ import annotations

import json
import unicodedata
from typing import Annotated, Any

from langchain_core.tools import tool
from pydantic import Field

from src.event_trees.models import ParticipantArg
from src.fact_graph.inputs import ChapterMetricsInput, EntityInput, EntityNameRef, ParagraphLabelInput
from src.fact_graph.schema import (
    CLIFFHANGER_DESCRIPTION,
    ENTITY_TAG_MAX_CHARS,
    ENTITY_TAG_MAX_COUNT,
    ENTITY_TAGS_RULE_TEXT,
    PIVOT_MOMENT_DESCRIPTION,
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
    """用于构建语义写入搜索解决和完成工具集"""

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
        representative: Annotated[
            bool | None,
            Field(description="规范名代表标记：True=把该实体标为同名身份的规范名，False=清除该标记，省略=保留现值"),
        ] = None,
    ) -> str:
        """登记或更新一个实体（一次一个），el 是你自定的章内引用键、绑定即生效

        新实体用本章出现的名称；已登记实体用登记名，只提交本次变化的字段
        （description 一句话简介、tags 与 representative 见参数说明）；
        未提交的字段保留现值。
        实体大类一经登记不可变更；同一词条的不同身份用区分性名称
        （如"圣城"是 location、"圣城朝堂"是 organization）。
        事件/关系/对话引用写正文名字与大类，未登记时由运行时自动登记。
        本入口用于补充 tags/description/representative 与 el 锚点。
        回执 content 回显该实体合并后的生效记录（含 run 级 id）。
        """
        # 登记序由 el 键承接，不设"提交 write_entity 前必须先 search_graph"硬闸：
        # 首写被检索挡在门外会迫使判定跨回合等待回执。
        entity = EntityInput(
            name=name,
            entity_type=entity_type,
            tags=tags or [],
            description=description,
            representative=representative,
        )
        present = {"name", "entity_type"}
        if tags is not None:
            present.add("tags")
        if description is not None:
            present.add("description")
        if representative is not None:
            present.add("representative")
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
        speaker: EntityNameRef | None = None,
        tone: Tone | None = None,
    ) -> str:
        """登记本章候选的三态判断，不提供既有对话订正入口

        speaker 写正文名字与 character 大类，运行时自动登记；归属无法确认时留空
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
        from_entity: EntityNameRef,
        to_entity: EntityNameRef,
        relation_type: Annotated[
            RelationType,
            Field(description="闭合关系类型，方向与两端实体类型约束如下：\n" + relation_catalog_text()),
        ],
    ) -> str:
        """登记本章局部关系，两端写正文名字与大类，运行时自动登记"""
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
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: str,
        evidence: int,
        progress: str | None = None,
        from_chapter_id: int | None = None,
        to_chapter_id: int | None = None,
        reason: str | None = None,
        isforeshadowing: bool = False,
        confidence: Confidence | None = None,
        characters: list[ParticipantArg] | None = None,
    ) -> str:
        """创建正式事件；问题、概要、类型、状态及真实证据必填，起止章节缺省当前章"""
        record = ledger.apply_event(
            el=el,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            evidence=evidence,
            progress=progress,
            from_chapter_id=from_chapter_id,
            to_chapter_id=to_chapter_id,
            reason=reason,
            isforeshadowing=isforeshadowing,
            confidence=confidence,
            characters=characters,
        )
        content = ledger.event_content(el=el, isroot="/" not in el)
        return json.dumps({"status": "written", "record": record, "content": content}, ensure_ascii=False)

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
