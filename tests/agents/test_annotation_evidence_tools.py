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
    ChunkParagraphInfo,
    DialogueInput,
    EntityInput,
    EventParticipantInput,
    ForeshadowingSearchResult,
    RelationInput,
    SearchResult,
    TextSearchResult,
    WriteEventInput,
)
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """2026-08-07 用于记录搜索解决与原文工具调用的测试查询服务"""

    def __init__(self, *, text_result_count: int = 1) -> None:
        """2026-08-30 用于初始化原文查询记录"""
        self.text_queries: list[tuple[str, str, int]] = []
        self.text_result_count = text_result_count

    def _case(self) -> CaseSearchResult:
        """2026-08-07 用于构造一个可严格解决的活动案例"""
        return CaseSearchResult(
            id="case-1",
            type="dialogue_speaker",
            chunk_id=10,
            created_chapter=10,
            keys=["住手", "说话人"],
            description="该句住手由谁说出",
        )

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
        """2026-08-07 用于验证已解决案例从后续池搜索隐藏

        2026-09-12 对齐服务合同：case_type 枚举不吃关键词（query 可为 None），
        只返回该类型案例；search_graph 的别名标注按此通道检索 entity_alias。
        """
        del limit
        if "case-1" in hidden_case_ids:
            return SearchResult()
        if case_type is not None:
            matches_type = case_type == "all" or case_type == self._case().type
            return SearchResult(results=[self._case()] if matches_type else [])
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


class _ForeshadowingCaseQueryService(_QueryService):
    """2026-09-04 用于提供已关联伏笔线程（target_ref 含 setup_id）的活动案例"""

    def _case(self) -> CaseSearchResult:
        """2026-09-04 用于构造伏笔疑点案例"""
        return CaseSearchResult(
            id="case-1",
            type="foreshadowing_suspect",
            chunk_id=10,
            keys=["线索"],
            description="伏笔疑点",
        )

    def fetch_active_case_details(self, case_id):
        """2026-09-04 用于返回挂上 thread-1 的伏笔案例稳定目标"""
        if case_id != "case-1":
            return None
        return ActiveCaseDetails(
            **self._case().model_dump(mode="python"),
            target_key="target-foreshadow-1",
            target_ref={"kind": "伏笔疑点", "chunk_id": 10, "setup_id": "thread-1"},
        )


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
        """2026-08-30 用于返回旧章完整原文命中"""
        self.text_queries.append((query, range_name, limit))
        return [
            TextSearchResult(
                chapter_id=9,
                paragraph_ids=[99],
                content="顾霜喝道",
                keyword_score=1.0,
            )
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


def _ledger(*, allow_future_context: bool = False) -> AnnotationToolLedger:
    """2026-08-30 用于构造带唯一当前原文和检索范围配置的工具账本

    2026-08-18：注入 paragraph_info 供事件锚点校验和证据派生使用。
    2026-09-04 单一写面：图域写工具（write_entities/write_relations/resolve_fact_case）
    以常驻 FactGraph 为唯一真相源，故默认注入空图；需要历史实体的用例随后覆盖
    ledger.graph。
    """
    chunk_text = "“住手”回荡"
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
        graph=FactGraph(),
        paragraph_info=paragraph_info,
    )


def _graph_with_entities(names: dict[str, str]) -> FactGraph:
    """2026-08-11 用于构造带历史实体的内存事实图

    2026-09-04 修正：display 名必须传名字本身，此前误把 entity_types 同值传给
    history_entity_names，search_graph 解析出的显示名变成 "character"。
    """
    return FactGraph(
        history_entity_types=dict(names),
        history_entity_names={name: name for name in names},
    )


def _tools(service: _QueryService, ledger: AnnotationToolLedger) -> list:
    """2026-08-07 用于构建绑定查询服务与账本的测试工具"""
    return build_annotation_tools(service, ledger)


def _surface_case(service: _QueryService, ledger: AnnotationToolLedger, *, query: str = "住手") -> int:
    """2026-09-11 案例改检索制：测试内经 search_pool 展示案例取得编号（展示即授权）

    旧合同用例直接调 register_initial_cases 登记初始候选；新合同下编号只能由
    search_pool 回执产生，测试准备阶段也走同一通道。
    """
    view = _call(_tools(service, ledger), "search_pool", {"query": query})
    return int(view["results"][0]["case_number"])


def _tools_with_entities(service: _QueryService, ledger: AnnotationToolLedger) -> list:
    """2026-08-22 用于构建已声明顾霜实体的测试工具（write_event 前置要求）"""
    tools = build_annotation_tools(service, ledger)
    _call(tools, "write_entities", _write_entities_args())
    return tools


