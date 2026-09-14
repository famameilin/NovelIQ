"""章节 Agent 语义写入工具与系统账本合同测试

2026-09-13 取消暂存：写入工具一次一个语义单元、写入即生效并返回真实回执
（{status: written, record}；实体另带 n），没有逐域 finish——唯一收尾是
finish_chunk（工具体只回 {status: pending}，判定在本回合全部调用处理完后由
账本执行），事件只暴露章内局部键（t1、t1/e1），真实 uuid 不外露。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from src.agents.annotation.errors import (
    AnnotationAuthorizationError,
    AnnotationInputError,
    AnnotationProtocolError,
    AnnotationStageRejection,
)
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.graph import _invoke_tool
from src.agents.annotation.schema import (
    ActiveCaseDetails,
    CaseSearchResult,
    ChunkParagraphInfo,
    DialogueInput,
    EntityInput,
    EventParticipantInput,
    RelationInput,
    SearchResult,
    TextSearchResult,
    Tone,
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

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
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
    2026-09-04 单一写面：图域写工具（write_entity/write_relation/resolve_fact_case）
    以常驻 FactGraph 为唯一真相源，故默认注入空图；需要历史实体的用例随后覆盖
    ledger.graph。
    2026-09-13 取消暂存：每个小调用写入即生效（written_* / event_trees 即时落账），
    直接调用工具的测试写完内容后统一调用 ledger.finish_chunk() 收尾。
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


def _write_metrics_args() -> dict:
    """2026-08-11 用于构造合法 write_metrics 参数"""
    return {
        "summary": "住手回荡",
        "emotional_valence": 0,
        "narrative_function": "铺垫",
    }


def _entity_number(ledger: AnnotationToolLedger, name: str) -> int:
    """2026-09-11 用于读取实体运行期编号（编号化合同的测试适配口）"""
    assert ledger.graph is not None
    number = ledger.graph.entity_number(name)
    assert number is not None, f"实体未登记: {name}"
    return number


def _call(tools: list, name: str, args: dict):
    """2026-08-07 用于同步调用测试工具并解析 JSON"""
    return json.loads(_find_tool(tools, name).invoke(args))


def _write_call(name: str, args: dict) -> dict:
    """2026-09-13 用于构造单个有类型小调用（一次只提交一个完整语义单元）"""
    return {"name": name, "args": args}


def _finish_call() -> dict:
    """2026-09-13 用于构造唯一 finish_chunk 收尾声明（判定在本回合全部调用处理完后执行）"""
    return _write_call("finish_chunk", {})


def _call_all(tools: list, calls: list[dict]) -> list:
    """2026-09-13 用于按顺序执行一组小调用并解析各自回执"""
    return [_call(tools, call["name"], call["args"]) for call in calls]


def _reject(tools: list, name: str, args: dict) -> dict:
    """2026-09-13 用于经生产路径（graph._invoke_tool）取单条记录的结构化拒绝回执

    schema 层（langchain 参数绑定）失败只在 _invoke_tool 这条生产路径翻译成
    AnnotationStageRejection，直接 .invoke 仍是裸 pydantic ValidationError。
    """
    tool_map = {candidate.name: candidate for candidate in tools}
    with pytest.raises(AnnotationStageRejection) as excinfo:
        asyncio.run(_invoke_tool(tool_map, _write_call(name, args)))
    return excinfo.value.receipt()


def _finish_chunk(tools: list, ledger: AnnotationToolLedger) -> dict:
    """2026-09-13 用于触发 chunk 收尾（工具体只回 pending，判定在生产批次末尾的同一汇点）

    直接调用工具的测试没有模型回合边界，这里先过 finish_chunk 调用点协议校验，
    再显式执行账本收尾；生产路径 graph._settle_chunk_finish 也是调用它。
    """
    call = _finish_call()
    pending = _call(tools, call["name"], call["args"])
    assert pending == {"status": "pending"}
    return ledger.finish_chunk()


def _entity_calls(*, name: str = "顾霜", entity_type: str = "character") -> list[dict]:
    """2026-09-13 用于构造 write_entity 小调用（一次登记一个实体）"""
    return [_write_call("write_entity", {"name": name, "entity_type": entity_type})]


def _metrics_calls() -> list[dict]:
    """2026-09-13 用于构造 write_metrics 小调用（指标整域一次提交）"""
    return [_write_call("write_metrics", _write_metrics_args())]


def _sentence_label_calls(items: list[tuple[str, int]] | None = None) -> list[dict]:
    """2026-09-13 用于构造 write_sentence_label 逐句小调用（默认两句满足每章软下限）"""
    resolved = items if items is not None else [("住手", -2), ("回荡", -1)]
    return [
        _write_call("write_sentence_label", {"sentence": sentence, "emotion": emotion})
        for sentence, emotion in resolved
    ]


def _dialogue_calls(items: list[tuple] | None = None) -> list[dict]:
    """2026-09-13 用于构造 write_dialogue 小调用（默认第一条候选判为真实对话）

    items 元组形如 (candidate_index, verdict, speaker, tone)，speaker 是运行期编号。
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
    order: int = 1,
    child_description: str = "顾霜收势",
    child_action: str = "收势",
) -> list[dict]:
    """2026-09-13 用于构造一棵事件树的小调用组（根 + 子事件 + 两条人物参与）

    同一 chunk 内 (人物, 动作) 二元组不得重复（人物动态状态唯一），多棵树同轮
    提交时各处的 action 必须互不相同，否则重复的那条记录会被结构化拒绝。
    """
    return [
        _write_call("write_event_root", {"tree_key": tree_key, "description": description}),
        _write_call(
            "write_event_child",
            {
                "tree_key": tree_key,
                "node_key": child_key,
                "order": order,
                "type": "main",
                "description": child_description,
            },
        ),
        _write_call(
            "write_character_participation",
            {
                "tree_key": tree_key,
                "node_key": "root",
                "entity": 1,
                "role": "主体",
                "narrative_role": "主体",
                "action": action,
                "emotion": -1,
            },
        ),
        _write_call(
            "write_character_participation",
            {
                "tree_key": tree_key,
                "node_key": child_key,
                "entity": 1,
                "role": "主体",
                "narrative_role": "主体",
                "action": child_action,
                "emotion": 0,
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
    sentence_label_calls: list[dict] | None = None,
) -> list:
    """2026-09-13 用于以小调用完成六个内部数据领域并统一收尾 chunk

    写入即生效：按依赖顺序提交（实体 → 指标/句标签 → 事件 → 关系 → 对话），
    全部写完后再发唯一 finish_chunk 收尾冻结（取消暂存后没有逐域结束声明）。
    传空列表表示该域不写内容（如 entity_calls=[] 表示本章不登记实体）。
    """
    resolved_entity_calls = _entity_calls() if entity_calls is None else entity_calls
    resolved_event_calls = _event_calls() if event_calls is None else event_calls
    resolved_relation_calls = _relation_calls() if relation_calls is None else relation_calls
    resolved_dialogue_calls = _dialogue_calls() if dialogue_calls is None else dialogue_calls
    resolved_label_calls = (
        _sentence_label_calls() if sentence_label_calls is None else sentence_label_calls
    )
    receipts = _call_all(
        tools,
        [
            *resolved_entity_calls,
            *resolved_label_calls,
            *_metrics_calls(),
            *resolved_event_calls,
            *resolved_relation_calls,
            *resolved_dialogue_calls,
        ],
    )
    receipts.append(_finish_chunk(tools, ledger))
    return receipts


def test_business_write_tool_contract_lists_write_tools_and_finish_chunk() -> None:
    """2026-09-07 用于锁定模型侧业务写入工具集合（旧合同为五个整域 write 工具）

    2026-09-13 取消暂存：业务写入面是九个有类型写工具 + 唯一收尾 finish_chunk；
    旧的 write_entities/write_dialogues/write_event/write_relations 整域工具与
    逐域 finish_domain 结束声明整体删除，句标签从 write_metrics 参数拆成
    write_sentence_label 独立工具，因此"五个业务写入工具"的旧断言改写为对
    新工具面的精确锁定。
    """
    tools = _tools(_QueryService(), _ledger())
    business_writes = {tool.name for tool in tools if tool.name.startswith("write_")}
    assert business_writes == {
        "write_entity",
        "write_metrics",
        "write_sentence_label",
        "write_dialogue",
        "write_relation",
        "write_event_root",
        "write_event_child",
        "write_character_participation",
        "write_noncharacter_participation",
    }
    # 唯一收尾声明 finish_chunk 恒定开放（收尾判定由批次末尾的账本兜底），旧结束声明不得再出现
    assert _find_tool(tools, "finish_chunk").name == "finish_chunk"
    assert business_writes.isdisjoint({"write_entities", "write_dialogues", "write_event", "write_relations"})
    assert not any(tool.name == "finish_domain" for tool in tools)


def test_schema_rejects_deleted_contract_fields() -> None:
    """2026-08-11 用于验证输入模型对已删除字段使用 extra=forbid 明确拒绝

    2026-09-13 取消暂存：整树 WriteEventInput 已删除，同样的 extra=forbid 约束
    现在由 write_event_root 参数面承接——未声明字段（anchor_paragraph_ids /
    event_type / location）经生产路径整条结构化拒绝，code=unknown_field。
    """
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
    tools = _tools(_QueryService(), _ledger())
    receipt = _reject(
        tools,
        "write_event_root",
        {
            "tree_key": "t1",
            "description": "进入山门",
            "anchor_paragraph_ids": [0],
            "event_type": "进入",
            "location": "山门",
        },
    )
    assert receipt["status"] == "rejected"
    assert receipt["record"] == "t1/root"
    assert receipt["code"] == "unknown_field"
    assert receipt["field"] in {"anchor_paragraph_ids", "event_type", "location"}


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


def test_small_calls_complete_chunk_in_write_order() -> None:
    """2026-08-30 用于验证同轮多个小调用写满六个内部领域并冻结 chunk

    2026-09-13 取消暂存：写工具改造前的五个整域 write 是"一次大载荷"，
    现在是同轮多个有类型小调用写入即生效 + 唯一 finish_chunk 收尾；
    完成语义（六内部领域、chunk 冻结、对话原文绑定）不变。
    """
    service = _QueryService()
    ledger = _ledger(allow_future_context=False)
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger)

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
    """2026-08-10 用于验证成功写入的模型回执固定压缩

    2026-09-13 取消暂存：旧的整域 write 回执（accepted/tool/domain/item_count
    +numbers）被"写入即生效"的两级小回执取代——每个写工具固定回
    status=written/record（实体另带 n），finish_chunk 收尾回执固定为
    status=completed/chunk_id/records/dialogue_defaulted，都不回传完整载荷。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    entity_receipt = _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    assert set(entity_receipt) == {"status", "record", "n"}
    assert entity_receipt == {"status": "written", "record": "entity/顾霜", "n": 1}

    metrics_receipt = _call(tools, "write_metrics", _write_metrics_args())
    assert metrics_receipt == {"status": "written", "record": "metrics"}

    domain_receipt = _finish_chunk(tools, ledger)
    assert set(domain_receipt) == {"status", "chunk_id", "records", "dialogue_defaulted"}
    assert domain_receipt == {
        "status": "completed",
        "chunk_id": 10,
        "records": {
            "entities": 1,
            "metrics": 1,
            "events": 0,
            "relations": 0,
            "dialogues": 1,
            "character_observations": 0,
            "sentence_labels": 0,
        },
        "dialogue_defaulted": [1],
    }


def test_failed_write_call_keeps_other_domain_receipts_and_written_records() -> None:
    """2026-08-11 用于验证单个写入失败后其他成功领域的 receipt 与已接受记录保留

    2026-09-13 取消暂存：失败粒度从"整域 write"变成"单条小调用"。参与者引用
    未登记编号时只拒绝该条记录（结构化拒绝），实体/指标写入即生效的记录、
    已实时落账的事件树与账本状态原样保留（旧 domain_receipts/staged_* 断言
    改写为 written_* 与 event_trees）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    _call(tools, "write_event_root", {"tree_key": "t1", "description": "顾霜喝止众人"})

    invalid = _write_call(
        "write_character_participation",
        {
            "tree_key": "t1",
            "node_key": "root",
            "entity": 999,
            "role": "主体",
            "narrative_role": "主体",
            "action": "喝止",
            "emotion": -1,
        },
    )
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(tools, invalid["name"], invalid["args"])
    assert excinfo.value.code == "unregistered_number"
    assert excinfo.value.record == "t1/root/participant/999"

    assert ledger.metrics_payload is not None
    assert list(ledger.written_entities) == ["顾霜"]
    assert list(ledger.tree_key_index) == ["t1"]
    tree = next(iter(ledger.event_trees.values()))
    assert tree["root_node_id"] is not None
    assert ledger.observation_by_record == {}
    # 收尾前的审计记录只在 finish_chunk 时按域汇总写出；失败调用不留痕迹
    assert ledger.write_records == []
    assert ledger.ready_chunk is None
    assert ledger.chunk_finished is False


def test_event_children_land_live_and_freeze_into_ready_chunk() -> None:
    """2026-08-30 用于验证最后一棵事件树收尾后 ready_chunk 冻结全部事件

    2026-09-13 取消暂存：事件节点写入即落账（bound_payloads["events"] 即时可见），
    不再有"结算前 ready_chunk 为空"的暂存态；收尾前 ready_chunk 仍为 None，
    finish_chunk 回执用 records 汇总各域条数（旧 events 结束回执的
    records/trees/character_observation_count 字段已删除）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call_all(
        tools,
        [
            *_entity_calls(),
            *_sentence_label_calls(),
            *_metrics_calls(),
            *_dialogue_calls(),
        ],
    )

    _call_all(tools, _event_calls(tree_key="t1", child_description="顾霜追击", child_action="追击"))
    assert [event.description for event in ledger.bound_payloads["events"]] == ["顾霜喝止众人", "顾霜追击"]
    assert ledger.ready_chunk is None
    assert ledger.chunk_finished is False

    _call_all(
        tools,
        [
            _write_call("write_event_root", {"tree_key": "t2", "description": "顾霜收势"}),
            _write_call(
                "write_event_child",
                {"tree_key": "t2", "node_key": "e1", "order": 1, "type": "main", "description": "新事件描述"},
            ),
            _write_call(
                "write_character_participation",
                {
                    "tree_key": "t2",
                    "node_key": "e1",
                    "entity": 1,
                    "role": "主体",
                    "narrative_role": "主体",
                    "action": "离场",
                    "emotion": 0,
                },
            ),
        ],
    )
    receipt = _finish_chunk(tools, ledger)
    assert receipt["records"]["events"] == 4
    assert receipt["records"]["character_observations"] == 3
    assert ledger.ready_chunk.events[-1].description == "新事件描述"
    assert ledger.ready_chunk.events[-1].cause_role == "main"
    assert [item.action for item in ledger.ready_chunk.character_observations] == ["喝止", "追击", "离场"]

    ledger.complete_active_chunk()
    assert ledger.completed_chunks[0].events[-1].description == "新事件描述"


def test_event_root_appends_new_tree_per_tree_key_and_updates_on_replay() -> None:
    """2026-08-22 事件契约：事件只增不改——每棵事件树独立追加

    2026-09-13 取消暂存：追加粒度从"每次 write_event 调用"变成"每个 tree_key"；
    同一 tree_key 重交即时更新根描述（不新增第二棵树），不再有 finalize 标志或
    逐域事件结算回执——旧断言 first/second 的 finalized 与 tree_id 改写为
    实时落账的树数与树 id 独立性，事件审计记录改为收尾时按域汇总的一条
    （payload["trees"] 列表内含全部树）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
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
    assert ledger.ready_chunk is None
    assert len(ledger.tree_key_index) == 2
    # 同 tree_key 重交按更新：根描述改写，不新增第三棵树
    replay = _call(tools, "write_event_root", {"tree_key": "t2", "description": "顾霜收势离场"})
    assert replay == {"status": "written", "record": "t2/root"}
    assert len(ledger.tree_key_index) == 2

    _call(tools, "write_metrics", _write_metrics_args())
    receipt = _finish_chunk(tools, ledger)
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


def test_complete_chunk_requires_finish_chunk_and_metrics() -> None:
    """2026-08-11 用于验证未收尾的 chunk 不能冻结，且缺指标时收尾被拒

    2026-09-13 取消暂存：没有逐域 finish_domain，唯一收尾是 finish_chunk——
    只写小调用不调用 finish_chunk 时 chunk 不冻结（旧合同"未调用领域"的等价物）；
    指标未提交时 finish_chunk 结构化拒绝 code=missing_record。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call_all(tools, [*_entity_calls(), *_event_calls()])
    assert ledger.written_entities and ledger.metrics_payload is None
    with pytest.raises(ValueError, match="尚未收尾"):
        ledger.complete_active_chunk()
    with pytest.raises(AnnotationStageRejection) as excinfo:
        ledger.finish_chunk()
    assert excinfo.value.code == "missing_record"
    assert excinfo.value.field == "metrics"
    assert ledger.chunk_finished is False
    assert ledger.completed_chunks == []
    assert ledger.phase == "chunk_open"


def test_dialogue_defaults_missing_candidates_to_not_dialogue() -> None:
    """2026-08-12 用于验证缺失候选软覆盖为 not_dialogue，收尾回执列出默认处理的序号

    2026-09-13 取消暂存：默认处理推迟到唯一 finish_chunk 收尾时一次执行（旧合同在
    finish_domain("dialogues") 结算时执行）；同序号重交是更新语义，旧"重复
    candidate_index 报错"断言改写为"同序号只保留一条记录"，越界仍拒绝（结构化
    拒绝记录键/字段/错误码）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    _call(tools, "write_metrics", _write_metrics_args())

    # 未提交判定：候选 1 在收尾时默认 not_dialogue，回执列出
    response = _finish_chunk(tools, ledger)
    assert response["dialogue_defaulted"] == [1]
    assert ledger.bound_payloads["dialogues"] == []

    # 补交后缺失列表为空
    filled = _ledger()
    filled_tools = _tools(service, filled)
    _call(filled_tools, "write_metrics", _write_metrics_args())
    _call(
        filled_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": None, "tone": None},
    )
    response = _finish_chunk(filled_tools, filled)
    assert response["dialogue_defaulted"] == []
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
    response = _finish_chunk(replay_tools, replay)
    assert response["records"]["dialogues"] == 1
    assert response["dialogue_defaulted"] == []
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
    assert over.chunk_finished is False


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

    2026-09-13 取消暂存：校验按入口分工——location 走 write_character_participation
    在调用点被拒（结构化拒绝 code=not_character），write_noncharacter_participation
    的参数面只有 tree_key/node_key/entity/role，三态字段表达不出来（旧整树合同的
    "非人物不得携带人物动态状态"由入口分工承接）；参与者写入即挂到实时落账的
    事件节点上。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entity", {"name": "山门", "entity_type": "location"})
    _call(tools, "write_event_root", {"tree_key": "t1", "description": "山门震动"})
    # 山门是本用例唯一登记实体，运行期编号为 1
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            tools,
            "write_character_participation",
            {
                "tree_key": "t1",
                "node_key": "root",
                "entity": 1,
                "role": "地点",
                "narrative_role": "主体",
                "action": "震动",
                "emotion": 0,
            },
        )
    assert excinfo.value.record == "t1/root/participant/1"
    assert excinfo.value.field == "entity"
    assert excinfo.value.code == "not_character"
    # 非人物入口的参数面只有 tree_key/node_key/entity/role，三态字段表达不出来
    noncharacter_tool = _find_tool(tools, "write_noncharacter_participation")
    assert set(noncharacter_tool.args_schema.model_fields) == {"tree_key", "node_key", "entity", "role"}
    receipt = _call(
        tools,
        "write_noncharacter_participation",
        {"tree_key": "t1", "node_key": "root", "entity": 1, "role": "地点"},
    )
    assert receipt == {"status": "written", "record": "t1/root/participant/1"}
    root_event = ledger.bound_payloads["events"][0]
    participant = root_event.participants[0]
    assert participant.entity == "山门"
    assert (participant.narrative_role, participant.action, participant.emotion) == (None, None, None)
    assert ledger.observation_by_record == {}


