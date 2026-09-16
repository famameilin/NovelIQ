"""2026-09-16 章内并行 CodeAct 章节代理合并面合同测试

覆盖绑定即编译的核心契约：句柄在编译期翻成正式引用、未绑定即拒绝并交回待绑定
清单、参与者冲突拒绝编译（不许最后写入者覆盖）、块完成顺序不构成顺序、
块内候选编号经映射对齐章级候选、段标签自动并入章级指标、
块 IR 按既有报告形状喂进写者取证准入、块授权足迹并入章账本。
"""

from __future__ import annotations

import json

import pytest

from src.agents.annotation.block_program import BlockRunOutcome
from src.agents.annotation.chapter_merge import (
    ChapterMergeRuntime,
    build_block_reports,
    build_handle_registry,
    transfer_authorizations,
)
from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.local_ir import (
    BlockAnnotation,
    LocalDialogue,
    LocalEvent,
    LocalEvidence,
    LocalLabel,
    LocalMention,
    LocalParticipant,
    LocalPending,
    LocalRelation,
)
from src.agents.annotation.schema import ChunkParagraphInfo, SearchResult
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


class _QueryService:
    """用于提供无数据库依赖的查询桩"""

    current_chapter_order = None

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


_BLOCK_TEXTS = ("顾霜喝道：“住手！”", "伯安拔剑相向。")


def _evidence(paragraph_id: int, quote: str) -> tuple[LocalEvidence, ...]:
    """用于构造一条已核验证据"""
    return (LocalEvidence(paragraph_id=paragraph_id, quote=quote),)


def _blocks() -> list[BlockAnnotation]:
    """用于构造两个块的生产形态局部标注（跨块同一人物、跨块事件延续、块内关系与待决项）"""
    first = BlockAnnotation(block_index=0, block_chunk_id=-1, block_text=_BLOCK_TEXTS[0])
    first.mentions = [
        LocalMention(
            key="m1",
            name="顾霜",
            entity_type="character",
            tags=[],
            description="剑客",
            attributes=None,
            evidence=_evidence(1, "顾霜"),
        )
    ]
    first.relations = [
        LocalRelation(
            key="r1",
            from_ref="m1",
            to_ref="m1",
            relation_type="盟友",
            evidence=_evidence(1, "顾霜"),
        )
    ]
    first.events = [
        LocalEvent(
            key="e1",
            description="顾霜喝止",
            participants=[
                LocalParticipant(
                    entity="m1",
                    role="主体",
                    narrative_role="主体",
                    action="喝止",
                    emotion=-1,
                    evidence=_evidence(1, "喝道"),
                )
            ],
            evidence=_evidence(1, "喝道"),
        )
    ]
    first.dialogues = [
        LocalDialogue(
            key="d1",
            candidate_index=1,
            verdict="dialogue",
            speaker="m1",
            tone="愤怒",
            evidence=_evidence(1, "住手！"),
        )
    ]
    first.labels = [LocalLabel(paragraph_id=1, emotion=-1, evidence=())]

    second = BlockAnnotation(block_index=1, block_chunk_id=-2, block_text=_BLOCK_TEXTS[1])
    second.mentions = [
        LocalMention(
            key="m1",
            name="顾霜",
            entity_type="character",
            tags=[],
            description=None,
            attributes=None,
            evidence=_evidence(3, "顾霜"),
        ),
        LocalMention(
            key="m2",
            name="伯安",
            entity_type="character",
            tags=[],
            description=None,
            attributes=None,
            evidence=_evidence(3, "伯安"),
        ),
    ]
    second.events = [
        LocalEvent(
            key="e1",
            description="伯安拔剑",
            participants=[
                LocalParticipant(
                    entity="m1",
                    role="客体",  # 与块一的"主体"冲突：必须显式裁决
                    narrative_role="客体",
                    action="被逼退",
                    emotion=-2,
                    evidence=_evidence(3, "顾霜"),
                ),
                LocalParticipant(
                    entity="m2",
                    role="主体",
                    narrative_role="主体",
                    action="拔剑",
                    emotion=1,
                    evidence=_evidence(3, "拔剑"),
                ),
            ],
            evidence=_evidence(3, "拔剑"),
        )
    ]
    second.labels = [LocalLabel(paragraph_id=3, emotion=1, evidence=())]
    second.pending = [
        LocalPending(
            key="q1",
            kind="case_clue",
            detail="两人关系前后矛盾，疑似伏笔",
            evidence=_evidence(3, "拔剑"),
            handles=["B2:e1"],
        )
    ]
    return [first, second]


def _chapter_text() -> str:
    """用于拼出章的完整正文（章会话账本按整章文本构造）"""
    return "".join(_BLOCK_TEXTS)


