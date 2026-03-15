"""
全局上下文管理模块

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 移除 operations 导入，使用 Repository 替代
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from loguru import logger

from src.storage.repositories import StatsRepository


def extract_global_context(first_chunks: list[str], client=None) -> dict[str, Any]:
    if not first_chunks:
        return {"core_characters": [], "world_setting": ""}

    combined_text = "\n".join(first_chunks[:3])

    if client is not None:
        return _extract_with_model(client, combined_text)

    return _extract_with_rules(combined_text)


def _extract_with_model(client, text: str) -> dict[str, Any]:
    try:
        prompt = f"""请从以下小说文本中提取：
1. 核心角色（最多5个主要人物名称）
2. 世界观设定（一句话描述故事背景）

请以JSON格式返回：
{{"core_characters": ["角色1", "角色2"], "world_setting": "世界观描述"}}

文本：
{text[:3000]}"""
        response = client._client.chat.completions.create(
            model=client._config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        result = _parse_json_response(content)
        if result:
            return result
    except Exception as e:
        logger.warning("model extraction failed: {}", str(e))

    return _extract_with_rules(text)


def _extract_with_rules(text: str) -> dict[str, Any]:
    names = _extract_chinese_names(text)
    name_counter = Counter(names)
    core_characters = [name for name, _ in name_counter.most_common(5)]

    world_setting = _extract_world_setting(text)

    return {"core_characters": core_characters, "world_setting": world_setting}


def _extract_chinese_names(text: str) -> list[str]:
    patterns = [
        r'[""「『]([^""」』]{2,4})[""」』]',
        r'(?:说道|问道|答道|喊道|叫道|笑道|怒道|冷道|叹道)[：:]\s*[""「『]?([^""「』\n]{2,4})',
        r"([\\u4e00-\\u9fa5]{2,3})(?:站起身|走上前|转过身|抬起头|低下头|睁开眼|闭上眼)",
    ]
    names = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        names.extend(matches)

    filtered_names = []
    for name in names:
        if len(name) >= 2 and len(name) <= 4:
            if not re.match(r"^[这那什么如何为何]", name):
                filtered_names.append(name)

    return filtered_names


def _extract_world_setting(text: str) -> str:
    keywords = [
        "修仙",
        "仙界",
        "魔界",
        "玄幻",
        "武侠",
        "江湖",
        "都市",
        "现代",
        "古代",
        "穿越",
        "重生",
        "异世",
        "帝国",
        "王朝",
        "门派",
        "宗门",
        "家族",
    ]
    found = []
    for kw in keywords:
        if kw in text:
            found.append(kw)

    if found:
        return f"故事背景涉及：{'、'.join(found[:3])}"

    return ""


def _parse_json_response(content: str) -> dict[str, Any] | None:
    json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if not json_match:
        return None

    try:
        result = json.loads(json_match.group())
        if isinstance(result, dict):
            core_characters = result.get("core_characters", [])
            if not isinstance(core_characters, list):
                core_characters = []
            world_setting = result.get("world_setting", "")
            if not isinstance(world_setting, str):
                world_setting = ""
            return {"core_characters": core_characters, "world_setting": world_setting}
    except json.JSONDecodeError:
        pass

    return None


def save_global_context(
    conn,
    novel_id: str,
    core_characters: list[str],
    world_setting: str,
    novel_title: str | None = None,
    run_id: str | None = None,
) -> None:
    """
    保存全局上下文信息到数据库

    修改时间: 2026-03-12
    修改者: TraeAI
    任务: fix-annotation-disambiguation-issues
    修改原因: 支持存储小说标题

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 使用 StatsRepository 替代 operations 函数，添加 run_id 参数
    """
    characters_str = json.dumps(core_characters, ensure_ascii=False)
    stats_repo = StatsRepository(conn)
    stats_repo.insert_global_context(run_id or "default", novel_id, characters_str, world_setting, novel_title)
    logger.debug("saved global context for novel_id={}", novel_id)


def load_global_context(
    conn,
    novel_id: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """
    加载全局上下文信息

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 使用 StatsRepository 替代 operations 函数，添加 run_id 参数
    """
    stats_repo = StatsRepository(conn)
    row = stats_repo.fetch_global_context(run_id or "default", novel_id)
    if row is None:
        return None

    novel_title, characters_str, world_setting, updated_at = row
    try:
        core_characters = json.loads(characters_str) if characters_str else []
    except json.JSONDecodeError:
        core_characters = []

    return {
        "core_characters": core_characters,
        "world_setting": world_setting or "",
        "updated_at": updated_at,
    }


def update_global_context_in_db(
    conn,
    novel_id: str,
    core_characters: list[str] | None = None,
    world_setting: str | None = None,
    run_id: str | None = None,
) -> None:
    """
    更新全局上下文信息

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: storage-layer-decoupling
    修改内容: 使用 StatsRepository 替代 operations 函数，添加 run_id 参数
    """
    kwargs = {}
    if core_characters is not None:
        kwargs["core_characters"] = json.dumps(core_characters, ensure_ascii=False)
    if world_setting is not None:
        kwargs["world_setting"] = world_setting

    if kwargs:
        stats_repo = StatsRepository(conn)
        stats_repo.update_global_context(run_id or "default", novel_id, **kwargs)
        logger.debug("updated global context for novel_id={}", novel_id)


def format_global_context_for_prompt(context: dict[str, Any]) -> str:
    if not context:
        return ""

    lines = ["【全局核心信息】"]

    core_characters = context.get("core_characters", [])
    if core_characters:
        characters_str = "、".join(core_characters)
        lines.append(f"核心角色：{characters_str}")

    world_setting = context.get("world_setting", "")
    if world_setting:
        lines.append(f"世界观：{world_setting}")

    return "\n".join(lines)
