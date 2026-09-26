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
from uuid import NAMESPACE_DNS, uuid5

import pytest
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
    ChapterParagraphInfo,
    DialogueInput,
    EntityInput,
    EventParticipantInput,
    RelationInput,
    SearchResult,
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

    def _case(self) -> CaseSearchResult:
        """2026-08-07 用于构造一个可严格解决的活动案例"""
        return CaseSearchResult(
            id="case-1",
            type="dialogue_speaker",
            chapter_id=10,
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
                "chapter_id": 10,
                "start": 1,
                "end": 3,
                "text": "住手",
            },
        )

    def has_dialogue_record(self, candidate_key: str) -> bool:
        """2026-09-18 用于回答对话记录是否已在本 run 落库（订正既有记录的前置校验）"""
        return candidate_key in self.known_dialogue_ids


class _AliasQueryService(_QueryService):
    """2026-08-09 用于提供 entity_alias 类型的活动案例"""

    def _case(self) -> CaseSearchResult:
        """2026-08-09 用于构造疑似同一人物案例"""
        return CaseSearchResult(
            id="alias-1",
            type="entity_alias",
            chapter_id=10,
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
            target_ref={"kind": "alias", "name_a": "顾霜", "name_b": "顾老", "chapter_id": 10},
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
            chapter_id=99,
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
            target_ref={"kind": "alias", "name_a": "顾霜", "name_b": "顾老", "chapter_id": 99},
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


def _entity_id(name: str) -> str:
    """2026-09-19 用于按生产同款规则铸造期望实体 id（uuid5(run_scope+归一化名)）

    本文件的 FactGraph 都用默认 run_scope=""（与 _ledger 的 run_scope 无关，
    id 铸造读的是 ledger.graph），期望值据此计算。
    """
    return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity::{name.casefold()}"))


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


def _surface_case(service: _QueryService, ledger: AnnotationToolLedger, *, query: str = "住手") -> str:
    """2026-09-11 案例改检索制；2026-09-19 案例面 id 化：经 search_pool 展示案例取得 id（展示即授权）

    旧合同用例直接调 register_initial_cases 登记初始候选；新合同下案例 id 只能由
    search_pool 回执产生（案例池行 uuid），测试准备阶段也走同一通道。
    """
    view = _call(_tools(service, ledger), "search_pool", {"query": query})
    return str(view["results"][0]["id"])


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
    status=completed/chapter_id/records/dialogue_defaulted，都不回传完整载荷。
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

    domain_receipt = _finish_chapter(tools, ledger)
    assert set(domain_receipt) == {"status", "chapter_id", "records", "dialogue_defaulted"}
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
        "dialogue_defaulted": [1],
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


def test_dialogue_defaults_missing_candidates_to_not_dialogue() -> None:
    """2026-08-12 用于验证缺失候选软覆盖为 not_dialogue，收尾回执列出默认处理的序号

    2026-09-13 取消暂存：默认处理推迟到唯一收尾声明时一次执行（旧合同在
    finish_domain("dialogues") 结算时执行）；同序号重交是更新语义，旧"重复
    candidate_index 报错"断言改写为"同序号只保留一条记录"，越界仍拒绝（结构化
    拒绝记录键/字段/错误码）。2026-09-14 收尾改名 finish。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    _call(tools, "write_metrics", _write_metrics_args())

    # 未提交判定：候选 1 在收尾时默认 not_dialogue，回执列出
    response = _finish_chapter(tools, ledger)
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
    response = _finish_chapter(filled_tools, filled)
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
    response = _finish_chapter(replay_tools, replay)
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


def test_write_entity_allowed_after_search_graph() -> None:
    """2026-08-09 用于验证 search_graph 之后可正常登记实体

    2026-09-13 取消暂存：提交形态变为单个实体，回执带运行期编号 n，写入即生效。
    2026-09-14 写入面重构：回执另带 el 绑定回显（NFC 归一键）。
    2026-09-14 检索前置闸门删除后，本用例保留为"检索后登记照常可用"的回归面。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character"})
    tools = _tools(service, ledger)

    _call(tools, "search_graph", {"entities": ["顾霜"]})
    receipt = _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    assert receipt == {
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


def test_complete_chunk_accepts_registered_entity_endpoint_without_declaration() -> None:
    """2026-08-09 用于验证已登记实体可直接作为事实端点，无需当前 chunk 重复声明

    2026-09-13 取消暂存：本章不登记实体时直接不写 write_entity（不再需要
    finish_domain("entities") 空域声明），事件参与者用 search_graph 回执编号
    直接引用历史实体，chunk 仍可收尾完成。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "伯安": "character"})
    tools = _tools(service, ledger)

    _write_all_domains(tools, ledger, entity_calls=[])

    assert ledger.domain_payloads["entities"].entities == []
    assert ledger.written_entities == {}
    ledger.complete_active_chapter()
    assert [item.character for item in ledger.bound_payloads["character_observations"]] == ["顾霜", "顾霜"]


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


def test_search_pool_numbers_cases_and_hides_resolved_from_pool() -> None:
    """2026-08-11 用于验证案例编号由 search_pool 回执产生且解决后不可重复、后续检索隐藏

    2026-09-18 案例面收窄：resolve_dialogue_case 等三个裁决工具删净，案例出口只剩
    close_case（无产出）与 promise_case（指向产出记录），本用例改走 close_case 走
    同一条编号授权链与"已解决案例不再出现"的检索隐藏语义。
    """
    service = _QueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert [item["result_kind"] for item in view["results"]] == ["case"]
    case_id = view["results"][0]["id"]
    response = json.loads(
        _find_tool(tools, "close_case").invoke({"case_id": case_id, "reason": "非连续性疑点"})
    )
    assert response["accepted"] is True
    assert response["action"] == "close"
    assert ledger.resolved_cases[0].case_id == "case-1"
    assert ledger.resolved_cases[0].action == "close"

    with pytest.raises(AnnotationInputError):
        _find_tool(tools, "close_case").invoke({"case_id": case_id, "reason": "重复"})
    hidden = json.loads(_find_tool(tools, "search_pool").invoke({"query": "住手"}))
    assert hidden["results"] == []


def test_write_dialogue_update_requires_declared_character_speaker() -> None:
    """2026-08-11 用于验证对话更新 speaker 必须是已登记或本章声明的人物

    2026-09-18 对话更新下沉到 write_dialogue(candidate_key=...)：speaker 仍是实体引用
    （2026-09-19 id 纪律：run 级 uuid id / el 键），未登记 id 在解析点结构化拒绝
    （code=unknown_entity_id，record 指向该对话记录）；解析成功后按登记名写进
    case_id 为空的 dialogue 解决项。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})

    dialogue_id = "dlg_prev_1"
    with pytest.raises(AnnotationStageRejection) as excinfo:
        _find_tool(tools, "write_dialogue").invoke(
            {"candidate_key": dialogue_id, "speaker": "00000000-0000-0000-0000-000000000987"}
        )
    assert excinfo.value.record == f"dialogue/{dialogue_id}"
    assert excinfo.value.field == "speaker"
    assert excinfo.value.code == "unknown_entity_id"

    response = json.loads(
        _find_tool(tools, "write_dialogue").invoke(
            {"candidate_key": dialogue_id, "speaker": "顾霜", "description": "后文点明"}
        )
    )
    assert response["status"] == "written"
    assert response["content"]["speaker"] == "顾霜"
    last = ledger.resolved_cases[-1]
    assert last.action == "dialogue"
    assert last.case_id == ""
    assert last.target_key == dialogue_id
    assert last.speaker == "顾霜"


