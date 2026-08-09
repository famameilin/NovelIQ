"""章节 Agent 语义写入工具与系统账本合同测试"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.agents.annotation.errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationProtocolError,
)
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    DialogueInput,
    EntityInput,
    EventInput,
    ForeshadowingInput,
    GraphSearchEntity,
    GraphSearchFact,
    GraphSearchResult,
    RelationInput,
    SearchResult,
    StateInput,
    TextEvidence,
    TextSearchResult,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-07 用于记录搜索解决与原文工具调用的测试查询服务"""

    def __init__(self) -> None:
        """2026-08-07 用于初始化原文查询范围与读取记录"""
        self.text_queries: list[tuple[str, str]] = []
        self.reads: list[int] = []

    def _case(self) -> CaseSearchResult:
        """2026-08-07 用于构造一个可严格解决的活动案例"""
        return CaseSearchResult(
            id="case-1",
            type="dialogue_speaker",
            chunk_id=10,
            keys=["住手", "说话人"],
            description="该句住手由谁说出",
            evidence=[TextEvidence(reason="当前原文尚未明确", chunk_id=10)],
        )

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-07 用于返回一个初始活动案例"""
        del current_text, semantic_limit, rotation_limit
        return [self._case()], ["case-1"]

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        """2026-08-07 用于验证已解决案例从后续池搜索隐藏"""
        del query, limit
        if "case-1" in hidden_case_ids:
            return SearchResult()
        return SearchResult(results=[self._case()])

    def search_graph(self, query, *, limit=50):
        """2026-08-07 用于返回上一章节图版本中的实体与事实语义"""
        del query, limit
        return GraphSearchResult(
            graph_version_id="graph-version-1",
            facts=[
                GraphSearchFact(
                    fact_id="fact-1",
                    fact_revision=1,
                    fact_type="character_observation",
                    predicate="action",
                    effective_chunk_id=1,
                    content={"kind": "character_observation", "action": "前章动作"},
                    evidence=[TextEvidence(reason="前章原文确认", chunk_id=1)],
                )
            ],
            entities=[
                GraphSearchEntity(
                    entity_id=42,
                    name="顾霜",
                    entity_type="character",
                    state_revision=1,
                    state={"status": "active"},
                )
            ],
        )

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于记录范围并返回原文候选"""
        del limit
        self.text_queries.append((query, range_name))
        return [
            TextSearchResult(
                chapter_id=2,
                chunk_id=20,
                excerpt="顾霜喝道",
                keyword_score=1.0,
            )
        ]

    def read_text(self, chunk_id):
        """2026-08-07 用于记录已由文本搜索候选授权的原文读取"""
        self.reads.append(chunk_id)
        return "顾霜喝道"

    def fetch_active_case_details(self, case_id):
        """2026-08-07 用于返回包含内部稳定目标的 active 案例"""
        if case_id != "case-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="target-1",
            target_ref={
                "kind": "dialogue",
                "candidate_key": "candidate-1",
                "chunk_id": 10,
                "start": 1,
                "end": 3,
                "text": "住手",
                "fact_id": "fact-dialogue",
                "fact_revision": 1,
            },
        )


def _find_tool(tools: list, name: str):
    """2026-08-07 用于按工具名取得 LangChain 测试工具"""
    return next(candidate for candidate in tools if candidate.name == name)


def _ledger(*, allow_future_context: bool = False) -> AnnotationToolLedger:
    """2026-08-07 用于构造带唯一 current 原文和后文开关的工具账本"""
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=10,
        current_chunk_text="“住手”回荡",
        allow_future_context=allow_future_context,
    )


def _tools(service: _QueryService, ledger: AnnotationToolLedger) -> list:
    """2026-08-07 用于构建绑定查询服务与账本的测试工具"""
    return build_annotation_tools(service, ledger)


def _write_metrics_args() -> dict:
    """2026-08-07 用于构造合法 write_metrics 参数"""
    return {
        "summary": "住手回荡",
        "emotional_valence": "neutral",
        "narrative_function": "铺垫",
        "confidence": "high",
        "reason": "本章开端",
    }


def _write_entities_args() -> dict:
    """2026-08-08 用于构造当前 chunk 合法实体目录参数（单列表）"""
    return {
        "entities": [
            {
                "name": "顾霜",
                "entity_type": "character",
                "confidence": "high",
                "reason": "人物出现",
            }
        ]
    }


