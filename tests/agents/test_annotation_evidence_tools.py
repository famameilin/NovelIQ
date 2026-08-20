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
    CharacterObservationInput,
    ChunkParagraphInfo,
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
        """2026-08-07 用于记录范围并返回原文候选（M6：候选定位到段落）"""
        del limit
        self.text_queries.append((query, range_name))
        return [
            TextSearchResult(
                chapter_id=2,
                paragraph_id=20,
                excerpt="顾霜喝道",
                keyword_score=1.0,
            )
        ]

    def read_text(self, paragraph_id):
        """2026-08-07 用于记录已由文本搜索候选授权的原文段落读取"""
        self.reads.append(paragraph_id)
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


class _ForeignChunkQueryService(_QueryService):
    """2026-08-11 用于提供锚定旧章节 chunk 的活动案例（需先读取授权）"""

    def _case(self) -> CaseSearchResult:
        """2026-08-11 用于构造疑似同一人物但原文在旧章节的案例"""
        return CaseSearchResult(
            id="foreign-1",
            type="entity_alias",
            chunk_id=99,
            keys=["同一人物", "顾霜", "顾老"],
            description="疑似同一人物：顾霜 与 顾老 共享邻居重叠度 50%",
        )

    def fetch_active_case_details(self, case_id):
        """2026-08-11 用于返回锚定旧 chunk 的 alias 案例稳定目标"""
        if case_id != "foreign-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="target-foreign-1",
            target_ref={"kind": "alias", "name_a": "顾霜", "name_b": "顾老", "chunk_id": 99},
        )

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-11 用于返回旧章段落原文候选"""
        del limit
        self.text_queries.append((query, range_name))
        return [
            TextSearchResult(
                chapter_id=9,
                paragraph_id=99,
                excerpt="顾霜喝道",
                keyword_score=1.0,
            )
        ]

    def read_text(self, paragraph_id):
        """2026-08-11 用于记录旧章段落原文读取"""
        self.reads.append(paragraph_id)
        return "顾霜喝道"


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


def _ledger(*, allow_future_context: bool = False) -> AnnotationToolLedger:
    """2026-08-07 用于构造带唯一 current 原文和后文开关的工具账本

    2026-08-18：注入 paragraph_info 供事件锚点校验和证据派生使用。
    """
    chunk_text = "\u201c住手\u201d回荡"
    paragraph_info = ChunkParagraphInfo(
        paragraph_ids=[0],
        char_spans=[(0, len(chunk_text))],
        texts=[chunk_text],
    )
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=10,
        current_chunk_text=chunk_text,
        allow_future_context=allow_future_context,
        paragraph_info=paragraph_info,
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
    """2026-08-12 用于构造数组格式对话判断参数 [序号, 三态, 说话人, 语气]"""
    return {"items": [[1, "dialogue", None, None]]}


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
                        {"entity": "顾霜", "role": "主体"}
                    ],
                    "anchor_paragraph_ids": [0],
                    "tree_id": "drink-order",
                    "cause_role": "root",
                }
            ]
        },
        "relations": {"items": []},
        "foreshadowings": {
            "items": [
                {
                    "description": "顾霜的玉戒尺异常发光",
                    "confidence": "high",
                    "setup_event_index": 1,
                }
            ]
        },
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
                "anchor_paragraph_ids": [0],
                "event_type": "进入",
                "location": "山门",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ForeshadowingInput.model_validate(
            {
                "description": "伏笔",
                "confidence": "high",
                "setup_event_index": 1,
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


def test_schema_rejects_tone_words_in_emotion_with_guidance() -> None:
    """2026-08-12 用于验证 tone 中文词写进 emotional_valence 时给出纠正引导"""
    with pytest.raises(ValidationError, match="emotional_valence 不接受 喜悦"):
        CharacterObservationInput.model_validate(
            {
                "character": "贺伯安",
                "role_function": "主体",
                "action": "打碎瓷瓶后逃窜",
                "emotion": "喜悦",
            }
        )


def test_schema_rejects_event_role_words_in_role_function_with_guidance() -> None:
    """2026-08-12 用于验证事件专属词写进 role_function 时给出纠正引导"""
    with pytest.raises(ValidationError, match="见证者、地点等只用于事件参与者的 role"):
        CharacterObservationInput.model_validate(
            {
                "character": "侯飞白",
                "role_function": "见证者",
                "action": "目睹兽棚化为火海",
                "emotion": "strong_negative",
            }
        )
    with pytest.raises(ValidationError, match="见证者、地点等只用于事件参与者的 role"):
        CharacterObservationInput.model_validate(
            {
                "character": "侯飞白",
                "role_function": "地点",
                "action": "目睹兽棚化为火海",
                "emotion": "strong_negative",
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
    assert ledger.phase == "completed"
    dialogue = chunk.dialogues[0]
    assert dialogue.candidate_key.startswith("dlg_")
    assert dialogue.content == "住手"
    assert "\u201c住手\u201d回荡"[dialogue.start : dialogue.end] == "住手"
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
        "item_count",
        "state_digest",
    }
    assert receipt == {
        "accepted": True,
        "tool": "write_entities",
        "domain": "entities",
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
    assert [record["domain"] for record in ledger.write_records] == ["metrics", "entities"]
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
            "anchor_paragraph_ids": [0],
            "tree_id": "drink-order",
            "cause_role": "root",
        }
    ]
    _call(tools, "write_events", first)
    second = _write_remaining_args()["events"]
    _call(tools, "write_events", second)

    stored = ledger.domain_payloads["events"]
    assert len(stored) == 1
    assert stored[0].description == "顾霜喝止众人"
    assert len([item for item in ledger.write_records if item["domain"] == "events"]) == 2


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


def test_write_dialogues_defaults_missing_candidates_to_not_dialogue() -> None:
    """2026-08-12 用于验证缺失候选软覆盖为 not_dialogue，回执列出默认处理的序号"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_character_observations", _write_remaining_args()["character_observations"])
    _call(tools, "write_events", _write_remaining_args()["events"])
    _call(tools, "write_relations", _write_remaining_args()["relations"])
    _call(tools, "write_foreshadowings", _write_remaining_args()["foreshadowings"])

    # 空提交不再拒绝：候选 1 默认 not_dialogue，回执列出
    response = _call(tools, "write_dialogues", {"items": []})
    assert response["accepted"] is True
    assert response["defaulted_not_dialogue"] == [1]
    assert ledger.bound_payloads["dialogues"] == []

    # 补交后缺失列表为空
    response = _call(tools, "write_dialogues", {"items": [[1, "dialogue", None, None]]})
    assert response["defaulted_not_dialogue"] == []
    assert len(ledger.bound_payloads["dialogues"]) == 1

    # 重复仍拒绝
    with pytest.raises(ValueError, match="重复"):
        _call(tools, "write_dialogues", {"items": [
            [1, "dialogue", None, None],
            [1, "dialogue", None, None],
        ]})
    # 越界仍拒绝
    with pytest.raises(ValueError, match="超出系统候选范围"):
        _call(tools, "write_dialogues", {"items": [[9, "dialogue", None, None]]})


