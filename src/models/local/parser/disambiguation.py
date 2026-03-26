"""
消歧解析模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分parser.py
说明: 提取消歧解析相关逻辑
"""

from __future__ import annotations

from typing import cast

from .json_utils import try_parse_json


class DisambiguationParseError(Exception):
    """人名消歧解析错误"""
    pass


def parse_alias_map(content: str, candidates: list[str] | list[dict[str, int]]) -> dict[str, str]:
    """
    解析消歧结果

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 支持 List[str] 和 List[Dict] 两种候选人名格式
    """
    parsed = try_parse_json(content)
    if parsed is None:
        raise DisambiguationParseError("disambiguate_characters json parse failed, content is empty or invalid")
    if not isinstance(parsed, dict):
        raise DisambiguationParseError("disambiguate_characters response not dict")
    alias_map = parsed.get("alias_map", {})
    if not isinstance(alias_map, dict):
        raise DisambiguationParseError("disambiguate_characters alias_map not dict")

    name_list: list[str] = []
    if candidates and isinstance(candidates[0], dict):
        dict_candidates = cast(list[dict[str, int]], candidates)
        name_list = [str(c["name"]) for c in dict_candidates]
    else:
        str_candidates = cast(list[str], candidates)
        name_list = list(str_candidates)

    result: dict[str, str] = {}
    for name in name_list:
        if name in alias_map:
            result[name] = str(alias_map[name])
        else:
            result[name] = name
    return result