def _write_metrics_args() -> dict:
    """2026-08-11 用于构造合法 write_metrics 参数"""
    return {
        "summary": "住手回荡",
        "emotional_valence": 0,
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


def _write_relations_args() -> dict:
    """2026-08-30 用于构造空关系领域的最小合法参数"""
    return {"items": []}


def _entity_number(ledger: AnnotationToolLedger, name: str) -> int:
    """2026-09-11 用于读取实体运行期编号（编号化合同的测试适配口）"""
    assert ledger.graph is not None
    number = ledger.graph.entity_number(name)
    assert number is not None, f"实体未登记: {name}"
    return number


def _character_participant(*, entity: int = 1, action: str = "喝止", emotion: int = -1) -> dict:
    """2026-08-30 用于构造携带人物动态状态的事件参与者（entity 为运行期编号，默认 1=顾霜）"""
    return {
        "entity": entity,
        "role": "主体",
        "narrative_role": "主体",
        "action": action,
        "emotion": emotion,
    }


def _write_event_args(**overrides) -> dict:
    """2026-08-30 用于构造携带人物动态状态的合法 write_event 参数"""
    payload = {
        "description": "顾霜喝止众人",
        "participants": [_character_participant()],
        "finalize_events": True,
    }
    payload.update(overrides)
    return payload


def _call(tools: list, name: str, args: dict):
    """2026-08-07 用于同步调用测试工具并解析 JSON"""
    return json.loads(_find_tool(tools, name).invoke(args))


def _sentence_labels_args(chunk_text: str = "“住手”回荡") -> list[dict]:
    """2026-09-07 用于构造两句自选句情绪标签（满足每章 2 句软下限，无覆盖告警）

    句标签随 write_metrics 的 sentence_labels 参数提交（不设独立工具）；
    整句 + 前缀子串保证两句 span 不同且都能在原文定位。
    """
    return [
        {"sentence": chunk_text, "emotion": -2},
        {"sentence": chunk_text[: max(2, len(chunk_text) // 2)], "emotion": -1},
    ]


def _write_all_domains(tools: list) -> None:
    """2026-08-30 用于通过既有写入工具完成六个内部数据领域（句标签随 metrics 搭车）"""
    _call(tools, "write_metrics", {**_write_metrics_args(), "sentence_labels": _sentence_labels_args()})
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_event", _write_event_args())
    _call(tools, "write_relations", _write_relations_args())


def test_business_write_tool_contract_has_exactly_five_tools() -> None:
    """2026-09-07 用于锁定模型侧仅暴露五个业务写入工具（句标签随 write_metrics 搭车，不新增工具）"""
    tools = _tools(_QueryService(), _ledger())
    business_writes = {
        tool.name
        for tool in tools
        if tool.name.startswith("write_") or tool.name == "write_event"
    }
    assert business_writes == {
        "write_metrics",
        "write_entities",
        "write_dialogues",
        "write_event",
        "write_relations",
    }


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
                "change_kind": "新增",
                "relation_id": "relation-1",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WriteEventInput.model_validate(
            {
                "description": "进入山门",
                "anchor_paragraph_ids": [0],
                "event_type": "进入",
                "location": "山门",
            }
        )


def test_schema_rejects_non_closed_enums() -> None:
    """2026-08-11 用于验证所有保留分类字段只接受中央闭合枚举"""
    with pytest.raises(ValidationError):
        EntityInput.model_validate({"name": "顾霜", "entity_type": "object"})
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
    with pytest.raises(ValidationError, match="emotion 不接受 喜悦"):
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
    assert "narrative_role" in EventParticipantInput.model_fields
    assert "role_function" not in EventParticipantInput.model_fields
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
    with pytest.raises(ValidationError, match="地点、行动者等只用于事件参与者的 role"):
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
    with pytest.raises(ValidationError, match="必须同时提供或同时省略"):
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
    null_patch = EntityInput.model_validate(
        {
            "name": "顾霜",
            "entity_type": "character",
            "attributes": None,
        }
    )
    assert null_patch.attributes == {}
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


def test_five_formal_writes_complete_chunk_in_stage_order() -> None:
    """2026-08-30 用于验证五个正式写入完成六个内部领域并冻结 chunk"""
    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
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
    """2026-08-10 用于验证成功 write 的模型回执固定压缩为 accepted/tool/domain/item_count"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _call(tools, "write_entities", _write_entities_args())

    assert set(receipt) == {
        "accepted",
        "tool",
        "domain",
        "item_count",
        "numbers",
    }
    assert receipt == {
        "accepted": True,
        "tool": "write_entities",
        "domain": "entities",
        "item_count": 1,
        "numbers": [[1, "顾霜"]],
    }
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
    invalid = _write_event_args()
    invalid["participants"][0]["entity"] = 999
    with pytest.raises(ValueError, match="实体编号 999 未登记"):
        _call(tools, "write_event", invalid)

    assert "metrics" in ledger.domain_receipts
    assert "entities" in ledger.domain_receipts
    assert "character_observations" not in ledger.domain_receipts
    assert [record["domain"] for record in ledger.write_records] == ["metrics", "entities"]
    assert ledger.ready_chunk is None


def test_write_event_children_rebuild_ready_chunk() -> None:
    """2026-08-30 用于验证最后一棵事件树完成后重建 ready_chunk 并冻结全部事件"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", {**_write_metrics_args(), "sentence_labels": _sentence_labels_args()})
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_relations", _write_relations_args())
    first_args = _write_event_args(finalize_events=False)
    _call(tools, "write_event", first_args)
    assert ledger.ready_chunk is None
    assert "events" not in ledger.domain_receipts
    assert "character_observations" not in ledger.domain_receipts

    receipt = _call(
        tools,
        "write_event",
        _write_event_args(
            participants=[],
            finalize_events=True,
            children=[
                {
                    "type": "main",
                    "description": "新事件描述",
                    "participants": [_character_participant(action="收势", emotion=0)],
                }
            ],
        ),
    )
    assert receipt["children"][0]["type"] == "main"
    assert receipt["character_observation_count"] == 1
    assert ledger.ready_chunk.events[-1].description == "新事件描述"
    assert [item.action for item in ledger.ready_chunk.character_observations] == ["喝止", "收势"]

    ledger.complete_active_chunk()
    assert ledger.completed_chunks[0].events[-1].description == "新事件描述"


def test_write_event_appends_new_tree_per_call() -> None:
    """2026-08-22 事件契约：事件只增不改——每次 write_event 追加一棵独立树"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entities", _write_entities_args())
    first = _call(tools, "write_event", _write_event_args(finalize_events=False))
    second = _call(
        tools,
        "write_event",
        _write_event_args(
            description="顾霜收势",
            participants=[_character_participant(action="收势", emotion=0)],
            finalize_events=True,
        ),
    )

    assert first["tree_id"] != second["tree_id"]
    stored = ledger.bound_payloads["events"]
    assert len(stored) == 2
    assert stored[-1].description == "顾霜收势"
    assert len([item for item in ledger.write_records if item["domain"] == "events"]) == 2
    assert first["finalized"] is False
    assert second["finalized"] is True
    assert ledger.domain_receipts >= {"events", "character_observations"}


def test_complete_chunk_requires_all_six_domains() -> None:
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
    _call(tools, "write_event", _write_event_args())
    _call(tools, "write_relations", _write_relations_args())

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
        _call(
            tools,
            "write_dialogues",
            {
                "items": [
                    [1, "dialogue", None, None],
                    [1, "dialogue", None, None],
                ]
            },
        )
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
    """2026-08-30 用于验证非人物事件参与者不得携带人物动态状态"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(
        tools,
        "write_entities",
        {"entities": [{"name": "山门", "entity_type": "location"}]},
    )
    # 山门是本用例唯一登记实体，运行期编号为 1
    invalid = _write_event_args(
        participants=[
            {
                "entity": 1,
                "role": "地点",
                "narrative_role": "主体",
                "action": "震动",
                "emotion": 0,
            }
        ]
    )
    with pytest.raises(ValueError, match="不是 character"):
        _call(tools, "write_event", invalid)
    assert "character_observations" not in ledger.domain_receipts


def test_event_location_participant_role_requires_location_type() -> None:
    """2026-08-11 用于验证事件参与者角色为地点时端点必须是 location 实体"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())
    args = _write_event_args(participants=[{"entity": 1, "role": "地点"}])
    with pytest.raises(ValueError, match="地点角色端点必须是 location"):
        _call(tools, "write_event", args)
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


def test_write_event_isforeshadowing_binds_setup_node() -> None:
    """2026-08-22 事件契约：isforeshadowing=true 自动生成伏笔绑定并拒绝多余字段"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    entities_response = _call(tools, "write_entities", _write_entities_args())
    assert entities_response["accepted"] is True
    response = _call(
        tools,
        "write_event",
        _write_event_args(
            isforeshadowing=True,
            setup_kind="悬念",
            expected_payoff_family="身份揭露",
            payoff_likelihood="medium",
        ),
    )
    assert response["accepted"] is True
    stored = ledger.bound_payloads["foreshadowings"]
    assert stored[0].description == "顾霜喝止众人"
    assert stored[0].confidence == "medium"
    assert stored[0].setup_node_id == response["root_node_id"]
    assert stored[0].setup_kind == "悬念"
    assert stored[0].expected_payoff_family == "身份揭露"
    assert stored[0].payoff_likelihood == "medium"
    with pytest.raises(ValidationError):
        WriteEventInput.model_validate(
            {"description": "伏笔", "isforeshadowing": True, "setup_kind": "其他"}
        )


def test_search_text_returns_bounded_content_and_authorizes_exact_paragraphs() -> None:
    """2026-08-30 用于验证单次文本查询限制正文并即时登记精确段落授权"""
    import asyncio

    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    payload = json.loads(asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"})))
    assert service.text_queries == [("顾霜", "previous", 8)]
    assert len(payload) == 1
    assert len(payload[0]["content"]) == 2000
    assert payload[0]["truncated"] is True
    assert "paragraph_id" not in payload[0]
    assert "paragraph_ids" not in payload[0]
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

    assert service.text_queries == [("顾霜", "all", 8)]


def test_search_pool_uses_case_numbers_and_resolve_dialogue_case() -> None:
    """2026-08-11 用于验证临时 case_number 解决对话案例且不可重复"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert [item["result_kind"] for item in view["results"]] == ["case"]
    case_number = view["results"][0]["case_number"]
    response = json.loads(
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": 1, "reason": "后文点明"}
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
            {"case_number": case_number, "speaker": 1, "reason": "重复"}
        )
    hidden = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert hidden["results"] == []


def test_resolve_case_rejects_unknown_case_number() -> None:
    """2026-08-11 用于验证未登记的 case_number 直接拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="未由 search_pool 返回: 999"):
        _find_tool(tools, "resolve_dialogue_case").invoke({"case_number": 999, "speaker": 1, "reason": "猜测"})


def test_resolve_dialogue_case_requires_declared_character_speaker() -> None:
    """2026-08-11 用于验证对话解决 speaker 必须是已登记或本章声明的人物"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    with pytest.raises(ValueError, match="resolve_dialogue_case.speaker 实体编号 987 未登记"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": 987, "reason": "猜测"}
        )
    response = json.loads(
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": 1, "reason": "后文点明"}
        )
    )
    assert response["accepted"] is True


def test_close_case_only_closes_alias_case() -> None:
    """2026-08-11 用于验证确认非同一人物用 close_case 只关闭案例不产生变化"""
    service = _AliasQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    response = json.loads(
        _find_tool(tools, "close_case").invoke({"case_number": case_number, "reason": "夫妻关系非同一人物"})
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[0].case_id == "alias-1"
    assert ledger.resolved_cases[0].action == "close"

    with pytest.raises(AnnotationInputError, match="已经解决"):
        _find_tool(tools, "close_case").invoke({"case_number": case_number, "reason": "重复"})


def test_resolve_fact_case_asserts_same_character_relation() -> None:
    """2026-08-11 用于验证 entity_alias 案例可用 resolve_fact_case 建同一人物关系"""
    service = _AliasQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    response = json.loads(
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "同一人物",
                "change_kind": "新增",
                "reason": "姓名指向同一人",
            }
        )
    )
    assert response["accepted"] is True
    # 2026-09-04 单一写面：fact 裁决进 FactGraph 操作日志与终态，不再进 resolved_cases
    assert ledger.resolved_cases == []
    assert ledger.graph.relation_exists("顾霜", "顾老", "同一人物") is True
    change_op = ledger.graph.relation_change_ops[0]
    assert change_op["case_id"] == "alias-1"
    assert change_op["relation_type"] == "同一人物"
    assert change_op["change_kind"] == "assert"


def test_resolve_fact_case_break_hides_edge_from_search_graph() -> None:
    """2026-09-04 第4章死锁回归：break 裁决后内存图同步解除，search_graph 不得再显示该边

    此前 resolve_fact_case 只写 ledger.resolved_cases、不动 FactGraph，模型"解除成功"
    的回执后 search_graph 仍返回同一条边，导致修复-验证循环打满 15 轮上限。
    """
    service = _AliasQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph.apply_relation(_graph_relation("顾霜", "顾老", "同一人物"))
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    # 先确认边在图中可见
    before = json.loads(
        _find_tool(tools, "search_graph").invoke({"entities": ["顾霜", "顾老"], "relation_type": None})
    )
    assert len(before["relations"]) == 1

    case_number = ledger.case_number_by_id["alias-1"]
    response = json.loads(
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "同一人物",
                "change_kind": "解除",
                "reason": "两人并非同一人物，边为误判",
            }
        )
    )
    assert response["accepted"] is True

    after = json.loads(
        _find_tool(tools, "search_graph").invoke({"entities": ["顾霜", "顾老"], "relation_type": None})
    )
    assert after["relations"] == []
    assert ledger.graph.relation_exists("顾霜", "顾老", "同一人物") is False
    change_op = ledger.graph.relation_change_ops[0]
    assert change_op["change_kind"] == "break"
    assert change_op["case_id"] == "alias-1"


def test_resolve_fact_case_rejects_unregistered_entity() -> None:
    """2026-08-11 用于验证 fact 解决端点必须已登记或本章声明"""
    service = _AliasQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    with pytest.raises(ValueError, match="resolve_fact_case.from_entity 实体编号 987 未登记"):
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 987,
                "to_entity": 2,
                "relation_type": "同一人物",
                "change_kind": "新增",
                "reason": "指向同一人",
            }
        )


def test_resolve_case_authorized_on_initial_display() -> None:
    """2026-08-30 用于验证初始案例展示即授权其源章无需额外原文工具"""
    service = _ForeignChunkQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    assert 99 in ledger.authorized_chapter_ids
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["foreign-1"]
    response = json.loads(
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "同一人物",
                "change_kind": "新增",
                "reason": "姓名指向同一人",
            }
        )
    )
    assert response["accepted"] is True
    # 2026-09-04 单一写面：fact 裁决只进 FactGraph 操作日志，不再进 resolved_cases
    assert ledger.resolved_cases == []
    assert ledger.graph.relation_change_ops[0]["case_id"] == "foreign-1"


def test_resolve_case_allowed_after_text_search_authorization() -> None:
    """2026-08-30 用于验证检索旧章正文时即时授权精确段落"""
    import asyncio

    service = _ForeignChunkQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    search = json.loads(asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"})))
    assert search[0]["content"] == "顾霜喝道"
    # 展示授权源章；search_text 即时登记真实 SQL 命中段落
    assert 99 in ledger.authorized_chapter_ids
    assert 99 in ledger.authorized_text_paragraph_ids

    case_number = ledger.case_number_by_id["foreign-1"]
    response = json.loads(
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "同一人物",
                "change_kind": "新增",
                "reason": "姓名指向同一人",
            }
        )
    )
    assert response["accepted"] is True
    # 2026-09-04 单一写面：fact 裁决只进 FactGraph 操作日志，不再进 resolved_cases
    assert ledger.resolved_cases == []
    assert ledger.graph.relation_change_ops[0]["case_id"] == "foreign-1"


def test_resolve_foreshadowing_case_rejects_foreign_enum_values() -> None:
    """2026-08-12 用于验证伏笔解决字段只接受闭合枚举（避免下游回收预期 KeyError）"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _surface_case(service, ledger)
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


def test_push_case_accepts_setup_id_and_resolve_foreshadowing_case() -> None:
    """2026-08-11 用于验证伏笔疑点携带 setup_id 且可动作式解决"""
    service = _ForeshadowingCaseQueryService()
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

    _surface_case(service, ledger)
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


def test_search_pool_requires_query_or_case_type() -> None:
    """2026-09-11 案例改检索制：query 与 case_type 至少提供一个，双空直接拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationInputError, match="至少提供一个"):
        _find_tool(tools, "search_pool").invoke({})


def test_search_pool_case_view_carries_created_chapter_and_pool_summary() -> None:
    """2026-09-11 案例回执携带 created_chapter 与池内规模，供模型判断案例新旧与剩余量

    池内时间轴只剩章节序号（案例不再注入），且回执必须自描述还有多少未展示案例，
    否则模型无法意识到检索是不完整的。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert view["results"][0]["created_chapter"] == 10
    assert view["pool"] == {"active_total": 0, "by_type": {}}
    assert view["truncated"] is False
    assert "hint" not in view


def test_search_pool_empty_keyword_result_returns_enumeration_hint() -> None:
    """2026-09-11 空结果回执带引导：报出关键词、池内类型分布与枚举写法

    检索制的失败模式是"搜不到就放弃"；把零结果变成下一步动作是设计的一部分。
    """

    class _EmptyPoolService(_QueryService):
        def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
            del hidden_case_ids, case_type, limit
            from src.agents.annotation.schema import CasePoolSummary

            return SearchResult(
                results=[],
                pool=CasePoolSummary(active_total=7, by_type={"entity_alias": 5, "伏笔疑点": 2}),
            )

    service = _EmptyPoolService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "不存在的词"}))
    assert view["results"] == []
    assert "不存在的词" in view["hint"]
    assert "case_type" in view["hint"]
    assert "all" in view["hint"]
    # 未知 case_type 名时提示直接给出池内真实类型名（避免模型继续猜标签）
    assert "entity_alias" in view["hint"]
    assert "伏笔疑点" in view["hint"]
    assert view["pool"]["active_total"] == 7
    assert view["pool"]["by_type"] == {"entity_alias": 5, "伏笔疑点": 2}


