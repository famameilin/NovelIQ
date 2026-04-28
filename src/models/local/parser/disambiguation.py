"""
消歧解析模块

说明: 提取消歧解析相关逻辑
"""

from __future__ import annotations

from src.models.disambiguation_types import NameCountCandidate

from .json_utils import try_parse_json


class DisambiguationParseError(Exception):
    """人名消歧解析错误"""

    pass


def parse_alias_map(content: str, candidates: list[NameCountCandidate]) -> dict[str, str]:
    """
    解析消歧结果
    """
    parsed = try_parse_json(content)
    if parsed is None:
        raise DisambiguationParseError("disambiguate_characters json parse failed, content is empty or invalid")
    if not isinstance(parsed, dict):
        raise DisambiguationParseError("disambiguate_characters response not dict")
    alias_map = parsed.get("alias_map", {})
    if not isinstance(alias_map, dict):
        raise DisambiguationParseError("disambiguate_characters alias_map not dict")

    name_list = [str(candidate["name"]) for candidate in candidates]

    result: dict[str, str] = {}
    for name in name_list:
        if name in alias_map:
            result[name] = str(alias_map[name])
        else:
            result[name] = name
    return result
