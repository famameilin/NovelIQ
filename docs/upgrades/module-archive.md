# 退役符号的定位、依据与恢复

基线 B0 为 `0ff05bdea28d2324461c4cfe3bfbd7d3e532f968`，表中提交 `0ff05bdea28d` 均指此完整提交。实现和本地归档清单仅留在原有忽略的 `deprecated/`，不进入 Git；本文只记录原路径、符号、判据、替代入口与恢复依据。

44 个生产符号与 36 份测试片段共 80 条记录。后者包含 4 份混合测试原始副本，并不表示把这 4 个测试的活动能力删除。`chunk_documents_with_chapters` 保留在 `src/text_processing/paragraphs.py`，不在退役列表。

恢复 R1：用 `git show 0ff05bdea28d2324461c4cfe3bfbd7d3e532f968:<原路径>` 只读查看原文件，提取所列符号及确有必要的依赖，按当前责任模块重新接入，不整文件覆盖，也不自动恢复旧导出。恢复 R2：同样从 B0 提取专属测试，只有重新决定启用对应能力时才配套恢复实现与测试。恢复 R3：混合测试只提取原退役断言；现有活动断言继续保留。恢复后均运行相关回归与 AST 边界检查。

以下“零调用”指源码、测试、既有脚本及本地导出工具中的可解析调用，排除纯描述字符串。除静态检索外，本次再次检查归档实现调用的辅助函数，没有发现因归档新产生的孤儿函数。框架入口、Pydantic 校验器、动态注册、资源释放与恢复/合法空状态分支不依据名称判死。

## 生产符号

