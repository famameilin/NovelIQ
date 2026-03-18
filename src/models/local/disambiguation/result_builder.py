"""
消歧结果构建模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 提取消歧结果构建逻辑
"""

from __future__ import annotations

from typing import Dict, List, cast

from ..schema import DisambiguateResponseModel


def build_result_from_response(
    response_data: DisambiguateResponseModel,
    candidates: List[str] | List[Dict[str, int]],
) -> Dict[str, str]:
    """
    从 DisambiguateResponseModel 构建结果字典，确保所有候选名都有映射

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 重构本地消歧客户端集成 Instructor

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
    修改内容: 提取为独立模块函数
    """
    name_list: list[str] = []
    if candidates and isinstance(candidates[0], dict):
        dict_candidates = cast(list[dict[str, int]], candidates)
        name_list = [str(c["name"]) for c in dict_candidates]
    else:
        str_candidates = cast(list[str], candidates)
        name_list = list(str_candidates)

    result: dict[str, str] = {}
    for name in name_list:
        if name in response_data.alias_map:
            result[name] = str(response_data.alias_map[name])
        else:
            result[name] = name
    return result
