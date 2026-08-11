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
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    DialogueInput,
    EntityInput,
    EventInput,
    ForeshadowingInput,
    ForeshadowingSearchResult,
    RelationInput,
    SearchResult,
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
        )

    def find_initial_case_candidates(self, current_text, *, semantic_limit=50, rotation_limit=50):
        """2026-08-07 用于返回一个初始活动案例"""
        del current_text, semantic_limit, rotation_limit
        return [self._case()], ["case-1"]

    def search_pool(self, query, *, hidden_case_ids, limit=50):
        """2026-08-07 用于验证已解决案例从后续池搜索隐藏"""
        del limit
        if "case-1" in hidden_case_ids:
            return SearchResult()
        if "线索" in query:
            return SearchResult(
                results=[
                    ForeshadowingSearchResult(
                        record_id="thread-1",
                        content={"setup_summary": "护佑山门", "setup_kind": "明确承诺"},
                    )
                ]
            )
        return SearchResult(results=[self._case()])

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
                "dialogue_id": "candidate-1",
                "chunk_id": 10,
                "start": 1,
                "end": 3,
                "text": "住手",
            },
        )

    def thread_exists(self, setup_id):
        """2026-08-11 用于校验 push_case 携带的伏笔线程 id"""
        return setup_id == "thread-1"


class _AliasQueryService(_QueryService):
    """2026-08-09 用于提供 entity_alias 类型的活动案例"""

    def _case(self) -> CaseSearchResult:
        """2026-08-09 用于构造疑似同一人物案例"""
        return CaseSearchResult(
            id="alias-1",
            type="entity_alias",
            chunk_id=10,
            keys=["同一人物", "顾霜", "顾老"],
            description="疑似同一人物：顾霜 与 顾老 共享邻居重叠度 50%",
        )

    def fetch_active_case_details(self, case_id):
        """2026-08-09 用于返回 alias 案例稳定目标"""
        if case_id != "alias-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="target-alias-1",
            target_ref={"kind": "alias", "name_a": "顾霜", "name_b": "顾老", "chunk_id": 10},
        )

    def thread_exists(self, setup_id):
        """2026-08-11 用于校验 push_case 携带的伏笔线程 id"""
        return setup_id == "thread-1"


class _GraphTestEntity:
    """2026-08-11 用于构造内存图测试实体目录项"""

    def __init__(self, name: str, entity_type: str) -> None:
        self.name = name
        self.entity_type = entity_type


def _graph_relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
    state: str,
) -> RelationInput:
    """2026-08-11 用于构造闭合类型关系输入"""
    return RelationInput(
        from_entity=from_entity,
        to_entity=to_entity,
        relation_type=relation_type,
        state=state,
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


def _graph_with_entities(names: dict[str, str]) -> FactGraph:
    """2026-08-11 用于构造带历史实体的内存事实图"""
    return FactGraph(
        history_entity_types=dict(names),
        history_entity_names=dict(names),
    )


def _tools(service: _QueryService, ledger: AnnotationToolLedger) -> list:
    """2026-08-07 用于构建绑定查询服务与账本的测试工具"""
    return build_annotation_tools(service, ledger)


def _write_metrics_args() -> dict:
    """2026-08-11 用于构造合法 write_metrics 参数"""
    return {
        "summary": "住手回荡",
        "emotional_valence": "neutral",
        "narrative_function": "铺垫",
    }


def _write_entities_args() -> dict:
    """2026-08-11 用于构造当前 chunk 合法实体目录参数（单列表）"""
    return {
        "entities": [
            {
                "name": "顾霜",
                "entity_type": "character",
            }
        ]
    }


def _write_dialogues_args() -> dict:
    """2026-08-11 用于构造按候选序号的对话判断参数"""
    return {
        "items": [
            {
                "candidate_index": 1,
                "verdict": "dialogue",
                "speaker": None,
                "tone": None,
            }
        ]
    }


def _write_remaining_args() -> dict:
    """2026-08-11 用于构造剩余五个领域的最小合法参数"""
    return {
        "character_observations": {
            "items": [
                {
                    "character": "顾霜",
                    "role_function": "主体",
                    "action": "喝止",
                    "emotion": "mild_negative",
                }
            ]
        },
        "events": {
            "items": [
                {
                    "description": "顾霜喝止众人",
                    "participants": [
                        {"entity": "顾霜", "role": "行动者"}
                    ],
                }
            ]
        },
        "relations": {"items": []},
        "foreshadowings": {"items": []},
    }


def _call(tools: list, name: str, args: dict):
    """2026-08-07 用于同步调用测试工具并解析 JSON"""
    return json.loads(_find_tool(tools, name).invoke(args))


def _write_all_domains(tools: list) -> None:
    """2026-08-11 用于写入全部七个领域"""
    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_character_observations", _write_remaining_args()["character_observations"])
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])