def test_event_location_participant_role_requires_location_type() -> None:
    """2026-08-11 用于验证事件参与者角色为地点时端点必须是 location 实体

    2026-09-13 取消暂存：整树提交改为逐条参与者提交，地点角色校验移到
    write_character_participation 调用点（结构化拒绝 code=role_type_mismatch），
    失败只拒绝该条参与者记录、不挂到已落账的事件节点。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    _call(tools, "write_event_root", {"tree_key": "t1", "description": "顾霜喝止众人"})
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            tools,
            "write_character_participation",
            {
                "tree_key": "t1",
                "node_key": "root",
                "entity": 1,
                "role": "地点",
                "narrative_role": "主体",
                "action": "喝止",
                "emotion": -1,
            },
        )
    assert excinfo.value.code == "role_type_mismatch"
    assert excinfo.value.field == "role"
    assert "地点角色端点必须是 location" in str(excinfo.value)
    assert ledger.bound_payloads["events"][0].participants == []
    assert ledger.observation_by_record == {}


def test_write_entity_requires_prior_search_graph_when_registered_entities_exist() -> None:
    """2026-08-09 用于验证存在已登记实体时未先 search_graph 禁止登记实体

    2026-09-13 取消暂存：write_entities（整目录）改为 write_entity（一次一个），
    准入闸门只对本章第一次登记生效（entity_gate_passed 单调放行）。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationAuthorizationError, match="必须先调用 search_graph"):
        _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    assert ledger.written_entities == {}