def test_close_case_only_closes_alias_case() -> None:
    """2026-08-11 用于验证确认非同一人物用 close_case 只关闭案例不产生变化"""
    service = _AliasQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    case_id = "alias-1"
    response = json.loads(
        _find_tool(tools, "close_case").invoke({"case_id": case_id, "reason": "夫妻关系非同一人物"})
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[0].case_id == "alias-1"
    assert ledger.resolved_cases[0].action == "close"

    with pytest.raises(AnnotationInputError):
        _find_tool(tools, "close_case").invoke({"case_id": case_id, "reason": "重复"})


def test_write_relation_create_kind_confirms_edge_without_case() -> None:
    """2026-08-11 用于验证显式 change_kind=新增 与省略等价：按建边处理且不产生案例

    2026-09-18 fact 裁决下沉到写入路径：关系变化不再经案例池，也不进 resolved_cases——
    建边只进 FactGraph（assert 操作日志 + 终态），"新增"走建边而非变化日志。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    receipt = _call(
        tools,
        "write_relation",
        {
            "from_entity": _entity_id("顾霜"),
            "to_entity": _entity_id("顾老"),
            "relation_type": "同一人物",
            "change_kind": "新增",
        },
    )
    assert receipt["status"] == "written"
    assert receipt["outcome"] == "assert"
    assert ledger.resolved_cases == []
    assert ledger.graph.relation_exists("顾霜", "顾老", "同一人物") is True
    assert ledger.graph.relation_change_ops == []
    assert [
        (op["from_entity"], op["to_entity"], op["relation_type"])
        for op in ledger.graph.relation_assert_ops
    ] == [("顾霜", "顾老", "同一人物")]


def test_write_relation_break_hides_edge_from_search_graph() -> None:
    """2026-09-04 第4章死锁回归：解除后内存图同步解除，search_graph 不得再显示该边

    2026-09-18 解除下沉到 write_relation(change_kind=解除)：端点按规范名提交，
    变化进图变更日志且 case_id 为空（写入路径自己发起，不是案例裁决）。此前裁决
    只写 resolved_cases、不动 FactGraph，模型"解除成功"后 search_graph 仍返回同一条
    边，导致修复-验证循环打满 15 轮上限。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph.apply_relation(_graph_relation("顾霜", "顾老", "同一人物"))
    tools = _tools(service, ledger)

    # 先确认边在图中可见
    before = json.loads(
        _find_tool(tools, "search_graph").invoke({"entities": ["顾霜", "顾老"], "relation_type": None})
    )
    assert len(before["relations"]) == 1

    receipt = _call(
        tools,
        "write_relation",
        {
            "from_entity": _entity_id("顾霜"),
            "to_entity": _entity_id("顾老"),
            "relation_type": "同一人物",
            "change_kind": "解除",
        },
    )
    assert receipt["status"] == "written"
    assert receipt["outcome"] == "break"

    after = json.loads(
        _find_tool(tools, "search_graph").invoke({"entities": ["顾霜", "顾老"], "relation_type": None})
    )
    assert after["relations"] == []
    assert ledger.graph.relation_exists("顾霜", "顾老", "同一人物") is False
    change_op = ledger.graph.relation_change_ops[0]
    assert change_op["change_kind"] == "break"
    assert change_op["case_id"] == ""
    assert change_op["target_ref"] == {"chapter_id": 10, "change_index": 0}


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
            "change_kind": "新增",
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


def test_case_resolution_authorized_on_initial_display() -> None:
    """2026-08-30 用于验证初始案例展示即授权其源章无需额外原文工具

    2026-09-18 案例出口收成 close_case/promise_case：展示授权链不变（search_pool
    展示即登记源章），本用例把原 fact 裁决换成 close_case，仍断言锚定旧章的案例
    在展示后可直接解决、无需先读原文。
    """
    service = _ForeignChunkQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    assert 99 in ledger.authorized_chapter_ids
    tools = _tools(service, ledger)

    case_id = "foreign-1"
    response = json.loads(
        _find_tool(tools, "close_case").invoke(
            {"case_id": case_id, "reason": "确认非同一人物"}
        )
    )
    assert response["accepted"] is True
    assert response["action"] == "close"
    assert ledger.resolved_cases[-1].case_id == "foreign-1"
    assert ledger.resolved_cases[-1].target_key == "target-foreign-1"


def test_foreign_case_resolution_allowed_after_text_search_authorization() -> None:
    """2026-08-30 用于验证检索旧章正文时即时授权精确段落

    2026-09-18 把原 fact 裁决换成 close_case：search_text 的段落授权登记与展示源章
    授权链不变，锚定旧章的案例在原文检索后可直接解决。
    """
    import asyncio

    service = _ForeignChunkQueryService()
    ledger = _ledger()
    _surface_case(service, ledger)
    tools = _tools(service, ledger)

    search = json.loads(asyncio.run(_find_tool(tools, "search_text").ainvoke({"query": "顾霜"})))
    assert search[0]["content"] == "顾霜喝道"
    # 展示授权源章；search_text 即时登记真实 SQL 命中段落
    assert 99 in ledger.authorized_chapter_ids
    assert 99 in ledger.authorized_text_paragraph_ids

    case_id = "foreign-1"
    response = json.loads(
        _find_tool(tools, "close_case").invoke(
            {"case_id": case_id, "reason": "确认非同一人物"}
        )
    )
    assert response["accepted"] is True
    assert ledger.resolved_cases[-1].case_id == "foreign-1"


def test_write_event_foreshadowing_attach_requires_closed_params() -> None:
    """2026-09-13 用于验证伏笔挂边只接受闭合参数面

    2026-09-18 伏笔挂边下沉到 write_event：foreshadowing_action 与 root_event_id
    必须同时给、action 只取 reinforce/payoff；单给一边即结构化拒绝且不留解决项。
    2026-09-19 挂边顺带更新树根属性：payoff_likelihood/strength 进参数面，但只在挂边时
    有效——没挂边就单给这两个参数按 not_on_attach 拒绝（它们改的是树根，不是本节点）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    orphan_likelihood = _reject(
        tools,
        ledger,
        "write_event",
        {"el": "t9", "isroot": True, "description": "伏笔", "payoff_likelihood": "high"},
    )
    assert orphan_likelihood["status"] == "rejected"
    assert orphan_likelihood["field"] == "payoff_likelihood"
    assert orphan_likelihood["code"] == "not_on_attach"

    orphan_strength = _reject(
        tools,
        ledger,
        "write_event",
        {"el": "t9", "isroot": True, "description": "伏笔", "strength": "low"},
    )
    assert orphan_strength["code"] == "not_on_attach"

    action_only = _reject(
        tools,
        ledger,
        "write_event",
        {"el": "t9", "isroot": True, "description": "伏笔", "foreshadowing_action": "reinforce"},
    )
    assert action_only["status"] == "rejected"
    assert action_only["record"] == "t9/root"
    assert action_only["field"] == "foreshadowing_action"
    assert action_only["code"] == "invalid_call"

    root_only = _reject(
        tools,
        ledger,
        "write_event",
        {"el": "t9", "isroot": True, "description": "伏笔", "root_event_id": "evt-root-1"},
    )
    assert root_only["code"] == "invalid_call"

    foreign_action = _reject(
        tools,
        ledger,
        "write_event",
        {
            "el": "t9",
            "isroot": True,
            "description": "伏笔",
            "foreshadowing_action": "expand",
            "root_event_id": "evt-root-1",
        },
    )
    assert foreign_action["code"] == "invalid_call"
    assert ledger.resolved_cases == []


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


def test_promise_case_rejects_unknown_result_id() -> None:
    """2026-09-18 result_id 必须是本章已经写出来的记录

    未命中按结构化拒绝回（code=unknown_record），案例不落已解决项。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    case_id = _surface_case(service, ledger)
    receipt = _reject(
        tools,
        ledger,
        "promise_case",
        {"case_id": case_id, "result_id": "dlg_not_exist"},
    )
    assert receipt["status"] == "rejected"
    assert receipt["field"] == "result_id"
    assert receipt["code"] == "unknown_record"
    assert ledger.resolved_cases == []


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


def test_push_case_without_setup_id_then_foreshadowing_attach_binds_tree() -> None:
    """2026-09-13 伏笔即事件树：push_case 不再带 setup_id；续接以章内局部键挂树

    2026-09-18 伏笔挂边下沉到 write_event（foreshadowing_action + root_event_id）：
    节点照常写进本章事件树，另记一条 case_id 为空的 foreshadowing 解决项——真实节点
    id 由账本内部持有，模型面只用章内局部键（t1、t2）。
    """
    service = _QueryService()
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
    assert "setup_id" not in pushed.target_ref

    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "守护誓言埋下",
            "isforeshadowing": True,
            "confidence": "high",
        },
    )
    _call(
        tools,
        "write_event",
        {"el": "t1/e1", "isroot": False, "type": "main", "description": "守护誓言再次出现"},
    )
    # 写入即生效：章内局部键随时可解析（旧合同要等事件域结算才生成真实 id）
    root_event_id = ledger.resolve_event_reference("t1")
    assert root_event_id is not None

    attachment = _call(
        tools,
        "write_event",
        {
            "el": "t2",
            "isroot": True,
            "description": "本章续接",
            "foreshadowing_action": "reinforce",
            "root_event_id": "t1",
        },
    )
    event_id = ledger.resolve_event_reference("t2")
    assert event_id is not None
    assert attachment["content"]["foreshadowing"] == {
        "action": "reinforce",
        "root_event_id": root_event_id,
        "event_id": event_id,
    }
    last = ledger.resolved_cases[-1]
    assert last.case_id == ""
    assert last.action == "foreshadowing"
    assert last.foreshadowing_action == "reinforce"
    assert last.foreshadowing_root_event_id == root_event_id
    assert last.foreshadowing_event_id == event_id


