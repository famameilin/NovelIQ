# 完整落地路线图: 协调 `generalize-rag-to-narrative-evidence` 与 `rebuild-knowledge-graph-architecture`

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建时间 | 2026-04-12 |
| 更新时间 | 2026-04-13 |
| 状态 | 阶段 1-3 已完成；阶段 4 已完成 authority 第一轮落地，进入阶段 4/5 |
| 文档定位 | 两份上游文档的联合实施路线图 |
| 上游文档 | `issues/generalize-rag-to-narrative-evidence.md` |
| 上游文档 | `issues/rebuild-knowledge-graph-architecture.md` |

---

## 一句话结论

两份文档不是“一个讲 evidence，一个讲图谱，所以分开做就行”。

它们的完整落地应该被理解为一条连续路线：

1. 先稳定 evidence layer 的前两阶段
2. 冻结图谱权威层向 `Level 1` 暴露的最小结构化契约
3. 再收编消歧侧和更多任务消费者
4. 再进入图谱完整领域层重构
5. 最后把图谱分析、时间轴、诊断、前端展示统一到新的权责边界

因此，这份文档不是只处理“两个议题怎么衔接”，而是给出：

- evidence layer 如何完整落地
- 知识图谱如何完整落地
- 时间轴和前端如何跟随迁移
- 分支如何拆
- 每个阶段做什么、不做什么、如何验收

---

## 这份文档解决什么问题

两份上游文档各自已经讲清楚了很多东西，但还缺少一个工程实施视角下的联合版本。

当前真正缺的不是概念，而是以下问题的统一答案：

1. 先做哪部分，后做哪部分
2. 哪些事情可以并行，哪些必须等契约冻结
3. evidence layer、图谱权威层、时间轴、前端图谱页分别在哪一阶段动
4. 每一阶段的输入、输出、验收、分支策略是什么

---

## 最终目标

### 目标 A: 完成 evidence layer 的真实落地

让 `Level 1 / 2 / 3` 在代码中真正成为：

- 全链路共享的分层叙事证据层

并被以下流程真实消费：

- annotation
- incremental disambiguation
- final disambiguation
- 至少一个非消歧新流程

### 目标 B: 完成知识图谱权威层的真实落地

让图谱不再只是“人物关系图页面的后端数据源”，而是：

- 结构化叙事实体权威层

它需要稳定回答：

- 谁是 canonical entity
- 哪些 alias 已被裁决
- 哪些关系是当前确认关系
- 哪些 entity type 是稳定值
- 哪些 relation event 可以被时间轴安全消费

### 目标 C: 明确下游依赖方向

最终应形成清晰关系：

- 图谱权威层 -> evidence layer 的 `Level 1`
- evidence layer -> annotation / disambiguation / Phase2/3/4
- 图谱权威层 -> 时间轴
- 图谱产品层 -> 图谱页 / 分析交互

---

## 顶层实施顺序

完整落地建议分 6 个大阶段。

### 阶段 0

统一术语、冻结边界

### 阶段 1

完成 evidence layer `Phase 1 / Phase 2`

### 阶段 2

冻结图谱 -> evidence layer 的最小 `Level 1` 契约

### 阶段 3

推进 evidence layer `Phase 3 / Phase 4`

### 阶段 4

完成知识图谱权威层重构

### 阶段 5

完成图谱产品层、时间轴、诊断和前端联动迁移

下面展开说明。

---

## 阶段 0: 统一术语、冻结边界

### 目标

让后续实现不再因为术语混乱而互相污染职责。

### 必须先冻结的术语

- 图谱权威层
- evidence layer
- `Level1AuthoritySnapshot`
- `EvidenceBundle`
- task renderer
- 图谱产品层
- 时间轴下游契约

### 必须先冻结的边界

#### 图谱权威层负责

- 稳定结构化事实
- 可被下游直接引用的领域语义

#### evidence layer 负责