def test_write_entity_allowed_after_search_graph() -> None:
    """2026-08-09 用于验证 search_graph 之后可正常登记实体

    2026-09-13 取消暂存：提交形态变为单个实体，回执带运行期编号 n，写入即生效。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    _call(tools, "search_graph", {"entities": ["顾霜"]})
    assert ledger.graph_queried is True
    receipt = _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    assert receipt == {"status": "written", "record": "entity/顾霜", "n": 1}


def test_complete_chunk_accepts_registered_entity_endpoint_without_declaration() -> None:
    """2026-08-09 用于验证已登记实体可直接作为事实端点，无需当前 chunk 重复声明

    2026-09-13 取消暂存：本章不登记实体时直接不写 write_entity（不再需要
    finish_domain("entities") 空域声明），事件参与者用 search_graph 回执编号
    直接引用历史实体，chunk 仍可收尾完成。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "伯安": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger, entity_calls=[])

    assert ledger.domain_payloads["entities"].entities == []
    assert ledger.written_entities == {}
    ledger.complete_active_chunk()
    assert [item.character for item in ledger.bound_payloads["character_observations"]] == ["顾霜", "顾霜"]


def test_write_entity_rejects_registered_entity_type_change() -> None:
    """2026-08-09 用于验证已登记实体重新提交时大类必须保持一致（写入时即失败）

    2026-09-13 取消暂存：整目录提交改为单实体 write_entity，类型冲突变成结构化
    拒绝（code=type_conflict、field=entity_type、record=entity/顾霜），失败不入账。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(tools, "write_entity", {"name": "顾霜", "entity_type": "item"})
    assert excinfo.value.record == "entity/顾霜"
    assert excinfo.value.field == "entity_type"
    assert excinfo.value.code == "type_conflict"
    assert "已登记实体不允许变更大类" in str(excinfo.value)
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
    metrics_receipt = _reject(tools, "write_metrics", args)
    assert metrics_receipt["status"] == "rejected"
    assert metrics_receipt["record"] == "metrics"
    assert metrics_receipt["field"] == "emotional_valence"
    assert metrics_receipt["code"] == "not_integer"

    dialogue_receipt = _reject(
        tools,
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
    ledger.complete_active_chunk()

    assert ledger.pushed_cases == []


def test_event_root_isforeshadowing_carries_payoff_fields_on_root() -> None:
    """2026-09-13 伏笔即事件树：isforeshadowing=true 根事件携带伏笔属性并拒绝 setup_kind

    2026-09-13 取消暂存：write_event 整树提交改为 write_event_root 写入即生效；
    伏笔两字段缺一在调用点即被拒（结构化拒绝），根节点 id 由服务端在写入时生成并
    由账本内部持有，旧整树模型 WriteEventInput 的 setup_kind 约束改由工具参数面
    的 extra=forbid 承接（经生产路径报 unknown_field）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    entities_receipt = _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    assert entities_receipt["status"] == "written"

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(
            tools,
            "write_event_root",
            {
                "tree_key": "t1",
                "description": "身份线索埋下",
                "isforeshadowing": True,
                "expected_payoff_family": "身份揭露",
            },
        )
    assert excinfo.value.record == "t1/root"
    assert excinfo.value.field == "payoff_likelihood"
    assert excinfo.value.code == "missing"

    response = _call(
        tools,
        "write_event_root",
        {
            "tree_key": "t1",
            "description": "身份线索埋下",
            "isforeshadowing": True,
            "expected_payoff_family": "身份揭露",
            "payoff_likelihood": "medium",
        },
    )
    assert response == {"status": "written", "record": "t1/root"}
    _call(
        tools,
        "write_event_child",
        {"tree_key": "t1", "node_key": "e1", "order": 1, "type": "main", "description": "身份线索再次出现"},
    )

    tree = next(iter(ledger.event_trees.values()))
    assert tree["isforeshadowing"] is True
    stored = ledger.bound_payloads["events"]
    root = next(node for node in stored if node.node_id == tree["root_node_id"])
    assert root.is_foreshadow_setup is True
    assert root.expected_payoff_family == "身份揭露"
    assert root.payoff_likelihood == "medium"
    setup_kind_receipt = _reject(
        tools,
        "write_event_root",
        {"tree_key": "t9", "description": "伏笔", "isforeshadowing": True, "setup_kind": "其他"},
    )
    assert setup_kind_receipt["status"] == "rejected"
    assert setup_kind_receipt["field"] == "setup_kind"
    assert setup_kind_receipt["code"] == "unknown_field"


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

    with pytest.raises(AnnotationAuthorizationError, match="未由 search_pool 检索或 push_case 登记返回: 999"):
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
    """2026-09-13 用于验证伏笔解决字段只接受闭合枚举（setup_status 已随线程退役）"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _surface_case(service, ledger)
    case_number = ledger.case_number_by_id["case-1"]
    base = {
        "case_number": case_number,
        "reason": "伏笔回收",
        "foreshadowing_action": "reinforce",
        "root_event_id": "evt-root-1",
        "event_id": "evt-bind-1",
    }
    with pytest.raises(ValidationError, match="payoff_likelihood"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {**base, "payoff_likelihood": "certain"}
        )
    with pytest.raises(ValidationError, match="strength"):
        _find_tool(tools, "resolve_foreshadowing_case").invoke({**base, "strength": "very_high"})
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


def test_push_case_rejects_unknown_dialogue_id() -> None:
    """2026-09-13 用于验证 push_case 校验 dialogue_id（伏笔线程 setup_id 参数已退役）"""
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


def test_push_case_then_resolve_foreshadowing_case_binds_tree() -> None:
    """2026-09-13 伏笔即事件树：push_case 不再带 setup_id；resolve 以章内局部键挂树

    2026-09-13 取消暂存：伏笔树经 write_event_root(isforeshadowing=true) 写入即生效，
    resolve 的 root/event 直接填章内局部键（t1、t1/e1）——真实节点 id 由账本内部
    持有，不再作为模型面寻址键，也不再有领域结算才生成 id 的窗口。
    """
    service = _ForeshadowingCaseQueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    response = json.loads(
        _find_tool(tools, "push_case").invoke(
            {
                "description": "伏笔疑点",
                "keys": ["线索"],
                "type": "foreshadowing_suspect",
            }
        )
    )
    assert response["accepted"] is True
    pushed = ledger.pushed_cases[0]
    assert pushed.target_ref["kind"] == "foreshadowing_suspect"

    _surface_case(service, ledger)
    case_number = ledger.case_number_by_id["case-1"]
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    _call(
        tools,
        "write_event_root",
        {
            "tree_key": "t1",
            "description": "守护誓言埋下",
            "isforeshadowing": True,
            "expected_payoff_family": "守护",
            "payoff_likelihood": "high",
        },
    )
    _call(
        tools,
        "write_event_child",
        {"tree_key": "t1", "node_key": "e1", "order": 1, "type": "main", "description": "守护誓言再次出现"},
    )
    # 写入即生效：章内局部键随时可解析（旧合同要等事件域结算才生成真实 id）
    root_event_id = ledger.resolve_event_reference("t1")
    event_id = ledger.resolve_event_reference("t1/e1")
    assert root_event_id is not None and event_id is not None

    resolved = json.loads(
        _find_tool(tools, "resolve_foreshadowing_case").invoke(
            {
                "case_number": case_number,
                "reason": "后续章节强化承诺",
                "foreshadowing_action": "reinforce",
                "root_event_id": "t1",
                "event_id": "t1/e1",
            }
        )
    )
    assert resolved["accepted"] is True
    last = ledger.resolved_cases[-1]
    assert last.action == "foreshadowing"
    assert last.foreshadowing_action == "reinforce"
    assert last.foreshadowing_root_event_id == root_event_id
    assert last.foreshadowing_event_id == event_id


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
        def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
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
        def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
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
    with pytest.raises(AnnotationAuthorizationError, match="未由 search_pool 检索或 push_case 登记返回: 1"):
        _find_tool(tools, "close_case").invoke({"case_number": 1, "reason": "凭空引用"})


def test_dialogue_small_calls_bind_speaker_tone_and_null_fields() -> None:
    """2026-08-12 用于验证对话判定绑定说话人与语气、null 字段合法

    2026-09-13 取消暂存：四元组数组参数变成 write_dialogue 有类型参数且写入即生效；
    旧"数组整体替换"的第二次提交是同序号更新语义。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_metrics", _write_metrics_args())
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "平静"},
    )
    stored = ledger.domain_payloads["dialogues"]
    assert stored[0].verdict == "dialogue"
    assert stored[0].speaker == "顾霜"
    assert stored[0].tone == "平静"

    # 同序号重交 null 字段：更新语义只保留最后一次判定
    replay = _ledger()
    replay_tools = _tools(service, replay)
    _call(replay_tools, "write_entity", {"name": "顾霜", "entity_type": "character"})
    _call(
        replay_tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "平静"},
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
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character"})

    receipt = _reject(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": foreign_tone},
    )

    assert receipt["status"] == "rejected"
    assert receipt["field"] == "tone"
    assert receipt["code"] == "invalid_value"
    assert foreign_tone in receipt["message"]
    assert "其他" in receipt["message"]
    assert "平静" in receipt["expected"] and "其他" in receipt["expected"]
    assert not ledger.written_dialogues


