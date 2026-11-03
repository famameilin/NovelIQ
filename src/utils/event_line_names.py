"事件线名称的格式、覆盖与去重校验"

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_LINE_NAME = re.compile(r"[^\s]{1,5}线")


def validate_event_line_names(names: Mapping[str, str], event_line_ids: Iterable[str]) -> None:
    "事件线名称须一次覆盖全部选定树，格式为 1–5 个非空白字符加「线」且互不相同"
    selected = set(event_line_ids)
    missing = sorted(selected - set(names))
    extra = sorted(set(names) - selected)
    if missing or extra:
        raise ValueError(f"事件线命名必须一次覆盖全部选定事件线：缺少 {missing}，多出 {extra}")
    invalid = {key: value for key, value in names.items() if _LINE_NAME.fullmatch(value) is None}
    if invalid:
        raise ValueError(f"事件线名称须为 1–5 个非空白字符加「线」：{invalid}")
    repeated = sorted({value for value in names.values() if list(names.values()).count(value) > 1})
    if repeated:
        raise ValueError(f"事件线名称不得重复：{repeated}")