- 组合结构化事实、局部上下文、语义召回
- 向任务侧输出统一证据对象

#### task renderer 负责

- 将 `EvidenceBundle` 渲染成 annotation / disambiguation / relation / dialogue 所需 prompt

#### 图谱产品层负责

- graph page
- summary / quality / analysis interaction

#### 时间轴负责

- 基于图谱权威层的角色子图和关系事件做时间轴表达

### 当前不应再做的事

- 在 provider 中继续新增任务专属 prompt helper
- 在 workflow 里继续拼 graph feedback 字符串
- 让图谱内部 schema 直接暴露给 annotation / disambiguation

### 验收

- 所有新增实现都能明确归类到上述 5 个边界之一

---

## 阶段 1: 完成 evidence layer `Phase 1 / Phase 2`

### 目标

完成 evidence layer 的表达层统一，让 annotation 主链路切到结构化 evidence。

### 这一阶段的真实含义

不是“把所有消费者都改完”，而是：

- 停止让旧 prompt string 继续塑形主数据结构
- 让 annotation 主链路成为第一个真实结构化消费者

### 已包含的工作

#### Step 1.1

provider 内部产出 `EvidenceBundle`

#### Step 1.2

annotation 主链路接 `EvidenceBundle`

#### Step 1.3

引入 annotation renderer，而不是在 workflow/context 中反向拼 prompt 字符串

#### Step 1.4

保留旧 helper，但降级为兼容接口

### 这一阶段还要收尾的点

#### A. `active_entities` 边界

需要明确它是：

- 并入 `local_evidence`

还是：

- annotation 的过渡输入

不能长期双轨模糊。

#### B. 遗留字符串字段退场方案

要明确：

- `disambig_context_str`
- `vector_evidence_str`

是仅兼容保留，还是下一阶段直接删。

### 验收

- provider 可稳定产出 `EvidenceBundle`
- annotation 主链路优先消费结构化 evidence
- 旧 helper 明确是兼容接口
- annotation 回归测试通过

---

## 阶段 2: 冻结图谱 -> evidence layer 的最小 `Level 1` 契约

### 目标

这是两份文档真正的交汇点，也是 evidence layer 下一阶段的前置条件。

### 为什么必须先做这个阶段

如果不先冻结这个契约，evidence layer 在进入 `Phase 3` 时会继续依赖：

- `build_graph_feedback_hint()`
- 散落的 graph repo 查询
- 临时字符串 adapter

这会导致：

- `Level 1` 边界继续漂移
- 消歧侧迁移无法稳定
- 图谱重构后 evidence layer 很难知道哪里被破坏

### 当前最小契约只冻结 4 类事实

1. `alias -> canonical`
2. `confirmed canonical names`
3. `confirmed relations`
4. `stable entity types`

### 本阶段的具体工作

#### Step 2.1

盘点当前来源

需要逐项明确：

- 当前来源 repository / projection 是什么
- 当前字段语义是否已经足够稳定
- 哪些只是“当前实现来源”，不是最终领域模型

#### Step 2.2

实现 `Level1AuthoritySnapshot`

建议先落地最小 dataclass：

```python
@dataclass
class Level1AuthoritySnapshot:
    alias_mappings: list[AliasMapping]
    canonical_entities: list[CanonicalEntity]
    confirmed_relations: list[ConfirmedRelation]
    entity_types: list[EntityTypeFact]
```

#### Step 2.3

实现单一装配入口

例如：

```python
class Level1AuthorityProvider:
    def build_snapshot(self, run_id: str) -> Level1AuthoritySnapshot:
        ...
```

#### Step 2.4

建立 snapshot 测试

必须测试：

- alias 映射是否完整
- confirmed relations 是否按当前关系快照输出
- entity types 是否来自稳定持久化值

### 本阶段不做什么

- 不做完整图谱领域层重构
- 不冻结 relation_events / stable_states / entity_lifecycle 的完整契约
- 不做图谱前端页面重构

