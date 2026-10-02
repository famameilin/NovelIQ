"""章节 Agent 语义写入工具与系统账本合同测试

2026-09-14 写入面重构：模型面为五个领域写工具（write_entity / write_metrics /
write_event / write_relation / write_dialogue）+ 唯一 finish 收尾。
写入一次一个语义单元、写入即生效并返回真实回执（{status: written, record}；实体另带
el 与 n），没有逐域 finish——收尾判定在本回合全部调用处理完后由账本执行；事件根/子/
参与者折叠进单工具 write_event（el 层级键：根=树键 t1、子=t1/e2，树内先后=调用顺序），
段落情绪标签并入 write_metrics.labels（{paragraph_id, emotion}），真实 uuid 不外露。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import (
    AnnotationInputError,
    AnnotationProtocolError,
    AnnotationStageRejection,
)
from src.agents.annotation.fact_graph import FactGraph, mention_uuid
from src.agents.annotation.graph import _invoke_tool
from src.agents.annotation.schema import (
    ChapterParagraphInfo,
    DialogueInput,
    EntityInput,
    EventParticipantInput,
    RelationInput,
    TextSearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-07 用于记录搜索解决与原文工具调用的测试查询服务"""

    def __init__(self, *, text_result_count: int = 1, known_dialogue_ids: set[str] | None = None) -> None:
        """2026-08-30 用于初始化原文查询记录

        2026-09-18 对话记录订正下沉到写入路径：账本对非本章候选问一次库
        （has_dialogue_record），桩按本集合回答前文已落库的对话记录标识。
        """
        self.text_queries: list[tuple[str, str, int]] = []
        self.text_result_count = text_result_count
        self.known_dialogue_ids = known_dialogue_ids if known_dialogue_ids is not None else {"dlg_prev_1"}


    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-30 用于记录范围查询并返回完整原文命中"""
        self.text_queries.append((query, range_name, limit))
        return [
            TextSearchResult(
                chapter_id=2,
                paragraph_ids=[20 + index],
                content="顾霜喝道" + "甲" * 2000,
                keyword_score=1.0,
            )
            for index in range(self.text_result_count)
        ]


class _GraphTestEntity:
    """2026-08-11 用于构造内存图测试实体目录项"""

    def __init__(self, name: str, entity_type: str) -> None:
        self.name = name
        self.entity_type = entity_type


def _graph_relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
) -> RelationInput:
    """2026-08-12 用于构造三字段关系边输入（本章确认存在的边）"""
    return RelationInput(
        from_entity=from_entity,
        to_entity=to_entity,
        relation_type=relation_type,
    )


def _find_tool(tools: list, name: str):
    """2026-08-07 用于按工具名取得 LangChain 测试工具"""
    return next(candidate for candidate in tools if candidate.name == name)


def _entity_id(name: str) -> str:
    """按测试章内图的 scope 和 chapter_id 计算提及 ID"""
    return mention_uuid("", 0, name)


def _ledger(*, allow_future_context: bool = False) -> AnnotationToolLedger:
    """2026-08-30 用于构造带唯一当前原文和检索范围配置的工具账本

    2026-08-18：注入 paragraph_info 供事件锚点校验和证据派生使用。
    2026-09-04 单一写面：图域写工具（write_entity/write_relation）
    以常驻 FactGraph 为唯一真相源，故默认注入空图；需要历史实体的用例随后覆盖
    ledger.graph。
    2026-09-13 取消暂存：每个小调用写入即生效（written_* / event_trees 即时落账），
    直接调用工具的测试写完内容后统一调用 ledger.finish_chapter() 收尾。
    2026-09-14 段落级监督：paragraph_info 给出两个段号（¶0/¶1），供
    write_metrics.labels 默认提交两段、满足每章 2 段软下限。
    """
    chapter_text = "“住手”回荡"
    mid = max(1, len(chapter_text) // 2)
    paragraph_info = ChapterParagraphInfo(
        paragraph_ids=[0, 1],
        char_spans=[(0, mid), (mid, len(chapter_text))],
        texts=[chapter_text[:mid], chapter_text[mid:]],
    )
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=10,
        current_chapter_text=chapter_text,
        allow_future_context=allow_future_context,
        graph=FactGraph(),
        paragraph_info=paragraph_info,
    )


def _graph_with_entities(names: dict[str, str], *, relations: set[tuple[str, str, str]] | None = None) -> FactGraph:
    """登记当前章图测试实体，不加载历史状态"""
    graph = FactGraph()
    graph.register_entities([EntityInput(name=name, entity_type=entity_type) for name, entity_type in names.items()])
    for from_name, to_name, relation_type in relations or set():
        graph.apply_relation(RelationInput(from_entity=from_name, to_entity=to_name, relation_type=relation_type))
    return graph


def _tools(service: _QueryService, ledger: AnnotationToolLedger) -> list:
    """2026-08-07 用于构建绑定查询服务与账本的测试工具"""
    return build_annotation_tools(service, ledger)


def _write_metrics_args() -> dict:
    """2026-08-11 用于构造合法 write_metrics 参数"""
    return {
        "summary": "住手回荡",
        "emotional_valence": 0,
        "narrative_function": "铺垫",
    }


def _call(tools: list, name: str, args: dict):
    """2026-08-07 用于同步调用测试工具并解析 JSON"""
    if name == "write_event" and "evidence" not in args:
        args = {**args, "evidence": 1}
    return json.loads(_find_tool(tools, name).invoke(args))


def _write_call(name: str, args: dict) -> dict:
    """2026-09-13 用于构造单个有类型小调用（一次只提交一个完整语义单元）"""
    if name == "write_event" and "evidence" not in args:
        args = {**args, "evidence": 1}
    return {"name": name, "args": args}


def _finish_call() -> dict:
    """2026-09-14 用于构造唯一 finish 收尾声明（判定在本回合全部调用处理完后执行）"""
    return _write_call("finish", {})


def _call_all(tools: list, calls: list[dict]) -> list:
    """2026-09-13 用于按顺序执行一组小调用并解析各自回执"""
    return [_call(tools, call["name"], call["args"]) for call in calls]


def _reject(tools: list, ledger: AnnotationToolLedger, name: str, args: dict) -> dict:
    """2026-09-13 用于经生产路径（graph._invoke_tool）取单条记录的结构化拒绝回执

    schema 层（langchain 参数绑定）失败只在 _invoke_tool 这条生产路径翻译成
    AnnotationStageRejection，直接 .invoke 仍是裸 pydantic ValidationError。
    2026-09-14 与 graph.tool_batch 同口径：执行前快照、失败后回滚——单条调用失败
    只回滚该调用自己，之前的成功写入原样保留（生产收尾前的直接调用测试走同一协议）。
    """
    tool_map = {candidate.name: candidate for candidate in tools}
    ledger_snapshot = ledger.snapshot()
    graph_snapshot = ledger.graph.snapshot() if ledger.graph is not None else None
    with pytest.raises(AnnotationStageRejection) as excinfo:
        asyncio.run(_invoke_tool(tool_map, _write_call(name, args)))
    ledger.restore(ledger_snapshot)
    if graph_snapshot is not None and ledger.graph is not None:
        ledger.graph.restore(graph_snapshot)
    return excinfo.value.receipt()


def _finish_chapter(tools: list, ledger: AnnotationToolLedger) -> dict:
    """2026-09-14 用于触发章节收尾（工具体只回 pending，判定在生产批次末尾的同一汇点）

    直接调用工具的测试没有模型回合边界，这里先过 finish 调用点协议校验，
    再显式执行账本收尾；生产路径 graph._settle_chapter_finish 也是调用它。
    """
    call = _finish_call()
    pending = _call(tools, call["name"], call["args"])
    assert pending == {"status": "pending"}
    return ledger.finish_chapter()


def _entity_calls(
    *,
    name: str = "顾霜",
    entity_type: str = "character",
    el: str | None = None,
) -> list[dict]:
    """2026-09-14 用于构造 write_entity 小调用（一次登记一个实体，el=章内引用键）"""
    return [
        _write_call(
            "write_entity",
            {"name": name, "entity_type": entity_type, "el": el if el is not None else name},
        )
    ]


def _metrics_calls(labels: list[dict] | None = None) -> list[dict]:
    """2026-09-14 用于构造 write_metrics 小调用（指标整域一次提交，段落标签随本域提交）"""
    args = dict(_write_metrics_args())
    if labels is not None:
        args["labels"] = labels
    return [_write_call("write_metrics", args)]


def _paragraph_labels(items: list[tuple[int, int]] | None = None) -> list[dict]:
    """2026-09-14 用于构造 write_metrics.labels 段落情绪标签条目（默认两段满足每章软下限）"""
    resolved = items if items is not None else [(1, -2), (2, -1)]
    return [{"paragraph_id": paragraph_id, "emotion": emotion} for paragraph_id, emotion in resolved]


def _dialogue_calls(items: list[tuple] | None = None) -> list[dict]:
    """2026-09-13 用于构造 write_dialogue 小调用（默认第一条候选判为真实对话）

    items 元组形如 (candidate_index, verdict, speaker, tone)，speaker 是实体引用
    （运行期编号 n 或本章的 el 键）。
    """
    resolved = items if items is not None else [(1, "dialogue", None, None)]
    return [
        _write_call(
            "write_dialogue",
            {
                "candidate_index": candidate_index,
                "verdict": verdict,
                "speaker": speaker,
                "tone": tone,
            },
        )
        for candidate_index, verdict, speaker, tone in resolved
    ]


def _relation_calls(items: list[tuple[int, int, str]] | None = None) -> list[dict]:
    """2026-09-13 用于构造 write_relation 小调用（默认空域，本章不写关系）"""
    resolved = items if items is not None else []
    return [
        _write_call(
            "write_relation",
            {"from_entity": from_entity, "to_entity": to_entity, "relation_type": relation_type},
        )
        for from_entity, to_entity, relation_type in resolved
    ]


def _event_calls(
    *,
    tree_key: str = "t1",
    description: str = "顾霜喝止众人",
    action: str = "喝止",
    child_key: str = "e1",
    child_description: str = "顾霜收势",
    child_action: str = "收势",
) -> list[dict]:
    """2026-09-14 用于构造一棵事件树的小调用组（write_event 根 + 子事件，参与者内联 characters）

    根 el=树键（不带 /），子 el=树键/节点键；树内先后=调用顺序（order 参数已下线）。
    同一章内 (人物, 动作) 二元组不得重复（人物动态状态唯一），多棵树同轮
    提交时各处的 action 必须互不相同，否则该条记录会被结构化拒绝。
    """
    return [
        _write_call(
            "write_event",
            {
                "el": tree_key,
                "isroot": True,
                "description": description,
                "characters": [
                    {
                        "entityid": _entity_id("顾霜"),
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": action,
                        "emotion": -1,
                    }
                ],
            },
        ),
        _write_call(
            "write_event",
            {
                "el": f"{tree_key}/{child_key}",
                "isroot": False,
                "type": "main",
                "description": child_description,
                "characters": [
                    {
                        "entityid": _entity_id("顾霜"),
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": child_action,
                        "emotion": 0,
                    }
                ],
            },
        ),
    ]


def _write_all_domains(
    tools: list,
    ledger: AnnotationToolLedger,
    *,
    entity_calls: list[dict] | None = None,
    event_calls: list[dict] | None = None,
    relation_calls: list[dict] | None = None,
    dialogue_calls: list[dict] | None = None,
    labels: list[dict] | None = None,
) -> list:
    """2026-09-14 用于以小调用完成五个内部数据领域并统一收尾章节

    写入即生效：按依赖顺序提交（实体 → 指标（段落标签随本域提交）→ 事件 →
    关系 → 对话），全部写完后再发唯一 finish 收尾冻结（没有逐域结束声明）。
    传空列表表示该域不写内容（如 entity_calls=[] 表示本章不登记实体）；
    labels=None 表示默认提交两段标签（满足每章 2 段软下限）。
    """
    resolved_entity_calls = _entity_calls() if entity_calls is None else entity_calls
    resolved_event_calls = _event_calls() if event_calls is None else event_calls
    resolved_relation_calls = _relation_calls() if relation_calls is None else relation_calls
    resolved_dialogue_calls = _dialogue_calls() if dialogue_calls is None else dialogue_calls
    resolved_labels = _paragraph_labels() if labels is None else labels
    receipts = _call_all(
        tools,
        [
            *resolved_entity_calls,
            *_metrics_calls(resolved_labels),
            *resolved_event_calls,
            *resolved_relation_calls,
            *resolved_dialogue_calls,
        ],
    )
    receipts.append(_finish_chapter(tools, ledger))
    return receipts


def test_schema_rejects_tone_words_in_emotion_with_guidance() -> None:
    """2026-08-12 用于验证 tone 中文词写进 emotional_valence 时给出纠正引导"""
    with pytest.raises(ValidationError):
        EventParticipantInput.model_validate(
            {
                "entity": "贺伯安",
                "role": "主体",
                "narrative_role": "主体",
                "action": "打碎瓷瓶后逃窜",
                "emotion": "喜悦",
            }
        )


def test_schema_rejects_event_role_words_in_narrative_role_with_guidance() -> None:
    """2026-08-30 用于验证事件专属词写进 narrative_role 时给出纠正引导

    2026-09-11 见证者已并入 RoleFunction 词表（实测 10 次映射失败），
    只剩地点等纯空间角色词仍被拒绝。
    """
    witness = EventParticipantInput.model_validate(
        {
            "entity": "侯飞白",
            "role": "见证者",
            "narrative_role": "见证者",
            "action": "目睹兽棚化为火海",
            "emotion": -2,
        }
    )
    assert witness.narrative_role == "见证者"
    with pytest.raises(ValidationError):
        EventParticipantInput.model_validate(
            {
                "entity": "侯飞白",
                "role": "见证者",
                "narrative_role": "地点",
                "action": "目睹兽棚化为火海",
                "emotion": -2,
            }
        )


def test_event_participant_requires_complete_character_state_group() -> None:
    """2026-08-30 用于拒绝只提交部分人物动态字段的事件参与者"""
    with pytest.raises(ValidationError):
        EventParticipantInput.model_validate(
            {
                "entity": "顾霜",
                "role": "主体",
                "narrative_role": "主体",
                "action": "喝止",
            }
        )


def test_dialogue_verdict_contract_rules() -> None:
    """2026-08-11 用于验证 not_dialogue 时 speaker/tone 必须为空"""
    with pytest.raises(ValidationError):
        DialogueInput.model_validate(
            {
                "candidate_index": 1,
                "verdict": "not_dialogue",
                "speaker": "顾霜",
                "tone": None,
            }
        )
    with pytest.raises(ValidationError):
        DialogueInput.model_validate(
            {
                "candidate_index": 1,
                "verdict": "not_dialogue",
                "speaker": None,
                "tone": "平静",
            }
        )
    valid = DialogueInput.model_validate(
        {
            "candidate_index": 1,
            "verdict": "not_dialogue",
            "speaker": None,
            "tone": None,
        }
    )
    assert valid.verdict == "not_dialogue"


def test_entity_attributes_merge_patch_validation() -> None:
    """2026-08-11 用于验证 attributes 键规范化与空键拒绝"""
    entity = EntityInput.model_validate(
        {
            "name": "顾霜",
            "entity_type": "character",
            "attributes": {" 修为 ": "筑基", "伤势": None},
        }
    )
    assert entity.attributes == {"修为": "筑基", "伤势": None}
    null_patch = EntityInput.model_validate(
        {
            "name": "顾霜",
            "entity_type": "character",
            "attributes": None,
        }
    )
    assert null_patch.attributes == {}
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {
                "name": "顾霜",
                "entity_type": "character",
                "attributes": {"  ": "值"},
            }
        )


def test_entity_tags_limited_to_three_and_five_chars() -> None:
    """2026-08-08 用于验证实体标签最多 3 个且每个最多 5 个字"""
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "item",
                "tags": ["法宝", "灵器", "神兵", "古剑"],
            }
        )
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "item",
                "tags": ["传世神兵法宝"],
            }
        )


def test_entity_tags_normalized_deduplicated_and_type_enforced() -> None:
    """2026-08-08 用于验证标签规范化去重并拒绝非法实体类型"""
    entity = EntityInput.model_validate(
        {
            "name": "赤羽炽尾鸡",
            "entity_type": "character",
            "tags": [" 灵兽 ", "灵兽", "妖兽"],
        }
    )
    assert entity.tags == ["灵兽", "妖兽"]
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "object",
            }
        )


def test_small_calls_complete_chapter_in_write_order() -> None:
    """2026-08-30 用于验证同轮多个小调用写满内部领域并冻结章

    2026-09-13 取消暂存：写工具改造前的五个整域 write 是"一次大载荷"，
    现在是同轮多个有类型小调用写入即生效 + 唯一收尾声明。
    2026-09-14 写入面重构：收尾声明改名 finish（段落标签随指标域提交），
    完成语义（实体/指标/事件/关系/对话各域、章冻结、对话原文绑定）不变。
    """
    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger)

    chapter = ledger.complete_active_chapter()
    assert ledger.completed_chapters[0] is chapter

    assert ledger.phase == "completed"
    dialogue = chapter.dialogues[0]
    assert dialogue.candidate_key.startswith("dlg_")
    assert dialogue.content == "住手"
    assert "\u201c住手\u201d回荡"[dialogue.start : dialogue.end] == "住手"
    assert dialogue.is_inner_monologue is False


def test_write_receipts_carry_fixed_compact_shape() -> None:
    """2026-08-10 用于验证成功写入的模型回执固定压缩

    2026-09-13 取消暂存：旧的整域 write 回执（accepted/tool/domain/item_count
    +numbers）被"写入即生效"的两级小回执取代——每个写工具固定回
    status=written/record（实体另带 el 与 n），收尾回执固定为
    status=completed/chapter_id/records，都不回传完整载荷。
    2026-09-14 写入面重构：实体回执新增 el 绑定回显；records 汇总键由
    sentence_labels 改为段落口径 paragraph_labels。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    entity_receipt = _call(
        tools,
        "write_entity",
        {"name": "顾霜", "entity_type": "character", "el": "顾霜"},
    )
    assert set(entity_receipt) == {"status", "record", "el", "id", "content"}
    assert entity_receipt == {
        "status": "written",
        "record": "entity/顾霜",
        "el": "顾霜",
        "id": _entity_id("顾霜"),
        "content": {
            "name": "顾霜",
            "entity_type": "character",
            "tags": [],
            "description": None,
            "attributes": {},
            "id": _entity_id("顾霜"),
        },
    }

    metrics_receipt = _call(tools, "write_metrics", _write_metrics_args())
    assert metrics_receipt == {
        "status": "written",
        "record": "metrics",
        "content": {
            "summary": "住手回荡",
            "emotional_valence": 0,
            "narrative_function": "铺垫",
            "pivot_moment": False,
            "cliffhanger": False,
            "labels": [],
        },
    }

    _call_all(tools, _dialogue_calls())
    domain_receipt = _finish_chapter(tools, ledger)
    assert set(domain_receipt) == {"status", "chapter_id", "records"}
    assert domain_receipt == {
        "status": "completed",
        "chapter_id": 10,
        "records": {
            "entities": 1,
            "metrics": 1,
            "events": 0,
            "relations": 0,
            "dialogues": 1,
            "character_observations": 0,
            "paragraph_labels": 0,
        },
    }


