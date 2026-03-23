"""
消歧消息构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧消息构建逻辑

修改时间: 2026-03-20
修改者: TraeAI
任务: fix-hardcoded-relation-types
修改内容: 动态生成层级关系类型说明，从配置读取而非硬编码

修改时间: 2026-03-23
修改者: TraeAI
任务: prompt-consolidation
修改内容: 使用占位符替换动态构建 prompt
"""

from __future__ import annotations

from typing import Dict, List, cast

from src.config import settings
from ..prompts import DISAMBIGUATE_SYSTEM_PROMPT, ANONYMOUS_DISAMBIG_SYSTEM_PROMPT


_RELATION_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "belongs_to": "人物属于某组织（如 伯安 belongs_to 贺家）",
    "member_of": "人物是某群体成员（如 张三 member_of 赤甲卫）",
    "leader_of": "人物是某群体/组织领袖（如 贺重明 leader_of 贺家）",
    "affiliated_with": "群体隶属于某组织（如 赤甲卫 affiliated_with 贺家）",
    "father_of": "A是B的父亲（如 褚军 father_of 褚大山）",
    "son_of": "A是B的儿子（如 褚大山 son_of 褚军）",
    "parent_of": "A是B的父母（如 赵兰英 parent_of 伯安）",
    "child_of": "A是B的子女（如 伯安 child_of 赵兰英）",
    "sibling_of": "A是B的兄弟姐妹（如 伯安 sibling_of 贺重明）",
    "spouse_of": "A是B的配偶（如 赵兰英 spouse_of 贺铮）",
}


def _build_relation_types_section() -> str:
    """
    根据配置动态构建层级关系类型说明

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: fix-hardcoded-relation-types
    说明: 从配置读取有效关系类型，动态生成说明文本
    """
    valid_types = settings.analysis.valid_hierarchical_relation_types
    lines = ["【层级关系类型说明】"]
    for rel_type in valid_types:
        desc = _RELATION_TYPE_DESCRIPTIONS.get(rel_type, f"{rel_type} 关系")
        lines.append(f"- {rel_type}：{desc}")
    return "\n".join(lines)


def _build_relation_types_union() -> str:
    """
    构建关系类型的联合类型字符串（用于 JSON 格式说明）

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: fix-hardcoded-relation-types
    """
    valid_types = settings.analysis.valid_hierarchical_relation_types
    return "|".join(valid_types)


def _build_dynamic_system_prompt() -> str:
    """
    构建动态的系统 prompt，替换占位符

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: fix-hardcoded-relation-types
    说明: 基于静态 prompt 模板，动态替换关系类型相关内容

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: prompt-consolidation
    修改内容: 使用占位符 {{RELATION_TYPES_UNION}} 和 {{RELATION_TYPES_SECTION}}
    """
    base_prompt = DISAMBIGUATE_SYSTEM_PROMPT

    relation_types_union = _build_relation_types_union()
    base_prompt = base_prompt.replace("{{RELATION_TYPES_UNION}}", relation_types_union)

    relation_types_section = _build_relation_types_section()
    base_prompt = base_prompt.replace("{{RELATION_TYPES_SECTION}}", relation_types_section)

    return base_prompt


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
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数

    修改时间: 2026-03-20
    创建者: TraeAI
    任务: fix-hardcoded-relation-types
    修改内容: 使用动态生成的系统 prompt，包含配置中的关系类型
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

    system_prompt = _build_dynamic_system_prompt()
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