def test_write_dialogue_rejects_oversized_tone_word_with_receipt() -> None:
    """2026-09-13 用于验证非语气长度的自由文本（关系词等）整条拒绝且回执可读"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _reject(tools, "write_dialogue", {"candidate_index": 1, "verdict": "dialogue", "tone": "强化关系"})
    assert receipt["status"] == "rejected"
    assert receipt["field"] == "tone"
    assert "tone" in receipt["message"]


def test_dialogue_input_rejects_foreign_tone_word() -> None:
    """2026-09-14 载荷模型层同样只接受闭合枚举（枚举外词在类型层整条拒绝）

    tone 回到真 enum 字段（Tone | None）后不再叠 require_tone：非法词的拒绝由枚举
    类型给出，工具面上的可自纠回执由记录级转换器负责（见 tone 拒绝用例）。
    """
    with pytest.raises(ValidationError, match="Input should be"):
        DialogueInput(candidate_index=1, verdict="dialogue", tone="委屈")
    assert DialogueInput(candidate_index=1, verdict="dialogue", tone="平静").tone == "平静"


def test_resolve_dialogue_case_coerces_foreign_tone_word() -> None:
    """2026-09-14 解决路径与写入路径同口径：枚举外语气词在参数绑定层被拒

    旧口径（09-13）是纯字符串参数 + 函数体内 require_tone 抛 AnnotationInputError；
    恢复真 enum 后拒绝提前到 schema 绑定，回执由记录级转换器按 case 编号产出。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    receipt = _reject(
        tools,
        "resolve_dialogue_case",
        {
            "case_number": case_number,
            "speaker": 1,
            "tone": "激动",
            "reason": "语气判断",
        },
    )
    assert receipt["status"] == "rejected"
    assert receipt["field"] == "tone"
    assert receipt["code"] == "invalid_value"
    assert "激动" in receipt["message"]
    assert "其他" in receipt["message"]
    assert "平静" in receipt["expected"] and "其他" in receipt["expected"]
    assert ledger.resolved_cases == []