def test_failed_write_call_keeps_other_domain_receipts_and_written_records() -> None:
    """2026-08-11 用于验证单个写入失败后其他成功领域的 receipt 与已接受记录保留

    2026-09-13 取消暂存：失败粒度从"整域 write"变成"单条小调用"。
    2026-09-14 写入面重构：参与者折叠进 write_event 的 characters 数组，参与者引用
    未登记编号时只拒绝该条记录（结构化拒绝 unregistered_number），实体/指标写入即
    生效的记录、已实时落账的事件树与账本状态原样保留（旧 domain_receipts/staged_*
    断言改写为 written_* 与 event_trees）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})

    invalid = _write_call(
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": "00000000-0000-0000-0000-000000000999",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                }
            ],
        },
    )
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(tools, invalid["name"], invalid["args"])
    assert excinfo.value.code == "unknown_entity_id"
    assert excinfo.value.record == "t1/root/participant/00000000-0000-0000-0000-000000000999"

    assert ledger.metrics_payload is not None
    assert list(ledger.written_entities) == ["顾霜"]
    assert list(ledger.tree_key_index) == ["t1"]
    tree = next(iter(ledger.event_trees.values()))
    assert tree["root_node_id"] is not None
    assert ledger.observation_by_record == {}
    # 收尾前的审计记录只在 finish 时按域汇总写出；失败调用不留痕迹
    assert ledger.write_records == []
    assert ledger.ready_chapter is None
    assert ledger.chapter_finished is False


def test_event_children_land_live_and_freeze_into_ready_chapter() -> None:
    """2026-08-30 用于验证最后一棵事件树收尾后 ready_chapter 冻结全部事件

    2026-09-13 取消暂存：事件节点写入即落账（bound_payloads["events"] 即时可见），
    不再有"结算前 ready_chapter 为空"的暂存态；收尾前 ready_chapter 仍为 None。
    2026-09-14 写入面重构：根/子/参与者折叠进单工具 write_event（el 层级键、
    characters 内联参与者），段落标签随 write_metrics 提交；收尾回执用 records
    汇总各域条数（旧 events 结束回执的 records/trees/character_observation_count
    字段已删除）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call_all(
        tools,
        [
            *_entity_calls(),
            *_metrics_calls(_paragraph_labels()),
            *_dialogue_calls(),
        ],
    )

    _call_all(tools, _event_calls(tree_key="t1", child_description="顾霜追击", child_action="追击"))
    assert [event.description for event in ledger.bound_payloads["events"]] == ["顾霜喝止众人", "顾霜追击"]
    assert ledger.ready_chapter is None
    assert ledger.chapter_finished is False

    _call_all(
        tools,
        [
            _write_call("write_event", {"el": "t2", "isroot": True, "description": "顾霜收势"}),
            _write_call(
                "write_event",
                {
                    "el": "t2/e1",
                    "isroot": False,
                    "type": "main",
                    "description": "新事件描述",
                    "characters": [
                        {
                            "entityid": "顾霜",
                            "role": "主体",
                            "narrative_role": "主体",
                            "action": "离场",
                            "emotion": 0,
                        }
                    ],
                },
            ),
        ],
    )
    _call_all(tools, _dialogue_calls())
    receipt = _finish_chapter(tools, ledger)
    assert receipt["records"]["events"] == 4
    assert receipt["records"]["character_observations"] == 3
    assert ledger.ready_chapter.events[-1].description == "新事件描述"
    assert ledger.ready_chapter.events[-1].cause_role == "main"
    assert [item.action for item in ledger.ready_chapter.character_observations] == ["喝止", "追击", "离场"]

    ledger.complete_active_chapter()
    assert ledger.completed_chapters[0].events[-1].description == "新事件描述"