### 验收

- 存在单一入口可构造 `Level1AuthoritySnapshot`
- 4 类最小字段来源已清楚
- 下游不再直接查散落 graph helper 拼 Level 1

---

## 阶段 3: 推进 evidence layer `Phase 3 / Phase 4`

### 目标

把消歧侧和更多任务消费点真正接入统一 evidence 语义。

### 只有在阶段 2 完成后才建议开始

因为 `Level 1` 的长期结构化来源这时才稳定。

### Phase 3: 收编消歧侧 helper

#### 要迁移的现有输入

- `context_sentences`
- `rag_hint`
- `build_graph_feedback_hint()`
- 其他基于 alias / relation 的临时 hint

#### 推荐做法

1. 先选 incremental 或 final 的一条链路
2. 把它映射到 `Level 1 / 2 / 3`
3. 引入 disambiguation renderer / adapter
4. 再缩旧 helper

#### 这一步最重要的改变

把：

- 图谱直出字符串

改成：

- 图谱输出结构化快照
- evidence layer 输出 `EvidenceBundle`
- disambiguation renderer 再输出任务专属 hint

### Phase 4: 接入非消歧新消费者

建议优先从以下三者中选一条：

1. Phase 2 伏笔分析
2. Phase 3 对话归属
3. Phase 4 关系抽取

### 推荐优先顺序

#### 方案 A

先做 Phase 2 伏笔分析

原因：

- 现有调用链已预留 `rag_retriever`
- 对图谱契约依赖较轻

当前状态：

- 已完成
- `Phase 2` 已真实消费共享 evidence layer
- `evidence_bundle` 已贯通 `workflow/context -> multi_phase -> phase2 -> message builder`
- `serial / parallel` 两条路径已对齐
- 已补充回归测试，覆盖 `Level 1 / 2 / 3` 提示拼装与 `anchor_text` 不得污染当前 chunk 的约束

#### 方案 B

先做 Phase 3 对话归属

原因：

- Level 1 / 2 接入价值非常直观

### 验收

- 至少一条消歧链路使用新的结构化 evidence 视图
- 至少一个非消歧流程真实消费 `Level 1 / 2 / 3`

---

## 阶段 4: 完成知识图谱权威层重构

### 目标

把图谱从“当前 projection + 页面后端”升级为真正稳定的领域权威层。

### 这一阶段真正要解决的问题

- 图谱实体定义是否扩展到多实体
- canonical entity 语义如何冻结
- confirmed relation 和 relation event 的边界如何冻结
- entity type / stable state 的领域定义如何冻结
- 图谱与时间轴的共享契约如何保护

### 本阶段的工作块

#### Step 4.1

权威层领域对象设计

至少包括：

- canonical entity
- alias mapping
- confirmed relation
- relation event
- entity lifecycle
- stable states

#### Step 4.2

projection / aggregate 重建

明确：

- 哪些 projection 服务图谱页面
- 哪些 projection 服务时间轴
- 哪些输出服务 evidence layer

#### Step 4.3

稳定 repository / service 边界

避免 evidence layer 和产品层继续直接依赖图谱内部实现。

### 当前已落地的阶段 4 内容

截至 2026-04-13，`refactor/knowledge-graph-authority` 已完成以下第一轮 authority 落地：

- 已引入 `KnowledgeGraphAuthorityService`
- 已落地 `Level1AuthoritySnapshot`
- 已落地 `TimelineAuthorityView`
- 已落地 `GraphAuthorityView`
- 已落地 `ActiveEntityContext`，用于承接 `Level 2` 近期活跃实体上下文
- 时间轴已改为消费 authority view，而不是直接依赖图谱 repository 的原始 ORM / dict 形状
- `/graph` 快照已改为消费 authority view
- 图谱节点 contract 已去除 `emotion_score` 这类不应进入稳定 authority contract 的瞬时字段
- 已修正 graph current/history 混合问题：
  - `confirmed_relations` 只表示当前仍有效的确认关系
  - `relation_events` 单独表示历史关系变化
  - graph summary / quality 重新回到“当前权威事实”语义

