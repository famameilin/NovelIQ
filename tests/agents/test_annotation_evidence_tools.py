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

from src.agents.annotation.errors import AnnotationStageRejection
from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.text_search import TextSearchCandidate
from src.agents.annotation.tool_batch import _invoke_tool
from src.event_trees.models import EventParticipantInput
from src.fact_graph.graph import FactGraph, mention_uuid
from src.fact_graph.inputs import ChapterParagraphInfo, DialogueInput, EntityInput, RelationInput
from src.fact_graph.outputs import TextSearchResult
from tests.support.annotation_work_tools import build_annotation_tools


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
            TextSearchCandidate(
                chapter_id=2,
                paragraph_id=20 + index,
                excerpt="顾霜喝道" + "甲" * 2000,
                keyword_score=1.0,
                semantic_score=None,
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


def test_event_participant_allows_partial_character_state_group() -> None:
    """2026-10-04 合同放开：人物动态字段允许部分缺省，缺省值原样保留为 None"""
    participant = EventParticipantInput.model_validate(
        {
            "entity": "顾霜",
            "role": "主体",
            "narrative_role": "主体",
            "action": "喝止",
        }
    )
    assert participant.emotion is None


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
    assert [(op["from_entity"], op["to_entity"], op["relation_type"]) for op in ops] == [("顾霜", "顾老", "友情")]
    assert ledger.domain_payloads["relations"][0].relation_type == "友情"


def test_relation_repeated_write_keeps_single_local_edge() -> None:
    """重复提交重放本章关系集合，不增加边数或支持度"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    _call(
        tools,
        "write_relation",
        {
            "from_entity": _entity_id("顾霜"),
            "to_entity": _entity_id("顾老"),
            "relation_type": "友情",
        },
    )

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
    assert not any(from_key == to_key for from_key, to_key, _relation_type in ledger.graph.active_relations)
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
