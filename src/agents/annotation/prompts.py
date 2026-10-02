"""正式章节标注提示词与原文注入"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import ChapterParagraphInfo, DialogueCandidate, paragraph_has_visible_prefix

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "data" / "prompts"


def _read_prompt_text(filename: str) -> str:
    """提示词缺失直接失败，不替换为另一套工作合同"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _read_prompt_text("agent.txt")

# 2026-09-18 三代理并发：subagent 面系统提示词同样从 txt 读（sub_agent.txt）。
# 2026-10-02 恢复：随章内三子代理路径一并加回（0.2.0 重构曾摘除）。
SUBAGENT_SYSTEM_PROMPT = _read_prompt_text("sub_agent.txt")

# subagent 各自的职责范围（只写在文案里，**不通过拿掉工具或构造器实现**）：
# 多块章按三条职责并发（角色名单源在 subagent_ir）。职责文案只留**分域**：这个角色负责
# 哪些域、不负责哪些域；参数取值、引用与证据口径、批量与收尾纪律全部在 execute_code 的
# 说明里（那份说明是模型读得到的唯一合同）。solo 形态随单块章归 agent 路径，职责表只有三条。
SUBAGENT_ROLE_SCOPES: dict[str, str] = {
    "structure": (
        "<RoleScope role=\"实体与关系\">\n"
        "你负责这一章的两个域：\n"
        "- entity：正文里出现的实体（人物/地点/物品/组织）都登记；\n"
        "- relation：实体之间成立的闭合关系边都写。\n"
        "事件与参与者、对话判定、段落标签与章级指标都不属于你（由本章其他 subagent 负责）。\n"
        "</RoleScope>"
    ),
    "event": (
        "<RoleScope role=\"事件与参与者\">\n"
        "你负责这一章的两个域：\n"
        "- event：有正文依据的事件都建节点；\n"
        "- participants：把每个事件节点的参与者挂上去。\n"
        "实体间的关系边、对话判定、段落标签与章级指标都不属于你。\n"
        "</RoleScope>"
    ),
    "evidence": (
        "<RoleScope role=\"对话与章级证据\">\n"
        "你负责这一章的三个域：\n"
        "- dialogue：<DialogueCandidates> 表里的候选逐条判定，一条不落；\n"
        "- label：本章自选 2~3 段的整段情绪标签；\n"
        "- metric：章级摘要与叙事指标。\n"
        "实体间的关系边与事件树构造都不属于你。\n"
        "</RoleScope>"
    ),
}


def _candidate_views(candidates: list[DialogueCandidate]) -> list[dict]:
    """2026-09-11 用于渲染对话候选表（读者块切片与写者全章表共用）

    2026-09-19 键名与落库/工具面统一为 candidate_key（原名 id）：这一个键既用来订正记录
    （dialogue(candidate_key=…)），也是记录行在库里的稳定标识，全链路只有这一个名字。
    """
    return [
        {
            "candidate_index": index,
            "candidate_key": candidate.candidate_key,
            "text": candidate.content,
            "parse_status": candidate.parse_status,
        }
        for index, candidate in enumerate(candidates, start=1)
    ]


def build_system_prompt() -> str:
    """章级 Agent 同时负责局部事实和有原文依据的跨章关联"""
    return (
        SYSTEM_PROMPT
        + "\n本轮工作为 formal_current。只写本章正式项、跨章关联和未确定案例；"
        "不得查询图、案例池或历史事件，不得修改已有正式记录。"
        "跨章依据直接读取原文，不等待其他章 Agent 的分析结论。"
        "search_text 支持 offset 翻页；命中段落用 read_text 读取完整内容与上下文。"
        "read_text(paragraph_id, quote=原文片段) 返回 source_ref，引用不能猜造。"
        "本章实体、事件、对话、关系写出后，用 anchor_record(record_id, source_ref) 绑定精确原文。"
        "确认跨章同一/不同人物、因果、伏笔照应或关系变化时，在本次任务调用 write_link；"
        "目标使用 read_text 的 source_ref，不要求目标章已有对象 ID。"
        "不能确定的关联用 push_case 并提供双方 evidence_refs，不强行合并或覆写。"
        "对话候选必须实际判定；不能确定说话人时保留未知并登记案例，不能将未判候选当作非对话。"
    )


