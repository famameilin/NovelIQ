# 0.2.1 升级检查与迁移边界

后端包、`uv.lock`、前端包与锁文件、FastAPI 元信息及健康接口的项目版本统一为 `0.2.1`。模块职责重划分不新增数据库结构变更；本次合并同时包含此前队列 work 与审计产物合并的结构变化，必须按实际库形状选择升级方式。

## 当前库检查

2026-10-08 对项目配置的 `novel_analysis/public` 执行只读检查：当前 ORM 必需表、字段及同 schema 外键均齐全，`pending/running/cancelling` 分析任务为 0。没有执行生产 DDL、历史记录转换、服务重启或付费模型请求。

从项目根目录执行：

```powershell
uv run python -m scripts.migrations.check_0_2_1 --schema public
```

命令读取根目录 `.env`，事务设为只读并限制查询时间。退出码 0 表示所检查结构齐全，2 表示缺项；连接或配置失败以异常退出。测试库使用 `--database-env TEST_DATABASE`。动态 `paragraph_embeddings` 的维度仍由既有专用入口管理，检查器不验证列类型、索引、数据质量或历史身份裁决，结构检查成功不能代替这些验收。

## 按源结构处理

| 实际库结构 | 处理方式 |
|---|---|
| 已有当前全部表、字段和外键 | 运行只读检查；无需重复六表迁移 |
| 新的空库 | 使用现有 `init_db()` 初始化当前 ORM，再运行只读检查 |
| 已完成角色 work 转换，仍使用旧审计表、章产物表和独立案例状态表 | 先备份、停写、收口任务，在隔离备份库演练下面的六表合并 |
| 原始 0.2.0 或更早，仍有旧流水线/身份裁决/缺少 work 与作者字段 | 当前仓库没有完整的一键语义转换入口；使用对应历史发布代码核对转换方案，不能跳过身份、作者与混存检查。六表工具会在 DDL 前拒绝不符合源合同的结构 |
| 新旧目标表部分混存 | 拒绝继续迁移，按备份与实际迁移记录核对；不自动猜测完成状态 |

`scripts.migrations.migrate_0_1_1_to_0_2_0` 是历史升级工具，依赖对应发布的 ORM；当前 ORM 已移除其目标流水线表。旧文档中的 `scripts.db.migrate_queue_agents` 源码没有进入 Git，当前不存在可发布入口。二者都不能用作当前版本的完整旧库升级命令。

## 角色 work 中间结构的六表合并

迁移实现和测试现已使用版本化入口，不依赖被 Git 忽略的 `scripts/db` 本地脚本。默认只读：

```powershell
uv run python -m scripts.migrations.migrate_turn_outputs_merge --database-env TEST_DATABASE --schema <隔离备份schema>
```

核对源表、字段、任务状态和归档冲突，确认业务结果与用量保持一致后，在隔离备份库执行：

```powershell
uv run python -m scripts.migrations.migrate_turn_outputs_merge --database-env TEST_DATABASE --schema <隔离备份schema> --apply --expect-database <测试数据库名>
uv run python -m scripts.migrations.check_0_2_1 --database-env TEST_DATABASE --schema <隔离备份schema>
```

实际发布窗口必须先保存完整数据库备份与原发布代码，停写并确认没有 `pending/running/cancelling` 任务；再将参数明确替换成实际发布库配置和数据库名。工具不自动启动生产迁移。

修复后的命令行在预检 SQL 前开启事务，解决 SQLAlchemy 查询自动开启事务后再次 `begin()` 的冲突；同时补齐旧脚本遗漏的工具调用 `message_key` 字段及唯一索引，保持后续审计去重可用。预检拒绝缺失源表/字段、部分目标结构、活动任务与已占用归档；执行要求数据库名匹配，并拒绝不存在的 schema 回退到 `public`。

合并保留原回合 ID 与工具调用关联、用量和无回合失败；保留章产物 ID、实际输入、work 与作者身份；每个 run 的诊断只迁入最新可读结果，旧诊断全量留在归档；案例状态及贡献并入原案例。旧审计消息全量归档，不伪造历史去重键。归档也保存原 `book_cases`，以便核对其合并前内容。

全部 DDL 与数据转换处于同一事务，失败整体回滚。归档 schema 为 `<源schema前35字符>_turn_outputs_archive`，内容是数据副本，不包含完整约束、索引与序列，不能替代完整备份。回退需停止新代码和写入，另存升级后新业务数据，再恢复发布前完整备份及匹配代码；不提供自动逆向迁移。

## 验证范围

隔离 PostgreSQL 演练覆盖完整合并、原 ID 和用量保留、最新诊断选择、案例贡献保留、无归属用量失败回滚、重复迁移拒绝、活动任务拒绝、缺失源合同、归档保护，以及实际命令行事务执行。结构检查另验证缺失 schema 不建表、缺失外键可检出及当前初始化幂等。

当前库只读结构检查与隔离迁移演练均通过。此结论不表示原始 0.2.0 语义转换或生产 DDL 已执行，历史身份与作者来源必须依据实际记录处理。

2026-10-08 合并前回归：

| 检查 | 实际结果 |
|---|---|
| 迁移与结构专项，`--no-cov` | 18 passed；pytest 6.34 秒，含启动墙钟 7.97 秒 |
| `scripts/dev.ps1 test` 全量后端 | 1784 passed，13 warnings；覆盖率 91.92%，达到 80% 门槛；pytest 112.73 秒，含启动与覆盖率的冷启动墙钟 117.66 秒，未超 5 分钟 |
| Ruff | `src`、`tests` 与两个新迁移入口通过 |
| mypy | 362 个源文件通过 |
| 前端完整测试 | 48 个文件通过；214 passed、1 skipped；Vitest 19.41 秒，含启动墙钟 20.01 秒 |
| 前端构建与 lint | TypeScript/Vite 构建通过；lint 0 errors、1 warning，来自生成的 `mockServiceWorker.js` |

本机 nvm 没有活动 Node 版本，前端使用已安装的 Codex Node 运行时执行包内 CLI。首次 Vitest 因沙箱临时目录重命名权限失败，未执行用例；切换正常临时目录并从 `frontend` 工作目录运行后通过。没有因测试环境问题修改前端实现或依赖。Vite 仍有既有包体积与插件耗时提示，本轮没有执行浏览器验收。