def test_schema_rejects_deleted_contract_fields() -> None:
    """2026-08-11 用于验证输入模型对已删除字段使用 extra=forbid 明确拒绝"""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EntityInput.model_validate(
            {
                "name": "顾霜",
                "entity_type": "character",
                "confidence": "high",
                "reason": "出现",
                "ref": "character_1",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EntityInput.model_validate(
            {
                "name": "顾霜",
                "entity_type": "character",
                "existing_entity_id": 42,
                "mentions": [{"chunk_id": 10, "start": 0, "end": 2, "text": "顾霜"}],
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DialogueInput.model_validate(
            {
                "candidate_index": 1,
                "verdict": "dialogue",
                "is_dialogue": True,
                "description": "喝止",
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
                "relation_id": "relation-1",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EventInput.model_validate(
            {
                "description": "进入山门",
                "event_type": "进入",
                "location": "山门",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ForeshadowingInput.model_validate(
            {
                "description": "伏笔",
                "confidence": "high",
                "setup_kind": "其他",
                "setup_summary": "伏笔",
                "is_new_setup": True,
            }
        )


def test_schema_rejects_non_closed_enums() -> None:
    """2026-08-11 用于验证所有保留分类字段只接受中央闭合枚举"""
    with pytest.raises(ValidationError):
        EntityInput.model_validate(
            {"name": "顾霜", "entity_type": "object"}
        )
    with pytest.raises(ValidationError):
        RelationInput.model_validate(
            {
                "from_entity": "顾霜",
                "to_entity": "山门",
                "relation_type": "归属",
            }
        )
    with pytest.raises(ValidationError):
        DialogueInput.model_validate(
            {
                "candidate_index": 1,
                "verdict": "unknown",
                "speaker": None,
                "tone": None,
            }
        )
    with pytest.raises(ValidationError):
        DialogueInput.model_validate(
            {
                "candidate_index": 1,
                "verdict": "dialogue",
                "speaker": None,
                "tone": "呵斥",
            }
        )


def test_dialogue_verdict_contract_rules() -> None:
    """2026-08-11 用于验证 not_dialogue 时 speaker/tone 必须为空"""
    with pytest.raises(ValidationError, match="speaker/tone 必须为 null"):
        DialogueInput.model_validate(
            {
                "candidate_index": 1,
                "verdict": "not_dialogue",
                "speaker": "顾霜",
                "tone": None,
            }
        )
    with pytest.raises(ValidationError, match="speaker/tone 必须为 null"):
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
    with pytest.raises(ValidationError, match="键不能为空"):
        EntityInput.model_validate(
            {
                "name": "顾霜",
                "entity_type": "character",
                "attributes": {"  ": "值"},
            }
        )


def test_entity_tags_limited_to_three_and_five_chars() -> None:
    """2026-08-08 用于验证实体标签最多 3 个且每个最多 5 个字"""
    with pytest.raises(ValidationError, match="最多 3 个标签"):
        EntityInput.model_validate(
            {
                "name": "玄剑",
                "entity_type": "item",
                "tags": ["法宝", "灵器", "神兵", "古剑"],
            }
        )
    with pytest.raises(ValidationError, match="每个标签最多 5 个字"):
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


def test_multiple_write_tools_same_round_then_complete_chunk() -> None:
    """2026-08-11 用于验证一个回复可调用多个 write 工具并完整冻结 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools)

    chunk = ledger.complete_active_chunk()
    assert chunk.chunk_id == 10

    assert ledger.completed_chunks[0].chunk_id == 10
    assert ledger.phase == "continuity_open"
    dialogue = chunk.dialogues[0]
    assert dialogue.candidate_key.startswith("dlg_")
    assert dialogue.content == "住手"
    assert "“住手”回荡"[dialogue.start : dialogue.end] == "住手"
    assert dialogue.is_inner_monologue is False


def test_write_receipts_carry_fixed_compact_shape() -> None:
    """2026-08-10 用于验证成功 write 的模型回执固定压缩为 accepted/tool/domain/revision/item_count/state_digest"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _call(tools, "write_entities", _write_entities_args())

    assert set(receipt) == {
        "accepted",
        "tool",
        "domain",
        "revision",
        "item_count",
        "state_digest",
    }
    assert receipt == {
        "accepted": True,
        "tool": "write_entities",
        "domain": "entities",
        "revision": 1,
        "item_count": 1,
        "state_digest": receipt["state_digest"],
    }
    assert receipt["state_digest"].startswith("sha256:")
    metrics_receipt = _call(tools, "write_metrics", _write_metrics_args())
    assert metrics_receipt["item_count"] == 1
    assert metrics_receipt["tool"] == "write_metrics"


def test_failed_write_keeps_other_domain_receipts_and_revisions() -> None:
    """2026-08-11 用于验证单个领域写入失败后其他成功领域的 receipt 与修订保留"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    invalid = _write_remaining_args()["character_observations"]
    invalid["items"][0]["character"] = "山门"
    with pytest.raises(ValueError, match="未在当前 chunk 的 write_entities 中声明"):
        _call(tools, "write_character_observations", invalid)

    assert "metrics" in ledger.domain_receipts
    assert "entities" in ledger.domain_receipts
    assert "character_observations" not in ledger.domain_receipts
    assert ledger.domain_revision_counts["metrics"] == 1
    assert ledger.domain_revision_counts["entities"] == 1
    assert "character_observations" not in ledger.domain_revision_counts
    assert ledger.ready_chunk is None


def test_replacement_write_rebuilds_ready_chunk_revision() -> None:
    """2026-08-11 用于验证七领域齐全后重写领域会重建 ready_chunk 且 complete 冻结新值"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools)
    assert ledger.ready_chunk is not None

    replaced = _write_remaining_args()["events"]
    replaced["items"][0]["description"] = "新事件描述"
    _call(tools, "write_events", replaced)
    assert ledger.ready_chunk.events[0].description == "新事件描述"

    ledger.complete_active_chunk()
    assert ledger.completed_chunks[0].events[0].description == "新事件描述"


def test_domain_reinvocation_completely_replaces_payload() -> None:
    """2026-08-11 用于验证领域重新调用完整替换旧暂存值"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entities", _write_entities_args())
    first = _write_remaining_args()["events"]
    first["items"] = [
        {
            "description": "旧事件",
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


def test_complete_chunk_requires_all_seven_domains() -> None:
    """2026-08-11 用于验证未调用领域无法完成 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    with pytest.raises(ValueError, match="尚未写入全部领域"):
        ledger.complete_active_chunk()
    assert ledger.completed_chunks == []
    assert ledger.phase == "chunk_open"


def test_write_dialogues_requires_full_candidate_coverage() -> None:
    """2026-08-11 用于验证对话候选缺失或重复在 write_dialogues 时即失败"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_character_observations", _write_remaining_args()["character_observations"])
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])

    with pytest.raises(ValueError, match="必须完整覆盖全部候选"):
        _call(tools, "write_dialogues", {"items": []})
    with pytest.raises(ValueError, match="超出系统候选范围"):
        _call(tools, "write_dialogues", {"items": [
            {"candidate_index": 2, "verdict": "dialogue", "speaker": None, "tone": None},
        ]})
    with pytest.raises(ValueError, match="重复"):
        _call(tools, "write_dialogues", {"items": [
            {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
            {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
        ]})
    with pytest.raises(ValueError, match="超出系统候选范围"):
        _call(tools, "write_dialogues", {"items": [
            {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
            {"candidate_index": 9, "verdict": "dialogue", "speaker": None, "tone": None},
        ]})
    assert "dialogues" not in ledger.domain_receipts


def test_write_dialogues_binds_inner_monologue_verdict() -> None:
    """2026-08-11 用于验证 inner_monologue 判定映射为对话记录独白标记"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_dialogues_args()
    args["items"][0]["verdict"] = "inner_monologue"
    _call(tools, "write_dialogues", args)
    bound = ledger.bound_payloads["dialogues"]
    assert len(bound) == 1
    assert bound[0].is_inner_monologue is True

    args["items"][0]["verdict"] = "not_dialogue"
    _call(tools, "write_dialogues", args)
    assert ledger.bound_payloads["dialogues"] == []


def test_fact_endpoint_validation_moves_to_write_time() -> None:
    """2026-08-11 用于验证事实端点校验前移到对应 write 调用"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    invalid = _write_remaining_args()["character_observations"]
    invalid["items"][0]["character"] = "山门"
    with pytest.raises(ValueError, match="未在当前 chunk 的 write_entities 中声明"):
        _call(tools, "write_character_observations", invalid)
    assert "character_observations" not in ledger.domain_receipts


def test_event_location_participant_role_requires_location_type() -> None:
    """2026-08-11 用于验证事件参与者角色为地点时端点必须是 location 实体"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    args = _write_remaining_args()["events"]
    args["items"][0]["participants"] = [
        {"entity": "顾霜", "role": "地点"}
    ]
    with pytest.raises(ValueError, match="端点类型必须属于"):
        _call(tools, "write_events", args)
    assert "events" not in ledger.domain_receipts


def test_write_entities_requires_prior_search_graph_when_registered_entities_exist() -> None:
    """2026-08-09 用于验证存在已登记实体时未先 search_graph 禁止提交实体目录"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="必须先调用 search_graph"):
        _call(tools, "write_entities", _write_entities_args())
    assert "entities" not in ledger.domain_receipts


def test_write_entities_allowed_after_search_graph() -> None:
    """2026-08-09 用于验证 search_graph 之后可正常提交实体目录"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    _call(tools, "search_graph", {"entities": ["顾霜"]})
    assert ledger.graph_queried is True
    _call(tools, "write_entities", _write_entities_args())


def test_complete_chunk_accepts_registered_entity_endpoint_without_declaration() -> None:
    """2026-08-09 用于验证已登记实体可直接作为事实端点，无需当前 chunk 重复声明"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "伯安": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    _write_all_domains(tools)

    ledger.complete_active_chunk()


def test_complete_chunk_rejects_registered_entity_type_change() -> None:
    """2026-08-09 用于验证已登记实体重新提交时大类必须保持一致（写入时即失败）"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    args = _write_entities_args()
    args["entities"][0]["entity_type"] = "item"
    with pytest.raises(ValueError, match="已登记实体不允许变更大类"):
        _call(tools, "write_entities", args)
    assert "entities" not in ledger.domain_receipts


def test_write_tools_reject_invalid_enum_at_call_time() -> None:
    """2026-08-11 用于验证非法枚举在工具参数校验阶段直接失败"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_metrics_args()
    args["emotional_valence"] = "unknown"
    with pytest.raises(ValidationError):
        _find_tool(tools, "write_metrics").invoke(args)
    assert ledger.domain_receipts == set()


def test_unresolved_speaker_no_longer_auto_creates_case() -> None:
    """2026-08-11 用于验证 speaker=null 的对话不再自动生成案例，案例只能由 push_case 登记"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools)
    ledger.complete_active_chunk()

    assert ledger.pushed_cases == []


def test_write_foreshadowings_only_accepts_description_and_confidence() -> None:
    """2026-08-11 用于验证伏笔合同只含 description 与 confidence"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = {"items": [{"description": "玉戒尺异常发光", "confidence": "high"}]}
    response = _call(tools, "write_foreshadowings", args)
    assert response["accepted"] is True
    stored = ledger.domain_payloads["foreshadowings"]
    assert stored[0].description == "玉戒尺异常发光"
    assert stored[0].confidence == "high"
    with pytest.raises(ValidationError):
        _find_tool(tools, "write_foreshadowings").invoke(
            {"items": [{"description": "伏笔", "setup_kind": "其他"}]}
        )


def test_future_disabled_rejects_future_search_and_read() -> None:
    """2026-08-07 用于验证关闭开关时 future 搜索与读取都不可用"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    payload = json.loads(
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))
    )
    assert payload[0]["result_number"] == 1
    ledger.set_phase("continuity_open")
    with pytest.raises(AnnotationAuthorizationError, match="allow_future_context=false"):
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))


def test_search_text_numbering_and_read_authorization() -> None:
    """2026-08-07 用于验证运行内编号读取真实原文且编号不可复用"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=True)
    ledger.set_phase("continuity_open")
    tools = _tools(service, ledger)

    payload = json.loads(
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))
    )
    assert payload[0]["result_number"] == 1
    assert "chunk_id" not in payload[0]
    read_receipt = json.loads(
        _find_tool(tools, "read_text").invoke({"result_number": 1})
    )
    assert read_receipt == {"content": "顾霜喝道"}
    assert service.reads == [20]

    ledger.set_phase("chunk_open")
    with pytest.raises(AnnotationAuthorizationError, match="不属于当前"):
        _find_tool(tools, "read_text").invoke({"result_number": 1})
    with pytest.raises(AnnotationAuthorizationError, match="未由本轮 search_text 返回"):
        _find_tool(tools, "read_text").invoke({"result_number": 99})


def test_search_pool_uses_case_numbers_and_resolve_dialogue_case() -> None:
    """2026-08-11 用于验证临时 case_number 解决对话案例且不可重复"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert [item["result_kind"] for item in view["results"]] == ["case"]
    case_number = view["results"][0]["case_number"]
    response = json.loads(
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": "顾霜", "reason": "后文点明"}
        )
    )
    assert response["accepted"] is True
    assert response["action"] == "dialogue"
    assert ledger.resolved_cases[0].case_id == "case-1"
    assert ledger.resolved_cases[0].action == "dialogue"
    assert ledger.resolved_cases[0].speaker == "顾霜"
    assert ledger.resolved_cases[0].target_key == "target-1"

    with pytest.raises(AnnotationInputError, match="已经解决"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": "顾霜", "reason": "重复"}
        )
    hidden = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert hidden["results"] == []


def test_resolve_case_rejects_unknown_case_number() -> None:
    """2026-08-11 用于验证未登记的 case_number 直接拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="未由初始候选或 search_pool 返回"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": 999, "speaker": "顾霜", "reason": "猜测"}
        )


def test_resolve_dialogue_case_requires_declared_character_speaker() -> None:
    """2026-08-11 用于验证对话解决 speaker 必须是已登记或本章声明的人物"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    with pytest.raises(ValueError, match="resolve_dialogue_case.speaker 未在当前"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": "无名客", "reason": "猜测"}
        )
    response = json.loads(
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": "顾霜", "reason": "后文点明"}
        )
    )
    assert response["accepted"] is True