def test_search_pool_case_type_enumeration_receipt() -> None:
    """2026-09-11 case_type 枚举回执：不依赖关键词，案例仍带编号且登记搜索日志"""

    class _EnumeratingService(_QueryService):
        def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50):
            del hidden_case_ids, limit
            from src.agents.annotation.schema import CasePoolSummary

            assert query is None
            return SearchResult(
                results=[self._alias_case()],
                pool=CasePoolSummary(active_total=1, by_type={"entity_alias": 1}),
                truncated=case_type == "entity_alias",
            )

        def _alias_case(self) -> CaseSearchResult:
            return CaseSearchResult(
                id="alias-1",
                type="entity_alias",
                chunk_id=3,
                created_chapter=3,
                keys=["同一人物", "顾霜", "顾老"],
                description="疑似同一人物：顾霜 与 顾老",
            )

    service = _EnumeratingService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"case_type": "entity_alias"}))
    assert view["results"][0]["case_number"] == 1
    assert view["results"][0]["type"] == "entity_alias"
    assert view["results"][0]["created_chapter"] == 3
    assert view["truncated"] is True
    assert ledger.search_log[-1]["case_type"] == "entity_alias"
    assert ledger.search_log[-1]["query"] is None
    # 枚举展示同样授权源章（案例展示即授权）
    assert ledger.authorized_chapter_ids == {3}