| 原路径 | 符号 | 依据 | 替代入口或处理 | 原提交 | 恢复 |
|---|---|---|---|---|---|
| `src/agents/annotation/ledger.py` | `relation_ledger` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | 无等价入口；活动关系状态由 state_entities / FactGraph 管理 | `0ff05bdea28d` | R1 |
| `src/agents/annotation/ledger.py` | `event_ledger` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | 无等价入口；活动事件状态由 state_events / EventTrees 管理 | `0ff05bdea28d` | R1 |
| `src/fact_graph/graph.py` | `reset_chapter_changes` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | 无替代；活动流程保存独立 work 贡献，不调用章节变更重置 | `0ff05bdea28d` | R1 |
| `src/storage/repositories/graph/event_forest.py` | `fetch_event_edges` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | 事件投影读取使用 event_trees.read.forest.EventForestQuery 及原始 EventForestRecords | `0ff05bdea28d` | R1 |
| `src/storage/repositories/run_repository.py` | `cancel_run` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | workflows.application.TaskApplicationService.cancel_task，保留既有取消状态机 | `0ff05bdea28d` | R1 |
| `src/storage/repositories/event_order.py` | `event_position` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | event_trees.read.order.formal_event_ordinals，按当前事件读投影排序 | `0ff05bdea28d` | R1 |
| `src/api/services/results_contracts.py` | `build_aggregate_metrics_contract` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | 各指标读 DTO 由 API 现有响应装配使用，无旧统一封装 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `sensory_density` | 仅定义/旧导出，无活动调用；本次扩展脚本与工具复核 | metrics.paragraph_metrics.compute_paragraph_metric_counts 提供原始五感命中；无旧密度封装 | `0ff05bdea28d` | R1 |
| `src/utils/identity.py` | `exact_digest` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | utils.identity.text_digest 保留活动文本摘要；无旧 exact_digest 导出 | `0ff05bdea28d` | R1 |
| `src/utils/preprocess.py` | `strip_empty_lines` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | text_processing.preprocess.normalize_text 和段落切分；不另建旧空行过滤能力 | `0ff05bdea28d` | R1 |
| `src/workflows/paragraphs.py` | `chunk_documents` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | text_processing.paragraphs.chunk_documents_with_chapters（活跃章节切分接口） | `0ff05bdea28d` | R1 |
| `src/agents/annotation/subagent_program.py` | `subagent_gap_is_clean` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 现行 subagent 绑定与 finish 校验；无旧 gap 派生判断 | `0ff05bdea28d` | R1 |
| `src/metrics/character_metrics.py` | `compute_character_closeness_centrality` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；未接入产品的旧图指标；现行关系集中度和度中心性仍保留 | `0ff05bdea28d` | R1 |
| `src/metrics/character_metrics.py` | `compute_character_eigenvector_centrality` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；未接入产品的旧图指标；现行关系集中度和度中心性仍保留 | `0ff05bdea28d` | R1 |
| `src/metrics/character_metrics.py` | `compute_clustering_coefficient` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；未接入产品的旧图指标；现行关系集中度和度中心性仍保留 | `0ff05bdea28d` | R1 |
| `src/metrics/character_metrics.py` | `compute_protagonist_betweenness` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；未接入产品的旧图指标；现行关系集中度和度中心性仍保留 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `average_word_length` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.style_metrics_extra.compute_avg_word_len，现行平均词长 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `function_word_distribution` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.style_metrics_extra.compute_function_word_vector，现行虚词向量 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `imagery_density` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.paragraph_metrics.compute_paragraph_metric_counts 原始意象计数，无旧密度封装 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `lexicon_density` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.lexicon_metrics.count_mixed_hits 与段落原始计数，无短块密度旧规则 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `metaphor_density` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.paragraph_metrics.compute_paragraph_metric_counts 原始明喻句计数 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `pause_density` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.paragraph_metrics.compute_paragraph_metric_counts 原始停顿计数 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `semantic_category_densities` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.style_metrics_extra.compute_category_density，现行类别指标 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `semantic_category_density` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.style_metrics_extra.compute_category_density，现行类别指标 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `sentence_length_stats` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.aggregate.aggregations 与 metrics.style_metrics_extra.compute_sent_len_std，现行充分统计量/总体标准差 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `SHORT_CHUNK_MIN_POSITIVE_DENSITY` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；短块抬升密度旧规则随封装归档 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `SHORT_CHUNK_TOKEN_THRESHOLD` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；短块抬升密度旧规则随封装归档 | `0ff05bdea28d` | R1 |
| `src/metrics/style_metrics.py` | `word_frequency_breadth` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.style_metrics_extra.compute_string_token_diversity，现行 token 多样性 | `0ff05bdea28d` | R1 |
| `src/metrics/lexicon_metrics.py` | `load_weighted_lexicon` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | lexicons.parser.load_lexicon_terms / LexiconRegistry.get，现行无权重词表 | `0ff05bdea28d` | R1 |
| `src/metrics/lexicon_metrics.py` | `term_weighted_counts` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.lexicon_metrics.term_mixed_counts，现行命中计数 | `0ff05bdea28d` | R1 |
| `src/metrics/lexicon_metrics.py` | `count_weighted_hits` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | metrics.lexicon_metrics.count_mixed_hits，现行无权重计数 | `0ff05bdea28d` | R1 |
| `src/lexicons/registry.py` | `base_dir` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | LexiconRegistry 构造参数保留；无未调用的公开路径属性 | `0ff05bdea28d` | R1 |
| `src/lexicons/registry.py` | `get_weighted` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | LexiconRegistry.get，现行词表值读取 | `0ff05bdea28d` | R1 |
| `src/lexicons/registry.py` | `version_hash` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；活动流程没有词表版本哈希消费者 | `0ff05bdea28d` | R1 |
| `src/lexicons/registry.py` | `list_all_keys` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | 无替代；活动流程按已知 key 读取词表 | `0ff05bdea28d` | R1 |
| `src/utils/lexicon_parser.py` | `load_weighted_lexicon` | 产品未接入，仅专属测试或旧包内调用；相关能力与专属测试一起归档 | lexicons.parser.load_lexicon_terms / LexiconRegistry.get，现行无权重词表 | `0ff05bdea28d` | R1 |
| `src/storage/repositories/chapter_repository.py` | `fetch_chapters_with_text` | 旧包装入口；全部现行调用者迁到已有原始读取后零调用 | ChapterRepository.fetch_chapter_texts；包括本地导出引用收集器在内的调用者已迁移 | `0ff05bdea28d` | R1 |
| `src/storage/repositories/paragraph_repository.py` | `fetch_chapter_paragraph_rows` | 旧包装入口；全部现行调用者迁到已有原始读取后零调用 | ParagraphRepository.fetch_paragraph_rows；夹具/查询使用现行原始读取 | `0ff05bdea28d` | R1 |
| `src/storage/repositories/run_repository.py` | `update_run_status` | 生产无调用；仅夹具构造使用，迁到测试支持后归档 | 生产继续用原有任务/run 状态机；仅夹具构造迁入 tests.support.run_records.set_run_status | `0ff05bdea28d` | R1 |
| `src/config/constants/text_normalization.py` | `TITLE_ALIAS_SUFFIXES` | 仅旧包导出，无活动调用；清理导出后归档 | 无替代；当前引用判定归 fact_graph，不使用该旧常量 | `0ff05bdea28d` | R1 |
| `src/config/constants/text_normalization.py` | `ALLOWED_PREV_CJK_CHARS` | 仅旧包导出，无活动调用；清理导出后归档 | 无替代；无活动消费者的旧规范化常量 | `0ff05bdea28d` | R1 |
| `src/config/constants/text_normalization.py` | `LIKELY_NAME_PREFIX_CHARS` | 仅旧包导出，无活动调用；清理导出后归档 | 无替代；无活动消费者的旧规范化常量 | `0ff05bdea28d` | R1 |

## 测试片段