def _write_dialogues_args() -> dict:
    """2026-08-07 用于构造按候选顺序的对话判断参数"""
    return {
        "items": [
            {
                "is_dialogue": True,
                "description": "喝止住手",
                "speaker": None,
                "confidence": "high",
                "reason": "原文双引号",
            }
        ]
    }


def _write_remaining_args() -> dict:
    """2026-08-07 用于构造剩余六个领域的最小合法参数"""
    return {
        "character_observations": {
            "items": [
                {
                    "character": "顾霜",
                    "role_function": "主体",
                    "action": "喝止",
                    "action_type": "对话",
                    "emotion": "mild_negative",
                    "confidence": "high",
                    "reason": "顾霜喝止",
                }
            ]
        },
        "events": {
            "items": [
                {
                    "description": "顾霜喝止众人",
                    "participants": [
                        {"entity": "顾霜", "participation": "主体"}
                    ],
                    "confidence": "high",
                    "reason": "喝止事件",
                }
            ]
        },
        "relations": {"items": []},
        "states": {"items": []},
        "foreshadowings": {"items": []},
    }


def _call(tools: list, name: str, args: dict):
    """2026-08-07 用于同步调用测试工具并解析 JSON"""
    return json.loads(_find_tool(tools, name).invoke(args))


def test_schema_rejects_deleted_contract_fields() -> None:
    """2026-08-07 用于验证输入模型对已删除字段使用 extra=forbid 明确拒绝"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EntityInput.model_validate(
            {
                "name": "顾霜",
                "confidence": "high",
                "reason": "出现",
                "ref": "character_1",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EntityInput.model_validate(
            {
                "name": "顾霜",
                "confidence": "high",
                "reason": "出现",
                "existing_entity_id": 42,
                "mentions": [{"chunk_id": 10, "start": 0, "end": 2, "text": "顾霜"}],
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DialogueInput.model_validate(
            {
                "is_dialogue": True,
                "description": "喝止",
                "confidence": "high",
                "reason": "双引号",
                "content": "住手",
                "start": 1,
                "end": 3,
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RelationInput.model_validate(
            {
                "from_entity": "顾霜",
                "to_entity": "山门",
                "relation_type": "位于",
                "change_kind": "assert",
                "confidence": "high",
                "reason": "进入",
                "relation_id": "relation-1",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EventInput.model_validate(
            {
                "description": "进入山门",
                "confidence": "high",
                "reason": "事件",
                "event_type": "进入",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StateInput.model_validate(
            {
                "entity": "顾霜",
                "predicate": "status",
                "value": "active",
                "confidence": "high",
                "reason": "状态",
                "ref": "state_1",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ForeshadowingInput.model_validate(
            {
                "foreshadowing_type": "场景",
                "setup_kind": "其他",
                "setup_summary": "伏笔",
                "why_unresolved_now": "未回收",
                "expected_payoff_family": "兑现",
                "payoff_likelihood": "medium",
                "setup_status": "open",
                "confidence": "high",
                "reason": "伏笔",
                "is_new_setup": True,
                "linked_setup_id": None,
            }
        )


def test_schema_rejects_non_closed_enums() -> None:
    """2026-08-07 用于验证所有保留分类字段只接受中央闭合枚举"""
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {"name": "顾霜", "confidence": "certain", "reason": "出现"}
        )
    with pytest.raises(ValidationError):
        RelationInput.model_validate(
            {
                "from_entity": "顾霜",
                "to_entity": "山门",
                "relation_type": "归属",
                "change_kind": "assert",
                "confidence": "high",
                "reason": "进入",
            }
        )
    with pytest.raises(ValidationError):
        DialogueInput.model_validate(
            {
                "is_dialogue": True,
                "description": "喝止",
                "confidence": "certain",
                "reason": "双引号",
            }
        )


def test_entity_tags_limited_to_three_and_three_chars() -> None:
    """2026-08-08 用于验证实体标签最多 3 个且每个最多 3 个字"""
    with pytest.raises(ValidationError, match="最多 3 个标签"):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "item",
                "tags": ["法宝", "灵器", "神兵", "古剑"],
                "confidence": "high",
                "reason": "出现",
            }
        )
    with pytest.raises(ValidationError, match="每个标签最多 3 个字"):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "item",
                "tags": ["传世法宝"],
                "confidence": "high",
                "reason": "出现",
            }
        )


def test_entity_tags_normalized_deduplicated_and_type_enforced() -> None:
    """2026-08-08 用于验证标签规范化去重并拒绝非法实体类型"""
    entity = EntityInput.model_validate(
        {
            "name": "赤羽炽尾鸡",
            "entity_type": "character",
            "tags": [" 灵兽 ", "灵兽", "妖兽"],
            "confidence": "high",
            "reason": "出现",
        }
    )
    assert entity.tags == ["灵兽", "妖兽"]
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "object",
                "confidence": "high",
                "reason": "出现",
            }
        )


def test_multiple_write_tools_same_round_then_complete_chunk() -> None:
    """2026-08-07 用于验证一个回复可调用多个 write 工具并完整冻结 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_character_observations", _write_remaining_args()["character_observations"])
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_states", _write_remaining_args()["states"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])

    response = _call(tools, "complete_chunk", {})
    assert response["accepted"] is True
    assert response["completed_chunk"] == 10

    chunk = ledger.completed_chunks[0]
    assert chunk.chunk_id == 10
    assert ledger.phase == "continuity_open"
    dialogue = chunk.dialogues[0]
    assert dialogue.candidate_key.startswith("dlg_")
    assert dialogue.content == "住手"
    assert "“住手”回荡"[dialogue.start : dialogue.end] == "住手"
    assert dialogue.evidence[0].chunk_id == 10


