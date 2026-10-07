"""
章内 subagent IR 校验 helpers：命名空间化、字段校验与结构化拒绝
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：subagent_ir.py 大文件拆分——校验 helpers 段（namespace_* / truncate_case_description /
# _reject / _require_*）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；闭集常量与 IR 数据类保留在 subagent_ir.py，
# 本模块引用其常量（subagent_ir.py 末尾对本模块符号 re-export，双向均定义先于引用，
# 任意导入顺序安全）。

from __future__ import annotations

import unicodedata
from typing import Any

from src.fact_graph.schema import EL_PATH_SEP

from .errors import AnnotationStageRejection
from .ir_contract import CASE_DESCRIPTION_MAX_CHARS, ROLE_NAMESPACE_SEP


def namespace_el(role: str, local_key: str) -> str:
    """用于把 subagent 局部引用键翻成落库 el 键（`角色:局部键`）

    三个 subagent 的引用键互不知情（都会用 a1/t1），而正式写入的 el 索引是全章一张表，
    所以命名空间化必须发生在写入口（构造器）而不是落库相位：写入即绑定的键在整个
    章内唯一，后面的关系/参与者/说话人引用直接用它。
    """
    return f"{role}{ROLE_NAMESPACE_SEP}{local_key}"


def namespace_event_el(role: str, el: str) -> str:
    """用于把事件 el（树键/节点键）按角色命名空间化（只前缀树键，节点键原样）"""
    tree_key, _, node_key = el.partition(EL_PATH_SEP)
    namespaced = namespace_el(role, tree_key)
    return f"{namespaced}{EL_PATH_SEP}{node_key}" if node_key else namespaced


def truncate_case_description(text: str) -> str:
    """用于把案例说明压进案例池的长度约束（超限即截断并留痕）"""
    cleaned = " ".join(text.split())
    if len(cleaned) <= CASE_DESCRIPTION_MAX_CHARS:
        return cleaned
    return cleaned[: CASE_DESCRIPTION_MAX_CHARS - 1] + "…"


def _reject(message: str, *, record: str, field: str, code: str, expected: str) -> AnnotationStageRejection:
    """用于构造 subagent 局部对象的记录级结构化拒绝（模型按 record/field/code 自纠）"""
    return AnnotationStageRejection(
        message,
        record=record,
        field=field,
        code=code,
        expected=expected,
    )


def _require_text(value: Any, *, record: str, field_name: str) -> str:
    """用于校验非空人类可读文本（NFC 归一 + strip）"""
    if not isinstance(value, str) or not value.strip():
        raise _reject(
            f"{field_name} 必须是非空字符串",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="非空文本",
        )
    return unicodedata.normalize("NFC", value).strip()


def _require_enum(value: Any, allowed: dict[str, str] | tuple[str, ...], *, record: str, field_name: str) -> str:
    """用于把取值限制在单源闭集内（越界值报出全部合法取值，一次自纠）"""
    catalog = list(allowed) if isinstance(allowed, dict) else list(allowed)
    text = value if isinstance(value, str) else str(value)
    if text not in catalog:
        raise _reject(
            f"{field_name} 取值越界：{value!r}",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="合法取值：" + "、".join(catalog),
        )
    return text


def _require_score(value: Any, *, record: str, field_name: str) -> int:
    """用于校验情绪分值（-2..2 整数，排除 bool）"""
    if isinstance(value, bool) or not isinstance(value, int) or not -2 <= value <= 2:
        raise _reject(
            f"{field_name} 必须是 -2..2 的整数",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="-2 强烈负面 / -1 轻微负面 / 0 中性 / 1 轻微正面 / 2 强烈正面",
        )
    return value


def _require_name(value: Any, *, record: str, field_name: str) -> str:
    """用于校验实体展示名（照抄正文写法，只作展示字段）

    名字不再是引用键：引用一律用模型自定的本 subagent id（见 _require_local_key），
    name 只用于落库时的实体登记与人类可读展示。
    """
    text = _require_text(value, record=record, field_name=field_name)
    if EL_PATH_SEP in text:
        raise _reject(
            f"{field_name} 不能包含斜杠（那是事件树层级键的分隔符）：{text}",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="照抄正文里的人物/地点/物品/组织名（如 沈遥、沈师姐）",
        )
    return text


def _require_local_key(value: Any, *, record: str, field_name: str) -> str:
    """用于校验模型自定的引用键（本 subagent 局部 id：实体 a1/a2…、事件树键 t1）"""
    text = _require_text(value, record=record, field_name=field_name)
    if EL_PATH_SEP in text or not all(char.isalnum() or char == "_" for char in text):
        raise _reject(
            f"{field_name} 只能是字母/数字/下划线组成的引用键：{text}",
            record=record,
            field=field_name,
            code="invalid_value",
            expected="你自定的短键（如 a1、a2、t1）；不要用空格、斜杠或汉字",
        )
    return text


def _require_paragraph_id(
    value: Any,
    *,
    record: str,
    field_name: str,
    paragraph_text_by_id: dict[int, str],
) -> int:
    """用于校验段首可见号属于本章（交给 label 构造器与待决项复用）

    越界号结构化拒绝并列出合法号范围（1..N）。
    """
    if isinstance(value, bool) or not isinstance(value, int) or value not in paragraph_text_by_id:
        size = len(paragraph_text_by_id)
        raise _reject(
            f"{field_name} 不属于本章：{value!r}",
            record=record,
            field=field_name,
            code="out_of_range",
            expected=f"本章段首可见号范围：1..{size}" if size else "本章没有可引用的段落号",
        )
    return value