def test_event_root_appends_new_tree_per_tree_key_and_updates_on_replay() -> None:
    """2026-08-22 事件契约：事件只增不改——每棵事件树独立追加

    2026-09-13 取消暂存：追加粒度是"每个树键"；同一 tree_key 重交即时更新根描述
    （不新增第二棵树），不再有 finalize 标志或逐域事件结算回执——旧断言 first/second
    的 finalized 与 tree_id 改写为实时落账的树数与树 id 独立性，事件审计记录改为
    收尾时按域汇总的一条（payload["trees"] 列表内含全部树）。
    2026-09-14 写入面重构：建树走单工具 write_event（el=树键、isroot=true），
    参与者内联 characters；收尾改名 finish。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call_all(tools, _event_calls(tree_key="t1"))
    _call_all(
        tools,
        _event_calls(
            tree_key="t2",
            description="顾霜收势",
            action="抱拳",
            child_description="顾霜离去",
            child_action="离去",
        ),
    )
    assert ledger.ready_chapter is None
    assert len(ledger.tree_key_index) == 2
    # 同树键重交按更新：根描述改写，不新增第三棵树
    replay = _call(tools, "write_event", {"el": "t2", "isroot": True, "description": "顾霜收势离场"})
    replay_content = replay.pop("content")
    assert replay == {"status": "written", "record": "t2/root"}
    assert replay_content["description"] == "顾霜收势离场"
    assert replay_content["isforeshadowing"] is False
    assert len(ledger.tree_key_index) == 2

    _call(tools, "write_metrics", _write_metrics_args())
    _call_all(tools, _dialogue_calls())
    receipt = _finish_chapter(tools, ledger)
    assert receipt["records"]["events"] == 4
    stored = ledger.bound_payloads["events"]
    roots = [node for node in stored if node.cause_role == "root"]
    assert [node.description for node in roots] == ["顾霜喝止众人", "顾霜收势离场"]
    assert roots[0].tree_id != roots[1].tree_id
    event_records = [item for item in ledger.write_records if item["domain"] == "events"]
    assert len(event_records) == 1
    trees = event_records[0]["payload"]["trees"]
    assert [tree["tree_key"] for tree in trees] == ["t1", "t2"]
    assert [tree["description"] for tree in trees] == ["顾霜喝止众人", "顾霜收势离场"]
    assert [item["domain"] for item in ledger.write_records] == [
        "entities",
        "metrics",
        "events",
        "relations",
        "dialogues",
    ]


def test_complete_chunk_requires_finish_chapter_and_metrics() -> None:
    """2026-08-11 用于验证未收尾的 chunk 不能冻结，且缺指标时收尾被拒

    2026-09-13 取消暂存：没有逐域 finish_domain，唯一收尾声明缺指标时结构化拒绝
    code=missing_record。2026-09-14 写入面重构：收尾改名 finish——只写小
    调用不调用 finish 时 chunk 不冻结（旧合同"未调用领域"的等价物）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call_all(tools, [*_entity_calls(), *_event_calls()])
    assert ledger.written_entities and ledger.metrics_payload is None
    with pytest.raises(ValueError):
        ledger.complete_active_chapter()
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.finish_chapter()
    assert excinfo.value.code == "missing_record"
    assert excinfo.value.field == "metrics"
    assert ledger.chapter_finished is False
    assert ledger.completed_chapters == []
    assert ledger.phase == "chapter_open"


