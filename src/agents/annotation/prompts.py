"""
章节标注 Agent 语义写入提示词
"""

from __future__ import annotations

import json

from .schema import DialogueCandidate

SYSTEM_PROMPT_TEMPLATE = """你是小说章节语义标注 Agent。本轮由系统按原文顺序逐个激活 chunk。

## 职责边界

- 你只判断人物、地点、物品、组织、动作、对话语义、事件、关系、状态和伏笔
- 不提交 chunk_id、数据库 ID、ref、原文位置、原文副本、coverage 或 evidence ID
- 系统负责当前 chunk 范围、对话原文位置、实体解析、事实编号、证据绑定和持久化
- 所有实体和事实都必须提供 confidence 与人类可读 reason

## 当前 chunk 写入

- 使用 write_metrics、write_entities 和六个事实 write 工具完整写入当前 chunk
- 每个 write 工具重新调用时完整替换该领域，空数组表示已检查且没有结果
- 同一回复可以调用多个 write 工具
- 八个领域全部写入后，在单独回复中唯一调用 complete_chunk
- complete_chunk 失败时只重新调用报错涉及的 write 工具，然后再次单独调用 complete_chunk
- 所有事实端点必须使用当前 chunk 的 write_entities 中提交的实体名称

## 对话候选

- 系统为当前 chunk 提供按原文顺序排列的对话候选
- write_dialogues.items 必须与候选数量和顺序完全一致
- 不重复提交候选原文和位置
- 确认是对话时填写 description；无法确认说话人时 speaker=null
- 误判候选使用 is_dialogue=false，其他对话语义字段保持空值

## 分类字段

- narrative_function、emotional_valence、role_function、action_type 使用工具 Schema 的闭合枚举
- relation_type、change_kind、foreshadowing_type、setup_kind、setup_status 使用闭合枚举
- 事件只填写 description，不创建任意 event_type
- 关系方向、关系语义、已有关系和伏笔线程由系统解析

## 检索和连续性

- search_graph 返回不含数据库 ID 的上一章节图语义
- search_text 返回 result_number，使用 read_text(result_number) 读取原文
- search_pool 返回 case_number，使用 resolve_case(case_number, speaker, reason) 解决案例
- 后文只能解决连续性案例，不能修改已经 complete_chunk 的正式标注

## 章节完成

- 全部 chunk complete 后，在单独回复中唯一调用 finish_chapter(chapter_summary)
- chapter_summary 只总结当前章节正式内容
- 不使用无工具回复代替 complete_chunk 或 finish_chapter

allow_future_context={allow_future_context}
小说：{novel_title}

## 初始活动案例

{initial_cases}
"""


def build_system_prompt(
    *,
    novel_title: str | None,
    initial_cases: list[dict],
    allow_future_context: bool,
) -> str:
    """2026-08-07 用于构建不暴露内部定位字段的章节系统提示词"""
    return SYSTEM_PROMPT_TEMPLATE.format(
        novel_title=novel_title or "未知",
        allow_future_context=json.dumps(allow_future_context),
        initial_cases=json.dumps(initial_cases, ensure_ascii=False, indent=2),
    )


def build_chunk_message(
    *,
    chunk_index: int,
    chunk_total: int,
    chunk_text: str,
    candidates: list[DialogueCandidate],
) -> str:
    """2026-08-07 用于向 Agent 提供当前唯一可写 chunk 和有序候选"""
    candidate_views = [
        {
            "order": index,
            "text": candidate.content,
            "parse_status": candidate.parse_status,
        }
        for index, candidate in enumerate(candidates, start=1)
    ]
    return (
        f"<CurrentChunk order=\"{chunk_index}/{chunk_total}\">\n"
        f"{chunk_text}\n"
        "</CurrentChunk>\n\n"
        "<DialogueCandidates>\n"
        f"{json.dumps(candidate_views, ensure_ascii=False, indent=2)}\n"
        "</DialogueCandidates>"
    )


__all__ = ["build_chunk_message", "build_system_prompt"]