def test_write_dialogues_binds_inner_monologue_verdict() -> None:
    """2026-08-11 用于验证 inner_monologue 判定映射为对话记录独白标记"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = _write_dialogues_args()
    args["items"][0][1] = "inner_monologue"
    _call(tools, "write_dialogues", args)
    bound = ledger.bound_payloads["dialogues"]
    assert len(bound) == 1
    assert bound[0].is_inner_monologue is True

    args["items"][0][1] = "not_dialogue"
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


def test_write_foreshadowings_only_accepts_description_confidence_and_setup_event_index() -> None:
    """2026-08-18 用于验证伏笔合同含 description、confidence 与 setup_event_index"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    args = {
        "items": [
            {"description": "玉戒尺异常发光", "confidence": "high", "setup_event_index": 1}
        ]
    }
    # 2026-08-18 协议顺序：事件参与者须先在 write_entities 声明，
    # 伏笔的 setup_event_index 绑定事件，必须在 write_events 成功后调用
    entities_response = _call(tools, "write_entities", _write_entities_args())
    assert entities_response["accepted"] is True
    events_response = _call(tools, "write_events", _write_remaining_args()["events"])
    assert events_response["accepted"] is True
    response = _call(tools, "write_foreshadowings", args)
    assert response["accepted"] is True
    stored = ledger.domain_payloads["foreshadowings"]
    assert stored[0].description == "玉戒尺异常发光"
    assert stored[0].confidence == "high"
    assert stored[0].setup_event_index == 1
    with pytest.raises(ValidationError):
        _find_tool(tools, "write_foreshadowings").invoke(
            {"items": [{"description": "伏笔", "setup_kind": "其他"}]}
        )