def test_case_number_from_pool_requires_search_surfacing() -> None:
    """2026-09-11 授权链收紧：池中存在案例但未经 search_pool 展示时编号不可用

    检索制下案例不再注入，编号只能由 search_pool 回执产生；模型若凭空使用编号，
    拒绝信息必须指回检索通道（而不是旧合同的"初始候选"）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    assert ledger.case_number_registry == {}
    with pytest.raises(AnnotationAuthorizationError, match="未由 search_pool 返回: 1"):
        _find_tool(tools, "close_case").invoke({"case_number": 1, "reason": "凭空引用"})


def test_write_dialogues_array_format_with_null_fields() -> None:
    """2026-08-12 用于验证数组格式四元组绑定与 null 字段"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())

    args = _write_dialogues_args()
    args["items"] = [[1, "dialogue", 1, "平静"]]
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
                "from_entity": 1,
                "to_entity": 2,
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
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "友情",
            }
        ]
    }
    response = _call(tools, "write_relations", args)
    assert response["accepted"] is True
    assert response["relations"][0]["outcome"] == "skipped_existing"
    assert ledger.graph.relation_exists("顾霜", "顾老", "友情") is True


def test_relation_alias_resolved_to_same_entity_skipped_self_loop() -> None:
    """2026-09-10 用于验证解析后两端同实体的边跳过不入图

    "同一人物"边解析后塌环（含同批双向重申、跨章重申、传递归并）= 归并已成立，
    按合同接受为 skipped_existing；普通关系类型塌成自环才是退化输入，标
    skipped_self_loop。照常入图都会在持久化插入 from_entity_id=to_entity_id
    自环行，违反 ck_graph_relations_distinct_endpoints 炸掉完成事务
    （run a83fae3d 第9章实锤：同批双向重申的第二条经 resolve_name 键变形
    逃逸了 existing 去重）。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"猴子": "character", "侯飞白": "character"},
        history_entity_names={"猴子": "猴子", "侯飞白": "侯飞白"},
        history_relations={("猴子", "侯飞白", "同一人物")},
    )
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    same_character_args = {
        "items": [
            {
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "同一人物",
            }
        ]
    }
    response = _call(tools, "write_relations", same_character_args)
    assert response["accepted"] is True
    assert response["relations"][0]["outcome"] == "skipped_existing"
    assert response["relations"][0]["from"] == response["relations"][0]["to"]

    ordinary_args = {
        "items": [
            {
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "友情",
            }
        ]
    }
    response = _call(tools, "write_relations", ordinary_args)
    assert response["accepted"] is True
    assert response["relations"][0]["outcome"] == "skipped_self_loop"

    # 退化边不入操作日志（持久化重放源），图中也不得出现自环键
    assert ledger.graph.relation_assert_ops == []
    assert not any(
        from_key == to_key
        for from_key, to_key, _relation_type in ledger.graph.active_relations
    )


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
                "from_entity": 1,
                "to_entity": 2,
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
        _find_tool(tools, "search_graph").invoke({"entities": ["顾霜", "贺老"], "relation_type": None})
    )
    assert payload["matches"][0]["name"] == "顾霜"
    assert isinstance(payload["matches"][0]["n"], int)
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
        _find_tool(tools, "search_graph").invoke({"entities": ["顾霜", "铁帅"], "relation_type": None})
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
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    # 2026-09-11 change_kind 已中文化，契约枚举在参数校验层直接拒绝非法值
    with pytest.raises(ValidationError, match="change_kind"):
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 1,
                "to_entity": 2,
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
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    with pytest.raises(AnnotationInputError, match="tone"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {
                "case_number": case_number,
                "speaker": 1,
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
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    response = json.loads(
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {
                "case_number": case_number,
                "speaker": 1,
                "tone": "愤怒",
                "reason": "语气判断",
            }
        )
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[0].tone == "愤怒"


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
    """2026-09-05 用于构造指定 chunk 原文的账本（覆盖告警用例需要多条对话候选）"""
    paragraph_info = ChunkParagraphInfo(
        paragraph_ids=[0],
        char_spans=[(0, len(text))],
        texts=[text],
    )
    return AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=10,
        current_chunk_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=paragraph_info,
    )


def _write_all_domains_with_dialogues(tools: list, dialogues_args: dict, ledger=None) -> None:
    """2026-09-05 用于以自定义对话判定完成六个内部领域

    2026-09-07：句标签随 write_metrics 搭车提交，默认取自账本章文本的前缀
    （各测试账本文本不同；不传 ledger 时退回默认章文本），两句满足每章
    2 句软下限，不产生句标签覆盖告警。
    """
    chunk_text = ledger.current_chunk_text if ledger is not None else "“住手”回荡"
    _call(tools, "write_metrics", {**_write_metrics_args(), "sentence_labels": _sentence_labels_args(chunk_text)})
    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_dialogues", dialogues_args)
    _call(tools, "write_event", _write_event_args())
    _call(tools, "write_relations", _write_relations_args())


def test_empty_dialogue_payload_freezes_with_coverage_warning() -> None:
    """2026-09-05 A1：候选>0 但 write_dialogues 空载荷时冻结 chunk 留痕覆盖告警"""
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)
    assert len(ledger.dialogue_candidates) >= 1

    _write_all_domains_with_dialogues(tools, {"items": []}, ledger=ledger)
    chunk = ledger.complete_active_chunk()

    assert ledger.phase == "completed"
    assert chunk.dialogues == []
    assert chunk.coverage_warnings == ["对话覆盖: 检出 2 条系统对话候选但对话域回执未提交任何判定"]


def test_partial_dialogue_judgement_freezes_with_defaulted_warning() -> None:
    """2026-09-05 A1：候选未逐条提交（按 not_dialogue 默认）时冻结 chunk 留痕告警"""
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)

    _write_all_domains_with_dialogues(tools, {"items": [[1, "dialogue", None, None]]}, ledger=ledger)
    chunk = ledger.complete_active_chunk()

    assert len(chunk.dialogues) == 1
    assert chunk.coverage_warnings == [
        "对话覆盖: 1 条候选未提交判定（序号 [2]），按 not_dialogue 默认处理"
    ]


def test_full_dialogue_judgement_freezes_without_coverage_warning() -> None:
    """2026-09-05 A1：候选全部逐条判定时冻结 chunk 不产生覆盖告警"""
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)

    _write_all_domains_with_dialogues(
        tools,
        {"items": [[1, "dialogue", None, None], [2, "dialogue", None, None]]},
        ledger=ledger,
    )
    chunk = ledger.complete_active_chunk()

    assert len(chunk.dialogues) == 2
    assert chunk.coverage_warnings == []


def test_chunk_without_candidates_freezes_without_coverage_warning() -> None:
    """2026-09-05 A1：无对话候选的 chunk 不产生覆盖告警"""
    ledger = _ledger_with_text("山门静默，无人应答。")
    tools = _tools(_QueryService(), ledger)
    assert ledger.dialogue_candidates == []

    _write_all_domains_with_dialogues(tools, {"items": []}, ledger=ledger)
    chunk = ledger.complete_active_chunk()

    assert chunk.coverage_warnings == []


def test_write_metrics_sentence_labels_bind_spans_and_freeze() -> None:
    """2026-09-07 用于验证随 write_metrics 提交的自选句按原文定位绑定区间并进入冻结 chunk"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    # 句标签随 metrics 可选参数提交（先绑定后写域，绑定失败整次调用不落写入）
    args = {**_write_metrics_args(), "sentence_labels": [
        {"sentence": "“住手”回荡", "emotion": -2},
        {"sentence": "回荡", "emotion": -1},
    ]}
    response = _call(tools, "write_metrics", args)
    assert response["accepted"] is True
    assert response["item_count"] == 1
    labels = ledger.bound_payloads["sentence_labels"]
    chunk_text = ledger.current_chunk_text
    assert [label.start for label in labels] == [0, chunk_text.index("回荡")]
    assert [label.emotion for label in labels] == [-2, -1]

    # 整体重交（完整替换语义，最后写入生效）
    _call(tools, "write_metrics", {**_write_metrics_args(), "sentence_labels": [
        {"sentence": "“住手”回荡", "emotion": -2},
        {"sentence": "住手", "emotion": -1},
    ]})
    labels = ledger.bound_payloads["sentence_labels"]
    assert [label.sentence for label in labels] == ["“住手”回荡", "住手"]

    _call(tools, "write_entities", _write_entities_args())
    _call(tools, "write_dialogues", _write_dialogues_args())
    _call(tools, "write_event", _write_event_args())
    _call(tools, "write_relations", _write_relations_args())
    chunk = ledger.complete_active_chunk()
    assert [label.sentence for label in chunk.sentence_labels] == ["“住手”回荡", "住手"]
    assert chunk.coverage_warnings == []