def test_dialogue_missing_candidates_reject_finish_without_default_judgment() -> None:
    """未判候选不能被系统当作非对话，补交实际判定后才能收尾"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    _call(tools, "write_metrics", _write_metrics_args())

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _finish_chapter(tools, ledger)
    assert (excinfo.value.field, excinfo.value.code) == ("dialogues", "missing_record")
    assert ledger.written_dialogues == {}
    assert ledger.ready_chapter is None and not ledger.chapter_finished

    # 补交后缺失列表为空
    filled = _ledger()
    filled_tools = _tools(service, filled)
    _call(filled_tools, "write_metrics", _write_metrics_args())
    _call(
        filled_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
    )
    response = _finish_chapter(filled_tools, filled)
    assert response["status"] == "completed"
    assert len(filled.bound_payloads["dialogues"]) == 1

    # 同序号重交按更新语义：只保留最后一次判定，不再报"重复"
    replay = _ledger()
    replay_tools = _tools(service, replay)
    _call(replay_tools, "write_metrics", _write_metrics_args())
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "inner_monologue", "speaker": None, "tone": None},
    )
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
    )
    response = _finish_chapter(replay_tools, replay)
    assert response["records"]["dialogues"] == 1
    assert replay.bound_payloads["dialogues"][0].is_inner_monologue is False

    # 越界仍拒绝：只拒绝该条记录并给出候选范围
    over = _ledger()
    over_tools = _tools(service, over)
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            over_tools,
            "write_dialogue",
            {"candidate_index": 9, "verdict": "dialogue", "speaker": None, "tone": None},
        )
    assert excinfo.value.record == "dialogue/9"
    assert excinfo.value.field == "candidate_index"
    assert excinfo.value.code == "out_of_range"
    assert over.written_dialogues == {}
    assert over.chapter_finished is False


def test_dialogue_verdict_binds_inner_monologue() -> None:
    """2026-08-11 用于验证 inner_monologue 判定映射为对话记录独白标记

    2026-09-13 取消暂存：逐个候选 write_dialogue 写入即生效；旧"重交
    not_dialogue 后载荷清空"的第二次提交按同序号更新语义覆盖独白判定。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "inner_monologue", "speaker": None, "tone": None},
    )
    bound = ledger.bound_payloads["dialogues"]
    assert len(bound) == 1
    assert bound[0].is_inner_monologue is True

    # 同序号重交 not_dialogue：更新语义覆盖独白判定，落账视图该候选被过滤
    replay = _ledger()
    replay_tools = _tools(service, replay)
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "inner_monologue", "speaker": None, "tone": None},
    )
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "not_dialogue", "speaker": None, "tone": None},
    )
    assert replay.bound_payloads["dialogues"] == []
    assert replay.written_dialogues[1].verdict == "not_dialogue"


def test_fact_endpoint_validation_moves_to_write_time() -> None:
    """2026-08-30 用于验证非人物事件参与者不得携带人物动态状态

    2026-09-13 取消暂存：校验移到参与者写入调用点。2026-09-14 写入面重构：两类
    参与者工具折叠进 write_event 的 characters 数组——location 实体条目携带三态
    字段在调用点被拒（结构化拒绝 code=observation_on_noncharacter，旧分工具时代
    的 not_character 在新参数面上的等价物）；非 character 条目只填 entityid/role
    （ParticipantArg 的参数面承接旧 write_noncharacter_participation 的窄表），
    参与者写入即挂到实时落账的事件节点上。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entity", {"name": "山门", "entity_type": "location", "el": "山门"})
    _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "山门震动"})
    # 山门是本用例唯一登记实体，运行期编号为 1
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            tools,
            "write_event",
            {
                "el": "t1",
                "isroot": True,
                "description": "山门震动",
                "characters": [
                    {
                        "entityid": "山门",
                        "role": "主体",
                        "narrative_role": "主体",
                        "action": "震动",
                        "emotion": 0,
                    }
                ],
            },
        )
    assert excinfo.value.record == "t1/root/participant/山门"
    assert excinfo.value.field == "narrative_role"
    assert excinfo.value.code == "observation_on_noncharacter"
    receipt = _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "山门震动",
            "characters": [{"entityid": "山门", "role": "地点"}],
        },
    )
    receipt_content = receipt.pop("content")
    assert receipt == {"status": "written", "record": "t1/root"}
    assert receipt_content["characters"] == [
        {"entity": "山门", "role": "地点", "narrative_role": None, "action": None, "emotion": None}
    ]
    root_event = ledger.bound_payloads["events"][0]
    participant = root_event.participants[0]
    assert participant.entity == "山门"
    assert (participant.narrative_role, participant.action, participant.emotion) == (None, None, None)
    assert ledger.observation_by_record == {}


def test_event_location_participant_role_requires_location_type() -> None:
    """2026-08-11 用于验证事件参与者角色为地点时端点必须是 location 实体

    2026-09-13 取消暂存：地点角色校验移到参与者写入调用点（结构化拒绝
    code=role_type_mismatch）。2026-09-14 写入面重构：参与者折叠进 write_event 的
    characters 数组，经生产路径（graph._invoke_tool + 单次调用回滚）拒绝，失败只
    拒绝该条记录、不挂到已落账的事件节点、也不在人物动态状态上留痕迹。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call(tools, "write_event", {"el": "t1", "isroot": True, "description": "顾霜喝止众人"})
    receipt = _reject(
        tools,
        ledger,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": "顾霜",
                    "role": "地点",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                }
            ],
        },
    )
    assert receipt["status"] == "rejected"
    assert receipt["record"] == "t1/root/participant/顾霜"
    assert receipt["code"] == "role_type_mismatch"
    assert receipt["field"] == "role"
    assert ledger.bound_payloads["events"][0].participants == []
    assert ledger.observation_by_record == {}


