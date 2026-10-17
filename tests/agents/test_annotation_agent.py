"""章节级标注 Agent（agent 路径，程序面）LangGraph 与 Runner 测试

2026-09-19 双路径定案：agent 路径（单块章）的模型可见面=[execute_code, finish]，模型
把工具调用写成 Python 程序提交；本文件按程序面驱动（_program_message），覆盖：

- 程序内跨领域调用全部生效、逐条独立回滚、失败不阻塞同程序 finish；
- 绑定面恒为 [execute_code, finish]（finish 也可直发，两条通道同一条收尾判定；
  分发面=完整工具表由 ProgramRuntime 执行）；
- 【进度账本】逐请求注入与临近上限收尾提醒；
- Runner 单次尝试/审计/失败回滚与章正文校验。
"""

from __future__ import annotations

import json
import unicodedata
from uuid import NAMESPACE_DNS, uuid5

import pytest
from langchain_core.messages import AIMessage

from src.agents.annotation.ledger import AnnotationToolLedger
from src.agents.annotation.output_models import BoundChapterAnnotation
from src.agents.annotation.validation import validate_bound_annotation
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterMetricsInput, ChapterParagraphInfo
from src.fact_graph.outputs import BoundDialogue, BoundParagraphLabel
from tests.support.annotation_work_tools import build_annotation_tools
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _QueryService:
    """2026-08-07 用于提供无数据库依赖的新合同查询桩"""

    async def search_text(self, query, *, range_name, limit=50):
        """2026-08-07 用于返回空原文候选"""
        del query, range_name, limit
        return []


class _SequenceLLM(StreamedFakeModelMixin):
    """2026-08-07 用于按顺序返回 Agent 消息的测试模型（仅 ainvoke，无流式）"""

    def __init__(self, responses: list[AIMessage]) -> None:
        """2026-08-07 用于保存待返回的模型消息序列"""
        self.responses = list(responses)
        self.calls = 0
        self.captured_messages: list[list] = []

    def bind_tools(self, tools):
        """2026-09-13 用于满足 LangChain 模型绑定合同"""
        return self

    async def ainvoke(self, messages):
        """2026-08-07 用于返回下一条测试模型消息并记录输入"""
        self.calls += 1
        self.captured_messages.append(list(messages))
        return self.responses.pop(0)


def _tool_message(calls: list[dict]) -> AIMessage:
    """2026-08-07 用于构造带工具调用的模型回复"""
    return AIMessage(content="", tool_calls=calls)


def _write_call(
    name: str,
    args: dict,
    *,
    call_id: str,
) -> dict:
    """2026-08-07 用于构造单个工具调用"""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _entity_id(name: str) -> str:
    """2026-09-19 用于按 FactGraph 同款算法铸造实体 run 级 uuid（uuid5(run_scope+归一化名)）

    本文件的 FactGraph() 用默认 run_scope=""（uuid 命名空间键 = "novel-annotation-entity::名"）。
    """
    key = unicodedata.normalize("NFC", name).strip().casefold()
    return str(uuid5(NAMESPACE_DNS, f"novel-annotation-entity::{key}"))


# ----------------------------------------------------------------------
# 程序面驱动：模型回复=一条 execute_code 调用，code 里的语句即工具调用


def _program_message(code: str, call_id: str = "call-program") -> AIMessage:
    """2026-09-19 用于构造一条 execute_code 程序回复（程序内的语句即工具调用）"""
    return _tool_message([_write_call("execute_code", {"code": code}, call_id=call_id)])


def _entity_stmt(
    name: str = "顾霜",
    entity_type: str = "character",
    *,
    extra_args: str = "",
) -> str:
    """2026-09-19 用于构造 write_entity 程序语句（el=章内引用键）"""
    return f'write_entity(name="{name}", entity_type="{entity_type}", el="{name}"{extra_args})'


def _metrics_stmt(*, labels: bool = True) -> str:
    """2026-09-19 用于构造 write_metrics 程序语句（段落标签随本域提交）"""
    labels_arg = ', labels=[{"paragraph_id": 1, "emotion": -2}]' if labels else ""
    return f'write_metrics(summary="住手回荡", emotional_valence=0, narrative_function="铺垫"{labels_arg})'


def _event_root_stmt(
    tree_key: str = "t1",
    description: str = "顾霜喝止众人",
    action: str = "喝止",
    *,
    emotion: int = -1,
) -> str:
    """2026-09-19 用于构造 write_event 根事件程序语句"""
    return (
        f'write_event(el="{tree_key}", isroot=True, description="{description}", '
        'characters=[{"name": "顾霜", "entity_type": "character", "role": "主体", "narrative_role": "主体", '
        f'"action": "{action}", "emotion": {emotion}}}])'
    )


def _event_child_stmt(
    tree_key: str = "t1",
    child_key: str = "e1",
    description: str = "顾霜收势",
    action: str = "收势",
    *,
    emotion: int = 0,
) -> str:
    """2026-09-19 用于构造 write_event 子事件程序语句"""
    return (
        f'write_event(el="{tree_key}/{child_key}", isroot=False, type="main", '
        f'description="{description}", '
        'characters=[{"name": "顾霜", "entity_type": "character", "role": "主体", "narrative_role": "主体", '
        f'"action": "{action}", "emotion": {emotion}}}])'
    )