def _render_paragraph_numbered_text(chapter_text: str, paragraph_info: ChapterParagraphInfo | None) -> str:
    """2026-09-18 用于按段首可见号渲染正文（每段一行，以 `N：` 开头）

    N=段首可见号（见 ChapterParagraphInfo.visible_ids：正文自带 `N：` 前缀时沿用该号，
    否则按块内 1 基顺序号）。段落文本本体逐字保留；正文已带前缀时不重复渲染一次号。
    无 paragraph_info 时原样返回。
    """
    if paragraph_info is None:
        return chapter_text
    parts: list[str] = []
    for visible_id, text in zip(paragraph_info.visible_ids(), paragraph_info.texts, strict=True):
        if paragraph_has_visible_prefix(text):
            parts.append(text)
        else:
            parts.append(f"{visible_id}：{text}")
    rendered = "\n".join(parts)
    return rendered if parts else chapter_text


def build_chapter_message(
    *,
    chapter_text: str,
    candidates: list[DialogueCandidate],
    paragraph_info: ChapterParagraphInfo | None = None,
) -> str:
    """2026-08-07 用于向 Agent 提供本章正文和有序候选

    2026-08-22事件不再携带段落锚点，移除 ¶N 段落标记注入。
    2026-09-14 段落级监督：¶ 标记以全局段落号回归，write_metrics.labels
    按 ¶ 号提交整段情绪标签（选段标准见该工具 docstring）。
    2026-09-10 候选字段 index 改名 candidate_index，消除与案例编号空间的混同
    （run a83fae3d 思考实测映射推理 1725 次、显式困惑 39 次）。
    2026-09-11 案例改检索制：ActiveCases 区块从编号表降级为通道说明，案例
    编号只由 search_pool 回执产生。
    2026-09-18 提示词面只留事实与动态数据：<ActiveCases> 通道说明（检索/授权/
    编号使用属处理方式规训）与 <ParagraphLabels> 选取指令一并撤出本条消息，
    只余正文本体 + <DialogueCandidates> 候选表。
    2026-09-19 章即块：每章恰好一份正文，order=i/n 序号协议退役。
    """
    candidate_views = _candidate_views(candidates)
    sections = [
        "<CurrentChapter>\n"
        f"{_render_paragraph_numbered_text(chapter_text, paragraph_info)}\n"
        "</CurrentChapter>",
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
    ]
    if paragraph_info is not None:
        sections.append("<ParagraphSources>\n" + json.dumps([
            {"visible_id": visible, "paragraph_id": paragraph_id}
            for visible, paragraph_id in zip(paragraph_info.visible_ids(), paragraph_info.paragraph_ids, strict=True)
        ], ensure_ascii=False) + "\n</ParagraphSources>")
    return "\n\n".join(sections)


def build_subagent_message(
    *,
    role: str,
    paragraph_info: ChapterParagraphInfo,
    candidates: list[DialogueCandidate],
    role_scope: str,
) -> str:
    """2026-09-17 三代理并发（§3/§4）用于构建一个 subagent 的唯一一次正文注入

    三个 subagent 拿到的是同一份整章正文（不切分正文）：正文以段落清单注入，每段一行、
    以段首可见号 `N：` 开头（见 _render_paragraph_numbered_text），该号即 evidence 锚点
    与标签段号。本条消息只余事实与动态数据：整章正文、对话候选表，以及 role_scope
    （三个 subagent 唯一的区分）；能力合同在 execute_code 的 description 里，两份文案同轮下发。
    2026-10-02 恢复：随章内三子代理路径一并加回（0.2.0 重构曾摘除）。
    """
    paragraph_views = _render_paragraph_numbered_text("", paragraph_info)
    sections = [
        f"<CurrentChapter role=\"{role}\">\n{paragraph_views}\n</CurrentChapter>",
        "<DialogueCandidates>\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        role_scope,
    ]
    return "\n\n".join(section for section in sections if section)


def build_subagent_gap_message(gap: dict[str, Any]) -> str:
    """2026-09-17 用于 subagent 关键产出缺失时把缺口交回同一个会话续跑（有界一次）

    提示词面只留缺口事实（缺收尾/缺候选判定/缺指标）——补写方式在
    finish/execute_code 的 description 里。
    2026-10-02 恢复：随章内三子代理路径一并加回（0.2.0 重构曾摘除）。
    """
    lines = ["<SubagentGap>"]
    if not gap.get("finished"):
        lines.append("- 还没调用 finish")
    if gap.get("missing_candidates"):
        lines.append(
            "- 未判定的对话候选（表内编号）：" + "、".join(str(item) for item in gap["missing_candidates"])
        )
    if gap.get("missing_metric"):
        lines.append("- 还没提交章级指标")
    lines.append("</SubagentGap>")
    return "\n".join(lines)


__all__ = [
    "SUBAGENT_ROLE_SCOPES",
    "SUBAGENT_SYSTEM_PROMPT",
    "build_chapter_message",
    "build_subagent_gap_message",
    "build_subagent_message",
    "build_system_prompt",
]