def test_write_entity_without_prior_search_graph_is_allowed() -> None:
    """2026-09-14 删除"提交 write_entity 前必须先 search_graph"硬闸

    旧行为（2026-08-09 起）：图中存在已登记实体时未先 search_graph 禁止登记。
    闸门（graph_queried / entity_gate_passed）删净后，首笔登记不再要求先检索——
    模型判完即写，写入不被检索回执推后一个回合。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    receipt = _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    assert receipt["status"] == "written"
    assert receipt["id"] == _entity_id("顾霜")
    assert list(ledger.written_entities) == ["顾霜"]


def test_write_entity_rejects_registered_entity_type_change() -> None:
    """2026-08-09 用于验证已登记实体重新提交时大类必须保持一致（写入时即失败）

    2026-09-13 取消暂存：整目录提交改为单实体 write_entity，类型冲突变成结构化
    拒绝（code=type_conflict、field=entity_type、record=entity/顾霜），失败不入账。
    2026-09-14 写入面重构：write_entity 必填 el。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(tools, "write_entity", {"name": "顾霜", "entity_type": "item", "el": "顾霜"})
    assert excinfo.value.record == "entity/顾霜"
    assert excinfo.value.field == "entity_type"
    assert excinfo.value.code == "type_conflict"
    assert ledger.written_entities == {}


def test_write_tools_reject_invalid_enum_at_call_time() -> None:
    """2026-08-11 用于验证非法枚举在工具参数校验阶段直接失败

    2026-09-13 取消暂存：小调用工具的 schema 层失败经生产路径
    （graph._invoke_tool）翻译成结构化拒绝回执，只指向出错的那条记录
    （record/field/code/expected），不进入任何写入结构也不留账本痕迹。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_metrics_args()
    args["emotional_valence"] = "unknown"
    metrics_receipt = _reject(tools, ledger, "write_metrics", args)
    assert metrics_receipt["status"] == "rejected"
    assert metrics_receipt["record"] == "metrics"
    assert metrics_receipt["field"] == "emotional_valence"
    assert metrics_receipt["code"] == "not_integer"

    dialogue_receipt = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "unknown", "speaker": None, "tone": None},
    )
    assert dialogue_receipt["status"] == "rejected"
    assert dialogue_receipt["record"] == "dialogue/1"
    assert dialogue_receipt["field"] == "verdict"
    assert dialogue_receipt["code"] == "invalid_value"
    assert ledger.metrics_payload is None
    assert ledger.written_dialogues == {}


def test_unresolved_speaker_no_longer_auto_creates_case() -> None:
    """2026-08-11 用于验证 speaker=null 的对话不再自动生成案例，案例只能由 push_case 登记

    2026-09-13 取消暂存：speaker=null 的 write_dialogue 写入即生效，
    完成路径与案例副作用保持不变。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger)
    ledger.complete_active_chapter()

    assert ledger.pushed_cases == []


def test_event_root_isforeshadowing_carries_confidence_on_root() -> None:
    """2026-09-13 伏笔即事件树：isforeshadowing=true 根事件携带置信度并拒绝未知参数

    2026-09-13 取消暂存：write_event 整树提交改为逐节点写入即生效。
    2026-09-14 写入面重构：根走 write_event(el=树键, isroot=true)，伏笔属性收敛为
    isforeshadowing+confidence——isforeshadowing=true 缺 confidence 在调用点即被拒
    （结构化拒绝），confidence 写进落账根节点的 payoff_likelihood；
    expected_payoff_family 全链退役（不再作为参数或节点字段）。根节点 id 由服务端
    在写入时生成并由账本内部持有；旧 setup_kind 约束由工具参数面的 extra=forbid
    承接（经生产路径报 unknown_field）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    entities_receipt = _call(
        tools,
        "write_entity",
        {"name": "顾霜", "entity_type": "character", "el": "顾霜"},
    )
    assert entities_receipt["status"] == "written"

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            tools,
            "write_event",
            {
                "el": "t1",
                "isroot": True,
                "description": "身份线索埋下",
                "isforeshadowing": True,
            },
        )
    assert excinfo.value.record == "t1/root"
    assert excinfo.value.field == "confidence"
    assert excinfo.value.code == "missing"

    response = _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "身份线索埋下",
            "isforeshadowing": True,
            "confidence": "medium",
        },
    )
    response_content = response.pop("content")
    assert response == {"status": "written", "record": "t1/root"}
    assert response_content["isforeshadowing"] is True
    assert response_content["confidence"] == "medium"
    _call(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "main", "description": "身份线索再次出现"},
    )

    tree = next(iter(ledger.event_trees.values()))
    assert tree["isforeshadowing"] is True
    stored = ledger.bound_payloads["events"]
    root = next(node for node in stored if node.node_id == tree["root_node_id"])
    assert root.is_foreshadow_setup is True
    assert root.payoff_likelihood == "medium"
    setup_kind_receipt = _reject(
        tools,
        ledger,
        "write_event",
        {"el": "t9", "isroot": True, "description": "伏笔", "isforeshadowing": True, "setup_kind": "其他"},
    )
    assert setup_kind_receipt["status"] == "rejected"
    assert setup_kind_receipt["record"] == "t9/root"
    assert setup_kind_receipt["field"] == "setup_kind"
    assert setup_kind_receipt["code"] == "unknown_field"


def test_search_text_returns_bounded_content_and_authorizes_exact_paragraphs() -> None:
    """2026-08-30 用于验证单次文本查询限制正文并即时登记精确段落授权"""
    import asyncio

    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    payload = json.loads(asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"})))
    assert service.text_queries == [("顾霜", "previous", 9)]
    assert len(payload) == 1
    assert len(payload[0]["content"]) == 2000
    assert payload[0]["truncated"] is True
    assert "paragraph_id" not in payload[0]
    assert payload[0]["paragraph_ids"] == [20]
    assert payload[0]["chapter_id"] == 2
    assert payload[0]["capability"] == "other_text"
    assert ledger.authorized_text_paragraph_ids == {20}
    assert ledger.search_log[-1]["hits"] == ["result-1"]


def test_search_text_caps_visible_results_and_authorization_at_eight() -> None:
    """2026-08-30 用于验证第九条命中不会回传或进入正式授权"""
    import asyncio

    service = _QueryService(text_result_count=9)
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    payload = json.loads(asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"})))

    assert len(payload) == 8
    assert ledger.authorized_text_paragraph_ids == set(range(20, 28))


def test_search_text_uses_all_range_when_future_context_is_enabled() -> None:
    """2026-08-30 用于验证后文开关仅影响服务端检索范围"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=True)
    tools = _tools(service, ledger)

    asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))

    assert service.text_queries == [("顾霜", "all", 9)]


