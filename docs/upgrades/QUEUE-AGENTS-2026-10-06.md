# 队列 Agent 与全书共享状态改造

分支：`codex/queue-agent-book-state`  
项目版本：`0.2.1`  
基线：`6e1883ee9b29e4bd930d9c87e091ab3f3da3f64f`  
依据：`docs/队列任务即Agent与全书共享工作区改造方案-2026-10-05.md`

## 实施结果

短章创建一个 solo work；长章按 `sub_chunk_max_chars` 创建 structure、event、evidence 三个 work，每个角色读取整章原文。队列按章序入队，各 work 独立执行、finish 和保存，不等待前序章或同章其他角色。工作身份由 run、章和角色确定；实际执行另有 invocation 身份。

`AnnotationAgent` 管理模型会话、程序运行、工具、实际章输入和局部产出，直接调用 run 内共享的 `FactGraph`、`EventTrees`、`CasePool`。队列与 Agent、队列与模型池、Agent 与 SSE/统计审计通过 eventbus 交互。模型池只维护运行期容量、选举与再次派发预算、失败权重和退避，不保存数据库状态。

成功 work 的队列状态、Agent 输入/产出、事实图、事件树和案例贡献，在同一数据库 Session、同一事务中顺序保存。精确核对存储后再确认内存状态、增加章进度和归还容量。提交结果不明确时先查询真实存储；确定未保存才撤销当前尝试。SSE 与统计审计分别管理自己的事务。

事件工具支持实际读取过的跨章端点和显式 main/secondary/causal/foreshadowing 连接。端点必须属于当前尝试或其他已保存 work；生产 invocation、读取内容和当前节点内容需一致。实际父边重建树归属，跨树因果边不改写父边。已经保存的 work 产出保持不可变，后续连接保留自己的作者。

案例业务数据只有 `case_id`、`description`。同说明登记幂等，`promise_case(case_id)` 在当前 Agent 内认领；忙碌立即返回，每个 work 最多办理一个案例。resolved 交付的占用保留到保存确认，deferred/contested 释放认领。系统不从说明推断目标、证据或修复操作，也不为剩余案例追加 Agent。

恢复保留角色齐全且实际保存的完整章节；未完成章节的全部角色、业务产出及依赖连接整章清理，再按当前输入和阈值创建 work。清理事务提交后发送 chapter_reset，清除该章全部旧角色展示；work_reset 绑定实际 invocation，隔离旧执行的迟到输出。已发生的审计和用量保留。章结果读取按角色聚合，不产生第二次章保存。

## 验收问题修复

- finish 只关闭模型写面，保存开始前的取消仍撤销本次贡献；保存开始后的取消等待原事务和确认结果，不重新执行模型
- 实际供应商超时和瞬态请求错误交付 retry，由模型池按失败权重重新选举；模型池结束后队列不再追加取消、撤销、反馈或新保存
- 提交、回滚或核查结果不明确时保持 save_unconfirmed 和容量，禁止猜测未保存而重派；已提交但内存确认失败时只读取并恢复当前 work 的三个域贡献，再完成确认
- 本 work 实际引用的实体 UUID、名称和类型保存为 entity_reference 事实，完整章引用源被清理后仍可恢复；引用不会伪造成实体写入、人物观察或身份裁决
- 案例整书恢复替换保留贡献，重复执行幂等；单作者确认恢复保留其他正在执行的贡献、交付和排他占用
- Token DTO 接受实际 reported/estimated/unknown 记账方式及 recorded_calls/partial/unknown 覆盖状态，保留 coverage_scope，避免校验异常把实际用量归零
- 恢复分析持久保存 task_reset；回放过滤之前的阶段和终态，保留已完成工作的展示。前后端均按实际 work/invocation 隔离旧输出，整章恢复也清除旧 lane
- SSE 持久页与内存缓存在同一任务锁下读取，避免短页查询期间大量并发消息使缓存截断，再用高游标跳过中间的已持久消息
- 旧人物归并裁决迁为当前同一人物关系贡献，作者取可对应成功保存章的实际 identity 事实或实体状态；缺来源、端点无效或裁决冲突逐记录报错，事务回滚
- 历史 event/identity 事实保留原内容，不参与当前四类贡献的操作排序；新旧产出混存时预检明确拒绝整库重建，保护当前已保存 work 的不可变贡献

## 代码与归档范围

