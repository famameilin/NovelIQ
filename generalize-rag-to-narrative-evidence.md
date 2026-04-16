# generalize-rag-to-narrative-evidence

## 背景

`refactor/trim-legacy-string-evidence` 的原始目标，是继续收口 annotation / disambiguation 主链路里的遗留字符串字段：

- `active_entities_str`
- `disambig_context_str`
- `vector_evidence_str`

当前实现里，除了主链路收口，还额外把 `EvidenceBundle` 接到了 `Phase2 / foreshadowing`，新增了 `ForeshadowingPromptBlocks` 与 `Narrative_Evidence_Level1/2/3` 的 prompt 注入。

## 为什么暂时保留

这部分改动虽然超出了“只做 evidence 主链路收口”的原始边界，但它表达的是一个明确方向：

1. `EvidenceBundle` 不再只服务 annotation / disambiguation。
2. 同一份 RAG 证据未来可以被更广义的 narrative 分析消费者复用。
3. `Phase2` 对稳定事实、近期活跃实体、语义回声的消费，已经是 narrative evidence 的雏形。

因此这里不回退代码，而是把它记录为一次显式的边界外扩，后续按单独主题继续治理。

## 当前约束

为了避免这次外扩继续失控，当前约束需要明确：

1. 本分支的主目标仍然是 evidence 主链路收口与兼容层降级。
2. `Phase2` 接入 `EvidenceBundle` 视为已落地的方向性扩展，而不是可以继续顺手泛化的信号。
3. 不在这轮继续扩 graph authority 契约。
4. 不在这轮把更多 narrative task 一并迁到新的 evidence layer。
5. 后续 narrative evidence 泛化，应单独立项并单独评审 prompt 边界、测试边界与模型行为变化。

## 后续建议

后续如果正式推进 narrative evidence 泛化，建议拆成单独主题处理：

1. 定义 narrative 消费者统一接口，而不是继续在 annotation renderer 中并排增加专用 prompt blocks。
2. 区分 annotation/disambiguation 的“身份判定证据”和 foreshadowing 的“叙事解释证据”。
3. 补齐针对 `Phase2` 的行为回归测试，而不只验证 prompt 中是否出现了新 section。
4. 明确 `EvidenceBundle` 中哪些字段是跨消费者共享的，哪些字段只属于特定任务。
