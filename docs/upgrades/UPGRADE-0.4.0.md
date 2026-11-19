# 从 0.3.0 升级到 0.4.0

入口：`scripts/migrations/migrate_0_3_0_to_0_4_0.py`。这是单文件入口，使用 0.4.0 正常安装的依赖、ORM 和数据库配置模块。脚本默认只读预检，只有显式指定 `--apply --expect-database` 才执行数据库升级。

本入口按本次明确允许的旧数据转换例外实现，不修改仓库默认的“数据处理只允许重建”约束，不在正式读写链增加旧格式兼容。

## 数据范围

脚本以 0.3.0 发布标签中的实际结构为源，以项目 0.4.0 ORM 为目标；两者均为 30 张业务表，表名相同，变化集中在 4 张表。源结构的列、类型、可空性、主键和外键目标直接内置在入口中，目标结构及领域约束使用项目现有接口。运行不需要配套 JSON、其他迁移脚本、初始化脚本或 Git。

执行时先将全部源表整体移动到归档 schema，保留原表 OID、记录、索引、序列和外键；再在原业务 schema 建立新表并逐表复制。默认归档名为 `<业务schema>_pre_0_4_0`，长名称取业务 schema 前 50 个字符后加后缀，也可通过 `--archive-schema` 指定。已经存在的归档不会被覆盖。

| 源数据 | 处理方式 |
| --- | --- |
| 小说、运行、章节、段落、图、对话、审计、指标等 28 张表 | 按源列原样复制；`novels.word_count` 为新增列，迁移后为空 |
| `paragraph_spans` | 按源列复制；新增 `emotion_polarity`、`emotion_negated`、`emotion_holder_token_index` 为空，情感观测需由正式流程重新生成 |
| `event_groups` 弧线行（`arc_kind` 非空） | 转 `kind='tree'`，`description` 取 `arc_objective`；`is_event_line` 置 false，`line_name` 与 `tree_key` 为空 |
| `event_groups` 结果行（`outcome_description` 非空） | 转 `kind='outcome'`，`description` 取 `outcome_description` |
| `event_groups` 的 `arc_kind`、`arc_role`、`arc_reason`、`parent_arc_id` | 新模型无对应列，随归档保留，不写入新表 |
| `event_links` 语义关系行 | 原样保留事件端点、关系类型、创建工作键与活动状态 |
| `event_links` 分组成员行（`member_event_id` 加 `arc_group_id` 或 `outcome_group_id`） | 转树成员行：`tree_id` 取所属分组，`position` 按同树 `created_at`（空值在后）与 `link_id` 排序后从 0 连续编号 |
| `event_links` 包含关系行（`contained_parent_id` / `contained_child_id`） | 新模型只保存整树父子引用，没有父/子事件包含列，不可映射 |
| 同一事件出现在多个旧分组、成员行带单树归属不允许的活动或因果标记、成员缺少所属分组 | 不可映射 |

`event_groups` 每一行必须恰好是弧线或结果之一，两者同时成立或同时为空时整笔升级拒绝。目标 `description` 不允许为空，`arc_objective` 或 `outcome_description` 为空的行会在约束处失败并整体回滚。

不可映射行默认阻断：退出码 `2`，整笔事务回滚，逐条报告来源身份，不写入任何数据。显式传入 `--drop-unmappable` 才丢弃这些行，并在报告 `dropped_rows`、`dropped_by_table` 中按原因计数，最多附 100 条来源样本。归档 schema 保存全部原行，不因丢弃而缺失。

旧事件线的选取、树名和树幂等键不能从旧数据推导，迁移一律写入普通树，需要事件线时由新流程重新选取并命名。旧事件成员、案例和图谱事实按真实身份保留，不补造新的组织结果。

## 使用

唯一入口为 `scripts/migrations/migrate_0_3_0_to_0_4_0.py`，公共接口固定为 `main() → migrate(database_env, schema, apply, expect_database)`，另有可选关键字参数 `archive_schema` 与 `drop_unmappable`。统一约定见 [迁移入口说明](../../scripts/migrations/README.md)。

