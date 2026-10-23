"""
章节标注语义写入工具与系统运行账本

核心合同: 写入面为五个领域工具（write_entity / write_metrics / write_event /
write_relation / write_dialogue），实体与事件节点用模型自定的 el 局部键寻址、
写入即生效并返回真实回执（{status: written, record}）；领域没有结束事件，
finish 与无工具响应是等价的结束请求；程序在批次完成后检查并冻结当前 work。
完整参数和完整结果只进入审计库，不回到模型上下文。

事件的来源身份是事件树节点 ID；局部 el 只用于
本 work 寻址，不表达包含结构或调用顺序。伏笔与情节推进只引用来源事件。

"""

# 账本与工具工厂按实际定义导入；本文件只维护查询工具和键规范化

from __future__ import annotations

import json
import unicodedata
from collections.abc import Sequence
from typing import Annotated, Any, Protocol

from langchain_core.tools import tool
from pydantic import ConfigDict, Field, create_model

from src.fact_graph.inputs import ChapterParagraphInfo
from src.fact_graph.outputs import SourceReference, TextSearchResult
from src.fact_graph.schema import EL_PATH_SEP, RESERVED_ROOT_KEY

from .errors import AnnotationAuthorizationError, AnnotationInputError

# 领域写入工具表：正式写入工具集合与失败归因共用同一份事件
_DOMAIN_WRITE_TOOLS: dict[str, tuple[str, ...]] = {
    "entities": ("write_entity",),
    "metrics": ("write_metrics",),
    "events": ("write_event",),
    "relations": ("write_relation",),
    "dialogues": ("write_dialogue",),
}
# 全部写入工具（schema 层失败翻译与正式工具集合使用）
_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    tool_name for tool_names in _DOMAIN_WRITE_TOOLS.values() for tool_name in tool_names
)
# 收尾在同回合写入处理完后统一校验，正式与连续性信封各自实现冻结边界
FINISH_TOOL_NAME: str = "finish"
# 五域固定遍历顺序：工具面排序、缺内容提醒与写入计数共用（无逐域结束事件）
_DOMAIN_ORDER = ("entities", "metrics", "events", "relations", "dialogues")
# 事件根节点在章内局部键空间里的固定名字（子事件键不得占用）；权威定义在 schema
_ROOT_NODE_KEY = RESERVED_ROOT_KEY
# 局部键路径分隔符：子事件 el = "<树键>/<节点键>"；权威定义在 schema
_EL_PATH_SEP = EL_PATH_SEP


def _norm_entity_key(name: str, entity_type: object = "") -> str:
    """用于生成实体身份键（与 FactGraph 复合键同源：规范名+实体大类）"""
    from src.fact_graph.graph import entity_key

    return entity_key(name, entity_type)


# 局部键由模型自行指定、写入即生效——同一轮里先建的键，后面的调用直接可用。
EntityLocalKey = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "本实体的章内局部键（el），由你指定（如 a1）；write_entity 写入即生效，"
            "同轮 write_event/write_relation/write_dialogue 的实体引用直接用它，不必等回执"
        ),
    ),
]
EventLocalKey = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "本节点的层级局部键，由你指定：根事件 el=树键（如 t1），"
            "子事件 el=树键/节点键（如 t1/e2，节点键不得占用 root）；"
            "写入即生效，同轮后面的子事件和参与者引用直接可用"
        ),
    ),
]


def tool_record_key(tool_name: str, args: dict[str, Any]) -> str | None:
    """用于按工具名与原始参数生成稳定记录键（成功回执与拒绝回执共用）

    参数可能是未过 schema 的原始值，此处只做展示级拼接、不做校验；
    键在 章收尾前保持稳定，重写同键即更新同一条记录。
    """
    if tool_name == "write_entity":
        return f"entity/{args.get('name')}"
    if tool_name == "write_metrics":
        return "metrics"
    if tool_name == "write_dialogue":
        return f"dialogue/{args.get('candidate_index')}"
    if tool_name == "write_relation":
        return f"relation/{args.get('from_entity')}-{args.get('to_entity')}/{args.get('relation_type')}"
    if tool_name == "write_event":
        el = str(args.get("el") or "")
        if _EL_PATH_SEP not in el and not bool(args.get("isroot")):
            # 子事件键写错形态时仍按原样回显，回执定位到被拒的那次调用
            return el or "event"
        if _EL_PATH_SEP in el:
            return el
        return f"{el}/{_ROOT_NODE_KEY}" if el else "event"
    if tool_name in {"anchor_record", "write_link"}:
        return str(args.get("record_id") or tool_name)
    return None