def test_write_relation_rejects_unregistered_entity_reference() -> None:
    """2026-08-11 用于验证关系端点必须已登记或本章声明

    2026-09-18 端点解析位于写入路径（编号 n / el 键）：未登记编号在解析点结构化
    拒绝（code=unregistered_number），不再抛裸 ValueError，也不落任何写入。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        ledger,
        "write_relation",
        {
            "from_entity": "00000000-0000-0000-0000-000000000987",
            "to_entity": "00000000-0000-0000-0000-000000000002",
            "relation_type": "同一人物",
        },
    )
    assert receipt["status"] == "rejected"
    unknown_pair = "00000000-0000-0000-0000-000000000987-00000000-0000-0000-0000-000000000002"
    assert receipt["record"] == f"relation/{unknown_pair}/同一人物"
    assert receipt["field"] == "from_entity"
    assert receipt["code"] == "unknown_entity_id"
    assert "00000000-0000-0000-0000-000000000987" in receipt["message"]
    assert ledger.written_relations == {}
    assert ledger.graph.relation_assert_ops == []


def test_push_case_accepts_arbitrary_type_and_record_id() -> None:
    """2026-08-11 用于验证 push_case 类型放开且疑点可指向本章产出记录

    2026-09-18 案例面收窄：第四参由 dialogue_id 改名 record_id，必须命中本章已写出
    的记录键（ledger.written_record_keys），未写出的记录不得凭空引用。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.written_record_keys.add("entity/顾霜")
    tools = _tools(service, ledger)

    response = json.loads(
        _find_tool(tools, "push_case").invoke(
            {
                "description": "神秘仪式疑点",
                "keys": ["住手", "仪式"],
                "type": "神秘仪式",
                "record_id": "entity/顾霜",
            }
        )
    )
    assert response["accepted"] is True
    assert response["case_id"]
    pushed = ledger.pushed_cases[0]
    assert pushed.type == "神秘仪式"
    assert pushed.target_ref["kind"] == "神秘仪式"
    assert pushed.target_ref["record_id"] == "entity/顾霜"
    assert pushed.target_ref["chapter_id"] == 10


def test_push_case_rejects_unknown_record_id() -> None:
    """2026-09-13 用于验证 push_case 校验记录标识确实来自本章已写出的记录

    2026-09-18 dialogue_id 退役（伏笔线程 setup_id 更早已退役），第四参改为产出记录键：
    不在 ledger.written_record_keys 里的键结构化拒绝（code=unknown_record），案例不落池。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        ledger,
        "push_case",
        {
            "description": "对话疑点",
            "keys": ["住手"],
            "type": "dialogue_speaker",
            "record_id": "dlg_not_exist",
        },
    )
    assert receipt["status"] == "rejected"
    assert receipt["record"] == "case/dialogue_speaker"
    assert receipt["field"] == "record_id"
    assert receipt["code"] == "unknown_record"
    assert ledger.pushed_cases == []


def test_push_case_blank_record_id_means_no_record() -> None:
    """2026-09-18 record_id 可为空：没有哪条产出记录承担这条疑点时留空即可

    留空与省略同义（都不写进 target_ref），不影响登记与运行期编号；填了值才按章级
    记录键校验。这里给空串，账本里没有任何已写出记录也照常登记。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    response = _call(
        tools,
        "push_case",
        {"description": "仪式疑点", "keys": ["住手"], "type": "神秘仪式", "record_id": ""},
    )
    assert response["accepted"] is True
    assert response["case_id"]
    assert "record_id" not in ledger.pushed_cases[0].target_ref


def test_push_case_rejects_json_fragment_in_description() -> None:
    """2026-08-11 用于验证 JSON 字段痕迹混入 description 被拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationInputError):
        _find_tool(tools, "push_case").invoke(
            {
                "description": '{"keys": ["住手"], "type": "疑点"}',
                "keys": ["住手"],
                "type": "疑点",
            }
        )


def test_push_case_rejects_overlong_description() -> None:
    """2026-09-04 用于验证 description 超过 100 字被拒绝（与 CaseSearchResult 读取上限对齐）"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationInputError, match="100"):
        _find_tool(tools, "push_case").invoke(
            {
                "description": "疑" * 101,
                "keys": ["线索"],
                "type": "疑点",
            }
        )
    assert ledger.pushed_cases == []


def test_dialogue_small_calls_bind_speaker_tone_and_null_fields() -> None:
    """2026-08-12 用于验证对话判定绑定说话人与语气、null 字段合法

    2026-09-13 取消暂存：四元组数组参数变成 write_dialogue 有类型参数且写入即生效；
    旧"数组整体替换"的第二次提交是同序号更新语义。
    2026-09-14 写入面重构：write_entity 必填 el（本用例直接以登记名为键）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": "平静"},
    )
    stored = ledger.domain_payloads["dialogues"]
    assert stored[0].verdict == "dialogue"
    assert stored[0].speaker == "顾霜"
    assert stored[0].tone == "平静"

    # 同序号重交 null 字段：更新语义只保留最后一次判定
    replay = _ledger()
    replay_tools = _tools(service, replay)
    _call(replay_tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": "平静"},
    )
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
    )
    stored = replay.domain_payloads["dialogues"]
    assert len(stored) == 1
    assert stored[0].speaker is None
    assert stored[0].tone is None


@pytest.mark.parametrize("foreign_tone", ["委屈", "严厉", "平和", "调侃", "温柔", "激动"])
def test_write_dialogue_rejects_foreign_tone_word_with_full_catalog(foreign_tone: str) -> None:
    """2026-09-13 用于验证枚举外语气词一律拒绝，且回执给出全词表与「其他」兜底指引

    run 431a66d8 实测 10 次 tone 拒绝全部是自造词（委屈/严厉/平和/调侃/温柔/激动）：
    闭合词表不放行枚举外取值，拒绝必须让模型一次自纠。
    2026-09-14 写入面重构：write_entity 必填 el；tone 是模型面真 enum，越界走
    记录级结构化拒绝（record=dialogue/<序号>）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})

    receipt = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": foreign_tone},
    )

    assert receipt["status"] == "rejected"
    assert receipt["field"] == "tone"
    assert receipt["code"] == "invalid_value"
    assert foreign_tone in receipt["message"]
    assert not ledger.written_dialogues


def test_write_dialogue_rejects_oversized_tone_word_with_receipt() -> None:
    """2026-09-13 用于验证非语气长度的自由文本（关系词等）整条拒绝且回执可读"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "tone": "强化关系"},
    )
    assert receipt["status"] == "rejected"
    assert receipt["field"] == "tone"
    assert "tone" in receipt["message"]


def test_relation_write_asserts_new_edge_immediately() -> None:
    """2026-08-11 用于验证三字段边在图中无对应边时自动按新建处理（assert）

    2026-09-13 取消暂存：逐条 write_relation 写入即入图（旧合同"结算前图中不得
    出现该边"的暂存语义废止），assert 结果由 FactGraph 操作日志承载——旧结束
    回执里的 relations outcome 列表随逐域 finish 一起删除。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    receipt = _call(
        tools,
        "write_relation",
        {"from_entity": _entity_id("顾霜"), "to_entity": _entity_id("顾老"), "relation_type": "友情"},
    )
    assert receipt == {
        "status": "written",
        "record": "relation/顾霜-顾老/友情",
        "outcome": "assert",
        "content": {"from_entity": "顾霜", "to_entity": "顾老", "relation_type": "友情"},
    }
    assert ("顾老", "顾霜", "友情") in ledger.graph.active_relations
    ops = ledger.graph.relation_assert_ops
    assert [(op["from_entity"], op["to_entity"], op["relation_type"]) for op in ops] == [
        ("顾霜", "顾老", "友情")
    ]
    assert ledger.domain_payloads["relations"][0].relation_type == "友情"


