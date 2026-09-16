"""2026-09-16 章内并行 CodeAct 块代理面合同测试

覆盖落地方案的块面边界：构造器当场校验当场生效（写入即生效的块内版本）、
evidence NFC 唯一命中核验、未知引用/枚举越界/三态缺失一律记录级结构化拒绝且
只废该条（程序继续跑）、检索走与写者面同一条单条事务边界、
块内句柄口径（B<n>:<key>）、会话结束时的悬空引用复核。

块代理不写正式账本、不裁决案例：这些测试同时断言账本写入面保持为空。
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.block_program import BlockProgramRuntime, build_block_constructors
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.local_ir import BlockAnnotation
from src.agents.annotation.schema import ChunkParagraphInfo, SearchResult
from src.agents.annotation.tools import AnnotationToolLedger


class _QueryService:
    """2026-09-16 用于提供无数据库依赖的查询桩"""

    def search_pool(self, query, *, hidden_case_ids, case_type=None, limit=50, pending_cases=()):
        """用于返回空案例检索结果"""
        del query, hidden_case_ids, case_type, limit, pending_cases
        return SearchResult()

    async def search_text(self, query, *, range_name, limit=50):
        """用于返回空正文命中"""
        del query, range_name, limit
        return []

    def search_event_history(self, query, *, limit=50):
        """用于返回空历史事件树"""
        del query, limit
        return []


_PARAGRAPHS = (
    "“住手！”顾霜喝道。",
    "她收起长刀，转身走进雨里。",
)


def _setup() -> tuple[AnnotationToolLedger, BlockAnnotation, BlockProgramRuntime]:
    """用于按生产装配方式构造块程序面（两段正文、一个候选）"""
    text = "".join(_PARAGRAPHS)
    split = len(_PARAGRAPHS[0])
    paragraph_info = ChunkParagraphInfo(
        paragraph_ids=[11, 12],
        char_spans=[(0, split), (split, len(text))],
        texts=list(_PARAGRAPHS),
    )
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=-1,
        current_chunk_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=paragraph_info,
    )
    block = BlockAnnotation(block_index=0, block_chunk_id=-1, block_text=text)
    runtime = BlockProgramRuntime(_QueryService(), ledger, block)
    return ledger, block, runtime


async def _run(runtime: BlockProgramRuntime, code: str) -> dict:
    """用于执行程序并解析压缩回执"""
    return json.loads(await runtime.execute(code))


@pytest.mark.asyncio
async def test_constructors_build_local_objects_with_handles() -> None:
    """构造器当场生效：回执给句柄，变量可承接，块内引用按短键闭合"""
    ledger, block, runtime = _setup()
    receipt = await _run(
        runtime,
        """