def test_write_metrics_sentence_labels_reject_missing_and_duplicate() -> None:
    """2026-09-07 用于验证非原文句与重复句直接报错自纠（绑定失败不落 metrics 写入）"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(ValueError, match="未在当前章节原文中找到唯一匹配"):
        _call(
            tools,
            "write_metrics",
            {**_write_metrics_args(), "sentence_labels": [{"sentence": "不存在的句子", "emotion": 0}]},
        )
    assert "metrics" not in ledger.domain_receipts
    with pytest.raises(ValueError, match="句子重复"):
        _call(
            tools,
            "write_metrics",
            {
                **_write_metrics_args(),
                "sentence_labels": [
                    {"sentence": "住手", "emotion": -2},
                    {"sentence": "住手", "emotion": -1},
                ],
            },
        )
    assert "metrics" not in ledger.domain_receipts


def test_sentence_label_coverage_warning_below_two() -> None:
    """2026-09-07 用于验证每章不足 2 句时冻结留痕覆盖告警（软下限不阻断）"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools)
    # 整体重交为单句（完整替换语义），触发句标签覆盖告警
    _call(
        tools,
        "write_metrics",
        {**_write_metrics_args(), "sentence_labels": [{"sentence": "住手", "emotion": 0}]},
    )
    chunk = ledger.complete_active_chunk()
    assert "句标签覆盖: 仅标注 1 句（每章应自选 2-3 句）" in chunk.coverage_warnings


