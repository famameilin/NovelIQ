"""
程序面 API 目录渲染与合同文案：签名渲染、参数说明表与 execute_code 工具说明
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：program.py 大文件拆分——API 目录渲染 + 合同文案（_dedent_catalog_text/_type_label/
# call_parameters/call_api_text/_CALL_PARAMETER_NOTES/PROGRAM_CONTRACT_TEXT 等）迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑、签名与模型可见文案；render_list_signature 与限额
# 常量保留在 program.py，由本模块反向引用（program.py 末尾 re-export 本模块符号）。

from __future__ import annotations

import inspect
from enum import StrEnum
from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from src.agents.annotation.program_contract import PROGRAM_MAX_CODE_CHARS, PROGRAM_MAX_OPS
from src.agents.annotation.validation_errors import _STAGE_FIELD_EXPECTATIONS
from src.event_trees.vocabulary import EventParticipantRole
from src.fact_graph.inputs import EntityNameRef
from src.fact_graph.schema import (
    CLIFFHANGER_DESCRIPTION,
    ENTITY_REF_FIELD_HINT,
    EVENT_ROLE_FIELD_HINT,
    PERSON_ROLE_FIELD_HINT,
    PIVOT_MOMENT_DESCRIPTION,
    EntityRefType,
)
from src.fact_graph.vocabulary import Confidence, DialogueVerdict, RoleFunction, Tone, relation_catalog_text

from .search_projection import (
    _PROJECTION_PARAMETER_LABELS,
    _PROJECTION_PARAMETERS,
    _SEARCH_PROJECTIONS,
)


def _dedent_catalog_text(text: str) -> str:
    """2026-09-18 用于把工具说明压成左对齐

    工具 docstring 的续行带 8 空格缩进（源码里为了让文档字符串字面量对齐），渲染进目录后
    是半截缩进段——看起来像加了层级，实际没有任何语义，同一份目录里一半条目缩进、一半不缩进。
    首行不动，其余行按最小的非空缩进量去掉公共前缀（条目内的项目符号缩进保留相对关系）。
    """
    lines = str(text or "").splitlines()
    if len(lines) < 2:
        return str(text or "")
    indented = [line for line in lines[1:] if line.strip()]
    if not indented:
        return lines[0]
    common = min(len(line) - len(line.lstrip()) for line in indented)
    if common == 0:
        return "\n".join(lines)
    return "\n".join([lines[0], *(line[common:] if line.strip() else "" for line in lines[1:])])


# 2026-09-20 具名渲染：目录签名里每个参数带类型标签（`evidence: 整数`）。
# 模型面此前只有参数名——evidence 是段首号、端点/参与者是实体引用都只能靠被拒才知道
# （run 54a72932：目录里那 23 条"参数形状不符"与 160 条 evidence 自由文本都出在这里）。
# 标签一律从注解派生，取不到就留空（宁缺勿猜）；取值域与判据仍在脚注的参数说明里。
_SCALAR_TYPE_LABELS: dict[Any, str] = {
    str: "文本",
    int: "整数",
    bool: "True/False",
    float: "小数",
    dict: "对象",
    list: "列表",
}


def _type_label(annotation: Any, *, metadata: tuple[Any, ...] = ()) -> str:
    """用于把参数注解渲染成目录里的类型标签（取不到就返回空串）

    实体引用按注解标记单独命名；枚举报"枚举（N 个取值）"——签名只报这是闭集，取值与
    判据在同一条参数说明里；容器取内层标签（list[str] → 文本列表）；可空只去掉 None
    分支，省略与否由默认值那一截表达。
    """
    if any(isinstance(item, EntityRefType) for item in metadata):
        return "实体引用"
    if annotation is None or annotation is inspect.Parameter.empty:
        return ""
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return _type_label(args[0], metadata=tuple(args[1:]))
    if origin in (Union, UnionType):
        branches = [item for item in get_args(annotation) if item is not type(None)]
        return _type_label(branches[0]) if len(branches) == 1 else ""
    if origin is Literal:
        return "取值 " + " / ".join(repr(value) for value in get_args(annotation))
    if origin is dict:
        return "对象"
    if origin in (list, tuple, set):
        inner = get_args(annotation)
        inner_label = _type_label(inner[0]) if inner else ""
        return f"{inner_label}列表" if inner_label else "对象列表"
    if annotation is EntityNameRef:
        return "名字与大类对象"
    if isinstance(annotation, type):
        if issubclass(annotation, StrEnum):
            return f"枚举（{len(list(annotation))} 个取值）"
        return _SCALAR_TYPE_LABELS.get(annotation, "")
    return ""


def _parameter_head(name: str, label: str) -> str:
    """用于渲染参数名与类型标签（类型取不到时只留参数名，与旧目录逐字一致）"""
    return f"{name}: {label}" if label else name


def _function_parameters(function: Any) -> list[tuple[str, str]]:
    """用于从函数签名取参数清单（(参数名, 调用写法)，默认值照原样渲染），构造器用

    注解按 eval_str 求值：本模块与 程序运行时 都在 `from __future__ import
    annotations` 下，不求值拿到的是字符串，渲染出来就是死文案。
    """
    try:
        signature = inspect.signature(function, eval_str=True)
    except (NameError, TypeError, ValueError):
        signature = inspect.signature(function)
    parameters: list[tuple[str, str]] = []
    for parameter in signature.parameters.values():
        head = _parameter_head(parameter.name, _type_label(parameter.annotation))
        if parameter.default is inspect.Parameter.empty:
            parameters.append((parameter.name, head))
        else:
            parameters.append((parameter.name, f"{head} = {parameter.default!r}"))
    return parameters


def _schema_parameters(tool: Any, *, extra: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """用于从 args_schema 取参数清单（必填与默认值由字段自己声明，不手抄）

    必填排在可选之前（Python 调用面的写法）；extra：schema 之外的调用面参数（检索的
    fields/limit 由程序面投影层消费，不在工具 schema 里），一律按可选渲染。
    """
    fields = getattr(getattr(tool, "args_schema", None), "model_fields", None) or {}
    required: list[tuple[str, str]] = []
    optional: list[tuple[str, str]] = []
    for name, field in fields.items():
        head = _parameter_head(
            str(name),
            _type_label(field.annotation, metadata=tuple(getattr(field, "metadata", ()) or ())),
        )
        if field.is_required():
            required.append((str(name), head))
        else:
            default = "None" if field.default is None else repr(field.default)
            optional.append((str(name), f"{head} = {default}"))
    optional.extend(
        (name, _parameter_head(name, _PROJECTION_PARAMETER_LABELS.get(name, "")) + " = None") for name in extra
    )
    return [*required, *optional]


def _projection_parameter_note(name: str, parameter: str) -> str:
    """用于按投影规则渲染检索工具 fields/limit 的取值（单一来源：_SEARCH_PROJECTIONS）"""
    rule = _SEARCH_PROJECTIONS[name]
    if parameter == "fields":
        return f"回执里保留的字段（可选：{'、'.join(rule.fields)}；省略时给 {'、'.join(rule.default_fields)}）"
    return f"最多回几条（1..{rule.max_limit}，默认 {rule.default_limit}）"


def call_parameters(name: str, target: Any) -> list[tuple[str, str]]:
    """用于取一个可调用对象的参数清单（带 args_schema 的读 schema，其余读函数签名）

    构造器是裸函数、工具带 args_schema，两者在目录与拒绝提示里都走本函数——同一个名字
    在两处渲染出同一个签名。
    """
    if getattr(target, "args_schema", None) is not None:
        extra = _PROJECTION_PARAMETERS if name in _SEARCH_PROJECTIONS else ()
        return _schema_parameters(target, extra=extra)
    return _function_parameters(target)


def _parameter_notes(name: str, parameters: list[tuple[str, str]]) -> list[str]:
    """用于逐行渲染参数说明（按 名字.参数 → 参数 查表；同名参数语义不同时点名覆盖）

    说明文本里的换行按续行缩进两格渲染：词表（关系类型 12 值、枚举判据）是多行的，
    不缩进会让下一条参数看起来还在上一条的说明里。
    """
    notes: list[str] = []
    for parameter, _ in parameters:
        text = _CALL_PARAMETER_NOTES.get(f"{name}.{parameter}") or _CALL_PARAMETER_NOTES.get(parameter)
        if text is None and name in _SEARCH_PROJECTIONS and parameter in _PROJECTION_PARAMETERS:
            text = _projection_parameter_note(name, parameter)
        if text:
            head, *rest = str(text).splitlines() or [""]
            notes.append(f"- {parameter}：{head}")
            notes.extend(f"  {line}" for line in rest if line.strip())
    return notes


def call_api_text(entries: list[tuple[str, list[tuple[str, str]], str]]) -> str:
    """用于把一批可调用对象渲染成模型可见的 API 目录（本面唯一的渲染路径）

    entries = [(名字, 参数清单, 说明文本)]：参数清单分别从函数签名（构造器）与 args_schema
    （工具）读出，说明文本来自函数对象的 docstring 或本面的覆盖表——两类条目在这一层没有
    形态差别（2026-09-18 之前构造器渲染成"签名 + 参数说明"、工具渲染成"名字 + 参数JSON
    Schema"，同一份目录两种呈现；schema 的 $defs/anyOf 是给校验器读的，模型面要的只是
    "这个参数是什么、取什么值"，由 _CALL_PARAMETER_NOTES 一行讲清）。
    """
    blocks: list[str] = []
    for name, parameters, summary in entries:
        lines = [render_list_signature(name, parameters), _dedent_catalog_text(summary).strip()]
        notes = _parameter_notes(name, parameters)
        if notes:
            lines.append("参数说明：")
            lines.extend(notes)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def constructor_call_entries(entries: list[tuple[str, Any, str]]) -> list[tuple[str, list[tuple[str, str]], str]]:
    """用于把构造器清单（名字, 可调用, 一句话说明）翻成目录条目

    2026-10-02 恢复：随章内多 Agent 路径一并加回（0.2.0 重构曾摘除）。
    """
    return [
        (name, _function_parameters(function), inspect.getdoc(function) or summary)
        for name, function, summary in entries
    ]


def tool_call_entries(
    tools: list[Any], *, descriptions: dict[str, str] | None = None
) -> list[tuple[str, list[tuple[str, str]], str]]:
    """用于把工具对象翻成目录条目（说明可被本面覆盖，参数面只取名字与默认值）

    2026-09-18 descriptions：按工具名覆盖目录里的说明。工具对象的 docstring 是生产工具的
    口径。参与者、关系两端、说话人在原生面与构造器面都使用正文名字与大类，
    构造器覆盖文案只解释本工作局部锚点，不引入另一套实体引用口径。
    未覆盖的工具一律不写第二份文案，仍以工具对象为单一事实源。
    """
    entries: list[tuple[str, list[tuple[str, str]], str]] = []
    for tool in tools:
        name = str(tool.name)
        raw = (descriptions or {}).get(name) or getattr(tool, "description", "") or ""
        entries.append((name, call_parameters(name, tool), raw))
    return entries


# 2026-09-17 §12.5① 目录里每个参数的取值与约束（模型可见面，构造器与工具共用一张表）。
# 章面收窄后 write_* 的参数说明退出模型可见面，而闭合关系目录只在 write_relation 的
# relation_type 说明里、tone 目录只在 write_dialogue 的 tone 说明里——块面与章面的
# 构造器于是只能靠被拒来猜（实测：verdict 一次 42 条、entity_type/relation_type 各数十条）。
# 本表按参数名给目录，文本一律从闭集常量与枚举类 docstring 派生（同一个来源，不手抄）；
# 查表顺序是 "名字.参数" → "参数"，同名参数语义不同时点名覆盖。
def _enum_parameter_note(enum_cls: Any) -> str:
    """用于按枚举类渲染参数说明（判据取类 docstring、取值取成员，两处都不手抄）

    schema 的 $defs 渲染出来就是这两样东西；模型面不再渲染 JSON，判据与取值在这里
    合成一行。
    """
    doc = inspect.getdoc(enum_cls) or ""
    return f"{doc}\n取值：{'、'.join(str(member.value) for member in enum_cls)}"


_CALL_PARAMETER_NOTES: dict[str, str] = {
    **_STAGE_FIELD_EXPECTATIONS,
    "relation_type": "闭合关系类型（方向与两端实体类型约束如下）：\n" + relation_catalog_text(),
    "tone": _enum_parameter_note(Tone),
    "confidence": _enum_parameter_note(Confidence),
    "from_entity": f"关系起点{ENTITY_REF_FIELD_HINT}",
    "to_entity": f"关系终点{ENTITY_REF_FIELD_HINT}",
    "speaker": f"说话人{ENTITY_REF_FIELD_HINT}",
    "el": "本章来源局部键：实体用 a1，事件声明用 e1；斜杠仅局部寻址，不表示包含",
    "query": "检索原文的关键词，多词任一命中；% 匹配任意长度，_ 匹配单个字符",
    "search_events.isforeshadowing": "只看伏笔根声明（True）或只看非伏笔根（False），不填返回全部；"
    "伏笔根 = write_event(isforeshadowing=True) 种下的树根，伏笔动作的引用来源只在其中",
    "search_events.compact": "紧凑索引模式：每条只回声明 id、章号、标题、类型、状态、保存态与伏笔标记，"
    "每页最多 100 条；用于通览全书声明，详情仍用 read_event",
    "evidence": "本章事件所在段落的段首号（整数），不是引文",
    "read_chapter_text.paragraph_id": "本章正文段首可见号，由引擎换算为全局段落号",
    "read_text.paragraph_id": "全局段落号，跨章检索命中时照抄 paragraph_ids 中的值",
    "pivot_moment": PIVOT_MOMENT_DESCRIPTION,
    "cliffhanger": CLIFFHANGER_DESCRIPTION,
    "verdict": _enum_parameter_note(DialogueVerdict),
    "event.title": "本章事件标题，不是逐个动作标签",
    "event.problem": "本事件围绕的具体问题",
    "event.summary": "原文支持的事件概要",
    "event.event_type": "简短事件类型，不是main/secondary",
    "event.status": "ongoing 或 resolved，章节结束不代表事件解决",
    "event.progress": "本章明确推进，可空；不得编造结局",
    "declaration_id": "章级事件声明来源身份，由 event 回执或 kind=declaration 检索获得，不是正式 event_id",
    "source_declaration_id": "伏笔来源声明身份，只接受伏笔树根：write_event(isforeshadowing=True) 种下的那棵树的根"
    "（read_event 回执 is_foreshadow_setup=True）；普通事件树根不算，须先读取该声明核对",
    "action_type": "伏笔动作类型：写英文常量 'reinforce'（强化）或 'payoff'（疑似回收），不写中文词",
    "target_declaration_id": "强化或回收所指声明身份，可空；填写时须先读取该声明",
    "characters": '[{"name": 正文名字, "entity_type": 实体大类, "role": 参与角色, "narrative_role": 叙事功能, '
    '"action": 做了什么, "emotion": -2..2 整数}, …]；'
    "role/narrative_role/action/emotion 都可省略或写偏：role 缺省按实体登记类型取"
    "（character→主体、location→地点、其余→客体），叙事功能近义词自动归一，"
    "emotion 越界按边界收敛；非 character 条目只给 name、entity_type 与 role。"
    f"role 取：{'、'.join(member.value for member in EventParticipantRole)}（{EVENT_ROLE_FIELD_HINT}）；"
    f"narrative_role 取：{'、'.join(member.value for member in RoleFunction)}（{PERSON_ROLE_FIELD_HINT}）",
    "participants.items": '[{"name": 正文名字, "entity_type": 实体大类, "role": 参与角色, '
    '"narrative_role": 叙事功能, "action": 一句话动作, "emotion": -2..2 整数}, …]；'
    "四个描述字段都可省略或写偏：role 缺省按实体登记类型取（character→主体、location→地点、"
    "其余→客体），叙事功能近义词自动归一，emotion 越界按边界收敛。"
    f"role 取：{'、'.join(member.value for member in EventParticipantRole)}（{EVENT_ROLE_FIELD_HINT}）；"
    f"narrative_role 取：{'、'.join(member.value for member in RoleFunction)}（{PERSON_ROLE_FIELD_HINT}）",
}


# 2026-09-18 重写成逐条：原来的单段散文把五个主题（语法/常量/失败/上限/回执）串成一句，
# 批量纪律与收尾纪律又夹在回执字段定义中间，模型要在几百字里切主题。分三块——运行规则、
# 回执字段是机制，引用与证据口径是取值面，工作方式是行为合同：**四块都在这一份说明里**
# （模型在这个面只有 execute_code 与 finish 两件工具，说明就是它读得到的全部合同）。
# 2026-10-02 恢复 AGENT_CONTRACT_TEXT：随章内多 Agent 路径一并加回（0.2.0 重构曾摘除）。
AGENT_CONTRACT_TEXT: str = (
    "执行一段 Python 程序，每次成功调用写入本次来源或候选记录，失败只作废那一条。"
    "正式事件仍须诊断统一发布。\n"
    "运行规则：\n"
    "- 对话序号：执行前预检可确定的 candidate_index 范围，越界时本程序不执行；动态返回值仍逐项校验。\n"
    "- 语法：变量赋值、字典下标赋值、列表/字典/元组、下标、列表拼接 +、for 与 if、==/!=/in；"
    "range(stop)/range(start, stop, step) 接受整数位置参数，最多500项；业务工具只写具名参数；"
    "没有 import、属性访问、函数定义或其他 Python API（没有 len 等内置函数）。"
    "常量写 True/False/None（也接受 true/false/null）；\n"
    "字典/列表一律写字面量（{…}/[…]）：dict()/list() 等构造器与列表推导不可用，循环一律用 for。\n"
    "- 检索结果自动出现在 reads，无需 print（未开放）。具名调用示例：\n"
    '  events_page = search_events(query="院门", chapter_id=24, limit=5, offset=0)\n'
    '  graph_page = search_graph(query="阿青", limit=5, offset=0, relation_offset=0)\n'
    '  for candidate in graph_page["entities"]:\n'
    '      entity_detail = read_entity(entity_id=candidate["id"])\n'
    '  for item in events_page["events"]:\n'
    '      detail = read_event(node_id=item["declaration_id"], kind="declaration")\n'
    "  后续翻页沿用原 query/筛选条件，offset 填上一页 next_offset；None 表示没有下一页。\n"
    "- 变量：程序里赋的变量在本章后续程序里保留；构造器与检索的返回值都能用变量承接。\n"
    "  工具名全部保留，不得作为变量（如 entity/event/metric/finish）；"
    "实体详情用 entity_detail，事件详情用 event_detail，检索页用 graph_page/events_page。\n"
    "- 执行前检查整段语法白名单，禁用语法使本程序不执行；"
    "业务失败只作废该条调用、后面的语句继续执行；动态运行错误停止本程序、已成功的调用保留。\n"
    f"- 上限：单个程序最多 {PROGRAM_MAX_CODE_CHARS} 字符、{PROGRAM_MAX_OPS} 条调用。\n"
    "回执字段：\n"
    "- status：本次程序的整体结果。\n"
    "- applied：本程序成功的调用条数。\n"
    "- failed：失败清单，每条给 op（第几条调用）、line（源码行）、record、field、code、expected。\n"
    "- written：本程序成功的 record 键，直接照抄，不自行拼接。\n"
    "- reads：本程序最近的读结果，正文可截短；references 保留全部 source_ref 与坐标，"
    "variables 给出仍可使用的原文引用变量，reads_omitted 是省略正文回显的实际条数。\n"
    "- progress：本 Agent 各类已写入记录的条数。\n"
    "- error：程序在写完之前就失败时的错误详情（type 与 message）。\n"
    "- 单次调用：写类回 status=written 带 record 与 ref（ref 是该次的产出，如 push_case 的案例编号）；"
    "读类直接给数据；被拒一律 status=rejected 带 record/field/code/expected/message。\n"
    "写类调用的成功正文不回显：记录键看 written，进度看 progress，原文句柄看 references。\n"
    "工作方式：\n"
    "- 一次程序把本章该判的内容写完：同一段程序里连续调用多个构造器、写多条记录都可以。\n"
    "- 判不了的用 pending 登记，不要硬套：正文只说见面、对峙这类没有闭合关系可表达的，宁缺勿滥。\n"
    "- reads 已经是本程序检索到的数据，不要用 print 或为看同一份结果反复检索；"
    "search_events 的节点列表在 events 字段，search_graph 的两组列表在 entities/relations 字段；"
    "failed 里那一条按 expected 当场改。\n"
    "- 产出写完时调用 finish 收尾：收尾不减损已写入的记录，回执点名还缺什么，缺的当场补。\n\n"
)


def render_list_signature(name: str, parameters: list[tuple[str, str]]) -> str:
    """2026-09-16 用于渲染调用签名（参数清单从函数签名或 args_schema 读出，不手抄）

    2026-09-18 参数清单先在调用方算好（构造器读函数、工具读 schema），本函数只做排版：
    构造器与工具在目录里是同一种签名的写法。
    2026-09-20 参数那一截自带类型标签（见 _type_label），本函数只负责拼。
    """
    return f"{name}(" + ", ".join(text for _, text in parameters) + ")"