def test_foreshadowing_attach_updates_root_confidence() -> None:
    """2026-09-19 挂边顺带更新树根：payoff_likelihood/strength 落进无案例的 foreshadowing 解决项

    落库层按这两个字段改根属性（`_persist_foreshadowing_resolution`），此前写入路径没接，
    于是"本章证据改变了回收预期"只能靠新建树表达。这里断言解决项带值、回执回显更新值。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    _call(tools, "write_entity", {"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    _call(
        tools,
        "write_event",
        {
            "el": "t1",
            "isroot": True,
            "description": "守护誓言埋下",
            "isforeshadowing": True,
            "confidence": "low",
        },
    )
    attachment = _call(
        tools,
        "write_event",
        {
            "el": "t2",
            "isroot": True,
            "description": "本章回收",
            "foreshadowing_action": "payoff",
            "root_event_id": "t1",
            "payoff_likelihood": "high",
            "strength": "medium",
        },
    )
    assert attachment["content"]["foreshadowing"] == {
        "action": "payoff",
        "root_event_id": ledger.resolve_event_reference("t1"),
        "event_id": ledger.resolve_event_reference("t2"),
        "payoff_likelihood": "high",
        "strength": "medium",
    }
    resolved = ledger.resolved_cases[-1]
    assert resolved.case_id == ""
    assert resolved.action == "foreshadowing"
    assert resolved.foreshadowing_action == "payoff"
    assert resolved.payoff_likelihood == "high"
    assert resolved.strength == "medium"


def test_search_pool_requires_query_or_case_type() -> None:
    """2026-09-11 案例改检索制：query 与 case_type 至少提供一个，双空直接拒绝"""
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    with pytest.raises(AnnotationInputError):
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
    assert "case_type" in view["hint"]
    assert "all" in view["hint"]
    # 未知 case_type 名时提示直接给出池内真实类型名（避免模型继续猜标签）
    assert "entity_alias" in view["hint"]
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
                chapter_id=3,
                created_chapter=3,
                keys=["同一人物", "顾霜", "顾老"],
                description="疑似同一人物：顾霜 与 顾老",
            )

    service = _EnumeratingService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    view = json.loads(_find_tool(tools, "search_pool").invoke({"case_type": "entity_alias"}))
    assert view["results"][0]["id"]
    assert view["results"][0]["type"] == "entity_alias"
    assert view["results"][0]["created_chapter"] == 3
    assert view["truncated"] is True
    assert ledger.search_log[-1]["case_type"] == "entity_alias"
    assert ledger.search_log[-1]["query"] is None
    # 枚举展示同样授权源章（案例展示即授权）
    assert ledger.authorized_chapter_ids == {3}


def test_case_id_from_pool_requires_search_surfacing() -> None:
    """2026-09-11 授权链收紧；2026-09-19 案例 id 化：未经 search_pool 展示的案例 id 不可用

    检索制下案例不再注入，案例 id 只能由 search_pool 回执产生；模型若凭空使用 id，
    拒绝信息必须指回检索通道（而不是旧合同的"初始候选"）。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    assert ledger.known_case_ids == set()
    with pytest.raises(AnnotationAuthorizationError):
        _find_tool(tools, "close_case").invoke({"case_id": "case-1", "reason": "凭空引用"})


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