def test_domain_reinvocation_completely_replaces_payload() -> None:
    """2026-08-07 用于验证领域重新调用完整替换旧暂存值"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    first = _write_remaining_args()["events"]
    first["items"] = [
        {
            "description": "旧事件",
            "confidence": "low",
            "reason": "旧理由",
        }
    ]
    _call(tools, "write_events", first)
    second = _write_remaining_args()["events"]
    _call(tools, "write_events", second)

    stored = ledger.domain_payloads["events"]
    assert len(stored) == 1
    assert stored[0].description == "顾霜喝止众人"
    assert ledger.domain_revision_counts["events"] == 2
    assert len([item for item in ledger.write_revisions if item["domain"] == "events"]) == 2


def test_complete_chunk_requires_all_eight_domains() -> None:
    """2026-08-07 用于验证未调用领域无法完成 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    with pytest.raises(ValueError, match="尚未写入全部领域"):
        _call(tools, "complete_chunk", {})
    assert ledger.completed_chunks == []
    assert ledger.phase == "chunk_open"


def test_complete_chunk_requires_dialogue_candidate_alignment() -> None:
    """2026-08-07 用于验证漏标或超标对话候选无法完成 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_character_observations", _write_remaining_args()["character_observations"])
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_states", _write_remaining_args()["states"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])
    _call(tools, "write_dialogues", {"items": []})

    with pytest.raises(ValueError, match="必须按系统候选顺序逐项提交"):
        _call(tools, "complete_chunk", {})


def test_complete_chunk_rejects_unknown_entity_endpoint() -> None:
    """2026-08-07 用于验证事实端点必须来自当前 chunk 的 write_entities"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    invalid = _write_remaining_args()["character_observations"]
    invalid["items"][0]["character"] = "山门"
    _call(tools, "write_character_observations", invalid)
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_states", _write_remaining_args()["states"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])

    with pytest.raises(ValueError, match="未在当前 chunk 的 write_entities 中声明"):
        _call(tools, "complete_chunk", {})


def test_write_tools_reject_invalid_enum_at_call_time() -> None:
    """2026-08-07 用于验证非法枚举在工具参数校验阶段直接失败"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_metrics_args()
    args["emotional_valence"] = "unknown"
    with pytest.raises(ValidationError):
        _find_tool(tools, "write_metrics").invoke(args)
    assert ledger.domain_receipts == set()


def test_unresolved_speaker_creates_system_pending_case() -> None:
    """2026-08-07 用于验证 speaker=null 的对话自动创建连续性案例"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_character_observations", _write_remaining_args()["character_observations"])
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_states", _write_remaining_args()["states"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])
    _call(tools, "complete_chunk", {})

    assert len(ledger.pending_cases) == 1
    pending = ledger.pending_cases[0]
    assert pending.type == "dialogue_speaker"
    assert pending.chunk_id == 10
    assert pending.target_ref["kind"] == "dialogue"
    assert pending.target_ref["chunk_id"] == 10
    assert pending.target_ref["start"] == 1
    assert pending.target_ref["end"] == 3
    assert pending.target_ref["text"] == "住手"


