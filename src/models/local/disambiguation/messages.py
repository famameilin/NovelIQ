"""
消歧消息构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧消息构建逻辑
"""

from __future__ import annotations

from typing import Dict, List, cast

from ..prompts import DISAMBIGUATE_SYSTEM_PROMPT, ANONYMOUS_DISAMBIG_SYSTEM_PROMPT


def build_disambiguate_messages(
    candidates: List[str] | List[Dict[str, int]],
    context_sentences: Dict[str, str] | None = None,
    existing_names: List[str] | None = None,
    rag_hint: str | None = None,
) -> List[Dict[str, str]]:
    """
    构建消歧消息

    修改时间: 2026-03-12
    创建者: TraeAI
    修改内容: 支持 List[str] 和 List[Dict] 两种候选人名格式，Dict 格式包含频次信息

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数
    """
    lines = []

    if candidates and isinstance(candidates[0], dict):
        dict_candidates = cast(List[Dict[str, int]], candidates)
        for item in dict_candidates:
            name = str(item["name"])
            count = item.get("count", 0)
            ctx = context_sentences.get(name, "") if context_sentences else ""
            if ctx:
                lines.append(f"- {name}（次数：{count}，参考：{ctx}）")
            else:
                lines.append(f"- {name}（次数：{count}）")
    else:
        str_candidates = cast(List[str], candidates)
        for name in str_candidates:
            ctx = context_sentences.get(name, "") if context_sentences else ""
            if ctx:
                lines.append(f"- {name}（参考：{ctx}）")
            else:
                lines.append(f"- {name}")

    body = "\n".join(lines)

    system_prompt = DISAMBIGUATE_SYSTEM_PROMPT
    if existing_names:
        anchor_str = "、".join(existing_names)
        system_prompt += f"\n\n【已存在的角色】以下名字已在知识库中存在：[{anchor_str}]。如果你有充分证据认为候选人名与这些角色是同一人物，可以合并；如果证据不足，保持独立。"

    user_parts = [
        "以下候选人名可能是同一人物的不同称呼，也可能是不同人物。",
        "请根据例句中的上下文判断，若两人明显是不同人物请不要合并。",
    ]
    if rag_hint:
        user_parts.append(rag_hint)
    user_parts.append(f"\n候选人名列表：\n{body}")
    user_content = "\n".join(user_parts)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def build_anonymous_disambig_messages(
    anonymous_names: List[str],
    anonymous_contexts: Dict[str, str],
    existing_names: List[str] | None = None,
    existing_contexts: Dict[str, str] | None = None,
) -> List[Dict[str, str]]:
    """
    构建匿名消歧消息

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数
    """
    info_parts = []
    for name in anonymous_names:
        ctx = anonymous_contexts.get(name, "无上下文")
        info_parts.append(f"【匿名人物】{name}\n上下文：\n{ctx}\n---")
    anonymous_info = "\n\n".join(info_parts)

    existing_lines = []
    if existing_names:
        for name in existing_names:
            ctx = existing_contexts.get(name, "") if existing_contexts else ""
            if ctx:
                existing_lines.append(f"- {name}（参考：{ctx}）")
            else:
                existing_lines.append(f"- {name}")
    existing_str = "\n".join(existing_lines) if existing_lines else "无"

    user_content = f"""以下匿名占位名需要识别真实身份。

【已知正式名】
{existing_str}

{anonymous_info}

请根据上下文判断每个匿名人物的真实身份。"""

    return [
        {"role": "system", "content": ANONYMOUS_DISAMBIG_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
