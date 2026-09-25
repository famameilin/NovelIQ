"""
章节标注 Agent 语义写入提示词
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import ChapterParagraphInfo, DialogueCandidate, paragraph_has_visible_prefix

# 2026-09-18 系统提示词从 data/prompts 的两个 txt 读：agent.txt＝写者面、sub_agent.txt＝subagent 面
# （提示词是数据不是代码，改提示词只改 txt；读不到文件直接抛错，不做静默兜底）。
# 路径从本文件算起（src/agents/annotation/prompts.py → 仓库根/data/prompts），不依赖 CWD；
# Dockerfile.backend 有 `COPY data ./data`，容器里同一路径成立。
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "data" / "prompts"


def _read_prompt_text(filename: str) -> str:
    """用于读取 data/prompts 下的提示词文本（首尾空白剔除，正文逐字保留）"""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()

# 2026-09-14 处理规则上提系统层（原在【进度账本】注入块
# 逐回合下发；规则是静态行为合同，属系统提示词，注入块只留动态状态）。实测依据
# run a8c29ec8：规则上线后 ch1-3 墙钟 -44%，回合构成变为"判完即写、一批收章"。
# 原"只能一行职责声明"的单行裁决就此废止。
# 同日删除"首写前必须先 search_graph"硬闸（tools.write_entity），
# 提示词里对应的从属条款一并删净——写入不再被检索回执推后一个回合。
# 2026-09-16 删去"你的思考对后续回合不可见，跨回合预演计划等于下回合从零重推"一句。
# 2026-09-17 回合压缩纪律回填：main 时代系统提示词要求"全部领域于同一回复批量提交，
# 通常 1-2 个回复完成全部写入"，实测 main run fda9e7a7（同书同日）每章只花 1 个写入
# 回合（write_metrics + write_entities + write_relations + write_dialogues + create_event
# 同轮发出）；本分支 09-14 重写的短提示词与 09-15 的程序面规则都丢了这条纪律，
# 实测 run 73d51472 每章 3-4 个写入回合、逐领域一个回合，同书墙钟 2h→8h 主要来自这里。
SYSTEM_PROMPT = _read_prompt_text("agent.txt")

# 2026-09-18 三代理并发：subagent 面系统提示词同样从 txt 读（sub_agent.txt）。
SUBAGENT_SYSTEM_PROMPT = _read_prompt_text("sub_agent.txt")

# subagent 各自的职责范围（只写在文案里，**不通过拿掉工具或构造器实现**，§3）：
# 多块章按三条职责并发（角色名单源在 subagent_ir）
# 2026-09-18 职责文案只留**分域**：这个角色负责哪些域、不负责哪些域。参数取值、引用与证据
# 口径、批量与收尾纪律全部在 execute_code 的说明里（那份说明是模型读得到的唯一合同），
# 原来这里把 id 口径、evidence 段首号、别名不归并、pending 别硬套又各抄一遍——同一件事
# 三处各写一遍，改一处漏两处，且属不属于这个角色的域混在一起反而看不清。
# 2026-09-19 双路径定案：solo 形态随单块章归 agent 路径一起退役，职责表只剩三条。
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
    """2026-08-30 用于构建 agent 路径（单块章）的系统提示词

    2026-09-04 曾追加"案例编号"检索管道规则，2026-09-05 裁决删除：
    该规则把非案例疑点（如对话说话人）误导进 search_pool 空转至上限
    （第3章 15 轮 40 次检索 0 写入）。id 授权=检索展示即授权
    + 工具层 case_id 校验（未授权 id 直接报错自纠）。
    2026-09-19 双路径定案：本提示词服务 agent 路径（单块章，程序面）；
    程序面合同在 execute_code 的说明里，subagent 路径用 sub_agent.txt。
    """
    return SYSTEM_PROMPT


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
    （三个 subagent 唯一的区分，2026-09-18 唯一保留的规则文案）；能力合同在 execute_code
    的 description 里，两份文案同轮下发。
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

    2026-09-18 提示词面清理：只留缺口事实（缺收尾/缺候选判定/缺指标），
    去掉"请补齐后再次调用 finish""逐条 dialogue() 判定""metric() 是硬前提"
    等处理方式规训句——补写方式在 finish/execute_code 的 description 里。
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