def test_resolve_dialogue_case_rejects_non_dialogue_case() -> None:
    """2026-09-08 用于验证无 dialogue_id 的案例（伏笔疑点等）被拒并指引正确通道

    第16章死锁回归：模型把编号表里的伏笔疑点案例误当对话疑点解决，
    工具层须按 target_ref 结构拒绝，否则持久化按对话路径找不到记录直接崩溃。
    """
    service = _ForeshadowingCaseQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    with pytest.raises(AnnotationInputError, match="含 dialogue_id 的对话类案例"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {"case_number": case_number, "speaker": 1, "reason": "误用"}
        )
    assert ledger.resolved_cases == []


def test_resolve_foreshadowing_case_rejects_alias_case() -> None:
    """2026-09-08 用于验证实体别名案例不能走伏笔确认路径（防凭空建线程）"""
    service = _AliasQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    with pytest.raises(AnnotationInputError, match="只能解决疑点类案例"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {"case_number": case_number, "reason": "误用", "setup_status": "reinforced"}
        )
    assert ledger.resolved_cases == []


def test_tone_catalog_accepts_extended_words_and_other_fallback() -> None:
    """2026-09-11 tone 扩表：实测自造高频词入表 + "其他"兜底，非法词仍拒绝

    run e84339d1 实测 13 次 tone 失败全部是模型自造词（得意/惊讶/疲惫/疑惑…），
    8 值词表与自然表达系统性错配。"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)
    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entities", _write_entities_args())

    args = _write_dialogues_args()
    args["items"] = [[1, "dialogue", 1, "得意"]]
    _call(tools, "write_dialogues", args)
    assert ledger.domain_payloads["dialogues"][0].tone == "得意"

    args["items"] = [[1, "dialogue", 1, "强装镇定"]]
    with pytest.raises(ValidationError, match="input_value='强装镇定'"):
        _call(tools, "write_dialogues", args)


def test_entity_number_contract_rejects_names_with_guidance() -> None:
    """2026-09-11 编号合同：实体引用写名称时给出直接可自纠的报错（名称通道已删净）"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    with pytest.raises(ValidationError, match="实体引用只接受编号（整数），收到名称 顾霜"):
        _call(tools, "write_event", _write_event_args(participants=[_character_participant(entity="顾霜")]))
    with pytest.raises(ValidationError, match="实体引用只接受编号（整数），收到名称 顾霜"):
        _call(tools, "write_relations", {"items": [{"from_entity": "顾霜", "to_entity": 2, "relation_type": "友情"}]})