def _relation_stmt() -> str:
    """2026-09-19 用于构造 write_relation 程序语句（两端=实体引用）"""
    return 'write_relation(from_entity="顾霜", to_entity="褚大山", relation_type="敌对")'


def _dialogue_stmt() -> str:
    """2026-09-19 用于构造 write_dialogue 程序语句（第一条候选判为真实对话）"""
    return 'write_dialogue(candidate_index=1, verdict="dialogue", speaker=None, tone="平静")'


def _finish_stmt() -> str:
    """2026-09-19 用于构造 finish 收尾声明（工具体只回 pending，程序末尾结算）"""
    return "finish()"


def _serial_program_messages() -> list[AIMessage]:
    """2026-09-19 用于构造三轮程序回复：实体+指标 → 事件树 → 对话+finish"""
    return [
        _program_message("\n".join([_entity_stmt(), _metrics_stmt()])),
        _program_message("\n".join([_event_root_stmt(), _event_child_stmt()])),
        _program_message("\n".join([_dialogue_stmt(), _finish_stmt()])),
    ]


def _bound_annotation(*, summary: str = "顾霜进入山门") -> BoundChapterAnnotation:
    """2026-08-07 用于构造 Runner 重试测试的最小章节标注（2026-09-19 章即块拍平）"""
    return BoundChapterAnnotation(
        metrics=ChapterMetricsInput(
            summary=summary,
            emotional_valence=0,
            narrative_function="铺垫",
        ),
        character_observations=[],
        dialogues=[],
        events=[],
    )


def _tool_receipts(captured_round: list) -> list[str]:
    """2026-08-10 用于提取某轮模型请求中的全部 ToolMessage 内容"""
    return [str(message.content) for message in captured_round if getattr(message, "type", "") == "tool"]


@pytest.mark.asyncio
async def test_second_write_entities_appends_to_catalog_not_replaces() -> None:
    """2026-08-26 回归（2026-09-04 单一写面改契约为 op log）：实体登记追加语义必须落进 FactGraph

    2026-09-13 小调用改造后一次登记一个实体（write_entity），op log 仍按提交顺序
    累积；同名重交按更新语义覆盖（tags/description 增量）。
    """
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[0],
            char_spans=[(0, 4)],
            texts=["住手回荡"],
        ),
    )
    tools = build_annotation_tools(_QueryService(), ledger)
    by_name = {tool.name: tool for tool in tools}
    await by_name["write_entity"].ainvoke(
        {"name": "侯飞白", "entity_type": "character", "el": "侯飞白", "description": "贺军情报头子之子"}
    )
    await by_name["write_entity"].ainvoke({"name": "褚大山", "entity_type": "character", "el": "褚大山"})
    await by_name["write_entity"].ainvoke(
        {"name": "猴子", "entity_type": "character", "el": "猴子", "description": "侯飞白外号"}
    )
    await by_name["write_entity"].ainvoke(
        {"name": "侯飞白", "entity_type": "character", "el": "侯飞白", "tags": ["小孩"]}
    )
    assert "entities" not in ledger.bound_payloads
    ops = ledger.graph.entity_ops
    assert [op["name"] for op in ops] == ["侯飞白", "褚大山", "猴子", "侯飞白"]
    assert ops[0]["description"] == "贺军情报头子之子"
    assert ops[3]["tags"] == ["小孩"]


@pytest.mark.asyncio
async def test_entity_reregistration_same_content_is_idempotent() -> None:
    """2026-09-13 同键同内容重放返回相同 written 回执且不重复写操作日志（重试不重复造数据）"""
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="住手回荡",
        allow_future_context=False,
        graph=FactGraph(),
    )
    tools = {tool.name: tool for tool in build_annotation_tools(_QueryService(), ledger)}
    first = await tools["write_entity"].ainvoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    replay = await tools["write_entity"].ainvoke({"name": "顾霜", "entity_type": "character", "el": "顾霜"})
    assert json.loads(first) == json.loads(replay)
    assert len(ledger.graph.entity_ops) == 1


def test_validate_bound_annotation_verifies_dialogue_original_text() -> None:
    """2026-08-07 用于验证对话原文位置与内容由系统绑定且可回查"""
    annotation = _bound_annotation()
    annotation.dialogues = [
        BoundDialogue(
            candidate_index=1,
            candidate_key="dlg_1",
            content="住手",
            start=0,
            end=2,
        )
    ]
    with pytest.raises(ValueError):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            chapter_text="顾霜进入山门",
        )


def test_validate_bound_annotation_verifies_paragraph_label_membership() -> None:
    """2026-09-14 段落级监督：自选段标签复核改段落号归属（段号没有逐字复核的对象）"""
    annotation = _bound_annotation()
    paragraph_info = ChapterParagraphInfo(
        paragraph_ids=[0, 1],
        char_spans=[(0, 4), (4, 9)],
        texts=["顾霜“住手”", "回荡"],
    )
    annotation.paragraph_labels = [BoundParagraphLabel(paragraph_id=0, emotion=0)]
    validate_bound_annotation(
        annotation,
        chapter_id=1,
        chapter_text="顾霜“住手”回荡",
        paragraph_info=paragraph_info,
    )
    annotation.paragraph_labels = [BoundParagraphLabel(paragraph_id=9, emotion=0)]
    with pytest.raises(ValueError):
        validate_bound_annotation(
            annotation,
            chapter_id=1,
            chapter_text="顾霜“住手”回荡",
            paragraph_info=paragraph_info,
        )
