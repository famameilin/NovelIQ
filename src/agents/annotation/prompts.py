"""正式章节标注提示词与原文注入"""

from __future__ import annotations

import json
from pathlib import Path

from src.fact_graph.schema import ChapterParagraphInfo, DialogueCandidate, paragraph_has_visible_prefix

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "data" / "prompts"


def _read_prompt_text(filename: str) -> str:
    """提示词缺失直接失败，不替换为另一套工作合同"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


ANNOTATION_SCOPE_POLICY = (
    "\n统一判据：\n"
    "- 人物：有姓名、代号、独立行动或实际发言的都登记；匿名行动者或说话人按正文称谓登记，"
    "不编造姓名。无独立行动的路人、士兵等背景群体不登记；代词和泛泛称呼不单独建实体。\n"
    "- 有稳定专指的别名与称号按正文写法分别登记，不自行推断身份；已确认同一人物的关系另行表达。\n"
    "- 机构名称兼指所在场所时统一登记 organization；只有纯地理场所才登记 location。"
    "同章同名只登记一种类型，不因进入、离开等地点用法重复建实体。\n"
    "- 对话：信件、便条、书籍引文及假设性台词判 not_dialogue，其内容保留在事件或证据中；"
    "实际说出口、口头转述或回忆中确实说过的话判 dialogue；真实内心想法判 inner_monologue。"
    "每个候选均需判断，不能因说话人未知而改判 not_dialogue。\n"
)


# solo 与长章角色共用当前系统提示词，正文和职责在每个 work 中单独注入
SUBAGENT_SYSTEM_PROMPT = _read_prompt_text("sub_agent.txt") + ANNOTATION_SCOPE_POLICY

# 长章角色职责只在文案中分域，工具能力共用；solo 负责整章全部领域
# 参数、引用、证据与收尾纪律由 execute_code 的目录说明给出
SUBAGENT_ROLE_SCOPES: dict[str, str] = {
    "structure": (
        "<RoleScope role=\"实体与关系\">\n"
        "你负责这一章的两个域：\n"
        "- entity：按统一判据登记正文里的人物、地点、物品与组织；\n"
        "- relation：实体之间成立的闭合关系边都写。\n"
        "事件与参与者、对话判定、段落标签与章级指标都不属于你（由本章其他 subagent 负责）。\n"
        "</RoleScope>"
    ),
    "event": (
        "<RoleScope role=\"事件与参与者\">\n"
        "你负责这一章的两个域：\n"
        "- event 与 participants：有正文依据的事件都建节点并填写参与者；优先直接调用 submit_events 工具，"
        "提交数据数组，引用与原文锚点由引擎完成。\n"
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




def build_subagent_message(
    *,
    role: str,
    paragraph_info: ChapterParagraphInfo,
    candidates: list[DialogueCandidate],
    role_scope: str,
) -> str:
    """给当前 work 注入整章原文、实际对话候选和角色职责

    段首可见号即 evidence 锚点与标签段号；长章各角色读取同一份整章正文。
    能力合同由 execute_code 的 description 提供。
    """
    paragraph_views = _render_paragraph_numbered_text("", paragraph_info)
    sections = [
        f"<CurrentChapter role=\"{role}\">\n{paragraph_views}\n</CurrentChapter>",
        "<DialogueCandidates>\n"
        f"total: {len(candidates)}\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        role_scope,
    ]
    return "\n\n".join(section for section in sections if section)




__all__ = [
    "SUBAGENT_ROLE_SCOPES",
    "SUBAGENT_SYSTEM_PROMPT",
    "build_subagent_message",
]