### 当前阶段 4 的边界说明

虽然 authority 第一轮落地已经完成，但这不等于阶段 4 全部结束。

当前更准确的状态是：

- authority service / view / contract 已成形
- current relation 与 relation history 的语义边界已收紧
- `Level 2` 活跃实体上下文已在 evidence 主线完成 authority 化消费适配
- results export 与 cloud diagnosis payload 已改为复用 authority graph view，而不是继续各自维护旧 graph summary 组装逻辑
- annotation 在 `rag` provider 不可用时的活跃实体 fallback 也已统一回 authority-owned `Level 2` 契约
- 但图谱产品层、timeline 完整契约和更上层 analysis 聚合仍未全部完成

### 本阶段不应直接耦合到 evidence layer 内部

图谱不应：

- 直接构造 `EvidenceBundle`
- 直接拼 annotation/disambiguation prompt

### 验收

- 图谱领域语义已稳定
- 图谱对 evidence layer 和时间轴的输出边界明确
- 图谱内部改动不再要求下游直接改内部 schema 解析

---

## 阶段 5: 完成图谱产品层、时间轴、诊断与前端联动迁移

### 目标

把图谱重构后的能力真正变成产品层分析能力，而不只是后端领域模型变化。

### 需要一起落地的区域

#### A. 图谱页

应从“人物关系图页面”升级为：

- 图谱分析入口
- summary / quality / events 的消费入口
- 关键角色 / 关键关系 / 弱连接 / 核心网络的分析界面

#### B. 时间轴

必须继续依赖图谱权威层的角色子图与关系事件契约。

需要明确保护：

- `entity_type="character"` 子图
- `first_seen_chunk`
- `last_seen_chunk`
- `GraphRelationEvent` 相关字段语义

#### C. 诊断与聚合指标

需要明确：

- 哪些结论直接来自图谱权威层
- 哪些来自 evidence layer
- 哪些是更上层的 analysis 聚合

### 本阶段的前端工作

建议分成 3 块：

1. graph page 重构
2. timeline 契约适配
3. diagnosis / summary 展示升级

### 验收

- 图谱页能消费 summary / quality / events 的结构化结果
- 时间轴与新图谱契约兼容
- 前端不再把图谱仅当作关系图渲染源

---

## 推荐的完整分支拆分

为了避免“一个分支同时改 evidence、graph、timeline、frontend”，推荐采用：

- 2 条长期主线分支
- 多条短生命周期子分支
- 一个明确的契约集成节点

### 长期主线分支

#### 主线 1

`refactor/level123-evidence-layer`

用途：

- 承接 `generalize-rag-to-narrative-evidence` 主线工作
- 作为 evidence layer 的长期集成分支

当前建议归入这条主线的工作包括：

- evidence layer `Phase 1 / Phase 2`
- `Level1AuthoritySnapshot` 接入 evidence layer
- `Phase 3` 消歧侧收编
- `Phase 4` 新消费者接入

#### 主线 2

`refactor/knowledge-graph-authority`

用途：

- 承接 `rebuild-knowledge-graph-architecture` 主线工作
- 作为知识图谱权威层的长期集成分支

当前建议归入这条主线的工作包括：

- 图谱权威层模型
- relation / entity type / authority contract
- projection / aggregate / repository 重构
- 为时间轴和 evidence layer 提供稳定下游契约

### 当前已执行的分支动作

截至 2026-04-13，以下状态已经完成：

