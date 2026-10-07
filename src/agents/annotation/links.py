"""标注 Agent 的精确原文读取、对象锚点与跨章关联工具"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

from .errors import AnnotationAuthorizationError, AnnotationInputError, AnnotationStageRejection
from src.utils.identity import stable_digest, text_digest
from src.fact_graph.schema import SourceReference

if TYPE_CHECKING:
    from .tools import AnnotationQueryService, AnnotationToolLedger

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


    return [read_text, read_chapter_text, anchor_record]