def _paragraph_info() -> ChunkParagraphInfo:
    """用于构造章级段落坐标（四个段落全局编号 1..4 里各块各占两段）"""
    texts = ["顾霜喝道：", "“住手！”", "伯安拔剑相向。", "剑光一闪。"]
    spans: list[tuple[int, int]] = []
    offset = 0
    for text in texts:
        spans.append((offset, offset + len(text)))
        offset += len(text)
    return ChunkParagraphInfo(paragraph_ids=[1, 2, 3, 4], char_spans=spans, texts=texts)


def _setup(
    *, reader_reports: bool = True
) -> tuple[AnnotationToolLedger, BlockAnnotation, BlockAnnotation, ChapterMergeRuntime]:
    """用于按生产装配方式构造章合并程序面"""
    blocks = _blocks()
    text = _chapter_text()
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=text,
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_paragraph_info(),
        reader_reports=build_block_reports(blocks) if reader_reports else None,
    )
    runtime = ChapterMergeRuntime(
        build_annotation_tools(_QueryService(), ledger),
        ledger,
        blocks,
        candidate_number_maps=[{1: 1}, {1: 2}],
    )
    return ledger, blocks[0], blocks[1], runtime


async def _run(runtime: ChapterMergeRuntime, code: str) -> dict:
    """用于执行程序并解析压缩回执"""
    return json.loads(await runtime.execute(code))


@pytest.mark.asyncio
async def test_bind_compiles_to_formal_entity_and_enables_event_merge() -> None:
    """bind 就地编译成 write_entity；随后 tree/event 用绑定表把块内参与者翻成正式引用"""
    ledger, _first, _second, runtime = _setup()
    receipt = await _run(
        runtime,
        """
bind(mention="B1:m1", el="gs")
bind(mention="B2:m1", el="gs", name="顾霜")
bind(mention="B2:m2", el="ba")
tree(key="t1", description="冲突", sources=["B1:e1"])
event(tree="t1", key="e2", description="拔剑", sources=["B2:e1"])
""",
    )
    assert "failed" not in receipt, receipt
    # 两个块里的"顾霜"是同一个 el：块内短键被编译期翻成了同一个正式实体
    assert ledger.entity_el_index == {"gs": "顾霜", "ba": "伯安"}
    nodes = ledger.bound_payloads["events"]
    assert {event.description for event in nodes} == {"冲突", "拔剑"}
    actions = {part.action for event in nodes for part in event.participants}
    assert actions == {"喝止", "被逼退", "拔剑"}


@pytest.mark.asyncio
async def test_unbound_mention_is_rejected_with_pending_list() -> None:
    """未绑定的提及不猜：编译期拒绝并把待绑定清单交回模型"""
    _ledger, _first, _second, runtime = _setup()
    receipt = await _run(runtime, 'tree(key="t1", description="冲突", sources=["B1:e1"])')
    failed = receipt["failed"][0]
    assert failed["code"] == "unbound_mention"
    assert "bind" in failed["expected"]


@pytest.mark.asyncio
async def test_participant_conflict_requires_explicit_arbitration() -> None:
    """跨块同一参与者字段冲突：编译拒绝，不许最后写入者覆盖；显式裁决后放行"""
    ledger, _first, _second, runtime = _setup()
    await _run(
        runtime,
        """
bind(mention="B1:m1", el="gs")
bind(mention="B2:m1", el="gs", name="顾霜")
bind(mention="B2:m2", el="ba")
""",
    )
    conflicted = await _run(
        runtime,
        'tree(key="t1", description="冲突", sources=["B1:e1", "B2:e1"])',
    )
    failed = conflicted["failed"][0]
    assert failed["code"] == "participant_conflict"
    assert "participants" in failed["field"]

    arbitrated = await _run(
        runtime,
        """
tree(
    key="t1",
    description="冲突",
    sources=["B1:e1", "B2:e1"],
    participants=[
        {"entityid": "gs", "role": "主体", "narrative_role": "主体", "action": "喝止", "emotion": -1},
        {"entityid": "ba", "role": "主体", "narrative_role": "主体", "action": "拔剑", "emotion": 1},
    ],
)
""",
    )
    assert "failed" not in arbitrated, arbitrated
    root = next(event for event in ledger.bound_payloads["events"] if event.description == "冲突")
    assert {part.entity for part in root.participants} == {"顾霜", "伯安"}


@pytest.mark.asyncio
async def test_import_relation_and_self_merge_skip() -> None:
    """块内关系编译成正式边；两端合并成同一实体时该边跳过"""
    ledger, _first, _second, runtime = _setup()
    receipt = await _run(
        runtime,
        """
bind(mention="B1:m1", el="gs")
import_relation(handle="B1:r1")
""",
    )
    assert receipt["refs"]["relation/B1:r1"]["skipped"] == "both_ends_merged"
    assert receipt["refs"]["relation/B1:r1"]["notes"]
    assert ledger.written_relations == {}