ev_person = [{"paragraph_id": 11, "quote": "顾霜"}]
ev_item = [{"paragraph_id": 12, "quote": "长刀"}]
ev_rel = [{"paragraph_id": 12, "quote": "她收起长刀"}]
ev_talk = [{"paragraph_id": 11, "quote": "住手！"}]
ev_event = [{"paragraph_id": 11, "quote": "顾霜喝道"}]
ev_act = [{"paragraph_id": 11, "quote": "喝道"}]
gs = mention(key="m1", name="顾霜", entity_type="character", evidence=ev_person)
knife = mention(key="m2", name="长刀", entity_type="item", evidence=ev_item)
relation(key="r1", from_mention="m1", to_mention="m2", relation_type="利益", evidence=ev_rel)
dialogue(key="d1", candidate_index=1, verdict="dialogue", speaker="m1", tone="愤怒", evidence=ev_talk)
local_event(key="e1", description="顾霜喝止", evidence=ev_event)
participant(event="e1", entity="m1", role="主体", narrative_role="主体", action="喝止", emotion=-1, evidence=ev_act)
label(paragraph_id=11, emotion=-1)
metric(key="k1", summary="顾霜喝止", emotional_valence=-1, narrative_function="冲突", evidence=ev_talk)
pending(key="q1", kind="case_clue", detail="长刀来路不明", handles=["m2"], evidence=ev_item)
""",
    )
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 9
    assert "failed" not in receipt
    assert set(receipt["refs"]) == {
        "B1:m1",
        "B1:m2",
        "B1:r1",
        "B1:d1",
        "B1:e1",
        "B1:label-11",
        "B1:k1",
        "B1:q1",
    }

    assert block.counts() == {
        "mentions": 2,
        "relations": 1,
        "dialogues": 1,
        "events": 1,
        "links": 0,
        "labels": 1,
        "metric_notes": 1,
        "pending": 1,
    }
    assert block.events[0].participants[0].entity == "m1"
    assert block.labels[0].paragraph_id == 11

    index = block.index()
    assert index["relations"][0]["from"] == "B1:m1"
    assert index["events"][0]["participants"][0]["entity"] == "B1:m1"
    assert index["dialogues"][0]["speaker"] == "B1:m1"

    detail = block.resolve("B1:e1")
    assert detail is not None and detail["kind"] == "events"
    assert detail["participants"][0]["entity"] == "B1:m1"


@pytest.mark.asyncio
async def test_block_never_touches_formal_ledger() -> None:
    """块代理绝不产生正式写入：账本写入面在块程序跑完后仍为空"""
    ledger, _block, runtime = _setup()
    await _run(
        runtime,
        'mention(key="m1", name="顾霜", entity_type="character", evidence=[{"paragraph_id": 11, "quote": "顾霜"}])',
    )
    assert ledger.written_entities == {}
    assert ledger.written_dialogues == {}
    assert ledger.written_relations == {}
    assert ledger.metrics_payload is None
    assert ledger.chapter_finished is False


@pytest.mark.asyncio
async def test_evidence_is_verified_at_construction() -> None:
    """evidence 走 NFC 唯一命中核验：改写引文/跨段引用/非本块段号一律记录级拒绝"""
    _ledger, _block, runtime = _setup()
    receipt = await _run(
        runtime,
        'mention(key="m1", name="顾霜", entity_type="character", evidence=[{"paragraph_id": 11, "quote": "顾霜怒斥"}])',
    )
    assert receipt["status"] == "partial"
    assert receipt["applied"] == 0
    failed = receipt["failed"][0]
    assert failed["code"] == "evidence_unverified"
    assert failed["field"] == "evidence"
    assert failed["record"] == "B1:m1"

    foreign = await _run(
        runtime,
        'mention(key="m1", name="顾霜", entity_type="character", evidence=[{"paragraph_id": 99, "quote": "顾霜"}])',
    )
    assert foreign["failed"][0]["code"] == "evidence_unverified"


@pytest.mark.asyncio
async def test_business_failures_keep_the_rest_of_the_program() -> None:
    """单条业务失败只废该条：后面的语句照常执行（与写者面同一条程序语义）"""
    _ledger, block, runtime = _setup()
    receipt = await _run(
        runtime,
        """
mention(key="m1", name="顾霜", entity_type="character", evidence=[{"paragraph_id": 11, "quote": "不存在"}])
mention(key="m2", name="长刀", entity_type="item", evidence=[{"paragraph_id": 12, "quote": "长刀"}])
""",
    )
    assert receipt["status"] == "partial"
    assert receipt["applied"] == 1
    assert [item.key for item in block.mentions] == ["m2"]


@pytest.mark.asyncio
async def test_unknown_reference_lists_known_keys() -> None:
    """引用本块未构造的键：结构化拒绝并列出已知键（一次自纠）"""
    _ledger, _block, runtime = _setup()
    receipt = await _run(
        runtime,
        'relation(key="r1", from_mention="m9", to_mention="m8", relation_type="利益",'
        ' evidence=[{"paragraph_id": 12, "quote": "长刀"}])',
    )
    failed = receipt["failed"][0]
    assert failed["code"] == "unknown_reference"
    assert failed["field"] == "from_mention"
    assert "已知键" in failed["expected"]


@pytest.mark.asyncio
async def test_closed_vocabularies_and_three_state_rules() -> None:
    """闭集词表越界、not_dialogue 带 speaker、character 三态不齐一律记录级拒绝"""
    _ledger, _block, runtime = _setup()
    receipt = await _run(
        runtime,
        """
