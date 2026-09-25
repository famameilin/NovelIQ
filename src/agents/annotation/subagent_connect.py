"""章内多代理并发：跨 agent 接续层（连接在写入当场成立，本层只处理跨 agent 的残余）

设计（《章内多代理重设计-三代理并发版》§5；2026-09-18 写入生效后收窄）：

- **连接在写入当场成立**：三个 subagent 的实体/关系/事件/参与者/说话人各自经生产单条
  事务边界即时落库（el 按角色命名空间化 `角色:局部键`，同名实体由 write_entity 自己会合）。
  所以本层**不再落任何节点**、不归并、不建别名表、不做全局键替换、不做指标兜底——
  这些都已下沉到构造器与章收尾链。
- **本层剩下的只有跨 agent 才看得出来的那件事：展示名分歧**。结构 subagent 是展示名的
  权威来源；非结构 subagent 登记了它名下没有的写法时（结构登记"沈遥"、事件 subagent
  登记"沈师姐"），如实保留两条实体 + 挂一条 entity_alias 案例待核，绝不静默归并
  （归并=改写已落记录，不在本层职责里）。
- **疑点在构造器里就入池**（登记即进池，同轮检索可见），指标与段落标签在章收尾链一次
  落库，两者都不经本层。
- 挂案例同样经生产单条事务边界（`graph._execute_call`）；挂不上逐条进 skipped（可见降级，
  不整章失败），合同违反照常上抛。本层不负责任何模型可见文案（§3.2：它的名字一个都不进
  模型可见面）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .errors import AnnotationInvariantError
from .graph import _execute_call
from .subagent_ir import SubagentAnnotation, truncate_case_description
from .tools import AnnotationToolLedger

# 展示名分歧入池的类型（待核是否同一身份的写法分歧）
ALIAS_CASE_TYPE = "entity_alias"

# 展示名的权威来源：这一路的 subagent 存在时，它的名字表就是"没有分歧"的基准
AUTHORITATIVE_ROLE = "structure"


@dataclass(slots=True)
class SubagentConnectionSummary:
    """跨 agent 接续层的产出（计数 + 分歧清单，供日志与离线对照消费）"""

    entities: int = 0
    diverged_names: list[str] = field(default_factory=list)
    alias_case_ids: dict[str, str] = field(default_factory=dict)
    # 接续建不起来的逐条原因（可见降级：不静默、不整章失败）
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """用于渲染接续摘要（日志/审计/测试共用一份形状）"""
        return {
            "entities": self.entities,
            "diverged_names": list(self.diverged_names),
            "alias_cases": len(self.alias_case_ids),
            "skipped": list(self.skipped),
        }


class SubagentConnectionLayer:
    """三个 subagent 的跨 agent 接续（逐条经生产单条事务边界，失败逐条降级）

    生命周期：一次章收尾建一次，在所有 subagent 写完之后跑；它只读各 subagent 的产出记录
    与共享账本，写出去的东西只有案例池条目。
    """

    def __init__(
        self,
        ledger: AnnotationToolLedger,
        tool_map: dict[str, Any],
        subagents: Sequence[SubagentAnnotation],
        *,
        observer: Any = None,
        stream: Any = None,
    ) -> None:
        """用于绑定章级账本、工具表与各 subagent 的产出记录"""
        self.ledger = ledger
        self.tool_map = tool_map
        self.subagents = list(subagents)
        self.observer = observer
        self.stream = stream
        self.summary = SubagentConnectionSummary()
        self._call_index = 0

    # ------------------------------------------------------------------
    # 入口

    async def connect(self) -> SubagentConnectionSummary:
        """用于处理全部跨 agent 残余并返回摘要"""
        if self.ledger.graph is None:
            raise AnnotationInvariantError("接续层需要常驻事实图，graph 缺失")
        await self._sweep_name_divergence()
        return self.summary

    # ------------------------------------------------------------------
    # 通用：一次工具调用

    async def _call(self, name: str, args: dict[str, Any], *, record: str) -> dict[str, Any]:
        """用于经生产单条事务边界执行一次写入并登记失败（不抛业务错误）"""
        self._call_index += 1
        entry = await _execute_call(
            {"name": name, "args": args, "id": f"connect-{self._call_index}"},
            tool_map=self.tool_map,
            ledger=self.ledger,
            observer=self.observer,
            stream=self.stream,
            call_index=self._call_index,
            program_meta={
                "program_id": "subagent_connect",
                "op_index": self._call_index,
                "source_line": None,
                "record": record,
                "direct_fallback": False,
            },
        )
        if str(entry.get("status") or "error") != "success":
            raw_receipt = entry.get("receipt")
            receipt: dict[str, Any] = raw_receipt if isinstance(raw_receipt, dict) else {}
            detail = str(receipt.get("message") or receipt.get("error") or entry.get("error") or "写入被拒")
            self._skip(record, detail)
        return entry

    def _skip(self, record: str, reason: str) -> None:
        """用于登记一条可见降级（接续建不起来，但整章继续）"""
        self.summary.skipped.append({"record": record, "reason": reason})
        logger.warning("接续层跳过一条记录 record={} reason={}", record, reason)

    # ------------------------------------------------------------------
    # 唯一的跨 agent 判断：三个 subagent 的展示名分歧

    async def _sweep_name_divergence(self) -> None:
        """用于把非权威 subagent 的独有写法登记成 entity_alias 案例

        只有"存在权威名字表且其它 subagent 与它写法不同"时才有分歧可言：单 subagent
        （solo）路径没有跨 agent 面，直接返回。案例只是登记（待核），不改写已落记录。
        """
        authoritative = {
            entity.name
            for subagent in self.subagents
            if subagent.role == AUTHORITATIVE_ROLE
            for entity in subagent.entities
        }
        if not authoritative:
            return
        seen: set[str] = set()
        for subagent in self.subagents:
            if subagent.role == AUTHORITATIVE_ROLE:
                continue
            for entity in subagent.entities:
                self.summary.entities += 1
                if entity.name in authoritative or entity.name in seen:
                    continue
                seen.add(entity.name)
                self.summary.diverged_names.append(entity.name)
                case_id = await self._push_alias_case(
                    entity.name,
                    implied_type=entity.entity_type,
                    role=subagent.role,
                )
                if case_id is not None:
                    self.summary.alias_case_ids[entity.name] = case_id

    async def _push_alias_case(self, name: str, *, implied_type: str, role: str) -> str | None:
        """用于把一处展示名分歧登记成 entity_alias 案例并返回案例 id（池行 uuid）"""
        entry = await self._call(
            "push_case",
            {
                "description": truncate_case_description(
                    f"非结构 subagent（{role}）登记的展示名不在结构 subagent 名下，"
                    f"按 {implied_type} 落库：{name}。（待核是否同一身份的写法分歧）"
                ),
                "keys": [name],
                "type": ALIAS_CASE_TYPE,
            },
            record=f"case/{name}",
        )
        raw_receipt = entry.get("receipt")
        receipt: dict[str, Any] = raw_receipt if isinstance(raw_receipt, dict) else {}
        raw_case_id = receipt.get("case_id")
        return str(raw_case_id) if isinstance(raw_case_id, str) and raw_case_id else None


__all__ = [
    "ALIAS_CASE_TYPE",
    "AUTHORITATIVE_ROLE",
    "SubagentConnectionLayer",
    "SubagentConnectionSummary",
]