def test_relation_repeated_write_keeps_single_local_edge() -> None:
    """重复提交重放本章关系集合，不增加边数或支持度"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    _call(tools, "write_relation", {
        "from_entity": _entity_id("顾霜"), "to_entity": _entity_id("顾老"), "relation_type": "友情",
    })

    receipt = _call(
        tools,
        "write_relation",
        {"from_entity": _entity_id("顾霜"), "to_entity": _entity_id("顾老"), "relation_type": "友情"},
    )
    assert receipt == {
        "status": "written",
        "record": "relation/顾霜-顾老/友情",
        "outcome": "assert",
        "content": {"from_entity": "顾霜", "to_entity": "顾老", "relation_type": "友情"},
    }
    assert ("顾老", "顾霜", "友情") in ledger.graph.active_relations
    assert len(ledger.graph.active_relations) == 1
    assert next(iter(ledger.graph.relation_attributes.values()))["support_count"] == 1


def test_relation_type_replacement_rebuilds_local_aliases() -> None:
    """更改本章同端点关系类型后，原同一人物边及其别名状态不再生效"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"猴子": "character", "侯飞白": "character"})
    tools = _tools(service, ledger)

    _call(
        tools,
        "write_relation",
        {"from_entity": _entity_id("猴子"), "to_entity": _entity_id("侯飞白"), "relation_type": "同一人物"},
    )
    # 同一对端点换类型即整体替换：同一人物边被友情边替换
    receipt = _call(
        tools,
        "write_relation",
        {"from_entity": _entity_id("猴子"), "to_entity": _entity_id("侯飞白"), "relation_type": "友情"},
    )
    assert receipt == {
        "status": "written",
        "record": "relation/猴子-侯飞白/友情",
        "outcome": "assert",
        "content": {"from_entity": "猴子", "to_entity": "侯飞白", "relation_type": "友情"},
    }
    assert len(ledger.written_relations) == 1
    assert ledger.written_relations[("猴子", "侯飞白")].relation_type == "友情"

    assert len(ledger.graph.relation_assert_ops) == 1
    assert not any(
        from_key == to_key
        for from_key, to_key, _relation_type in ledger.graph.active_relations
    )
    # 同一人物/友情均为双向关系：稳定键按端点名排序
    assert ("侯飞白", "猴子", "同一人物") not in ledger.graph.active_relations
    assert ("侯飞白", "猴子", "友情") in ledger.graph.active_relations


def test_relation_state_field_rejected_from_contract() -> None:
    """2026-08-12 用于验证关系合同已删除 state 字段

    2026-09-13 取消暂存：write_relation 扁平三参数——state 在工具参数面上根本
    不存在（多余字段经生产路径整条拒绝）；内部形态 RelationInput 仍以
    extra=forbid 兜底拒绝该字段。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RelationInput.model_validate(
            {
                "from_entity": "顾霜",
                "to_entity": "顾老",
                "relation_type": "友情",
                "state": "ended",
            }
        )
    receipt = _reject(
        tools,
        ledger,
        "write_relation",
        {"from_entity": "顾霜", "to_entity": "顾老", "relation_type": "友情", "state": "ended"},
    )
    assert receipt["field"] == "state"
    assert receipt["code"] == "unknown_field"
    assert ledger.written_relations == {}


def test_finish_chapter_requires_chunk_frozen_first() -> None:
    """2026-08-07 用于验证 chunk 未冻结时不能 finish"""
    service = _QueryService()
    ledger = _ledger()
    _tools(service, ledger)

    with pytest.raises(AnnotationProtocolError):
        ledger.finish()


def test_finish_chapter_generates_summary_from_chunk_summaries() -> None:
    """2026-08-11 用于验证章节摘要由系统用各 chunk summary 自动生成

    2026-09-13 小调用改造：完成路径改为小调用 + 领域结算，摘要生成逻辑不变。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger)
    ledger.complete_active_chapter()
    annotation = ledger.finish()
    assert annotation.metrics.summary == "住手回荡"


def test_text_search_result_accepts_paragraph_id_zero() -> None:
    """2026-08-30 用于验证首段可作为精确命中段落授权"""
    result = TextSearchResult(
        chapter_id=1,
        paragraph_ids=[0],
        content="开篇第一段",
        keyword_score=2.0,
    )
    assert result.paragraph_ids == [0]


def test_text_search_result_rejects_invalid_paragraph_ids() -> None:
    """2026-08-30 用于验证负数和重复段落身份均被拒绝"""
    with pytest.raises(ValidationError):
        TextSearchResult(
            chapter_id=1,
            paragraph_ids=[-1],
            content="非法段落",
            keyword_score=0.0,
        )
    with pytest.raises(ValidationError):
        TextSearchResult(
            chapter_id=1,
            paragraph_ids=[1, 1],
            content="重复段落",
            keyword_score=0.0,
        )


def _ledger_with_text(text: str) -> AnnotationToolLedger:
    """2026-09-05 用于构造指定章原文的账本（覆盖告警用例需要多条对话候选）

    2026-09-14 段落级监督：paragraph_info 给出两个段号，供默认标签满足每章 2 段软下限。
    """
    mid = max(1, len(text) // 2)
    paragraph_info = ChapterParagraphInfo(
        paragraph_ids=[0, 1],
        char_spans=[(0, mid), (mid, len(text))],
        texts=[text[:mid], text[mid:]],
    )
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=10,
        current_chapter_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=paragraph_info,
    )


def _paragraph_labels_for_ledger(ledger: AnnotationToolLedger) -> list[dict]:
    """2026-09-14 用于按账本段号构造满足软下限（2 段）的 write_metrics.labels 条目"""
    assert ledger.paragraph_info is not None
    known = ledger.paragraph_info.visible_ids()
    return _paragraph_labels(list(zip(known[:2], [-2, -1], strict=True)))


def _write_all_domains_with_dialogues(
    tools: list,
    ledger: AnnotationToolLedger,
    dialogue_calls: list[dict],
) -> None:
    """2026-09-05 用于以自定义对话判定完成五个内部数据领域

    2026-09-13 取消暂存：整域 items 载荷变成 write_dialogue 小调用列表；未提交候选在
    收尾时一次性默认 not_dialogue。2026-09-14 写入面重构：句标签按账本段号随
    write_metrics 提交（不再独立成域）。
    """
    _write_all_domains(
        tools,
        ledger,
        dialogue_calls=dialogue_calls,
        labels=_paragraph_labels_for_ledger(ledger),
    )


def test_empty_dialogue_payload_cannot_finish() -> None:
    """有候选而无判定时禁止将空对话域冻结为完成"""
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)
    assert len(ledger.dialogue_candidates) >= 1

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _write_all_domains_with_dialogues(tools, ledger, [])
    assert (excinfo.value.field, excinfo.value.code) == ("dialogues", "missing_record")
    assert ledger.dialogue_ledger()["pending"] == [1, 2]
    assert ledger.written_dialogues == {}
    assert ledger.ready_chapter is None and not ledger.chapter_finished


def test_partial_dialogue_judgment_keeps_chapter_open() -> None:
    """只判定部分候选时保留成功结果，不补造剩余判定"""
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _write_all_domains_with_dialogues(tools, ledger, _dialogue_calls([(1, "dialogue", None, None)]))
    assert (excinfo.value.field, excinfo.value.code) == ("dialogues", "missing_record")
    assert set(ledger.written_dialogues) == {1}
    assert ledger.dialogue_ledger()["pending"] == [2]
    assert ledger.ready_chapter is None and not ledger.chapter_finished


def test_full_dialogue_judgement_freezes_without_coverage_warning() -> None:
    """2026-09-05 A1：候选全部逐条判定时冻结 chunk 不产生覆盖告警

    2026-09-13 取消暂存：两条候选各发一条 write_dialogue 小调用，收尾时无待默认候选。
    """
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)

    _write_all_domains_with_dialogues(
        tools,
        ledger,
        _dialogue_calls([(1, "dialogue", None, None), (2, "dialogue", None, None)]),
    )
    chunk = ledger.complete_active_chapter()

    assert len(chunk.dialogues) == 2
    assert chunk.coverage_warnings == []