| 范围 | 主要入口和行为 |
|---|---|
| 队列、模型池 | `src/workflows/chapter_pool.py`、`src/agents/model_capacity.py`、`src/agents/event_bus.py` |
| Agent、业务工具 | `src/agents/annotation/agent.py`、`work.py`、`work_tools.py`；保留现有 CodeAct 程序、构造器、IR 和 LangGraph 内部能力 |
| 全书状态 | `fact_graph.py`、`event_trees.py`、`case_pool.py`；单条工具的读取、修改和失败回滚在 run 锁内，模型、原文 I/O、数据库和消息交互在锁外 |
| SSE、统计审计 | `src/agents/sse.py`、`src/agents/audit/module.py`；真实消息身份去重、生成顺序游标、持久重放和实际 reported/estimated/unknown 用量 |
| 读取与前端 | 章角色聚合、图树/时间线/权威实体/导出、`book_state` API；PipelineBoundary 展示保存工作、纯文字案例和真实连接 |

旧 cutoff、freeze、projection、semantic command、数据库 work 租约、规则摘要、章/阶段摘要和全局上下文链路退出主流程。结合 0.2.1 兼容清理，共 73 份基线副本（含 30 份测试基线）保存在 `deprecated/annotation_pipeline/`；包含整份退役文件和只退役部分旧接口的源码或测试。具体文件及逐份基线校验见该目录的 `README.md`。依赖旧 ORM 的版本迁移脚本也已归档。

旧 `runner.py`、`subagent_runner.py` 已退出运行时，当前验证迁入 `validation.py`。CodeAct 解释器、构造器、IR、领域工具、记录级拒绝回执和相关回归仍使用当前工作合同；归档测试不计入全量测试收集。

本次发布项目版本统一为 `0.2.1`，模块、消息、工具和存储均使用项目版本。

## 0.2.1 以下版本运行时兼容清理

当前运行时只接受 0.2.1 工作合同：

- 删除旧章级 runner、自动章组装、延迟 finish 结算、缺口默认放行及独立容量 dispatch/consume 入口。每个 work 必须真实通过 finish，缺少必需指标或候选判定不能保存。
- 删除结构化 PendingCase、旧案例 type/keys/record_id/evidence_refs 参数和旧 source_ref/target_ref 连接接口。案例只有纯文字说明；连接使用实际读取的实体或事件 ID。
- 删除旧主题标签数组读取与前端显示分支，标签使用主题 ID 到说明的字典；无有效 topic_model_runs 契约的 Top-5 历史结果不再判为完成或参与聚合，缺少推断总量不改用旧权重求和。
- 删除 canonical_entity_id、identity_status、identity_cutoff 等旧身份字段读取，以及人物查询旧 name 列回退。情绪分只接受当前整数范围，旧中文值、字符串、布尔值或越界值明确报错，不静默转换。
- LTP 输出必须显式包含 sdp，DialogueCandidate 的 chapter_id 必须为正数；不再默认补旧缺失字段或接收负数子块身份。空文本的显式空结果和当前依赖库输出格式仍按现有合同处理。

一次性升级迁移工具和 `deprecated/` 基线用于数据转换、审查及回退，保留在运行时之外。上述清理没有改写生产记录；旧数组标签或 Top-5 结果需重新运行对应主题/诊断阶段，不能通过运行时兼容读取充当当前结果。

## Schema 与 API

新增四张表：

- `annotation_work`：只保存成功 work 的 run/章/角色、实际 invocation 和 saved 状态
- `book_cases`：案例 ID、说明及创建时间
- `book_case_states`：办理状态和实际作者贡献，不存案例目标或结构化意图
- `audit_messages`：实际审计消息的持久去重回执

`chapter_annotations` 改为 run/章/角色唯一，保存实际输入、局部产出、work 与 invocation。图事实、实体/关系状态、事件节点/边、对话增加实际作者；事件节点增加生产 invocation 和父节点，事件边增加 main/secondary 的 cause_role，并按端点、类型、作者唯一。审计 invocation 增加执行身份、work 和角色。SSE 的 event_outbox 使用生成时分配的实际顺序，不保留 cutoff 字段。小说标题从 `novels.title` 读取。

退出的 15 张表：`work_items`、`semantic_commands`、`text_evidence`、`command_outcomes`、`continuity_cases`、`case_heads`、`case_claims`、`analysis_cutoffs`、`partition_heads`、`cutoff_partitions`、`source_manifests`、`formal_artifacts`、`global_context`、`chapter_summaries`、`stage_summaries`。

