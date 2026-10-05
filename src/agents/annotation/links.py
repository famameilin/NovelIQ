"""标注 Agent 的精确原文读取、对象锚点与跨章关联工具"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, Literal, get_args, get_origin

from langchain_core.tools import tool
from pydantic import Field

from .errors import AnnotationAuthorizationError, AnnotationInputError, AnnotationStageRejection
from .identity import stable_digest, text_digest
from .schema import CrossChapterLink, SourceReference

if TYPE_CHECKING:
    from .tools import AnnotationQueryService, AnnotationToolLedger

_CHANGE_KIND_VALUES = next(
    get_args(branch) for branch in get_args(CrossChapterLink.model_fields["change_kind"].annotation)
    if get_origin(branch) is Literal
)
LINK_KIND_CHANGE_PAIRING_TEXT = (
    "kind | change_kind\n"
    + " / ".join(
        kind for kind in get_args(CrossChapterLink.model_fields["kind"].annotation) if kind != "relation_change"
    )
    + " | 省略或 None\nrelation_change | 必填 " + " / ".join(_CHANGE_KIND_VALUES)
    + "；按原文选择关系变化方向"
)


def build_link_tools(query_service: AnnotationQueryService, ledger: AnnotationToolLedger) -> list[Any]:
    """所有写工具只接受本次读回执和本章已写出的对象"""

    def require_open() -> None:
        if ledger.phase != "chapter_open":
            raise AnnotationAuthorizationError("章节已收尾，不能追加原文引用或关联")

    def require_record(record_id: str) -> str:
        require_open()
        # 2026-10-04 裸树键补全：树键（如 t1）按自然形态当记录键时翻译成根记录再校验，
        # 原值或翻译值任一在本章写出的记录键集合里即接受，返回统一为生产键
        resolved = ledger.production_record_key(record_id)
        if record_id not in ledger.written_record_keys and resolved not in ledger.written_record_keys:
            raise AnnotationStageRejection(
                f"{record_id}(record_id={record_id!r})：record_id 必须是本章实际写出的记录键",
                record=record_id, field="record_id", code="unknown_record",
                expected="本章已写出的记录键",
            )
        return resolved

    def reference(source_ref: str, *, record: str, field: str) -> SourceReference:
        if source_ref not in ledger.text_references:
            raise AnnotationStageRejection(
                f"{record}({field}={source_ref!r})：引用未由本次 read_text 授权",
                record=record, field=field, code="unauthorized_reference",
                expected="本次 read_text 已授权的 source_ref",
            )
        return ledger.text_references[source_ref]

    @tool
    async def read_text(paragraph_id: int, quote: str | None = None, occurrence: int = 1) -> str:
        """读取完整段落或精确原文片段，返回跨章引用能力；不依赖该章标注是否完成"""
        require_open()
        if occurrence < 1:
            raise AnnotationInputError("occurrence 必须从 1 开始")
        paragraph: dict[str, Any] | None = None
        if ledger.paragraph_info is not None:
            for identifier, content in zip(
                ledger.paragraph_info.paragraph_ids, ledger.paragraph_info.texts, strict=True,
            ):
                if identifier == paragraph_id:
                    paragraph = {"chapter_id": ledger.current_chapter_id, "paragraph_id": identifier, "text": content}
                    break
        if paragraph is None:
            paragraph = await query_service.read_paragraph(
                paragraph_id, allow_future_context=ledger.allow_future_context,
            )
        content = str(paragraph["text"])
        start, end = 0, len(content)
        if quote is not None:
            if not quote:
                raise AnnotationInputError("quote 不能为空")
            start = -1
            for _ in range(occurrence):
                start = content.find(quote, start + 1)
                if start < 0:
                    raise AnnotationInputError("quote 或 occurrence 不匹配原文")
            end = start + len(quote)
        value = SourceReference(chapter_id=paragraph["chapter_id"], paragraph_id=paragraph_id,
                                char_start=start, char_end=end, text_hash=text_digest(content[start:end]))
        source_ref = stable_digest(ledger.run_scope, value.model_dump(mode="json"))
        ledger.text_references[source_ref] = value
        ledger.authorized_text_paragraph_ids.add(paragraph_id)
        return json.dumps({**value.model_dump(mode="json"), "content": content[start:end],
                           "source_ref": source_ref}, ensure_ascii=False)

    @tool
    async def read_chapter_text(paragraph_id: int, quote: str | None = None, occurrence: int = 1) -> str:
        """按本章段首可见号读取原文与 source_ref；跨章检索命中的全局段落号使用 read_text"""
        require_open()
        info = ledger.paragraph_info
        if info is None:
            raise AnnotationInputError("本章段落坐标映射缺失")
        identifiers = dict(zip(info.visible_ids(), info.paragraph_ids, strict=True))
        if paragraph_id not in identifiers:
            raise AnnotationInputError(f"段首可见号越界，可用号：{list(identifiers)}")
        return await read_text.ainvoke({
            "paragraph_id": identifiers[paragraph_id], "quote": quote, "occurrence": occurrence,
        })

    @tool
    def anchor_record(record_id: str, source_ref: str) -> str:
        """将本章已写出的对象绑定到精确原文；同一区间匹配多个对象时不会自动选一个"""
        record = require_record(record_id)
        value = reference(source_ref, record=record, field="source_ref")
        if value.chapter_id != ledger.current_chapter_id:
            raise AnnotationStageRejection(
                f"{record}(source_ref={source_ref!r}, source.chapter_id={value.chapter_id})："
                f"只能给本章对象绑定本章原文锚点（本章 chapter_id={ledger.current_chapter_id}）",
                record=record, field="source_ref", code="chapter_mismatch",
                expected=f"source.chapter_id={ledger.current_chapter_id}",
            )
        values = ledger.source_anchors.setdefault(record, [])
        if value not in values:
            values.append(value)
        return json.dumps({"accepted": True, "record": record, "source_ref": source_ref}, ensure_ascii=False)

    @tool
    def write_link(
        record_id: str, source_ref: str, target_ref: str,
        kind: Annotated[
            Literal["same_entity", "different_entity", "causal", "foreshadowing", "relation_change"],
            Field(description=LINK_KIND_CHANGE_PAIRING_TEXT),
        ],
        change_kind: Annotated[
            Literal["assert", "reinforce", "weaken", "refine", "break", "supersede", "retract"] | None,
            Field(description=LINK_KIND_CHANGE_PAIRING_TEXT),
        ] = None,
    ) -> str:
        """提交已确认跨章关联，自动绑定已授权的本章 source_ref；未确定内容使用 push_case"""
        record = require_record(record_id)
        source = reference(source_ref, record=record, field="source_ref")
        target = reference(target_ref, record=record, field="target_ref")
        expected_domain = "entity/" if kind in {"same_entity", "different_entity"} else (
            "relation/" if kind == "relation_change" else None
        )
        if expected_domain is not None and not record.startswith(expected_domain):
            raise AnnotationStageRejection(
                f"{record}(kind={kind})：关联类型与本章记录领域不匹配",
                record=record, field="kind", code="domain_mismatch", expected=f"record_id 以 {expected_domain} 开头",
            )
        if expected_domain is None and record.startswith(("entity/", "relation/", "dialogue/", "metrics")):
            raise AnnotationStageRejection(
                f"{record}(kind={kind})：因果与伏笔照应必须指向本章事件记录",
                record=record, field="kind", code="domain_mismatch", expected="本章事件记录键",
            )
        if source.chapter_id != ledger.current_chapter_id:
            raise AnnotationStageRejection(
                f"{record}(source_ref={source_ref!r}, source.chapter_id={source.chapter_id})："
                f"关联来源必须属于本章（本章 chapter_id={ledger.current_chapter_id}）",
                record=record, field="source_ref", code="chapter_mismatch",
                expected=f"source.chapter_id={ledger.current_chapter_id}",
            )
        # 联合约束在工具边界点名实际两端和字段值，模型不必从整条载荷反推错误字段
        if source.chapter_id == target.chapter_id:
            raise AnnotationStageRejection(
                f"{record}(source.chapter_id={source.chapter_id}, target.chapter_id={target.chapter_id})："
                "跨章关联的两端必须属于不同章节",
                record=record, field="target_ref", code="invalid_combination",
                expected="source.chapter_id != target.chapter_id",
            )
        if kind == "relation_change" and change_kind is None:
            raise AnnotationStageRejection(
                f"{record}(kind={kind}, change_kind=None)：关系变化缺少 change_kind",
                record=record, field="change_kind", code="missing",
                expected="assert / reinforce / weaken / refine / break / supersede / retract",
            )
        if kind != "relation_change" and change_kind is not None:
            raise AnnotationStageRejection(
                f"{record}(kind={kind}, change_kind={change_kind})：change_kind 只用于 relation_change",
                record=record, field="change_kind", code="invalid_combination", expected="change_kind=None",
            )
        value = CrossChapterLink(record_id=record, kind=kind, source=source, target=target, change_kind=change_kind)
        # 全部关联校验通过后才补锚点，拒绝调用不留下绑定副作用
        anchors = ledger.source_anchors.setdefault(record, [])
        if source not in anchors:
            anchors.append(source)
        if value not in ledger.cross_chapter_links:
            ledger.cross_chapter_links.append(value)
        return json.dumps({"accepted": True, "record": record, "kind": kind}, ensure_ascii=False)

    return [read_text, read_chapter_text, anchor_record, write_link]
