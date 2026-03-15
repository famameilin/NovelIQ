from __future__ import annotations

from src.config import settings

SYSTEM_PROMPT = settings.prompts.local_annotation_system
FORMAT_REQUIREMENTS = settings.prompts.local_annotation_format
FEW_SHOT_EXAMPLES = settings.prompts.local_annotation_few_shot
DISAMBIGUATE_SYSTEM_PROMPT = settings.prompts.local_disambiguate_system
ANONYMOUS_DISAMBIG_SYSTEM_PROMPT = settings.prompts.local_anonymous_disambig_system

SYSTEM_PROMPT_V2 = settings.prompts.local_annotation_system_v2
FORMAT_REQUIREMENTS_V2 = settings.prompts.local_annotation_format_v2
FEW_SHOT_EXAMPLES_V2 = settings.prompts.local_annotation_few_shot_v2
USER_TEMPLATE_V2 = settings.prompts.local_annotation_user_template

FORESHADOWING_SYSTEM_PROMPT = settings.prompts.foreshadowing_system
FORESHADOWING_USER_TEMPLATE = settings.prompts.foreshadowing_user_template
FORESHADOWING_EXAMPLES = settings.prompts.foreshadowing_examples


def build_retry_prompt(original_user_prompt: str, bad_output: str, invalid_names: list[str]) -> str:
    """
    构建重试 prompt

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
