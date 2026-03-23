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


def build_retry_prompt(original_user_prompt: str, bad_output: str, invalid_names: list[str]) -> str:
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
    return f"""{original_user_prompt}

【上次输出有误，请重新标注】
上次输出中以下名字未在文本中出现，属于捏造：{invalid_names_str}
上次的错误输出：
{bad_output}

请严格遵守【严格限制】规则，重新输出正确的 JSON。"""
