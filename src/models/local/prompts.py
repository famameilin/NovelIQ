"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: Prompt 常量和工具函数

修改时间: 2026-03-23
修改者: TraeAI
任务: prompt-consolidation
修改内容: 使用新的按任务组织的 prompt 结构
"""

from __future__ import annotations

from src.config import settings

SYSTEM_PROMPT_V2 = settings.prompts.phase1.system
FORMAT_REQUIREMENTS_V2 = settings.prompts.phase1.format
FEW_SHOT_EXAMPLES_V2 = settings.prompts.phase1.few_shot
USER_TEMPLATE_V2 = settings.prompts.phase1.user_template

FORESHADOWING_SYSTEM_PROMPT = settings.prompts.phase2.system
FORESHADOWING_USER_TEMPLATE = settings.prompts.phase2.user_template
FORESHADOWING_EXAMPLES = settings.prompts.phase2.examples

DISAMBIGUATE_SYSTEM_PROMPT = settings.prompts.disambiguate
ANONYMOUS_DISAMBIG_SYSTEM_PROMPT = settings.prompts.anonymous_disambig


def build_retry_prompt(
    original_user_prompt: str,
    bad_output: str,
    invalid_names: list[str],
    validation_details: dict[str, list[str]] | None = None,
) -> str:
    """
    构建重试 prompt

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor

    Args:
        original_user_prompt: 原始用户 prompt
        bad_output: 上次的错误输出
        invalid_names: 无效人名列表

    Returns:
        重试 prompt
    """
    invalid_names_str = "、".join(invalid_names)
    sections: list[str] = []
    details = validation_details or {}

    hallucinated_names = details.get("hallucinated_names") or []
    dangling_names = details.get("dangling_names") or []

    if hallucinated_names:
        sections.append(
            f"上次输出中以下名字未在文本或可用上下文中出现：{'、'.join(hallucinated_names)}"
        )
    if dangling_names:
        sections.append(
            "上次输出中以下名字出现在 relations 或 dialogues 中，"
            f"但没有写入 characters：{'、'.join(dangling_names)}"
        )
    if not sections:
        sections.append(f"上次输出中以下名字需要修正：{invalid_names_str}")

    sections_text = "\n".join(sections)
    return f"""{original_user_prompt}

【上次输出有误，请重新标注】
{sections_text}
上次的错误输出：
{bad_output}

请严格遵守【严格限制】规则，重新输出正确的 JSON。"""
