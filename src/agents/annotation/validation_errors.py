"""
章节标注校验错误翻译层：把 pydantic 校验失败翻成模型可自纠的结构化拒绝回执
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：tools.py 大文件拆分——原校验错误翻译层（_STAGE_FIELD_* 三表 +
# _translate_record_validation / translate_write_validation_error）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；记录键仍由 tools.tool_record_key 生成，
# tools.py 对外保留 re-export（program/graph 的导入零改动）。

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import ValidationError

from src.fact_graph.schema import ENTITY_TAGS_RULE_TEXT
from src.fact_graph.vocabulary import tone_catalog_text

from .errors import AnnotationStageRejection
from .tools import tool_record_key


def _short_pydantic_message(msg: str) -> str:
    """2026-09-12 用于剥离 pydantic 报错样板（Value error 前缀与文档链接尾注）"""
    cleaned = msg
    if cleaned.startswith("Value error, "):
        cleaned = cleaned[len("Value error, ") :]
    return re.sub(r"\s*\[type=[^\]]*\]$", "", cleaned)


# 2026-09-13 小调用改造：字段级取值域纠错文案（按 pydantic 失败族翻译成可自纠说明）
_EVENT_ROLE_VALUES_TEXT = "主体/客体/接收者/帮助者/反对者/见证者/地点"

_EVENT_NARRATIVE_ROLE_VALUES_TEXT = "主体/客体/发送者/接收者/帮助者/反对者/见证者"
_STAGE_FIELD_EXPECTATIONS: dict[str, str] = {
    "verdict": "dialogue=真实对话 / inner_monologue=内心独白 / not_dialogue=误判候选",
    "tone": tone_catalog_text(),
    "relation_type": "闭合关系类型（见 write_relation 参数说明）",
    # 2026-09-20 回执只报字段取值域，"这个字段是什么、怎么判"归提示词面——写在载荷模型的
    # 字段说明里（schema.ParticipantArg.role/narrative_role），本表不再替它复述。
    "role": _EVENT_ROLE_VALUES_TEXT,
    "narrative_role": _EVENT_NARRATIVE_ROLE_VALUES_TEXT,
    "entity_type": "character / location / item / organization",
    "narrative_function": "冲突 / 铺垫 / 转折",
    "confidence": "high / medium / low（伏笔回收可能性三档）",
    "payoff_likelihood": "high / medium / low",
    "type": '"main"（顺延主因链）或 "secondary"（挂在当时主链尾）',
    "emotion": "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    "emotional_valence": "-2..2 整数分值（-2 强烈负面 … 2 强烈正面）",
    "entityid": "实体引用：本章自定的 el 键，或 write_entity 回执里的 run 级 id",
    "speaker": "说话人实体引用：el 键或 run 级 id",
    "candidate_index": "1 基候选序号（见 DialogueCandidates 表）",
    "el": "实体/事件节点的章内局部键（实体如 a1；事件根如 t1、子事件如 t1/e2），由你指定",
    "isroot": "true=建事件树根（el=树键），false=子事件（el=树键/节点键）",
    "characters": "参与者数组，每项 {entityid, role[, narrative_role, action, emotion]}（character 三态必填）",
    "labels": "段落情绪标签数组，每项 {paragraph_id, emotion}（paragraph_id 取段首可见号，即正文每段开头的 `N：`）",
    "paragraph_id": "段首可见号（正文每段开头的 `N：`）",
    "tags": f"字符串数组，{ENTITY_TAGS_RULE_TEXT}",
    "paragraph_ids": "全局段落 ID 列表",
    "summary": "本章摘要（非空文本）",
}
_STAGE_FIELD_CODES: dict[str, str] = {
    "missing": "missing",
    "enum": "invalid_value",
    "literal_error": "invalid_value",
    "int_parsing": "not_integer",
    "int_type": "not_integer",
    "int_from_float": "not_integer",
    "string_too_short": "too_short",
    "string_too_long": "too_long",
    "greater_than_equal": "out_of_range",
    "less_than_equal": "out_of_range",
    "greater_than": "out_of_range",
    "less_than": "out_of_range",
    "extra_forbidden": "unknown_field",
    # 记录级联合约束（三态字段组合、单表内一致性）由 model_validator 抛出
    "value_error": "invalid_combination",
}
# 2026-09-14 闭合枚举字段的拒绝文案：枚举类型只给出合法值本身，这里补上"没有贴合的用哪个"
_STAGE_ENUM_FALLBACKS: dict[str, str] = {
    "tone": "没有贴合的用「其他」",
}


def _translate_record_validation(
    record: str,
    exc: ValidationError,
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> AnnotationStageRejection:
    """2026-09-13 用于把单条记录的 pydantic 失败翻成结构化拒绝回执

    只报第一个失败字段：小调用的粒度就是一个字段一个语义单元，一次修一处。
    """
    errors = exc.errors()
    first: dict[str, Any] = dict(errors[0]) if errors else {}
    raw_location: tuple[int | str, ...] = first.get("loc") or ()
    location = (
        [str(part) for part in raw_location if str(part) != "__root__"]
        if isinstance(raw_location, (list, tuple))
        else []
    )
    field = location[-1] if location else None
    kind = str(first.get("type") or "")
    code = _STAGE_FIELD_CODES.get(kind, kind or "invalid")
    expected = _STAGE_FIELD_EXPECTATIONS.get(field or "")
    detail = _short_pydantic_message(str(first.get("msg") or ""))
    message = f"{tool_name} 记录不符合合同: {field or '参数'} {detail}"
    if kind == "missing" and expected:
        message = f"{tool_name} 缺少必填字段 {field}：{expected}"
    if kind == "extra_forbidden":
        # 2026-09-13 未声明参数不再被静默丢弃：整条拒绝并指出多余字段名
        expected = "只提交本工具声明的参数（多余字段会被整条拒绝）"
        message = f"{tool_name} 不接受参数 {field}：该字段不属于本工具"
    if kind == "enum" and expected:
        # 2026-09-14 闭合枚举字段（tone 等）：pydantic 只说"输入必须是…"，把取值域与
        # 兜底指引写全，模型一次就能自纠（不回显整份合同）
        value = first.get("input")
        fallback = _STAGE_ENUM_FALLBACKS.get(field or "")
        suffix = f"（{fallback}）" if fallback else ""
        message = f"{tool_name} 记录不符合合同: {field} 只能是 {expected}{suffix}，收到 {value}"
    # 消息点名参与者，record 仍指向整条被拒的事件调用，保留原子写入的定位合同
    record_label = record
    if args is not None and len(raw_location) >= 2 and raw_location[0] == "characters":
        participants = args.get("characters")
        index = raw_location[1]
        if isinstance(participants, list) and isinstance(index, int) and 0 <= index < len(participants):
            participant = participants[index]
            if isinstance(participant, dict) and participant.get("entityid") is not None:
                record_label = f"{record}/participant/{participant['entityid']}"
    # 缺失与显式 null 分开报告，字段错误只回显该字段的实际输入
    if location:
        submitted = "<未提供>" if kind == "missing" else repr(first.get("input"))
        message = f"{record_label}({'.'.join(location)}={submitted})：{message}"
    elif isinstance(first.get("input"), dict):
        # 联合约束无字段路径时，优先回显报错明确提到的字段，不猜测纠正取值
        named_fields = set(re.findall(r"\b[A-Za-z_]\w*\b", detail))
        values = {name: value for name, value in first["input"].items() if name in named_fields}
        values = values or first["input"]
        submitted = ", ".join(
            f"{name}={repr(value.value if isinstance(value, Enum) else value)}" for name, value in values.items()
        )
        message = f"{record_label}({submitted})：{message}"
    else:
        message = f"{record_label}：{message}"
    return AnnotationStageRejection(
        message,
        record=record,
        field=field,
        code=code,
        expected=expected or detail,
    )


def translate_write_validation_error(
    tool_name: str,
    args: dict[str, Any],
    exc: ValidationError,
) -> AnnotationStageRejection:
    """2026-09-13 用于把工具层 schema（langchain 参数绑定）失败翻成结构化拒绝回执

    schema 层的失败发生在工具函数体之前，记录键只能从原始参数拼装。
    """
    record = tool_record_key(tool_name, args) or tool_name
    return _translate_record_validation(record, exc, tool_name=tool_name, args=args)