mention(key="m1", name="顾霜", entity_type="character", evidence=[{"paragraph_id": 11, "quote": "顾霜"}])
mention(key="m2", name="长刀", entity_type="item", evidence=[{"paragraph_id": 12, "quote": "长刀"}])
dialogue(key="d1", candidate_index=1, verdict="not_dialogue", speaker="m1")
local_event(key="e1", description="喝止", evidence=[{"paragraph_id": 11, "quote": "喝道"}])
participant(event="e1", entity="m1", role="主体", evidence=[{"paragraph_id": 11, "quote": "喝道"}])
participant(event="e1", entity="m2", role="地点", action="挡路", evidence=[{"paragraph_id": 12, "quote": "长刀"}])
relation(key="r1", from_mention="m1", to_mention="m2", relation_type="亲爹",
         evidence=[{"paragraph_id": 12, "quote": "长刀"}])
""",
    )
    codes = [item["code"] for item in receipt["failed"]]
    assert codes == ["invalid_value", "missing_field", "invalid_value", "invalid_value"]
    assert receipt["applied"] == 3
    # 三态不齐的 character 与多填非 character 都没进事件参与者
    assert _block.events[0].participants == []


@pytest.mark.asyncio
async def test_duplicate_mention_keys_are_updates_not_new_entries() -> None:
    """同键重写=更新语义（与正式写入同口径），不会产生第二条局部对象"""
    _ledger, block, runtime = _setup()
    await _run(
        runtime,
        """
ev = [{"paragraph_id": 11, "quote": "顾霜"}]
mention(key="m1", name="顾霜", entity_type="character", evidence=ev)
mention(key="m1", name="顾霜", entity_type="character", description="剑客", evidence=ev)
""",
    )
    assert len(block.mentions) == 1
    assert block.mentions[0].description == "剑客"


@pytest.mark.asyncio
async def test_search_rides_the_same_transaction_boundary() -> None:
    """检索调用走生产单条事务边界：回执是字典，逐 op 记录与构造器同一套字段"""
    _ledger, _block, runtime = _setup()
    receipt = await _run(runtime, 'hits = search_text(query="顾霜")')
    assert receipt["status"] == "applied"
    assert receipt["applied"] == 1
    assert runtime.ops[-1]["tool_name"] == "search_text"
    assert runtime.ops[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_wrong_parameter_names_give_the_signature() -> None:
    """参数名写错：拒绝回执里原样给出构造器签名（自纠不需要猜）"""
    _ledger, _block, runtime = _setup()
    receipt = await _run(runtime, 'mention(handle="m1", name="顾霜", entity_type="character", evidence=[])')
    failed = receipt["failed"][0]
    assert failed["code"] == "invalid_call"
    assert "mention(" in failed["expected"]


@pytest.mark.asyncio
async def test_validate_reports_dangling_references_at_session_end() -> None:
    """会话结束复核：待决项里指向不存在句柄的引用在 validate 时被拦下"""
    _ledger, block, runtime = _setup()
    await _run(runtime, 'pending(key="q1", kind="other", detail="没建过的引用", handles=["m7"])')
    assert block.dangling_references() == ["B1:q1 引用 B1:m7"]
    with pytest.raises(Exception) as excinfo:
        block.validate()
    assert "dangling_reference" in str(getattr(excinfo.value, "code", ""))


def test_constructor_api_text_renders_real_signatures() -> None:
    """构造器目录的签名取自函数对象本身（参数名/默认值与实现同源）"""
    from src.agents.annotation.program import constructor_api_text

    entries = build_block_constructors(
        BlockAnnotation(block_index=0, block_chunk_id=-1, block_text="x"),
        paragraph_text_by_id={1: "x"},
        case_number_registry={},
        candidate_total=3,
    )
    text = constructor_api_text(entries)
    assert 'mention(key, name, entity_type, evidence, tags=None, description=None, attributes=None)' in text
    assert "local_event(key, description, evidence, is_foreshadowing=False, confidence=None, note=None)" in text
    assert "participant(event, entity, role, evidence, narrative_role=None, action=None, emotion=None)" in text
