"""章内并行两段式：读者一次性报告（2026-09-12 修订，取代旧消息池）

2026-09-12 修订（推翻 09-11 文档 §5.1 的"增量多次发送"）：
- send_message 每轮读者激活只允许调用一次，载荷按观察类分组复合上报；
- 格式/枚举/引文核验失败一律不打回：观察照常送达写者（写者是 LLM，
  读得懂带杂质的观察），问题以 warnings 随回执与写者视图呈现；
- 读者→写者直达，无消息池；唯一保留的硬门槛是写者取证准入——
  写库引文必须来自通过段内唯一命中核验的证据（防幻觉，unverified 引文
  不得作为案例裁决取证）。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# 复合报告的数组观察组与单对象观察组（2026-09-12 一次性上报合同）
REPORT_LIST_GROUPS = (
    "entities",
    "relations",
    "paragraph_labels",
    "dialogues",
    "cases",
    "event_trees",
    "notes",
)
REPORT_SINGLE_GROUPS = ("metric",)


def normalize_message_name(name: str) -> str:
    """2026-09-11 用于生成与实体目录一致的名称匹配键（NFC + strip + casefold）"""
    return unicodedata.normalize("NFC", name).strip().casefold()


@dataclass(slots=True)
class ReaderReport:
    """单次读者激活的一次性上报（send_message 唯一一次调用的整体观察）"""

    # 0 基子块序号（写者视图按块序渲染）
    block_index: int
    # 复合载荷原文：{group: [观察项...]} / {metric: {...}}，观察项内嵌 evidence
    report: dict[str, Any]
    # 就地核验/合同检查发现的问题（照常送达，不回退重发）
    warnings: list[str] = field(default_factory=list)


def verify_quote_against_paragraph(
    paragraph_id: Any,
    quote: Any,
    paragraph_text_by_id: dict[int, str],
) -> tuple[int, str] | str:
    """2026-09-12 用于核验单条逐字证据（通过返回规范化条目，失败返回原因文本）

    判据与 09-11 一致：paragraph_id 属于本子块，quote 经 NFC 归一后在该段落
    内唯一命中。核验失败的证据不丢弃，由调用方打 unverified 标记照常送达。
    """
    if isinstance(paragraph_id, bool) or not isinstance(paragraph_id, int):
        return "paragraph_id 必须是整数段落 id（见正文 <paragraph id=…>）"
    paragraph_text = paragraph_text_by_id.get(paragraph_id)
    if paragraph_text is None:
        return f"paragraph_id={paragraph_id} 不属于本子块（只能引用 <CurrentSubBlock> 内列出的段落）"
    if not isinstance(quote, str) or not quote.strip():
        return "quote 必须是非空逐字摘录"
    normalized_text = unicodedata.normalize("NFC", paragraph_text)
    normalized_quote = unicodedata.normalize("NFC", quote)
    hits = normalized_text.count(normalized_quote)
    if hits == 0:
        return f"引文不在段落 {paragraph_id} 内（NFC 归一后未命中）：请从该段落原样摘录，不要改写"
    if hits > 1:
        return f"引文在段落 {paragraph_id} 内命中 {hits} 处，不唯一：请加长摘录"
    return paragraph_id, quote


def decorate_evidence(
    item: dict[str, Any],
    *,
    label: str,
    paragraph_text_by_id: dict[int, str],
    warnings: list[str],
    require_evidence: bool,
) -> None:
    """2026-09-12 用于对单条观察的 evidence 就地核验（失败打 unverified 标记不丢弃）

    通过核验的条目保持 {paragraph_id, quote}；失败条目补 unverified=true 并把
    原因追加进 warnings。写者视图因此能看到全部引文及其可信标记。
    """
    evidence = item.get("evidence")
    if evidence is None or evidence == []:
        item.pop("evidence", None)
        if require_evidence:
            warnings.append(f"{label} 缺少 evidence 逐字引文（该观察无法用于案例裁决取证）")
        return
    if not isinstance(evidence, list):
        item["evidence"] = [{"quote": str(evidence), "unverified": True}]
        warnings.append(f"{label}.evidence 必须是 [{{paragraph_id, quote}}] 数组，已按未验证处理")
        return
    decorated: list[dict[str, Any]] = []
    for entry_index, entry in enumerate(evidence):
        sub_label = f"{label}.evidence.{entry_index}"
        raw_entry = entry if isinstance(entry, dict) else {}
        result = verify_quote_against_paragraph(
            raw_entry.get("paragraph_id"),
            raw_entry.get("quote"),
            paragraph_text_by_id,
        )
        if isinstance(result, str):
            decorated.append(
                {
                    "paragraph_id": (
                        raw_entry.get("paragraph_id")
                        if isinstance(raw_entry.get("paragraph_id"), int)
                        and not isinstance(raw_entry.get("paragraph_id"), bool)
                        else None
                    ),
                    "quote": str(raw_entry.get("quote") or ""),
                    "unverified": True,
                }
            )
            warnings.append(f"{sub_label} {result}（已按未验证处理）")
        else:
            paragraph_id, quote = result
            decorated.append({"paragraph_id": paragraph_id, "quote": quote})
    item["evidence"] = decorated


def report_entity_name_keys(reports: list[ReaderReport]) -> set[str]:
    """2026-09-12 用于写者取值域准入：复合报告中陈述过的实体名集合

    覆盖与旧消息池 entity_name_keys 相同的来源面：entities 名称、event_trees
    参与者（根与 children）、relations 两端、dialogues 说话人、cases 涉及实体。
    名字准入不区分证据是否核验通过（写者发明名字才是要拦的对象）。
    """
    keys: set[str] = set()
    for report in reports:
        payload = report.report
        for item in payload.get("entities") or []:
            name = _item_field(item, "name")
            if name:
                keys.add(normalize_message_name(name))
        for item in payload.get("relations") or []:
            for endpoint in ("from_entity", "to_entity"):
                name = _item_field(item, endpoint)
                if name:
                    keys.add(normalize_message_name(name))
        for tree in payload.get("event_trees") or []:
            _collect_participant_names(tree, keys)
        for item in payload.get("dialogues") or []:
            speaker = _item_field(item, "speaker")
            if speaker:
                keys.add(normalize_message_name(speaker))
        for item in payload.get("cases") or []:
            entities = item.get("entities") if isinstance(item, dict) else None
            if isinstance(entities, list):
                for name in entities:
                    if isinstance(name, str) and name.strip():
                        keys.add(normalize_message_name(name))
    return keys


def _item_field(item: Any, field_name: str) -> str | None:
    """2026-09-12 用于从观察项安全取字符串字段（脏项容错）"""
    if isinstance(item, dict):
        value = item.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _collect_participant_names(tree: Any, keys: set[str]) -> None:
    """2026-09-12 用于遍历事件树根与 children 的参与者实体名"""
    if not isinstance(tree, dict):
        return
    for participants in (
        tree.get("participants"),
        *[child.get("participants") for child in (tree.get("children") or []) if isinstance(child, dict)],
    ):
        if not isinstance(participants, list):
            continue
        for participant in participants:
            name = _item_field(participant, "entity")
            if name:
                keys.add(normalize_message_name(name))


def report_case_quotes(reports: list[ReaderReport]) -> tuple[str, ...]:
    """2026-09-12 用于写者案例裁决取证准入：cases 观察中通过核验的引文集合

    只认 evidence 未带 unverified 标记的引文（09-12 裁决：防幻觉硬门槛保留
    在写者取证面，unverified 引文不得支撑案例裁决）。
    """
    quotes: list[str] = []
    for report in reports:
        for item in report.report.get("cases") or []:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence")
            if not isinstance(evidence, list):
                continue
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                quote = entry.get("quote")
                if not isinstance(quote, str) or not quote.strip() or entry.get("unverified"):
                    continue
                quotes.append(unicodedata.normalize("NFC", quote))
    return tuple(quotes)


def render_reader_reports(
    reports: list[ReaderReport | None],
    *,
    block_total: int,
) -> str:
    """2026-09-12 用于把一次性报告渲染进写者首条请求（按块序，缺块给占位）"""
    by_block = {report.block_index: report for report in reports if report is not None}
    sections: list[str] = []
    for index in range(block_total):
        report = by_block.get(index)
        if report is None or not report.report:
            sections.append(
                f'<ReaderReport block="{index + 1}">\n（本块读者未上报观察）\n</ReaderReport>'
            )
            continue
        lines = [f'<ReaderReport block="{index + 1}">']
        if report.warnings:
            lines.append(f"format_warnings: {'；'.join(report.warnings)}")
        lines.append(json.dumps(report.report, ensure_ascii=False, indent=1))
        lines.append("</ReaderReport>")
        sections.append("\n".join(lines))
    return "\n".join(sections)


__all__ = [
    "REPORT_LIST_GROUPS",
    "REPORT_SINGLE_GROUPS",
    "ReaderReport",
    "decorate_evidence",
    "normalize_message_name",
    "render_reader_reports",
    "report_case_quotes",
    "report_entity_name_keys",
    "verify_quote_against_paragraph",
]