def test_close_case_only_closes_alias_case() -> None:
    """2026-08-11 用于验证确认非同一人物用 close_case 只关闭案例不产生变化"""
    service = _AliasQueryService()
    ledger = _ledger()
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    response = json.loads(
        _find_tool(tools, "close_case").invoke(
            {"case_number": case_number, "reason": "夫妻关系非同一人物"}
        )
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[0].case_id == "alias-1"
    assert ledger.resolved_cases[0].action == "close"

    with pytest.raises(AnnotationInputError, match="已经解决"):
        _find_tool(tools, "close_case").invoke(
            {"case_number": case_number, "reason": "重复"}
        )


def test_resolve_fact_case_asserts_same_character_relation() -> None:
    """2026-08-11 用于验证 entity_alias 案例可用 resolve_fact_case 建同一人物关系"""
    service = _AliasQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    response = json.loads(
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": "顾霜",
                "to_entity": "顾老",
                "relation_type": "同一人物",
                "change_kind": "assert",
                "reason": "姓名指向同一人",
            }
        )
    )
    assert response["accepted"] is True
    resolved = ledger.resolved_cases[0]
    assert resolved.action == "fact"
    assert resolved.relation_type == "同一人物"
    assert resolved.change_kind == "assert"


def test_resolve_fact_case_rejects_unregistered_entity() -> None:
    """2026-08-11 用于验证 fact 解决端点必须已登记或本章声明"""
    service = _AliasQueryService()
    ledger = _ledger()
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    with pytest.raises(ValueError, match="resolve_fact_case.from_entity 未在当前"):
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": "顾霜",
                "to_entity": "顾老",
                "relation_type": "同一人物",
                "change_kind": "assert",
                "reason": "指向同一人",
            }
        )