def test_chunk_without_candidates_freezes_without_coverage_warning() -> None:
    """2026-09-05 A1：无对话候选的 chunk 不产生覆盖告警

    2026-09-13 取消暂存：无候选时不发 write_dialogue，直接收尾。
    """
    ledger = _ledger_with_text("山门静默，无人应答。")
    tools = _tools(_QueryService(), ledger)
    assert ledger.dialogue_candidates == []

    _write_all_domains_with_dialogues(tools, ledger, [])
    chunk = ledger.complete_active_chapter()

    assert chunk.coverage_warnings == []


def test_paragraph_labels_bind_and_freeze() -> None:
    """2026-09-07 用于验证段落情绪标签落账并进入冻结 chunk

    2026-09-13 取消暂存：句标签曾拆成 write_sentence_label 逐句调用且写入即绑定。
    2026-09-14 写入面重构：句级口径退役，标签并入 write_metrics.labels（段落级监督，
    整域重交按最后一次为准）。旧"同区间重交覆盖分值（记录数不变）、新句追加而
    不整体替换"换算为：同一次提交内按 paragraph_id 去重（后到覆盖、记录数不变）、
    多段共存（新段追加不覆盖已标注段）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    first = _call(
        tools,
        "write_metrics",
        {**_write_metrics_args(), "labels": _paragraph_labels([(1, -2), (2, -1)])},
    )
    assert first == {
        "status": "written",
        "record": "metrics",
        "content": {
            "summary": "住手回荡",
            "emotional_valence": 0,
            "narrative_function": "铺垫",
            "pivot_moment": False,
            "cliffhanger": False,
            "labels": [{"paragraph_id": 1, "emotion": -2}, {"paragraph_id": 2, "emotion": -1}],
        },
    }
    labels = ledger.bound_payloads["paragraph_labels"]
    # 绑定载荷落库口径：段首可见号在这里已映射回全局 paragraph_id
    assert [label.paragraph_id for label in labels] == [0, 1]
    assert [label.emotion for label in labels] == [-2, -1]

    # 同段号重交覆盖分值：按段号去重、记录数不变（旧"记录键 sentence_label/x:y"
    # 换算为指标域整域回执 record=metrics）
    replay = _call(
        tools,
        "write_metrics",
        {**_write_metrics_args(), "labels": _paragraph_labels([(1, -2), (2, -1), (2, 1)])},
    )
    assert replay == {
        "status": "written",
        "record": "metrics",
        "content": {
            "summary": "住手回荡",
            "emotional_valence": 0,
            "narrative_function": "铺垫",
            "pivot_moment": False,
            "cliffhanger": False,
            "labels": [{"paragraph_id": 1, "emotion": -2}, {"paragraph_id": 2, "emotion": 1}],
        },
    }
    labels = ledger.bound_payloads["paragraph_labels"]
    assert len(labels) == 2
    assert labels[-1].emotion == 1

    _write_all_domains(tools, ledger, labels=_paragraph_labels([(1, -2), (2, 1)]))
    chunk = ledger.complete_active_chapter()
    assert [(label.paragraph_id, label.emotion) for label in chunk.paragraph_labels] == [(0, -2), (1, 1)]
    assert chunk.coverage_warnings == []


def test_paragraph_labels_reject_foreign_paragraph_and_dedup_on_replay() -> None:
    """2026-09-07 用于验证越界段号直接报错自纠（拒绝不落任何写入）

    2026-09-13 取消暂存：非原句只拒绝该条记录（结构化拒绝，旧记录键带原句文本），
    不牵连其他域。2026-09-14 写入面重构：段文本/span 概念没了，句文本定位失败
    （not_found）换算为段号归属失败（code=out_of_range，record=metrics，
    field=paragraph_id）；旧"同区间重交只保留一条记录"换算为提交内按段号去重。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            tools,
            "write_metrics",
            {**_write_metrics_args(), "labels": _paragraph_labels([(1, 0), (7, 1)])},
        )
    assert excinfo.value.record == "metrics"
    assert excinfo.value.field == "paragraph_id"
    assert excinfo.value.code == "out_of_range"
    assert ledger.metrics_payload is None
    assert ledger.bound_payloads.get("paragraph_labels") in (None, [])

    # 同段号重复提交：去重为一条记录、后到覆盖，不报错
    _call(
        tools,
        "write_metrics",
        {**_write_metrics_args(), "labels": _paragraph_labels([(1, -2), (1, -1)])},
    )
    labels = ledger.bound_payloads["paragraph_labels"]
    assert len(labels) == 1
    assert labels[0].emotion == -1
    # 旧"句标签不触碰指标域"随域合并退役：标签并入指标整域，提交即落账
    assert ledger.metrics_payload is not None


def test_paragraph_label_coverage_warning_below_two() -> None:
    """2026-09-07 用于验证每章不足 2 段时冻结留痕覆盖告警（软下限不阻断）

    2026-09-13 取消暂存：句标签没有整批重交/替换通道，只提交一条小调用即触发。
    2026-09-14 写入面重构：句级改段级，告警文案为"情绪标签覆盖: 仅标注 N 段"；
    触发路径换算为 write_metrics.labels 只提交一段，告警判据不变。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger, labels=_paragraph_labels([(1, 0)]))
    chunk = ledger.complete_active_chapter()
    assert chunk.coverage_warnings


def test_tone_rejection_receipt_is_self_correcting_through_production_path() -> None:
    """2026-09-14 枚举外语气词的拒绝回执必须一次可自纠：指回记录、给出全词表与「其他」

    词表进 schema 后越界调用很少，但一旦发生，回执仍要能自纠（不靠模型再猜一轮）。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_index": 2, "verdict": "dialogue", "speaker": _entity_id("顾霜"), "tone": "强装镇定"},
    )
    assert receipt["status"] == "rejected"
    assert receipt["record"] == "dialogue/2"
    assert receipt["field"] == "tone"
    assert receipt["code"] == "invalid_value"
    assert not ledger.written_dialogues


def test_entity_ref_contract_rejects_name_as_reference_with_guidance() -> None:
    """2026-09-14 双键空间 → 2026-09-19 id 纪律：名称写进实体引用槽仍被拒且可自纠

    实体引用只有两条通道：本章 write_entity 登记的 el 键、write_entity /
    search_graph 回执里的 run 级 uuid id。名称写进引用槽既不是 el 也不是 id，
    在账本解析点结构化拒绝（code=unknown_entity_id），报错列出已登记 id 样例，
    expected 指回两条合法通道，语义意图（可自纠引导）不变。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "a1"})

    participant_receipt = _reject(
        tools,
        ledger,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "顾霜喝止众人",
            "characters": [
                {
                    "entityid": "顾霜",
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "喝止",
                    "emotion": -1,
                }
            ],
        },
    )
    assert participant_receipt["record"] == "t1/root/participant/顾霜"
    assert participant_receipt["field"] == "entityid"
    assert participant_receipt["code"] == "unknown_entity_id"
    relation_receipt = _reject(
        tools,
        ledger,
        "write_relation",
        {"from_entity": "顾霜", "to_entity": "顾老", "relation_type": "友情"},
    )
    assert relation_receipt["field"] == "from_entity"
    assert relation_receipt["code"] == "unknown_entity_id"
    # 生产口径：失败调用只回滚自己，登记与引用解析不留下半途状态
    assert ledger.written_relations == {}


def test_write_dialogue_speaker_name_gets_self_correction_guidance() -> None:
    """2026-09-19 id 纪律：write_dialogue speaker 写名称给出可自纠报错

    名称写进 speaker 引用槽既不是 el 键也不是 run 级 id，账本解析点结构化拒绝
    （code=unknown_entity_id），message 带已登记 id 样例、expected 指回两条合法通道。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": None},
    )
    assert receipt["record"] == "dialogue/1"
    assert receipt["field"] == "speaker"
    assert receipt["code"] == "unknown_entity_id"
    assert ledger.written_dialogues == {}