def test_relation_write_asserts_new_edge_immediately() -> None:
    """2026-08-11 用于验证三字段边在图中无对应边时自动按新建处理（assert）

    2026-09-13 取消暂存：逐条 write_relation 写入即入图（旧合同"结算前图中不得
    出现该边"的暂存语义废止），assert 结果由 FactGraph 操作日志承载——旧结束
    回执里的 relations outcome 列表随逐域 finish 一起删除。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
    )
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    receipt = _call(tools, "write_relation", {"from_entity": 1, "to_entity": 2, "relation_type": "友情"})
    assert receipt == {"status": "written", "record": "relation/顾霜-顾老/友情", "outcome": "assert"}
    assert ledger.graph.relation_exists("顾霜", "顾老", "友情") is True
    ops = ledger.graph.relation_assert_ops
    assert [(op["from_entity"], op["to_entity"], op["relation_type"]) for op in ops] == [
        ("顾霜", "顾老", "友情")
    ]
    assert ledger.domain_payloads["relations"][0].relation_type == "友情"


def test_relation_existing_edge_skipped_existing_receipt() -> None:
    """2026-08-12 用于验证已存在同一条边的再次提交接受为 skipped_existing（no-op）

    2026-09-13 取消暂存：逐条 write_relation 写入即入图，重复提交不新增图边也
    不重复累计支持度；写入回执直接带本条边的入图结果（skipped_existing）。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
        history_relations={("顾霜", "顾老", "友情")},
    )
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    receipt = _call(tools, "write_relation", {"from_entity": 1, "to_entity": 2, "relation_type": "友情"})
    assert receipt == {
        "status": "written",
        "record": "relation/顾霜-顾老/友情",
        "outcome": "skipped_existing",
    }
    assert ledger.graph.relation_exists("顾霜", "顾老", "友情") is True
    # no-op 判据：已存在的边不进入本章新增集合（不重复累计支持度）
    assert ledger.graph.chapter_added_relations == set()