def test_push_case_accepts_arbitrary_type_and_dialogue_id() -> None:
    """2026-08-11 用于验证 push_case 类型放开且对话疑点携带 dialogue_id"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    dialogue_id = ledger.dialogue_candidates[0].candidate_key
    response = json.loads(
        _find_tool(tools, "push_case").invoke(
            {
                "description": "神秘仪式疑点",
                "keys": ["住手", "仪式"],
                "type": "神秘仪式",
                "dialogue_id": dialogue_id,
            }
        )
    )
    assert response["accepted"] is True
    assert response["target_key"]
    pushed = ledger.pushed_cases[0]
    assert pushed.type == "神秘仪式"
    assert pushed.target_ref["kind"] == "神秘仪式"
    assert pushed.target_ref["dialogue_id"] == dialogue_id
    assert pushed.target_ref["chunk_id"] == 10


def test_push_case_rejects_unknown_dialogue_or_thread_id() -> None:
    """2026-08-11 用于验证 push_case 校验 dialogue_id 与 setup_id"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationInputError, match="不是当前 chunk 的对话候选 id"):
        _find_tool(tools, "push_case").invoke(
            {
                "description": "对话疑点",
                "keys": ["住手"],
                "type": "dialogue_speaker",
                "dialogue_id": "dlg_not_exist",
            }
        )
    with pytest.raises(AnnotationInputError, match="不是当前 run 的活跃伏笔线程"):
        _find_tool(tools, "push_case").invoke(
            {
                "description": "伏笔疑点",
                "keys": ["线索"],
                "type": "foreshadowing_suspect",
                "setup_id": "thread-not-exist",
            }
        )