def test_write_dialogue_update_rejects_foreign_tone_word() -> None:
    """2026-09-14 更新路径与判定路径同口径：枚举外语气词在参数绑定层被拒

    2026-09-18 案例裁决退役后 tone 拒绝对齐 write_dialogue(candidate_key=...) 更新入口：
    记录级转换器给出全词表与「其他」兜底指引，失败不留解决项。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)

    receipt = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_key": "dlg_prev_1", "tone": "激动"},
    )
    assert receipt["status"] == "rejected"
    assert receipt["field"] == "tone"
    assert receipt["code"] == "invalid_value"
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
    tools = _tools(service, ledger)

    receipt = _call(
        tools,
        "write_relation",
        {"from_entity": _entity_id("顾霜"), "to_entity": _entity_id("顾老"), "relation_type": "友情"},
    )
    assert receipt == {
        "status": "written",
        "record": "relation/顾霜-顾老/友情",
        "outcome": "skipped_existing",
        "content": {"from_entity": "顾霜", "to_entity": "顾老", "relation_type": "友情"},
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
        "outcome": "skipped_self_loop",
        "content": {"from_entity": "猴子", "to_entity": "侯飞白", "relation_type": "友情"},
    }
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
    assert isinstance(payload["matches"][0]["id"], str)
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


def test_write_relation_rejects_foreign_change_kind() -> None:
    """2026-08-12 用于验证关系变化的 change_kind 必须是闭合关系变化枚举（避免下游整章回滚）

    2026-09-18 变化入口从案例裁决换成 write_relation：枚举外中文值仍在参数绑定层
    被拒，回执给出全闭集，失败不落图变更日志。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    # 2026-09-11 change_kind 已中文化，契约枚举在参数校验层直接拒绝非法值
    receipt = _reject(
        tools,
        ledger,
        "write_relation",
        {
            "from_entity": "00000000-0000-0000-0000-000000000001",
            "to_entity": "00000000-0000-0000-0000-000000000002",
            "relation_type": "同一人物",
            "change_kind": "强化关系",
        },
    )
    assert receipt["status"] == "rejected"
    assert receipt["field"] == "change_kind"
    assert receipt["code"] == "invalid_value"
    assert ledger.graph.relation_change_ops == []
    assert ledger.resolved_cases == []


