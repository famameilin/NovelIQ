# 从 0.1.0 升级到 0.1.1

0.1.1 没有修改已有业务表的 ORM 结构。升级脚本检查 0.1.0 数据库是否具备本版需要的表和字段，核对正式标注、事件证据和诊断主题标签，并在 `noveliq_release_migrations` 中登记一次性升级结果。脚本不改写小说原文、正式标注、事件或诊断结果。

## 执行顺序

1. 停止 API 和分析 worker，等待运行中的任务结束，并按现有部署方式备份 PostgreSQL 数据库。
2. 使用 0.1.1 代码及其依赖，从仓库根目录运行只读检查：

   ```powershell
   .venv\Scripts\python.exe -X utf8 -m scripts.db.migrate_0_1_0_to_0_1_1
   ```

3. 核对报告的 `database`、`schema`、`schema_errors`、`blocking_issues`、`active_run_ids`。前两项必须指向预期目标，后三项必须为空。
4. 登记升级；将示例库名替换为报告中的实际 `database`：

   ```powershell
   .venv\Scripts\python.exe -X utf8 -m scripts.db.migrate_0_1_0_to_0_1_1 --apply --expect-database novel_analysis
   ```

5. 再次运行只读检查，确认 `already_applied: true`。随后启动 0.1.1 API 和前端，检查 `/health`、已完成任务的事件树、主题与诊断页面。

脚本读取仓库根目录 `.env` 或进程环境中的 `DATABASE_URL`、`DATABASE_USERNAME`、`DATABASE_PASSWORD`。目标不是 `public` 时使用 `--schema <名称>`；测试库可使用 `--database-env TEST_DATABASE`。`--apply` 会拒绝数据库名不匹配、运行中的任务、缺失结构、正式标注缺少 `metrics` 合同或事件段落锚点矛盾。重复执行不会重复登记。

## 历史数据的精度边界

- `legacy_topic_label_run_ids`：0.1.0 的诊断主题标签是数组，不能可靠按位置绑定 LDA `topic_id`。原值保留；要获得逐主题标签，需要对这些任务重新运行诊断。
- `chapter_evidence_event_count`：0.1.0 事件只有章节级原文证据。0.1.1 会明确显示章节级依据；要获得段落级定位，需要重新分析原文。
- `incomplete_annotation_run_ids`：正式标注缺少当前 `metrics` 合同，脚本阻止登记。先用现有任务入口重新分析相关任务，再运行脚本。

这些历史结果不会被脚本伪造为更细的证据。报告不包含小说正文、数据库密码或模型密钥。