`GET /api/novels/{novel_id}/pipeline?task_id=...` 现在返回 completed_chapters、total_chapters、saved_work_count、works、case_states、cases 和 connections。SSE 保留实际 work/invocation/message 身份；work_saved 刷新共享状态，work_reset 清理对应工作输出，chapter_reset 清理整章旧角色，task_reset 标识实际恢复分析的展示边界。用量覆盖范围根据实际请求和消息来源判断，未知用量不能视为全程覆盖完整。

## 上线与迁移

本节记录 2026-10-06 的历史迁移设计与预检，不是当前可执行的升级说明。原 `scripts.db.migrate_queue_agents` 源码未进入 Git，当前版本不提供该命令；历史实现与测试结果不能代替当前升级验收。0.2.1 当前可执行入口、源结构限制与回退方法见 [0.2.1 升级检查](UPGRADE-0.2.1.md)。

2026-10-08 当前 `novel_analysis/public` 只读复查已满足 0.2.1 ORM 的表、字段和外键要求，没有待运行、运行中或取消中的任务；没有执行生产 DDL。下面的历史章数与身份冲突计数不能当作当前库的阻塞项。

当前版本从项目根目录执行只读结构检查：

```powershell
uv run python -m scripts.migrations.check_0_2_1 --schema public
```

非默认 schema 必须显式指定实际名称。检查器不建表、不更改历史数据。原始 0.2.0 旧库仍需先完成历史业务合同转换，不能直接用六表合并替代转换，也不能靠 `init_db()` 补表后声称完成迁移。

以下均为历史设计和当时预检。原只读回执中的 `identity_preflight` 检查 canonical 裁决支持与真实作者来源，`output_preflight` 检查当前已保存 work 与历史章混存。当前只读结构检查器不重做这两项语义转换，也不据此补造人物身份或作者。

2026-10-06 修复后生产只读预检：108 份历史章、0 份当前 work；37 对明确旧归并中，33 对由迁移拟重建的实际关系覆盖，1 对可按真实 identity 事实新增贡献，3 对无法转换为“同一人物”。这些计数是转换预检，尚未在生产执行转换或验收读侧归并。3 对的两端实际 `entity_type` 均为 `item`：

| run_id | entity_id | canonical_entity_id | source_entity_type / target_entity_type |
|---|---|---|---|
| 08f9ba42 | 77f2fc03-904f-5aed-88f8-2a2648b0c4d9 | 9a2505a2-ec9b-5d45-aacc-f4a38f65c84a | item / item |
| 08f9ba42 | d4730fd1-7192-5b47-9034-4040aef34cd0 | fa810843-3025-5bd0-9eb1-db7d9d3ec02b | item / item |
| 483cd5c5 | dd392961-ab41-5cfd-80bc-fd4f4288a383 | 2bc4d8de-182b-51b8-bc01-4952c00a0a7f | item / item |

需要核对这些实际记录的归并语义，再决定相应数据修复或当前合同支持；不能仅为迁移通过就把 item 改成人物、移除实际旧裁决或补造作者。本轮没有修改上述生产记录。

迁移在一个 PostgreSQL 事务中完成，转换错误会回滚 DDL 和数据。旧 15 张表整体迁入 `<当前schema前35字符>_annotation_archive`；即将改写的小说、章产出、图、树、对话、分析、展示和 invocation 表先保存数据副本。数据副本使用 CREATE TABLE AS，不能替代保留全部索引、约束和序列的完整数据库备份。

历史完整章转换为已保存 solo，保留原输入和产出。使用可对应的真实成功审计身份；没有审计时使用原保存记录身份，不补造模型请求或用量。图按原存储实体状态、关系和事实重建，规范实体身份时同步更新别名与事实引用；原事件和身份事实保留。旧 canonical 裁决若尚未由当前同一人物关系覆盖，使用真实裁决来源转换为作者贡献，迁移回执记录 converted_identity_decisions；不得把 first_seen/last_seen 当作裁决作者章。缺少实际来源或裁决冲突会中止整个迁移。只有实际父边标记为 main/secondary，普通跨树 causal 边保持原意。

旧案例只转换已保存章登记的纯文字说明，同说明保留多位实际作者。原结构化裁决留在归档，新案例从 pending 开始；不声称旧案例已按新办理协议 resolved。说明为空或超过 100 字、原章输入缺失等问题会中止整个迁移，需逐条核查原记录后重新演练。