def test_push_case_rejects_json_fragment_in_description() -> None:
    """2026-08-11 用于验证 JSON 字段痕迹混入 description 被拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationInputError, match="独立参数"):
        _find_tool(tools, "push_case").invoke(
            {
                "description": '{"keys": ["住手"], "type": "疑点"}',
                "keys": ["住手"],
                "type": "疑点",
            }
        )


def test_push_case_accepts_setup_id_and_resolve_foreshadowing_case() -> None:
    """2026-08-11 用于验证伏笔疑点携带 setup_id 且可动作式解决"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    response = json.loads(
        _find_tool(tools, "push_case").invoke(
            {
                "description": "伏笔疑点",
                "keys": ["线索"],
                "type": "foreshadowing_suspect",
                "setup_id": "thread-1",
            }
        )
    )
    assert response["accepted"] is True
    pushed = ledger.pushed_cases[0]
    assert pushed.target_ref["setup_id"] == "thread-1"

    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    case_number = ledger.case_number_by_id["case-1"]
    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "setup_status": "reinforced",
                "reason": "后续章节强化",
            }
        )
    )
    assert resolved["accepted"] is True
    assert ledger.resolved_cases[-1].action == "foreshadowing"
    assert ledger.resolved_cases[-1].setup_status == "reinforced"


