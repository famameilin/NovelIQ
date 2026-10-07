"""事实图：标注域契约与写入面（graph）

说明: 标注域契约（identity 稳定身份、vocabulary 值域、schema/inputs/outputs 提交与
绑定模型、evidence 证据格式）随写入面同包——它们只有标准库与 pydantic 依赖。本包是
标注 agent 的私有域：agent 自建 FactGraph 写图；编排层（workflows）、持久化（storage）
与传输层（api）都不 import 本包，图谱读视图在 storage（repositories/graph/authority）。

包级不维护 re-export（写入面与存储层互相引用，eager 导入会形成环）；消费者按子模块
路径导入（`src.fact_graph.graph` / `src.fact_graph.schema`）。
"""

from __future__ import annotations
