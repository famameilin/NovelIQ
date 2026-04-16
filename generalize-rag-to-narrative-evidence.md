# generalize-rag-to-narrative-evidence

## 背景

`refactor/trim-legacy-string-evidence` 的主目标一直是收口 annotation / disambiguation 主链路里的遗留字符串字段：

- `active_entities_str`
- `disambig_context_str`
- `vector_evidence_str`

这轮评审后，我们进一步明确了边界：本分支只负责 evidence 主链路收口、消费者边界整理，以及旧字段降级为兼容层；不再把这轮工作继续外扩成新的 narrative evidence 泛化改造。

## 本轮保留的范围

当前分支允许保留的改动只有三类：

1. `ChunkContext` / workflow 主链路优先消费 `annotation_prompt_blocks` 与 `evidence_bundle`。
2. annotation / disambiguation 消费者尽量复用同一套 `EvidenceBundle` 渲染逻辑，减少重复字符串拼装。
3. 遗留字符串字段继续保留兼容入口，但不得反向覆盖新的主语义入口。

## 本轮额外接受的整理

结合这轮评审结论，`Phase2 / foreshadowing` 允许做一项额外整理，但边界只限于共享 evidence 消费入口的收口：

1. `Phase2` 可以被动消费上游已经准备好的 `evidence_bundle`。
2. `Phase2` 可以复用共享 evidence renderer 的输出结果来补充 prompt。
3. 这项调整被视为“共享 evidence 消费入口整理”，不是新的 narrative evidence 泛化立项。

## 本轮明确不做的事

下面这些方向不属于本轮范围：

1. 不顺手扩 graph authority 契约。
2. 不把更多 narrative task 一并迁移到新的 evidence layer。
3. 不把 `Phase2 / foreshadowing` 做成“自行取证 + 自行解释”的新消费范式。

评审后已经按这个边界回收实现：

- `Phase2` 现在只消费上游已经准备好的 `evidence_bundle`，不再在自己的重试闭包里额外触发 `rag_retriever` 取证。
- annotation message 组装在调用方显式提供 `alias_map` 时，不再把 bundle 里的 Level 1 alias facts 通过 `disambig_context` 反向注入，避免新旧入口共存时出现优先级错位。

## 对 Phase2 实现的具体要求

为了不偏离这轮目标，`Phase2` 的实现应该满足：

1. 只消费调用方已经准备好的 `evidence_bundle`。
2. 不在 `Phase2` 的重试闭包或消息构建阶段再引入新的取证分支。
3. 行为变化需要有独立测试覆盖，重点验证 prompt 边界与 fallback 语义，而不只是检查 section 是否出现。

## 为什么要这样收边界

如果本分支同时承担“旧字符串收口”和“narrative evidence 泛化”，会出现几个问题：

1. 很难判断回归到底来自兼容层调整，还是来自新的 narrative consumer 行为变化。
2. `Phase2` 的 prompt 边界、模型行为、验证方式都和 annotation / disambiguation 不同，应该单独评审。
3. graph authority 契约一旦被顺手改动，会把本轮 review 面扩大到 authority consumer 的稳定性，而这不是当前任务的重点。

## 后续如果要正式推进 narrative evidence 泛化

建议单独开主题处理，并至少满足下面几项：

1. 明确 narrative consumer 的独立接口，而不是继续在 annotation renderer 上叠加专用 prompt blocks。
2. 区分“身份判定证据”和“叙事解释证据”，不要复用同一套字段语义硬塞到所有消费者里。
3. 补齐 `Phase2` 行为回归测试，重点验证模型输入边界和 fallback 语义，而不只是检查 prompt 中是否出现了新 section。
4. 单独评审 authority / evidence / consumer 三层边界，避免再次出现“任务收口顺手带出契约迁移”的情况。