def test_search_pool_exposes_thread_id_for_foreshadowing_results() -> None:
    """2026-08-11 用于验证伏笔线程视图携带 id 供 push_case 登记疑点"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "线索"}))
    assert view["results"][0]["result_kind"] == "foreshadowing"
    assert view["results"][0]["id"] == "thread-1"
    assert view["results"][0]["content"]["setup_summary"] == "护佑山门"


def test_write_dialogues_ignores_order_field() -> None:
    """2026-08-09 用于验证模型附带多余字段时仍能通过并按候选序号绑定"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_dialogues_args()
    args["items"][0]["order"] = 1
    response = _call(tools, "write_dialogues", args)
    assert response["accepted"] is True
    stored = ledger.domain_payloads["dialogues"]
    assert stored[0].verdict == "dialogue"
    assert not hasattr(stored[0], "order")


def test_relation_state_present_auto_assert_on_missing_edge() -> None:
    """2026-08-11 用于验证 present 状态在图中无对应边时自动按新建处理"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
    )
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    args = {
        "items": [
            {
                "from_entity": "顾霜",
                "to_entity": "顾老",
                "relation_type": "友情",
            }
        ]
    }
    response = _call(tools, "write_relations", args)
    assert response["accepted"] is True
    assert ledger.graph.relation_exists("顾霜", "顾老", "友情") is True


def test_relation_ended_requires_existing_edge() -> None:
    """2026-08-11 用于验证 ended 状态在图中无对应边时直接拒绝"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
    )
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    args = {
        "items": [
            {
                "from_entity": "顾霜",
                "to_entity": "顾老",
                "relation_type": "友情",
                "state": "ended",
            }
        ]
    }
    with pytest.raises(ValueError, match="关系变化未匹配到已存在活动关系"):
        _call(tools, "write_relations", args)