class AnnotationQueryService(Protocol):
    """章级标注使用的全书原文查询能力"""

    async def search_text(
        self,
        query: str,
        *,
        range_name: str,
        limit: int = 50,
    ) -> Sequence[Any]:
        """返回段落级候选行（storage 的 TextSearchCandidate），域模型由本层构造"""
        ...

    async def read_paragraph(self, paragraph_id: int, *, allow_future_context: bool) -> dict[str, Any]: ...


def _normalize_query(query: str, *, tool_name: str) -> str:
    """用于统一校验查询工具输入长度与空白"""
    normalized = unicodedata.normalize("NFC", query).strip()
    if not normalized or len(normalized) > 2000:
        raise AnnotationInputError(f"{tool_name}.query 必须为 1 至 2000 个 Unicode 字符")
    return normalized


def _norm_graph_name(name: str) -> str:
    """用于生成与 FactGraph 一致的实体名称精确匹配键"""
    return unicodedata.normalize("NFC", name).strip().casefold()


def _forbid_undeclared_args(tool_candidate: Any) -> None:
    """用于让写入类工具拒绝未事件参数

    langchain 由函数签名生成的参数模型默认 extra=ignore：模型多写的字段被静默丢弃，
    例如把 isforeshadowing 写到子事件上仍报 staged，语义丢失却看不出错。收紧为整条
    拒绝后，多余字段名随结构化回执回到模型，一次改一处。
    """
    schema = tool_candidate.args_schema
    if schema is None:
        return
    tool_candidate.args_schema = create_model(
        schema.__name__,
        __base__=schema,
        __config__=ConfigDict(extra="forbid"),
    )


class TextReadLedger(Protocol):
    """原文工具只依赖读取授权，不要求调用方拥有章级写入账本"""

    @property
    def run_scope(self) -> str: ...
    @property
    def phase(self) -> str: ...
    @property
    def allow_future_context(self) -> bool: ...
    @property
    def current_chapter_id(self) -> int | None: ...
    @property
    def paragraph_info(self) -> ChapterParagraphInfo | None: ...
    @property
    def text_references(self) -> dict[str, SourceReference]: ...
    @property
    def authorized_text_paragraph_ids(self) -> set[int]: ...
    def append_search_log(self, entry: dict[str, Any]) -> None: ...


def build_search_tools(
    query_service: AnnotationQueryService,
    ledger: TextReadLedger,
) -> list[Any]:
    """标注仅检索原文，不依赖其他章节的分析完成顺序"""

    @tool
    async def search_text(query: str, offset: int = 0) -> str:
        """按关键词检索正文，每个命中是一段正文

        关键词命中的段落排在前面（keyword_score 是命中的查询词项数）；
        其后补该查询的语义相近段落，这类条目 keyword_score 为 0，只表示相近，不含查询词。
        查询支持多关键词（空格/标点分隔，任一命中即返回）与通配符
        （% 匹配任意长度、_ 匹配单个字符），如「伯安 偷%」或「赤羽_尾鸡」；
        回执包含章节、段落和服务端绑定的来源能力，提交审计据此登记。
        命中只给段落定位（paragraph_ids），不产生 source_ref；
        要把原文作为案例证据或锚点，需再 read_text 该段取 source_ref。
        """
        normalized_query = _normalize_query(query, tool_name="search_text")
        if offset < 0:
            raise AnnotationInputError("offset 不能为负数")
        if ledger.phase not in {"chapter_open", "diagnosis_open"}:
            raise AnnotationAuthorizationError(f"阶段 {ledger.phase} 不允许 search_text")
        expected_range = "all" if ledger.allow_future_context else "previous"
        results = [
            TextSearchResult(
                chapter_id=row.chapter_id,
                paragraph_ids=[row.paragraph_id],
                content=row.excerpt,
                keyword_score=row.keyword_score,
                semantic_score=row.semantic_score,
            )
            for row in await query_service.search_text(
                normalized_query,
                range_name=expected_range,
                limit=offset + 9,
            )
        ]
        views: list[dict[str, Any]] = []
        for item in results[offset : offset + 8]:
            visible_content = item.content[:2000]
            ledger.authorized_text_paragraph_ids.update(item.paragraph_ids)
            view = {
                "content": visible_content,
                "truncated": len(item.content) > len(visible_content),
                "keyword_score": item.keyword_score,
                "semantic_score": item.semantic_score,
            }
            view.update(
                {
                    "chapter_id": item.chapter_id,
                    "paragraph_ids": list(item.paragraph_ids),
                    "capability": "current_text" if item.chapter_id == ledger.current_chapter_id else "other_text",
                }
            )
            views.append(view)
        if views and len(results) > offset + 8:
            views[-1]["next_offset"] = offset + 8
        ledger.append_search_log(
            {
                "tool": "search_text",
                "query": normalized_query,
                "hits": [f"result-{index}" for index in range(1, len(views) + 1)],
                "digest": "",
            }
        )
        return json.dumps(views, ensure_ascii=False)

    return [search_text]
