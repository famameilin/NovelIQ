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
CANONICAL_RESELECT_SYSTEM_PROMPT = settings.prompts.reselect_canonical
ANONYMOUS_DISAMBIG_SYSTEM_PROMPT = settings.prompts.anonymous_disambig

STAGE_SUMMARY_SYSTEM_PROMPT = """你是一个小说分析助手。请根据以下分块摘要，生成一个100字以内的阶段性摘要。

要求：
1. 保留关键事件和人物名称
2. 突出情节发展脉络
3. 不包含人物关系推断，只总结事件
4. 控制在100字以内
5. 输出纯文本，不要包含任何标记或格式"""

STAGE_SUMMARY_USER_TEMPLATE = """以下是连续{count}个分块的摘要：

{summaries}

请生成一个100字以内的阶段性摘要，概括这一段情节的发展。"""


def build_retry_prompt(
    original_user_prompt: str,
    bad_output: str,
    invalid_names: list[str] | None = None,
    validation_details: dict[str, list[str]] | None = None,
    is_repetitive: bool = False,
) -> str:
    """
    构建重试 prompt

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor

    修改时间: 2026-03-30
    修改者: TraeAI
    任务: feature/chunk-summary-timeline-only
    修改内容: 添加 is_repetitive 参数，支持重复输出重试

    Args:
        original_user_prompt: 原始用户 prompt
        bad_output: 上次的错误输出
        invalid_names: 无效人名列表（可选）
        is_repetitive: 是否为重复输出错误

    Returns:
        重试 prompt
    """
    if is_repetitive:
        return f"""{original_user_prompt}

【上次输出有误，请重新标注】
上次输出存在重复内容，请确保：
1. 每个字段只出现一次
2. 不要重复相同的 JSON 结构
3. 输出简洁、无冗余

上次的错误输出（已截断）：
{bad_output[:1000]}...

请严格遵守格式要求，输出正确的 JSON。"""

    invalid_names = invalid_names or []
    invalid_names_str = "、".join(invalid_names)
    sections: list[str] = []
    details = validation_details or {}

    hallucinated_names = details.get("hallucinated_names") or []
    dangling_names = details.get("dangling_names") or []

    if hallucinated_names:
        sections.append(f"上次输出中以下名字未在文本或可用上下文中出现：{'、'.join(hallucinated_names)}")
    if dangling_names:
        sections.append(
            f"上次输出中以下名字出现在 relations 或 dialogues 中，但没有写入 characters：{'、'.join(dangling_names)}"
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