def test_future_disabled_limits_search_to_previous() -> None:
    """2026-08-14 用于验证关闭开关时 search_text 仅检索前文范围"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    payload = json.loads(
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))
    )
    assert payload[0]["result_number"] == 1
    assert service.text_queries == [("顾霜", "previous")]


def test_future_enabled_searches_all_and_read_permission_follows_config() -> None:
    """2026-08-14 用于验证开启开关时 search_text 检索前后文，read_text 授权随配置收放"""
    import asyncio

    service = _QueryService()
    ledger = _ledger(allow_future_context=True)
    tools = _tools(service, ledger)

    payload = json.loads(
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))
    )
    assert service.text_queries == [("顾霜", "all")]
    assert payload[0]["result_number"] == 1
    assert "chunk_id" not in payload[0]
    assert "paragraph_id" not in payload[0]
    read_receipt = json.loads(
        _find_tool(tools, "read_text").invoke({"result_number": 1})
    )
    assert read_receipt == {"content": "顾霜喝道"}
    assert service.reads == [20]
    # M6：read 授权实际返回的段落及上下文各 1 段（与查询服务上下文契约对齐）
    assert 20 in ledger.authorized_text_paragraph_ids
    assert 19 in ledger.authorized_text_paragraph_ids
    assert 21 in ledger.authorized_text_paragraph_ids

    # 关闭开关后，已检索的后文结果不再可读（权限随配置收放）
    ledger.allow_future_context = False
    with pytest.raises(AnnotationAuthorizationError, match="超出当前权限范围"):
        _find_tool(tools, "read_text").invoke({"result_number": 1})
    # 未授权的编号依旧被拒
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


def test_resolve_case_authorized_on_initial_display() -> None:
    """2026-08-12 用于验证初始案例展示即授权其源章，无需先 read_text 即可解决"""
    service = _ForeignChunkQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    assert 99 in ledger.authorized_chapter_ids
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["foreign-1"]
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
    assert ledger.resolved_cases[0].case_id == "foreign-1"


def test_resolve_case_allowed_after_read_authorization() -> None:
    """2026-08-11 用于验证读取旧章段落原文后解决案例成功"""
    import asyncio

    service = _ForeignChunkQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    search = json.loads(
        asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"}))
    )
    _find_tool(tools, "read_text").invoke({"result_number": search[0]["result_number"]})
    # 展示授权源章；read 授权实际返回的段落（含上下文）
    assert 99 in ledger.authorized_chapter_ids
    assert 99 in ledger.authorized_text_paragraph_ids
    assert 98 in ledger.authorized_text_paragraph_ids
    assert 100 in ledger.authorized_text_paragraph_ids

    case_number = ledger.case_number_by_id["foreign-1"]
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
    assert ledger.resolved_cases[0].case_id == "foreign-1"


def test_resolve_foreshadowing_case_rejects_foreign_enum_values() -> None:
    """2026-08-12 用于验证伏笔解决字段只接受闭合枚举（避免下游回收预期 KeyError）"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    case_number = ledger.case_number_by_id["case-1"]

    with pytest.raises(ValidationError, match="setup_status"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {"case_number": case_number, "setup_status": "已揭示", "reason": "伏笔回收"}
        )
    with pytest.raises(ValidationError, match="payoff_likelihood"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {"case_number": case_number, "payoff_likelihood": "certain", "reason": "伏笔回收"}
        )
    with pytest.raises(ValidationError, match="strength"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {"case_number": case_number, "strength": "very_high", "reason": "伏笔回收"}
        )
    assert ledger.resolved_cases == []


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


