"""标注 Agent 的精确原文读取、对象锚点与跨章关联工具"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.tools import tool

from .errors import AnnotationAuthorizationError, AnnotationInputError
from .identity import stable_digest, text_digest
from .schema import CrossChapterLink, SourceReference

if TYPE_CHECKING:
    from .tools import AnnotationQueryService, AnnotationToolLedger


def build_link_tools(query_service: AnnotationQueryService, ledger: AnnotationToolLedger) -> list[Any]:
    """所有写工具只接受本次读回执和本章已写出的对象"""

    def require_open() -> None:
        if ledger.phase != "chapter_open":
            raise AnnotationAuthorizationError("章节已收尾，不能追加原文引用或关联")

    def require_record(record_id: str) -> str:
        require_open()
        if record_id not in ledger.written_record_keys:
            raise AnnotationInputError("record_id 必须是本章实际写出的记录键")
        return record_id

    def reference(source_ref: str) -> SourceReference:
        if source_ref not in ledger.text_references:
            raise AnnotationAuthorizationError("source_ref 未由本次 read_text 授权")
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
    def anchor_record(record_id: str, source_ref: str) -> str:
        """将本章已写出的对象绑定到精确原文；同一区间匹配多个对象时不会自动选一个"""
        record = require_record(record_id)
        value = reference(source_ref)
        if value.chapter_id != ledger.current_chapter_id:
            raise AnnotationInputError("只能给本章对象绑定本章原文锚点")
        values = ledger.source_anchors.setdefault(record, [])
        if value not in values:
            values.append(value)
        return json.dumps({"accepted": True, "record": record, "source_ref": source_ref}, ensure_ascii=False)

    @tool
    def write_link(
        record_id: str, source_ref: str, target_ref: str,
        kind: Literal["same_entity", "different_entity", "causal", "foreshadowing", "relation_change"],
        change_kind: Literal["assert", "reinforce", "weaken", "refine", "break", "supersede", "retract"] | None = None,
    ) -> str:
        """提交本章对象与另一章原文对象的已确认关联，未确定内容应使用 push_case"""
        record = require_record(record_id)
        source, target = reference(source_ref), reference(target_ref)
        expected_domain = "entity/" if kind in {"same_entity", "different_entity"} else (
            "relation/" if kind == "relation_change" else None
        )
        if expected_domain is not None and not record.startswith(expected_domain):
            raise AnnotationInputError("关联类型与本章记录领域不匹配")
        if expected_domain is None and record.startswith(("entity/", "relation/", "dialogue/", "metrics")):
            raise AnnotationInputError("因果与伏笔照应必须指向本章事件记录")
        if source.chapter_id != ledger.current_chapter_id or source not in ledger.source_anchors.get(record, []):
            raise AnnotationAuthorizationError("source_ref 必须先通过 anchor_record 绑定本章对象")
        value = CrossChapterLink(record_id=record, kind=kind, source=source, target=target, change_kind=change_kind)
        if value not in ledger.cross_chapter_links:
            ledger.cross_chapter_links.append(value)
        return json.dumps({"accepted": True, "record": record, "kind": kind}, ensure_ascii=False)

    return [read_text, anchor_record, write_link]