- 已创建 `refactor/level123-evidence-layer`
- 已将当前 evidence 子分支 `refactor/generalize-rag-to-narrative-evidence-phase1-2` 合入 `refactor/level123-evidence-layer`
- 已创建 `refactor/knowledge-graph-authority`
- 已创建 `refactor/level1-authority-snapshot`
- 已将 `refactor/level1-authority-snapshot` 合入 `refactor/knowledge-graph-authority`
- 已将最小 `Level 1` 契约同步到 `refactor/level123-evidence-layer`
- 已创建 `refactor/evidence-layer-phase3-disambiguation`
- 已将 `refactor/evidence-layer-phase3-disambiguation` 合入 `refactor/level123-evidence-layer`
- 已完成 `Phase 2` 伏笔分析接入共享 evidence layer
- 已将 `codex/phase4-foreshadowing-evidence-consumer` 合入 `refactor/level123-evidence-layer`
- 已补齐 `Phase 2` 的相邻 chunk 文本透传与 evidence 回归测试
- 已从 `codex/knowledge-graph-authority-stage4` 拆出 authority 相关提交并合入 `refactor/knowledge-graph-authority`
- 已在 `refactor/knowledge-graph-authority` 上完成 authority service / graph snapshot / timeline view 的第一轮落地
- 已将 `codex/knowledge-graph-authority-stage4` 中用于收口 authority contract 的后续修复继续合入 `refactor/knowledge-graph-authority`
- 已完成 graph summary / relation events / quality 的 contract 分离，避免 summary 再混入 history/diagnostic 语义
- 已完成 results export 与 cloud diagnosis payload 的 authority graph view 对齐
- 已完成 annotation fallback 的 `Level 2` 活跃实体 authority 化收口
- 已明确将混合提交中的 evidence consumer 改动留在 evidence 主线处理，不强行并入 graph 主线

### 短生命周期子分支

以下子分支不直接从 `main` 开，默认从对应主线分支开。

#### 子分支 1

`refactor/generalize-rag-to-narrative-evidence-phase1-2`

归属主线：

- `refactor/level123-evidence-layer`

说明：

- evidence layer 前两阶段

#### 子分支 2

`refactor/level1-authority-snapshot`

归属主线：

- 默认从 `refactor/knowledge-graph-authority` 开
- 在需要接入 evidence layer 时再合入 `refactor/level123-evidence-layer`

说明：

- 图谱到 evidence layer 的最小契约桥

#### 子分支 3

`refactor/evidence-layer-phase3-disambiguation`

归属主线：

- `refactor/level123-evidence-layer`

说明：

- 收编消歧侧 evidence helper

#### 子分支 4

`refactor/evidence-layer-phase4-consumers`

归属主线：

- `refactor/level123-evidence-layer`

说明：

- 接入 Phase2/3/4 中至少一个新消费者

当前状态补充：

- 该阶段目标已由 `codex/phase4-foreshadowing-evidence-consumer` 先行完成 `Phase 2` 伏笔分析接入
- 如后续继续扩展，可沿用该子分支命名承接 `Phase 3 / Phase 4` 其他消费者

#### 子分支 5

`refactor/knowledge-graph-authority-layer`

归属主线：

- `refactor/knowledge-graph-authority`

说明：

- 图谱完整权威层重构

#### 子分支 6

`refactor/timeline-graph-contract-alignment`

归属主线：

- 默认从 `refactor/knowledge-graph-authority` 开

说明：

- 时间轴与图谱共享契约适配

#### 子分支 7

`refactor/graph-product-surface`

归属主线：

- 默认从 `refactor/knowledge-graph-authority` 开

说明：

- 图谱页、summary、quality、analysis interaction

### 契约集成节点

这套分支策略里最关键的不是“最后一起合 main”，而是中途必须有一次明确的契约集成。

建议集成节点是：

1. `refactor/knowledge-graph-authority` 先补齐最小 `Level 1` 契约
2. 将该契约相关改动合入 `refactor/level123-evidence-layer`
3. evidence 主线再继续做 `Phase 3`

也就是说：