def test_write_dialogue_update_guards_state_and_requires_update_fields() -> None:
    """2026-09-18 对话更新下沉到写入路径后的前置校验：状态不对/无字段/标识不存在都结构化拒绝

    本章候选必须先判过且判成真对话/独白才能订正（candidate_not_judged / not_dialogue），
    非本章候选问一次库（has_dialogue_record，unknown_record），四个更新字段一个不给是
    no_update；成功时解决项指向对话记录标识且 case_id 为空。
    """
    service = _QueryService()
    ledger = _ledger()
    tools = _tools(service, ledger)
    dialogue_id = ledger.dialogue_candidates[0].candidate_key

    not_judged = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_key": dialogue_id, "tone": "平静"},
    )
    assert not_judged["code"] == "candidate_not_judged"
    assert not_judged["record"] == f"dialogue/{dialogue_id}"

    _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "not_dialogue", "speaker": None, "tone": None},
    )
    not_dialogue = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_key": dialogue_id, "tone": "平静"},
    )
    assert not_dialogue["code"] == "not_dialogue"

    unknown = _reject(
        tools,
        ledger,
        "write_dialogue",
        {"candidate_key": "dlg_not_exist", "tone": "平静"},
    )
    assert unknown["code"] == "unknown_record"

    _call(
        tools,
        "write_dialogue",
        {"candidate_index": 1, "verdict": "inner_monologue", "speaker": None, "tone": None},
    )
    no_update = _reject(tools, ledger, "write_dialogue", {"candidate_key": dialogue_id})
    assert no_update["code"] == "no_update"
    assert no_update["record"] == f"dialogue/{dialogue_id}"

    response = json.loads(
        _find_tool(tools, "write_dialogue").invoke(
            {"candidate_key": dialogue_id, "description": "改判为独白", "is_inner_monologue": True}
        )
    )
    assert response["status"] == "written"
    last = ledger.resolved_cases[-1]
    assert last.case_id == ""
    assert last.action == "dialogue"
    assert last.target_ref == {"chapter_id": 10, "candidate_key": dialogue_id}
    assert last.description == "改判为独白"
    assert last.is_inner_monologue is True


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
    chunk = ledger.complete_active_chapter()

    assert ledger.phase == "completed"
    assert chunk.dialogues == []
    assert chunk.coverage_warnings == [
        "对话覆盖: 2 条候选未提交判定（序号 [1, 2]），按 not_dialogue 默认处理"
    ]