def test_relation_alias_resolved_to_same_entity_skipped_self_loop() -> None:
    """2026-09-10 用于验证解析后两端同实体的边跳过不入图

    "同一人物"边解析后塌环（含同批双向重申、跨章重申、传递归并）= 归并已成立，
    按合同接受为 skipped_existing；普通关系类型塌成自环才是退化输入，标
    skipped_self_loop。照常入图都会在持久化插入 from_entity_id=to_entity_id
    自环行，违反 ck_graph_relations_distinct_endpoints 炸掉完成事务
    （run a83fae3d 第9章实锤：同批双向重申的第二条经 resolve_name 键变形
    逃逸了 existing 去重）。

    2026-09-13 取消暂存：同一对端点重写即整体替换（旧合同两条边各回一条
    outcome，现只剩替换后的那条），退化边不入操作日志、图中无自环键的判据不变。
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

    _call(tools, "write_relation", {"from_entity": 1, "to_entity": 2, "relation_type": "同一人物"})
    # 同一对端点换类型即整体替换：同一人物边被友情边替换
    receipt = _call(tools, "write_relation", {"from_entity": 1, "to_entity": 2, "relation_type": "友情"})
    assert receipt == {"status": "written", "record": "relation/猴子-侯飞白/友情", "outcome": "skipped_self_loop"}
    assert len(ledger.written_relations) == 1
    assert ledger.written_relations[("猴子", "侯飞白")].relation_type == "友情"

    # 退化边不入操作日志（持久化重放源），图中也不得出现自环键
    assert ledger.graph.relation_assert_ops == []
    assert not any(
        from_key == to_key
        for from_key, to_key, _relation_type in ledger.graph.active_relations
    )
    # 历史"同一人物"边保持原样（塌环判定只是跳过，不误删已成立归并）
    assert ledger.graph.relation_exists("猴子", "侯飞白", "同一人物") is True


def test_relation_state_field_rejected_from_contract() -> None:
    """2026-08-12 用于验证关系合同已删除 state 字段

    2026-09-13 取消暂存：write_relation 扁平三参数——state 在工具参数面上根本
    不存在（多余字段经生产路径整条拒绝）；内部形态 RelationInput 仍以
    extra=forbid 兜底拒绝该字段。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = FactGraph(
        history_entity_types={"顾霜": "character", "顾老": "character"},
        history_entity_names={"顾霜": "顾霜", "顾老": "顾老"},
    )
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    relation_tool = _find_tool(tools, "write_relation")
    assert set(relation_tool.args_schema.model_fields) == {"from_entity", "to_entity", "relation_type"}
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
        "write_relation",
        {"from_entity": 1, "to_entity": 2, "relation_type": "友情", "state": "ended"},
    )
    assert receipt["field"] == "state"
    assert receipt["code"] == "unknown_field"
    assert ledger.written_relations == {}


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
    """2026-08-11 用于验证章节摘要由系统用各 chunk summary 自动生成

    2026-09-13 小调用改造：完成路径改为小调用 + 领域结算，摘要生成逻辑不变。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger)
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
    """2026-09-14 用于验证对话解决的 tone 与写入路径共用同一闭合枚举

    真 enum 参数下非法词在 schema 绑定层就被拒（非法词由类型层拦下，
    「其他」是唯一兜底取值），函数体内的 require_tone 转换已随之退役。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_number = ledger.case_number_by_id["case-1"]
    with pytest.raises(ValidationError, match="Input should be"):
        _find_tool(tools, "resolve_dialogue_case").invoke(
            {
                "case_number": case_number,
                "speaker": 1,
                "tone": "委屈",
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


def _sentence_label_calls_for_text(chunk_text: str) -> list[dict]:
    """2026-09-13 用于按指定章文本构造两句可定位的 write_sentence_label 小调用

    覆盖告警用例的账本章文本各不相同：整句 + 前缀子串保证两句 span 不同、
    都能在原文定位，且满足每章 2 句软下限。
    """
    return _sentence_label_calls(
        [
            (chunk_text, -2),
            (chunk_text[: max(2, len(chunk_text) // 2)], -1),
        ]
    )


def _write_all_domains_with_dialogues(
    tools: list,
    ledger: AnnotationToolLedger,
    dialogue_calls: list[dict],
) -> None:
    """2026-09-05 用于以自定义对话判定完成六个内部领域

    2026-09-13 取消暂存：整域 items 载荷变成 write_dialogue 小调用列表；
    句标签按账本章文本逐句提交（不再随 write_metrics 搭车），未提交候选在
    finish_chunk 收尾时一次性默认 not_dialogue。
    """
    _write_all_domains(
        tools,
        ledger,
        dialogue_calls=dialogue_calls,
        sentence_label_calls=_sentence_label_calls_for_text(ledger.current_chunk_text),
    )


def test_empty_dialogue_payload_freezes_with_coverage_warning() -> None:
    """2026-09-05 A1：候选>0 但对话域空载荷时冻结 chunk 留痕覆盖告警

    2026-09-13 取消暂存：空载荷 = 不发任何 write_dialogue 小调用，收尾时未提交
    候选统一默认 not_dialogue。默认判定在收尾时先行物化，所以冻结告警走的是
    "按 not_dialogue 默认处理"那条文案（旧"对话域回执未提交任何判定"分支在收尾
    路径已不可达）；覆盖缺口仍被留痕，判据（候选数与判定的差值）不变。
    """
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)
    assert len(ledger.dialogue_candidates) >= 1

    _write_all_domains_with_dialogues(tools, ledger, [])
    chunk = ledger.complete_active_chunk()

    assert ledger.phase == "completed"
    assert chunk.dialogues == []
    assert chunk.coverage_warnings == [
        "对话覆盖: 2 条候选未提交判定（序号 [1, 2]），按 not_dialogue 默认处理"
    ]


def test_partial_dialogue_judgement_freezes_with_defaulted_warning() -> None:
    """2026-09-05 A1：候选未逐条提交（按 not_dialogue 默认）时冻结 chunk 留痕告警

    2026-09-13 取消暂存：只提交候选 1 的 write_dialogue 小调用，候选 2 在
    finish_chunk 收尾时默认处理。
    """
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)

    _write_all_domains_with_dialogues(
        tools,
        ledger,
        _dialogue_calls([(1, "dialogue", None, None)]),
    )
    chunk = ledger.complete_active_chunk()

    assert len(chunk.dialogues) == 1
    assert chunk.coverage_warnings == [
        "对话覆盖: 1 条候选未提交判定（序号 [2]），按 not_dialogue 默认处理"
    ]


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
    chunk = ledger.complete_active_chunk()

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
    chunk = ledger.complete_active_chunk()

    assert chunk.coverage_warnings == []


def test_sentence_labels_bind_spans_and_freeze() -> None:
    """2026-09-07 用于验证自选句按原文定位绑定区间并进入冻结 chunk

    2026-09-13 取消暂存：句标签从 write_metrics 可选参数拆成
    write_sentence_label 逐句调用且写入即绑定。旧"整批重交/完整替换"断言改写为：
    同区间重交覆盖分值（记录数不变）、新句追加而不清空已绑定句。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    first = _call(tools, "write_sentence_label", {"sentence": "“住手”回荡", "emotion": -2})
    assert first == {"status": "written", "record": "sentence_label/0:6"}
    _call(tools, "write_sentence_label", {"sentence": "回荡", "emotion": -1})
    labels = ledger.bound_payloads["sentence_labels"]
    chunk_text = ledger.current_chunk_text
    assert [label.start for label in labels] == [0, chunk_text.index("回荡")]
    assert [label.emotion for label in labels] == [-2, -1]

    # 同一区间重交覆盖分值：不新增记录
    replay = _call(tools, "write_sentence_label", {"sentence": "回荡", "emotion": 1})
    assert replay == {"status": "written", "record": "sentence_label/4:6"}
    labels = ledger.bound_payloads["sentence_labels"]
    assert len(labels) == 2
    assert labels[-1].emotion == 1

    # 新句追加（不整体替换已绑定句）
    _call(tools, "write_sentence_label", {"sentence": "住手", "emotion": -1})
    labels = ledger.bound_payloads["sentence_labels"]
    assert [label.sentence for label in labels] == ["“住手”回荡", "回荡", "住手"]

    _write_all_domains(tools, ledger, sentence_label_calls=[])
    chunk = ledger.complete_active_chunk()
    assert [label.sentence for label in chunk.sentence_labels] == ["“住手”回荡", "回荡", "住手"]
    assert chunk.coverage_warnings == []


def test_sentence_labels_reject_missing_and_update_on_replay() -> None:
    """2026-09-07 用于验证非原文句直接报错自纠（绑定失败不落任何写入）

    2026-09-13 取消暂存：非原句只拒绝该条记录（结构化拒绝 code=not_found，
    记录键带原句文本），不牵连指标域；旧"同批重复句报错"是同一区间重交——
    按更新语义只保留一条记录，断言改写为"重复提交不产生重复标签"。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationStageRejection) as excinfo:
        _call(tools, "write_sentence_label", {"sentence": "不存在的句子", "emotion": 0})
    assert excinfo.value.record == "sentence_label/不存在的句子"
    assert excinfo.value.field == "sentence"
    assert excinfo.value.code == "not_found"
    assert "未在当前章节原文中找到唯一匹配" in str(excinfo.value)
    assert ledger.metrics_payload is None
    assert ledger.bound_payloads.get("sentence_labels") in (None, [])

    # 同一句重复提交：同区间更新为一条记录，不报错
    _call(tools, "write_sentence_label", {"sentence": "住手", "emotion": -2})
    _call(tools, "write_sentence_label", {"sentence": "住手", "emotion": -1})
    labels = ledger.bound_payloads["sentence_labels"]
    assert len(labels) == 1
    assert labels[0].emotion == -1
    assert ledger.metrics_payload is None


def test_sentence_label_coverage_warning_below_two() -> None:
    """2026-09-07 用于验证每章不足 2 句时冻结留痕覆盖告警（软下限不阻断）

    2026-09-13 取消暂存：句标签没有整批重交/替换通道，旧"先写两句再重交单句"
    的触发路径改写为直接只提交一条 write_sentence_label 小调用，告警判据不变。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger, sentence_label_calls=_sentence_label_calls([("住手", 0)]))
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
            {
                "case_number": case_number,
                "reason": "误用",
                "foreshadowing_action": "reinforce",
                "root_event_id": "evt-root-1",
                "event_id": "evt-bind-1",
            }
        )
    assert ledger.resolved_cases == []


def test_tone_catalog_accepts_extended_words_and_other_fallback() -> None:
    """2026-09-11 tone 扩表：实测自造高频词入表 + "其他"兜底，非法词仍拒绝

    run e84339d1 实测 13 次 tone 失败全部是模型自造词（得意/惊讶/疲惫/疑惑…），
    8 值词表与自然表达系统性错配。
    2026-09-13 取消暂存：write_dialogues 四元组 → write_dialogue 参数，合法 tone
    写入即进入载荷；2026-09-14 词表进 enum、越界值经记录级转换器报结构化拒绝。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)
    _call(tools, "write_metrics", _write_metrics_args())

    invalid = _reject(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "强装镇定"},
    )
    assert invalid["field"] == "tone"
    assert invalid["code"] == "invalid_value"
    assert "得意" in invalid["expected"] and "其他" in invalid["expected"]
    _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": 1, "tone": "得意"},
    )
    assert ledger.domain_payloads["dialogues"][0].tone == "得意"