回退时停止新代码和写入，使用发布前完整备份恢复数据库，并部署上述基线代码。迁移归档供逐条核对与数据恢复；本次没有提供自动逆向迁移，也不会通过 reset 或清库回退用户数据。若升级后产生了新业务数据，应先另存这些数据再决定回退方案。

## 验证与限制

| 检查 | 实际结果 |
|---|---|
| `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 test` | 修复后 1793 passed，34 warnings；覆盖率 90.81%，达到 80% 门槛；pytest 108.88 秒，含启动和覆盖率的冷启动墙钟 115.18 秒，未超 5 分钟 |
| 队列故障、引用存储、SSE 与 Token 专项，`--no-cov` | 41 passed，pytest 4.62 秒，含启动墙钟 8.64 秒 |
| 真实事务确认恢复、并发贡献保护、阈值变化与 SSE 分页专项，`--no-cov` | 20 passed，pytest 5.84 秒，含启动墙钟 9.90 秒 |
| 域恢复与迁移专项，`--no-cov` | 最终 16 passed，pytest 2.57 秒，含启动墙钟 5.92 秒；包含迁移后实际恢复和混合状态拒绝 |
| 此前当前合同与旧输入拒绝专项，`--no-cov` | 57 passed，pytest 3.79 秒；本轮由上述全量再次覆盖，没有单独重复运行 |
| `uv run ruff check src tests scripts/db/migrate_queue_agents.py` | 通过 |
| `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 typecheck` | 305 个源文件通过 |
| `npm run test -- --reporter=dot` | 修复后 48 个测试文件通过，214 passed、1 skipped，15.70 秒 |
| `npm run build` | TypeScript 与 Vite 构建通过，Vite 6.63 秒；保留包体积、插件耗时警告 |
| `npm run lint` | 0 errors、1 warning，来自生成的 mockServiceWorker.js 未使用 eslint-disable |
| `npm run test:e2e -- e2e/queue-agent-workspace.spec.ts` | 本轮 Edge headless + 隔离真实 API，2 passed，6.2 秒；共享案例、跨章连接、刷新与持久 SSE 回放 |
| 隔离 PostgreSQL 迁移演练 | 包含于上述迁移专项及全量结果；验证失败整体回滚、真实身份转换、迁移后恢复、重复迁移和混合状态拒绝 |
| Git 差异、归档 | diff --check 通过；73 份归档内容逐份与基线核对，仅允许换行差异 |

回归覆盖独立角色保存、保存前后取消、实际供应商超时与重选、提交前后丢回执、核查与回滚结果不明、真实事务后的单 work 确认恢复及其他在飞贡献保护、模型池退出、实体引用源清理、纯文字案例认领、整章恢复阈值变化、旧 invocation 隔离、410 条并发消息分页、实际审计与用量、迁移幂等和失败事务回滚；另验证旧主题标签数组、旧情绪值、旧结构化案例字段、缺失 SDP 和负数章身份的拒绝行为。solo 与 evidence 的缺口回执均检查实际候选及指标，完整事件提交回归核对序列化参与者与人物情绪结果。后端测试使用已有虚拟环境与项目入口，没有将编译时间混入上述测试运行时间；专项 pytest 运行均未超过 30 秒，全量冷启动墙钟未超过 5 分钟。

迁移演练使用独立 PostgreSQL schema，覆盖历史 work 外键、标题、原产出、实际用量、主链和跨树因果、旧别名实际读侧归并、历史事件和身份事实原内容、重复案例多作者、迁移后恢复及重复执行。浏览器验收使用隔离 schema 的真实 API 与真实 Agent 程序执行，模型响应为确定性替身；检查案例认领/办理、跨章主链、事件树展开和刷新一致性。第二项浏览器用例使用实际 SSE 路由、持久事件表与 Vite 加载的前端 store，清空服务器缓存后回放，验证旧终态/旧执行不出现、其他保存 work 保留，以及刷新后重新回放。截图保存在 `outputs/queue-agent-acceptance/queue-agent-workspace.png`，本轮日志和只读预检在同目录 `repair-*` 文件。

上述结果验证实现和协议行为，不代表付费真实模型的整书运行、标注质量或生产迁移已验收。临时验收服务及其 schema 在交付前清理，现有生产服务保持原运行状态。
