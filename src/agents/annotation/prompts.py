"""正式章节标注提示词与原文注入"""

from __future__ import annotations

import json
from pathlib import Path

from src.fact_graph.inputs import ChapterParagraphInfo, DialogueCandidate, paragraph_has_visible_prefix

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "data" / "prompts"


def _read_prompt_text(filename: str) -> str:
    """提示词缺失直接失败，不替换为另一套工作合同"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


ANNOTATION_SCOPE_POLICY = (
    "\n事件职责（event）：同时记录正文明确的问题推进、目标改变、线索揭示，"
    "调用 plotline 并提供前后状态与本章段首证据，关联声明填 declaration_id。"
    "伏笔强化或回收先读取声明，再调用 foreshadow_action，填写 source_declaration_id、"
    "target_declaration_id；照应边不能判回收，埋设随声明自动保存。\n"
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


# annotation 与长章角色共用当前系统提示词，正文和职责在每个 work 中单独注入
AGENT_SYSTEM_PROMPT = _read_prompt_text("annotation_agent.txt") + ANNOTATION_SCOPE_POLICY

# 长章角色职责只在文案中分域，工具能力共用；annotation 负责整章全部领域
# 参数、引用、证据与收尾纪律由 execute_code 的目录说明给出
AGENT_ROLE_SCOPES: dict[str, str] = {
    "entity": (
        '<RoleScope role="实体与关系">\n'
        "你负责这一章的两个域：\n"
        "- entity：按统一判据登记正文里的人物、地点、物品与组织；\n"
        "- relation：实体之间成立的闭合关系边都写。\n"
        "事件与参与者、对话判定、段落标签与章级指标都不属于你（由本章其他 Agent 负责）。\n"
        "</RoleScope>"
    ),
    "event": (
        '<RoleScope role="事件与参与者">\n'
        "你负责这一章的两个域：\n"
        "- event 与 participants：有正文依据的事件写完整声明并填写参与者；使用 event 入口逐条写入，"
        "参与者引用直接写正文名字与大类，运行时自动登记，无需先 entity()；原文锚点由既有引擎完成。\n"
        "- plotline 与 foreshadow_action：保存本章明确的情节推进及伏笔强化/疑似回收，不用实体首次登记冒充推进。\n"
        "实体间的关系边、对话判定、段落标签与章级指标都不属于你。\n"
        "</RoleScope>"
    ),
    "metric": (
        '<RoleScope role="对话与章级证据">\n'
        "你负责这一章的三个域：\n"
        "- dialogue：<DialogueCandidates> 表里的候选逐条判定，一条不落；\n"
        "- label：本章自选 2~3 段的整段情绪标签；\n"
        "- metric：章级摘要与叙事指标。\n"
        "实体间的关系边与事件树构造都不属于你。\n"
        "</RoleScope>"
    ),
}


def _candidate_views(candidates: list[DialogueCandidate]) -> list[dict]:
    """用于渲染对话候选表（读者块切片与写者全章表共用）"""
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
    """用于按段首可见号渲染正文（每段一行，以 `N：` 开头）

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


def build_agent_message(
    *,
    role: str,
    paragraph_info: ChapterParagraphInfo,
    candidates: list[DialogueCandidate],
    role_scope: str,
    chapter_id: int,
    chapter_order: int | None = None,
) -> str:
    """给当前 work 注入整章原文、实际对话候选和角色职责

    段首可见号即 evidence 锚点与标签段号；长章各角色读取同一份整章正文。
    块头写明章号与章级 id：跨章检索按 chapter_id 过滤、跨章引用按章号叙述连续性，
    模型不应再靠检索反推自己在前书的位置。
    能力合同由 execute_code 的 description 提供。
    """
    paragraph_views = _render_paragraph_numbered_text("", paragraph_info)
    order_attr = f' chapter_order="{chapter_order}"' if chapter_order is not None else ""
    sections = [
        f'<CurrentChapter role="{role}"{order_attr} chapter_id="{chapter_id}">\n{paragraph_views}\n</CurrentChapter>',
        "<DialogueCandidates>\n"
        f"total: {len(candidates)}\n"
        f"{json.dumps(_candidate_views(candidates), ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>",
        role_scope,
    ]
    return "\n\n".join(section for section in sections if section)


__all__ = [
    "AGENT_ROLE_SCOPES",
    "AGENT_SYSTEM_PROMPT",
    "build_agent_message",
]

AGENT_SYSTEM_PROMPT += (
    "\nevent 写本章事件级声明（标题、问题、概要、类型、推进、状态、证据）。"
    "全书身份、阶段与包含由诊断确认后一次发布；不按动作拆分过程。"
    "标注阶段不要调用完整事件、过程归属或 submit_events 类工具。"
)