| 原路径 | 符号 | 依据 | 活动替代或处理 | 原提交 | 恢复 |
|---|---|---|---|---|---|
| `tests/preprocess/test_preprocess.py` | `test_strip_empty_lines` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/chunking/test_chunking.py` | `test_chunk_documents_accumulates_run_global_offsets` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/chunking/test_chunking.py` | `test_chunk_documents_offsets_use_preprocessed_length` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/chunking/test_chunking.py` | `test_chunk_documents_accumulates_chapter_ids` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/agents/test_annotation_identity.py` | `test_original_text_and_formal_payload_hash_preserve_whitespace_and_unicode` | 混合测试原始副本；只移除退役符号断言 | 原文件的活动文本摘要 / subagent 完成约束断言保留 | `0ff05bdea28d` | R3 |
| `tests/agents/test_annotation_subagent_program.py` | `test_subagent_gap_for_non_evidence_subagent_only_looks_at_finished` | 混合测试原始副本；只移除退役符号断言 | 原文件的活动文本摘要 / subagent 完成约束断言保留 | `0ff05bdea28d` | R3 |
| `tests/agents/test_annotation_subagent_program.py` | `test_subagent_gap_for_evidence_subagent_also_looks_at_candidates_and_metric` | 混合测试原始副本；只移除退役符号断言 | 原文件的活动文本摘要 / subagent 完成约束断言保留 | `0ff05bdea28d` | R3 |
| `tests/agents/test_annotation_subagent_program.py` | `test_subagent_gap_evidence_subagent_is_incomplete_without_finish_declaration` | 混合测试原始副本；只移除退役符号断言 | 原文件的活动文本摘要 / subagent 完成约束断言保留 | `0ff05bdea28d` | R3 |
| `tests/metrics/test_character_metrics.py` | `TestProtagonistBetweenness` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_character_metrics.py` | `TestCharacterClosenessCentrality` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_character_metrics.py` | `TestCharacterEigenvectorCentrality` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_character_metrics.py` | `TestClusteringCoefficient` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_semantic_category.py` | `TestSemanticCategoryDensities` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_emotion_enhancement.py` | `TestWeightedDensity` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_lexicon_v2.py` | `TestVersionHash` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_registry_v3.py` | `TestVersionHashV3` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_registry_v3.py` | `test_get_weighted` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/utils/test_lexicon_parser.py` | `TestLoadWeightedLexicon` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_style_density_bounds.py` | `test_mixed_lexicon_density_is_capped_at_one` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_style_density_bounds.py` | `test_token_lexicon_density_is_capped_at_one` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/api/test_analysis.py` | `test_update_run_status_completed_at_is_consistent_with_started_at` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/api/test_analysis_service_state_machine.py` | `test_update_run_status_completed_persists_completed_at` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/api/test_analysis_service_state_machine.py` | `test_update_run_status_failed_persists_completed_at` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_sentence_length_stats` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_sentence_length_stats_empty` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_pause_density` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_pause_density_per_hundred_chars` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_metaphor_density` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_function_word_distribution` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_function_word_distribution_basic` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_function_word_distribution_empty_tokens` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_function_word_distribution_empty_function_words` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_function_word_distribution_no_matches` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_function_word_distribution_relative_frequency` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_semantic_category_density` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |
| `tests/metrics/test_metrics.py` | `test_imagery_density` | 所测退役接口的专属测试；无产品契约消费者 | 无同名旧能力；现行文本/指标/词表/状态机测试保留 | `0ff05bdea28d` | R2 |


## 独立审核后的补充归档

本批依据源码、测试、既有脚本的可解析调用检索，只归档以下两个零调用函数。`relation_id` 仍活跃，已迁入 `fact_graph.identity`，保持 UUID 算法不变，不计入退役清单。`dialogue_length` 仍用于段落指标，仅移除旧封装中的专用导入。

| 原路径 | 符号 | 依据 | 替代入口或处理 | 原提交 | 恢复 |
|---|---|---|---|---|---|
| `src/metrics/style_metrics.py` | `dialogue_ratio` | 产品、测试和既有脚本无调用；同名 DTO 字段不属于函数调用 | `metrics.aggregate.aggregations` 按充分统计量计算，合法无分母仍返回 None | `3fd6b74e5fb3df069d76e91931cf40c58215d10e` | R4 |
| `src/storage/repositories/graph/identity.py` | `normalized_name` | 无调用；活动事实图使用自身名称规范化规则 | `fact_graph.graph._norm`；不重建仓储旧入口 | `3fd6b74e5fb3df069d76e91931cf40c58215d10e` | R4 |

恢复 R4：使用表中完整提交执行 `git show <提交>:<原路径>`，只提取相应符号及必要依赖；如决定重新启用，先确认现行职责和业务口径，再补消费者和回归。两份实现片段及清单只留在本地 `deprecated/architecture/2026-10-08/`，原有 deprecated 忽略规则保持不变。