def test_tone_enters_model_visible_tool_schema_as_closed_enum() -> None:
    """2026-09-14 语气枚举进工具 schema：取值域写在模型可见面（预防），不是只在被拒后可见

    纯字符串参数 + Field 描述词表时，模型要先自造词撞一次拒绝才看到全表；
    恢复真 enum 后 write_dialogue / resolve_dialogue_case 的参数都是 enum 清单，
    模型一次就能选对。
    """
    service = _QueryService()
    tools = _tools(service, _ledger())
    catalog = [member.value for member in Tone]
    assert len(catalog) >= 20 and "其他" in catalog

    for name in ("write_dialogue", "resolve_dialogue_case"):
        schema = convert_to_openai_tool(_find_tool(tools, name))["function"]["parameters"]
        tone_schema = schema["properties"]["tone"]
        branches = tone_schema if "enum" in tone_schema else next(
            branch for branch in tone_schema.get("anyOf", []) if "enum" in branch
        )
        assert branches["enum"] == catalog


def test_tone_rejection_receipt_is_self_correcting_through_production_path() -> None:
    """2026-09-14 枚举外语气词的拒绝回执必须一次可自纠：指回记录、给出全词表与「其他」

    词表进 schema 后越界调用很少，但一旦发生，回执仍要能自纠（不靠模型再猜一轮）。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        "write_dialogue",
        {"candidate_index": 2, "verdict": "dialogue", "speaker": 1, "tone": "强装镇定"},
    )
    assert receipt["status"] == "rejected"
    assert receipt["record"] == "dialogue/2"
    assert receipt["field"] == "tone"
    assert receipt["code"] == "invalid_value"
    assert "强装镇定" in receipt["message"]
    assert "其他" in receipt["message"]
    assert "平静" in receipt["expected"] and "其他" in receipt["expected"]
    assert not ledger.written_dialogues


def test_entity_number_contract_rejects_names_with_guidance() -> None:
    """2026-09-11 编号合同：实体引用写名称时给出直接可自纠的报错（名称通道已删净）

    2026-09-13 取消暂存：参与记录与关系边都走小调用工具，schema 层编号字段失败
    经生产路径翻成结构化拒绝，message/expected 里保留"写名称该怎么改"的引导。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    ledger.graph_queried = True
    tools = _tools(service, ledger)

    participant_receipt = _reject(
        tools,
        "write_character_participation",
        {
            "tree_key": "t1",
            "node_key": "root",
            "entity": "顾霜",
            "role": "主体",
            "narrative_role": "主体",
            "action": "喝止",
            "emotion": -1,
        },
    )
    assert participant_receipt["record"] == "t1/root/participant/顾霜"
    assert participant_receipt["field"] == "entity"
    assert "实体引用只接受编号（整数），收到名称 顾霜" in participant_receipt["message"]
    assert "运行期编号" in participant_receipt["expected"]
    relation_receipt = _reject(
        tools,
        "write_relation",
        {"from_entity": "顾霜", "to_entity": 2, "relation_type": "友情"},
    )
    assert relation_receipt["field"] == "from_entity"
    assert "实体引用只接受编号（整数），收到名称 顾霜" in relation_receipt["message"]


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


def test_write_dialogue_speaker_name_gets_self_correction_guidance() -> None:
    """2026-09-11 编号合同：write_dialogue speaker 写名称给出可自纠报错

    2026-09-13 取消暂存：四元组数组 → 有类型参数，schema 层编号字段失败经生产
    路径翻成结构化拒绝，引导文案保持在 message 里。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "dialogue", "speaker": "顾霜", "tone": None},
    )
    assert receipt["record"] == "dialogue/1"
    assert receipt["field"] == "speaker"
    assert "实体引用只接受编号（整数），收到名称 顾霜" in receipt["message"]
    assert ledger.written_dialogues == {}