def test_write_dialogues_requires_description_for_valid_dialogue() -> None:
    """2026-08-07 用于验证有效对话必须提供 description"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_dialogues_args()
    del args["items"][0]["description"]
    with pytest.raises(ValidationError, match="有效对话必须提供 description"):
        _find_tool(tools, "write_dialogues").invoke(args)
    assert ledger.domain_receipts == set()


def test_future_disabled_rejects_future_search_and_read() -> None:
    """2026-08-07 用于验证关闭开关时 future 搜索与读取都不可用"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="range 必须为 previous"):
        asyncio.run(_find_tool(tools, "search_text").ainvoke(
            {"query": "顾霜", "range": "future"}
        ))
    ledger.set_phase("continuity_open")
    with pytest.raises(AnnotationAuthorizationError, match="allow_future_context=false"):
        asyncio.run(_find_tool(tools, "search_text").ainvoke(
            {"query": "顾霜", "range": "future"}
        ))


def test_search_text_numbering_and_read_authorization() -> None:
    """2026-08-07 用于验证运行内编号读取真实原文且编号不可复用"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=True)
    ledger.set_phase("continuity_open")
    tools = _tools(service, ledger)

    payload = json.loads(
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜", "range": "future"}))
    )
    assert payload[0]["result_number"] == 1
    assert "chunk_id" not in payload[0]
    content = _find_tool(tools, "read_text").invoke({"result_number": 1})
    assert content == "顾霜喝道"
    assert service.reads == [20]

    ledger.set_phase("chunk_open")
    with pytest.raises(AnnotationAuthorizationError, match="不属于当前"):
        _find_tool(tools, "read_text").invoke({"result_number": 1})
    with pytest.raises(AnnotationAuthorizationError, match="未由本轮 search_text 返回"):
        _find_tool(tools, "read_text").invoke({"result_number": 99})


def test_search_pool_uses_case_numbers_and_resolve_case() -> None:
    """2026-08-07 用于验证临时 case_number 解决活动案例且不可重复"""
    service = _QueryService()
    ledger = _ledger()
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert [item["result_kind"] for item in view["results"]] == ["case"]
    case_number = view["results"][0]["case_number"]
    response = json.loads(
        _find_tool(tools, "resolve_case").invoke(
            {"case_number": case_number, "speaker": "顾霜", "reason": "后文点明"}
        )
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[0].case_id == "case-1"
    assert ledger.resolved_cases[0].target_key == "target-1"

    with pytest.raises(AnnotationInputError, match="已经解决"):
        _find_tool(tools, "resolve_case").invoke(
            {"case_number": case_number, "speaker": "顾霜", "reason": "重复"}
        )
    hidden = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert hidden["results"] == []


def test_resolve_case_rejects_unknown_case_number() -> None:
    """2026-08-07 用于验证未登记的 case_number 直接拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="未由初始候选或 search_pool 返回"):
        _find_tool(tools, "resolve_case").invoke(
            {"case_number": 999, "speaker": "顾霜", "reason": "猜测"}
        )


def test_search_graph_hides_database_ids_from_agent() -> None:
    """2026-08-07 用于验证图查询结果不暴露数据库 ID 与内部字段"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    payload = json.loads(_find_tool(tools, "search_graph").invoke({"query": "顾霜"}))
    assert "fact_id" not in payload["facts"][0]
    assert "fact_revision" not in payload["facts"][0]
    assert "entity_id" not in payload["entities"][0]
    assert payload["facts"][0]["content"]["action"] == "前章动作"


def test_finish_chapter_requires_chunk_frozen_first() -> None:
    """2026-08-07 用于验证 chunk 未冻结时不能 finish_chapter"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationProtocolError, match="不允许 finish_chapter"):
        _find_tool(tools, "finish_chapter").invoke({"chapter_summary": "章节结束"})