def test_search_graph_exposes_runtime_numbers_not_database_ids() -> None:
    """2026-09-11 编号合同：search_graph 回执带运行期编号 n，数据库 id 不进模型视图"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    payload = json.loads(_find_tool(tools, "search_graph").invoke({"entities": ["顾霜"], "relation_type": None}))
    match = payload["matches"][0]
    assert match["n"] == 1
    assert match["name"] == "顾霜"
    assert "entity_id" not in match


def test_resolve_fact_case_maps_chinese_change_kind_to_internal_value() -> None:
    """2026-09-11 change_kind 中文化：模型写中文值，操作日志落内部英文值（持久化契约不变）"""
    service = _AliasQueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["alias-1"]
    response = json.loads(
        _find_tool(tools, "resolve_fact_case").invoke(
            {
                "case_number": case_number,
                "from_entity": 1,
                "to_entity": 2,
                "relation_type": "同一人物",
                "change_kind": "新增",
                "reason": "指向同一人",
            }
        )
    )
    assert response["accepted"] is True
    assert ledger.graph.relation_change_ops[0]["change_kind"] == "assert"


def test_write_dialogues_speaker_name_gets_self_correction_guidance() -> None:
    """2026-09-11 编号合同：write_dialogues 元组位写名称给出可自纠报错"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(ValidationError, match="实体引用只接受编号（整数），收到名称 顾霜"):
        _call(tools, "write_dialogues", {"items": [[1, "dialogue", "顾霜", None]]})
