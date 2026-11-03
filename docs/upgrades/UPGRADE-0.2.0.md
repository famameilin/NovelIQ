# 从 0.1.1 升级到 0.2.0

使用 0.2.0 发布代码及其项目依赖，入口固定为 `scripts/migrations/migrate_0_1_1_to_0_2_0.py`。脚本复用该发布的 ORM，不需要其他迁移脚本或配套 JSON。通用接口见 [迁移入口约定](../../scripts/migrations/README.md)。

保存完整 PostgreSQL 备份与 0.1.1 代码，停止 API 和分析 worker，等待任务收口。先在测试库恢复备份，从 0.2.0 项目根目录运行：

```powershell
python -m scripts.migrations.migrate_0_1_1_to_0_2_0 --database-env TEST_DATABASE --schema isolated_restore
python -m scripts.migrations.migrate_0_1_1_to_0_2_0 --database-env TEST_DATABASE --schema isolated_restore --apply --expect-database novel_analysis_test
python -m scripts.migrations.migrate_0_1_1_to_0_2_0 --database-env TEST_DATABASE --schema isolated_restore
```

上述 schema 和数据库名须替换为隔离恢复库的实际值。默认只读；`--apply` 在一笔事务内新增 13 张流水线表、补充 `analysis_runs` 与 `chapter_annotations` 的列和约束、调整图实体名称索引并解除指向 `work_items` 的外键，最后登记 `noveliq_release_migrations`。

该发布迁移会删除旧队列残留表 `case_resolution_mappings`、`case_pool_cases` 及其记录，并清空 `work_items` 的旧队列记录。正式标注、事件、段落、诊断及原文不改写；迁移检查相关业务表行数，失败整体回滚。预检报告的 `legacy_purge` 列出待清除范围，执行前必须核对。

复查 `schema_errors`、`changes_pending`、`active_run_ids`、`changes_applied` 及台账结果。重复执行保持幂等。不能在当前 0.3.0 项目中以替代 ORM 执行本历史迁移；回退使用发布前完整备份与匹配代码。