def test_partial_dialogue_judgement_freezes_with_defaulted_warning() -> None:
    """2026-09-05 A1：候选未逐条提交（按 not_dialogue 默认）时冻结 chunk 留痕告警

    2026-09-13 取消暂存：只提交候选 1 的 write_dialogue 小调用，候选 2 在
    finish 收尾时默认处理（2026-09-14 收尾声明改名）。
    """
    ledger = _ledger_with_text("“住手”她喝止，“退下。”")
    tools = _tools(_QueryService(), ledger)

    _write_all_domains_with_dialogues(
        tools,
        ledger,
        _dialogue_calls([(1, "dialogue", None, None)]),
    )
    chunk = ledger.complete_active_chapter()

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


def test_search_graph_exposes_runtime_ids_not_internal_keys() -> None:
    """2026-09-19 id 纪律：search_graph 回执带 run 级 uuid id，内部定位键不进模型视图"""
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    tools = _tools(service, ledger)

    payload = json.loads(_find_tool(tools, "search_graph").invoke({"entities": ["顾霜"], "relation_type": None}))
    match = payload["matches"][0]
    assert match["id"] == _entity_id("顾霜")
    assert match["name"] == "顾霜"
    assert "entity_id" not in match


def test_write_relation_maps_chinese_change_kind_to_internal_value() -> None:
    """2026-09-11 change_kind 中文化：模型写中文值，操作日志落内部英文值（持久化契约不变）

    2026-09-18 变化入口从案例裁决换成 write_relation：同一张 RELATION_CHANGE_KIND_LABELS
    译表仍在写入路径生效，案例字段一律为空（不进案例锁定与解决映射）。
    """
    service = _QueryService()
    ledger = _ledger()
    ledger.graph = _graph_with_entities({"顾霜": "character", "顾老": "character"})
    ledger.graph.apply_relation(_graph_relation("顾霜", "顾老", "同一人物"))
    tools = _tools(service, ledger)

    receipt = _call(
        tools,
        "write_relation",
        {
            "from_entity": _entity_id("顾霜"),
            "to_entity": _entity_id("顾老"),
            "relation_type": "同一人物",
            "change_kind": "强化",
        },
    )
    assert receipt["status"] == "written"
    assert receipt["outcome"] == "reinforce"
    assert ledger.graph.relation_change_ops[0]["change_kind"] == "reinforce"
    assert ledger.graph.relation_change_ops[0]["case_id"] == ""
    assert ledger.resolved_cases == []


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