@pytest.mark.asyncio
async def test_merge_dialogues_maps_block_candidates_to_chapter_space() -> None:
    """块内候选编号按映射翻成章级编号；说话人未绑定时跳过并交回原因"""
    ledger, _first, _second, runtime = _setup()
    skipped = await _run(runtime, "merge_dialogues()")
    assert skipped["refs"]["dialogues"]["merged"] == 0
    assert skipped["refs"]["dialogues"]["skipped"][0]["handle"] == "B1:d1"

    merged = await _run(
        runtime,
        """
bind(mention="B1:m1", el="gs")
merge_dialogues()
""",
    )
    assert merged["refs"]["dialogues"]["merged"] == 1
    assert list(ledger.written_dialogues) == [1]
    assert ledger.written_dialogues[1].speaker == "顾霜"
    assert ledger.written_dialogues[1].tone == "愤怒"


@pytest.mark.asyncio
async def test_metrics_auto_merges_block_labels() -> None:
    """metric 省略 labels 时自动并入各块段标签（按段号去重）"""
    ledger, _first, _second, runtime = _setup()
    receipt = await _run(
        runtime,
        'metric(summary="章摘要", emotional_valence=0, narrative_function="冲突")',
    )
    assert "failed" not in receipt
    assert receipt["refs"]["metrics"]["labels"] == 2
    assert {label.paragraph_id: label.emotion for label in ledger.metrics_payload.labels} == {1: -1, 3: 1}


@pytest.mark.asyncio
async def test_inspect_and_decide_pending() -> None:
    """inspect 按句柄读明细（引用已展开成句柄），decide_pending 留痕不写正式记录"""
    _ledger, _first, _second, runtime = _setup()
    receipt = await _run(
        runtime,
        """
detail = inspect(handle="B2:e1")
decide_pending(handle="B2:q1", decision="并入事件 t1/e2", note="同一冲突的延续")
""",
    )
    assert "failed" not in receipt, receipt
    assert receipt["refs"]["B2:q1"]["pending_kind"] == "case_clue"
    assert runtime.decisions[0]["handle"] == "B2:q1"
    assert runtime.decisions[0]["case_id"] is None


@pytest.mark.asyncio
async def test_unknown_handle_lists_known_handles() -> None:
    """未知句柄：结构化拒绝并列出已知句柄"""
    _ledger, _first, _second, runtime = _setup()
    receipt = await _run(runtime, 'inspect(handle="B9:m9")')
    failed = receipt["failed"][0]
    assert failed["code"] == "unknown_handle"
    assert "B1:m1" in failed["expected"]


def test_block_ir_feeds_writer_admissibility() -> None:
    """块 IR 按既有报告形状喂进准入：块内陈述过的实体名通过，凭空名字被拒"""
    blocks = _blocks()
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=_chapter_text(),
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_paragraph_info(),
        reader_reports=build_block_reports(blocks),
    )
    from src.agents.annotation.schema import EntityInput

    ledger.admit_entity_directory([EntityInput(name="顾霜", entity_type="character")])
    with pytest.raises(ValueError):
        ledger.admit_entity_directory([EntityInput(name="查无此人", entity_type="character")])


def test_transfer_authorizations_merges_footprints_and_case_ids() -> None:
    """块授权足迹并入章账本：正文/章/事件集合取并集，案例 id 按章编号重新登记"""
    _ledger, first, second, _runtime = _setup()
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chunk_id=1,
        current_chunk_text=_chapter_text(),
        allow_future_context=False,
        graph=FactGraph(),
        paragraph_info=_paragraph_info(),
    )
    outcomes = [
        BlockRunOutcome(
            block=first,
            final_messages=[],
            authorized_text_paragraph_ids={1, 2},
            authorized_chapter_ids={7},
            authorized_event_ids={f"ev-{index}" for index in range(len(first.events))},
            authorized_tree_ids={"tree-a"},
            case_ids={"case-a"},
        ),
        BlockRunOutcome(
            block=second,
            final_messages=[],
            authorized_text_paragraph_ids={3},
            authorized_chapter_ids={8},
            authorized_event_ids={"ev-history"},
            authorized_tree_ids={"tree-b"},
            case_ids={"case-b"},
        ),
    ]
    transfer_authorizations(ledger, outcomes)
    assert ledger.authorized_text_paragraph_ids == {1, 2, 3}
    assert ledger.authorized_chapter_ids == {7, 8}
    assert "ev-history" in ledger.authorized_event_ids
    assert ledger.authorized_tree_ids == {"tree-a", "tree-b"}
    assert set(ledger.case_number_registry.values()) == {"case-a", "case-b"}


def test_handle_registry_covers_every_local_object() -> None:
    """句柄寻址表覆盖块内全部对象（含段标签）"""
    registry = build_handle_registry(_blocks())
    assert "B1:m1" in registry
    assert "B1:r1" in registry
    assert "B1:d1" in registry
    assert "B1:e1" in registry
    assert "B1:label-1" in registry
    assert "B2:q1" in registry