def test_search_graph_returns_one_hop_neighborhood() -> None:
    """2026-08-09 用于验证图查询返回节点、missing、边和邻居且不暴露内部字段"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        history_relations={("顾老", "顾霜", "同一人物")},
    )
    tools = _tools(service, ledger)

    payload = json.loads(
        _find_tool(tools, "search_graph").invoke(
            {"entities": ["顾霜", "贺老"], "relation_type": None}
        )
    )
    assert payload["matches"][0]["name"] == "顾霜"
    assert payload["missing"] == ["贺老"]
    assert payload["relations"][0]["relation_type"] == "同一人物"
    assert payload["neighbors"][0]["name"] == "顾老"
    assert "entity_id" not in payload["matches"][0]
    assert "relation_id" not in payload["relations"][0]
    assert "facts" not in payload
    assert "paths" not in payload


def test_search_graph_queries_live_fact_graph_without_database() -> None:
    """2026-08-11 用于验证 search_graph 只访问常驻内存图，本章增量立即可见"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        history_entity_tags={"顾霜": ["女主"]},
        history_entity_attributes={"顾霜": {"entity_type": "character", "description": "主角"}},
        history_entity_state={"顾霜": {"status": "active"}},
        history_relations={("顾老", "顾霜", "同一人物")},
        history_relation_attributes={("顾老", "顾霜", "同一人物"): {"support_count": 1}},
    )
    ledger.graph.apply_relation(_graph_relation("顾老", "顾霜", "同一人物", "present"))
    tools = _tools(service, ledger)

    payload = json.loads(
        _find_tool(tools, "search_graph").invoke(
            {"entities": ["顾霜", "铁帅"], "relation_type": None}
        )
    )

    assert [item["name"] for item in payload["matches"]] == ["顾霜"]
    assert payload["missing"] == ["铁帅"]
    assert payload["matches"][0]["tags"] == ["女主"]
    assert payload["matches"][0]["state"]["status"] == "active"
    assert len(payload["relations"]) == 1
    relation = payload["relations"][0]
    assert {relation["from_name"], relation["to_name"]} == {"顾霜", "顾老"}
    assert relation["relation_type"] == "同一人物"
    assert relation["is_active"] is True
    assert relation["attributes"]["support_count"] == 2
    assert [item["name"] for item in payload["neighbors"]] == ["顾老"]


def test_finish_chapter_requires_chunk_frozen_first() -> None:
    """2026-08-07 用于验证 chunk 未冻结时不能 finish_chapter"""
    service = _QueryService()
    ledger = _ledger()
    _tools(service, ledger)

    with pytest.raises(AnnotationProtocolError, match="不允许 finish_chapter"):
        ledger.finish()


def test_finish_chapter_generates_summary_from_chunk_summaries() -> None:
    """2026-08-11 用于验证章节摘要由系统用各 chunk summary 自动生成"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools)
    ledger.complete_active_chunk()
    annotation = ledger.finish()
    assert annotation.chapter_summary == "住手回荡"
    assert annotation.contract_version == "agent-semantic-v1"