- evidence 主线前两阶段可以先跑
- graph 主线可以并行补契约
- 但两条主线在 evidence `Phase 3` 开始前必须做一次合流

### 最终回到 `main` 的建议方式

不建议让所有子分支直接反复合回 `main`。

更稳妥的顺序是：

1. 子分支先合到对应主线
2. 主线在内部完成阶段性验证
3. 两条主线完成必要集成
4. 再从主线合回 `main`

---

## 测试与验证矩阵

完整落地不能只测单元测试。

### A. evidence layer 测试

- `EvidenceBundle`
- renderer
- annotation workflow
- disambiguation adapter

### B. graph authority 测试

- snapshot builder
- current relation projection
- entity type projection
- authority contract regression
- export / diagnosis payload graph contract regression
- annotation fallback 的 `Level 2` authority contract regression

### C. timeline 测试

- character subgraph consumption
- relation event consumption
- first/last seen compatibility

### D. frontend / API 验证

- `/graph` 输出兼容性
- graph page 交互
- timeline page 正确性
- summary / quality / events 展示

### E. 迁移回归

- annotation 识别率
- disambiguation 合并率
- graph summary 正确性
- timeline 关键节点正确性

---

## 风险与应对

### 风险 1: 过早进入图谱完整重构

后果：

- evidence layer 的 `Level 1` 还没冻结就被拖入领域层大改

应对：

- 必须先完成阶段 2

### 风险 2: 过早推进 evidence layer `Phase 3`

后果：

- 消歧侧继续依赖临时 graph helper

应对：

- 先落 `Level1AuthoritySnapshot`

### 风险 3: 时间轴被隐性破坏

后果：

- 页面能跑，但语义已经错

应对：

- 把时间轴契约单独列为阶段 5 必做项

### 风险 4: 前端仍停留在关系图展示

后果：

- 后端重构完成，但用户看不到分析价值

应对：

- graph page 必须单独作为完整阶段推进，而不是附带小优化

---

## 完整验收标准

### 联合验收 A

- [x] evidence layer `Phase 1 / Phase 2` 完成
- [x] annotation 主链路稳定消费结构化 evidence

### 联合验收 B

- [x] 图谱 -> evidence layer 最小 `Level 1` 契约冻结
- [x] `Level1AuthoritySnapshot` 可实际构造

### 联合验收 C

- [x] 至少一条消歧链路接入新的结构化 evidence 视图
- [x] 至少一个非消歧任务接入 `Level 1 / 2 / 3`

### 联合验收 D

- [~] 图谱权威层完整重构推进中
- [x] authority service / view / current-history 边界第一轮落地完成
- [ ] 时间轴共享契约完成适配

### 联合验收 E

- [ ] 图谱页不再只是人物关系图
- [ ] summary / quality / events 真正进入产品层消费
- [ ] evidence layer、图谱权威层、时间轴、产品层边界稳定

---

## 当前立即建议执行的下一步

上述阶段 1、阶段 2 和阶段 3 的当前目标已经完成，且 `Phase 4` 的首个非消歧消费者（`Phase 2` 伏笔分析）也已落地。接下来更合理的推进顺序是：

1. 从 `refactor/knowledge-graph-authority` 继续推进图谱权威层完整重构
2. 启动时间轴共享契约与图谱产品层迁移规划
3. 视收益再决定是否继续在 evidence 主线中扩展 `Phase 3` 对话归属或 `Phase 4` 关系抽取消费者

---

## 最终建议

两份文档的完整落地，不应该被理解为：

- 先做一个 evidence 文档
- 再做一个 graph 文档

而应该理解为一条完整路线：

**evidence 表达层统一 -> Level 1 契约冻结 -> 消费侧扩展 -> 图谱权威层重构 -> 时间轴与产品层联动迁移。**

只有按这条路线推进，最后得到的才不是“两套各自改了一半的系统”，而是一套边界清晰、可持续演进的叙事分析架构。