def test_write_dialogues_array_format_with_null_fields() -> None:
    """2026-08-12 用于验证数组格式四元组绑定与 null 字段"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())

    args = _write_dialogues_args()
    args["items"] = [[1, "dialogue", "顾霜", "平静"]]
    _call(tools, "write_dialogues", args)
    stored = ledger.domain_payloads["dialogues"]
    assert stored[0].verdict == "dialogue"
    assert stored[0].speaker == "顾霜"
    assert stored[0].tone == "平静"

    args["items"] = [[1, "dialogue", None, None]]
    _call(tools, "write_dialogues", args)
    stored = ledger.domain_payloads["dialogues"]
    assert stored[0].speaker is None
    assert stored[0].tone is None


def test_relation_state_present_auto_assert_on_missing_edge() -> None:
    """2026-08-11 用于验证三字段边在图中无对应边时自动按新建处理（assert）"""
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
    assert response["relations"][0]["outcome"] == "assert"
    assert ledger.graph.relation_exists("顾霜", "顾老", "友情") is True


def test_relation_existing_edge_skipped_existing_receipt() -> None:
    """2026-08-12 用于验证已存在同一条边的再次提交接受为 skipped_existing（no-op）"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        history_relations={("顾霜", "顾老", "友情")},
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
    assert response["relations"][0]["outcome"] == "skipped_existing"
    assert ledger.graph.relation_exists("顾霜", "顾老", "友情") is True


def test_relation_state_field_rejected_from_contract() -> None:
    """2026-08-12 用于验证关系合同已删除 state 字段（三字段边，extra=forbid 拒绝）"""
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
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
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
    ledger.graph.apply_relation(_graph_relation("顾老", "顾霜", "同一人物"))
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
    assert relation["attributes"]["support_count"] == 1
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
    assert len(annotation.chunks) == 1


def test_resolve_fact_case_rejects_foreign_change_kind() -> None:
    """2026-08-12 用于验证 fact 解决的 change_kind 必须是闭合关系变化枚举（避免下游整章回滚）"""
    service = _AliasQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    with pytest.raises(AnnotationInputError, match="change_kind"):
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": "顾霜",
                "to_entity": "顾老",
                "relation_type": "同一人物",
                "change_kind": "强化关系",
                "reason": "指向同一人",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_dialogue_case_rejects_foreign_tone() -> None:
    """2026-08-12 用于验证对话解决的 tone 必须是闭合语气枚举（避免绕过 write_dialogues 的 Tone 约束）"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    with pytest.raises(AnnotationInputError, match="tone"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {
                "case_number": case_number,
                "speaker": "顾霜",
                "tone": "强化关系",
                "reason": "语气判断",
            }
        )
    assert ledger.resolved_cases == []


def test_resolve_dialogue_case_accepts_closed_tone_enum() -> None:
    """2026-08-12 用于验证闭合枚举内的 tone 正常登记为对话解决结果"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    initial_cases, rotation_ids = service.find_initial_case_candidates("current")
    ledger.register_initial_cases(initial_cases, rotation_ids)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    response = json.loads(
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {
                "case_number": case_number,
                "speaker": "顾霜",
                "tone": "愤怒",
                "reason": "语气判断",
            }
        )
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[0].tone == "愤怒"


def test_text_search_result_accepts_paragraph_id_zero() -> None:
    """2026-08-15 H1 回归：paragraph_id 按设计 §5.1 从 0 起算，全书第一段是合法检索命中"""
    result = TextSearchResult(
        chapter_id=1,
        paragraph_id=0,
        excerpt="开篇第一段",
        keyword_score=2.0,
    )
    assert result.paragraph_id == 0


def test_text_search_result_rejects_negative_paragraph_id() -> None:
    """2026-08-15 H1 回归：负 paragraph_id 仍应被约束拒绝"""
    with pytest.raises(ValidationError):
        TextSearchResult(
            chapter_id=1,
            paragraph_id=-1,
            excerpt="非法段落",
            keyword_score=0.0,
        )