从包含本入口的项目代码运行；入口只负责 0.3.0 到 0.4.0 的结构转换，不按代码版本拒绝执行。数据库连接使用 `.env` 中现有的平铺配置：`DATABASE_URL/USERNAME/PASSWORD` 或 `TEST_DATABASE_URL/USERNAME/PASSWORD`；schema 默认读取对应的 `DATABASE_SCHEMA` 或 `TEST_DATABASE_SCHEMA`，未配置时使用 `public`。

先在隔离的 0.3.0 备份恢复库预检：

```powershell
uv run python -m scripts.migrations.migrate_0_3_0_to_0_4_0 --database-env TEST_DATABASE --schema <业务schema> --report <新报告文件.json>
```

核对 `source_row_counts`、`converted_rows`、`converted_by_table`、`dropped_rows`、`dropped_by_table` 与 `samples`。`ready: true` 表示只读预检通过；不可映射行在预检中同样列入阻断项，先确认这些行能否接受归档后丢弃，再决定是否使用 `--drop-unmappable`。

执行前保留完整数据库备份和 0.3.0 发布代码，停止业务写入，并确认没有执行中的分析任务。隔离演练和实际执行都要求明确匹配数据库名：

```powershell
uv run python -m scripts.migrations.migrate_0_3_0_to_0_4_0 --database-env TEST_DATABASE --schema <业务schema> --apply --expect-database <测试数据库名> --report <新执行报告.json>
```

实际发布时，将连接选择改为 `--database-env DATABASE`，同时明确填写实际 schema 和数据库名。脚本不会自动切换服务或重新运行分析。

0.4.0 启动时不再核对既有库结构，`init_db()` 只对全新库建表并安装领域约束。已有 0.3.0 库必须通过本入口迁移，不能依赖服务启动时的结构检查发现差异。

## 执行保护与核对

- 预检事务只读，schema 不存在时拒绝，不回退到 `public`
- 源 30 张表的列、类型、可空性、主键与外键逐表核对，漂移即阻断
- 执行使用事务级迁移互斥锁和源表停写锁，获得锁后重新检查源结构；等锁限时 5 秒，单条 SQL 限时 60 秒
- 新表、归档、复制、组织转换、目录与逐表行数核对在同一事务中完成，任何失败整体回滚
- 逐表核对 `converted_rows + dropped_rows` 等于源行数；`event_links` 的语义行与成员行按新形状约束校验
- 新业务 schema 只有当前 30 张业务表；执行报告写入归档的 `migration_report`
- 已是完整目标结构时返回 `already_migrated: true, applied: false`，不重复写入
- `--report` 不覆盖已有文件；退出码 `2` 表示阻断或执行失败。退出码 `3` 表示数据库已经提交，但本地报告写入失败，数据库内的执行报告仍保留

数据库升级不等同于分析结果重建验收；`word_count`、情感观测、事件线与事件树组织需要由正式流程从原始输入重新生成。归档 schema 也不能代替完整数据库备份。

## 验证范围

使用 0.3.0 标签的真实结构在 `TEST_DATABASE` 的独立 schema 中演练，覆盖只读预检、完整执行、重复执行、目标表与 ORM 一致、组织行转换、成员行树内编号、不可映射行识别、默认阻断与整体回滚、归档内容。演练只操作隔离测试 schema，完成后清理，不执行现用数据库迁移，不重跑真实模型分析。

0.4.0 发布前验证记录：

| 检查 | 结果 |
| --- | --- |
| `compileall` | `src`、`tests` 与迁移脚本编译通过 |
| Ruff | `src`、`tests` 与 API 启动入口通过；迁移入口单独检查通过 |
| mypy | `src` 486 个源文件通过；迁移入口单文件检查通过 |
| 后端全量 pytest | 2267 项通过，22 条警告；147.70 秒 |
| 前端构建 | TypeScript 与 Vite 生产构建通过 |
| 前端 vitest | 60 个文件，260 项通过、1 项跳过 |
| 隔离 PostgreSQL 迁移演练 | 执行、重复执行与阻断回滚全部符合预期 |

逐提交验收在独立 worktree 中运行后端全量、Ruff、mypy、前端构建与 vitest，五个闸门全部通过。
