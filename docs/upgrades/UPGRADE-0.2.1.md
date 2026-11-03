# 从 0.2.0 升级到 0.2.1

使用 0.2.1 发布代码及其项目依赖，唯一入口固定为 `scripts/migrations/migrate_0_2_0_to_0_2_1.py`。角色 work 转换、身份来源预检、审计与产物合并均包含在该文件内，不依赖其他迁移脚本或配套 JSON。公共接口与环境规则见 [迁移入口约定](../../scripts/migrations/README.md)。

## 预检与执行

保存完整 PostgreSQL 备份和 0.2.0 发布代码，停止业务写入、等待任务收口，先在测试库恢复备份。从 0.2.1 项目根目录运行：

```powershell
python -m scripts.migrations.migrate_0_2_0_to_0_2_1 --database-env TEST_DATABASE --schema isolated_restore
python -m scripts.migrations.migrate_0_2_0_to_0_2_1 --database-env TEST_DATABASE --schema isolated_restore --apply --expect-database novel_analysis_test
python -m scripts.migrations.migrate_0_2_0_to_0_2_1 --database-env TEST_DATABASE --schema isolated_restore
```

将 schema 和数据库名替换为隔离恢复库的实际值。命令读取根目录 `.env`；省略 `--schema` 时，按所选环境读取 `DATABASE_SCHEMA` 或 `TEST_DATABASE_SCHEMA`，未配置时使用 `public`。不指定 `--apply` 时事务只读；所有执行变更在同一事务中，失败整体回滚。退出码 0 表示预检或执行成功，2 表示阻断或错误。

迁移前后使用同一个入口，核对 `blocking_issues`、`active_run_ids`、`current_schema`、`already_migrated` 和转换统计。不需要另运行结构检查脚本或六表合并脚本。

## 源结构边界

| 实际源结构 | 同一入口的处理 |
|---|---|
| 原始 0.2.0，含旧流水线、身份裁决、缺少 work 与作者字段 | 完整预检，通过后先转换角色 work，再合并审计与产物 |
| 角色 work 已转换，仍保留旧审计、章产物及独立案例状态表 | 核对完整中间结构后，仅执行文件内的合并逻辑，报告 `merge_only` |
| 已有完整 0.2.1 表、字段与外键且旧流水线已退役 | 返回 `already_migrated`，不重复写入 |
| 目标表部分存在、新旧结构混存、旧章与已保存 work 混存 | 报告阻断，按备份和实际迁移记录核对 |
| 0.1.1 或更早 | 先使用匹配目标发布的历史入口升级到 0.2.0 |

脚本要求匹配 0.2.1 项目代码，拒绝借用当前发布的领域模型执行该历史转换。动态 `paragraph_embeddings` 仍由该发布的专用入口管理，不计入静态发布表检查。

## 数据与回退

完整转换检查源字段、活动任务、部分目标结构、章输入与段落、保存结果混存，以及身份裁决的实际作者。无法确定身份、作者或原文来源时阻断，不伪造身份贡献。获取源表锁后再次预检。

合并保留原回合 ID、工具关联、用量和无回合失败；保留章产物 ID、实际输入、work 与作者；每个运行的诊断仅迁入最新可读结果，旧诊断全量留在归档；案例状态与贡献并入原案例。旧审计消息全量归档，不伪造历史去重键。

合并归档 schema 为 `<源schema前35字符>_turn_outputs_archive`，保存原审计、产物、工具关联与案例数据副本。归档冲突会阻断。副本不包含完整约束、索引与序列，不能替代完整备份。完整转换成功后，旧流水线表及其残留记录按该发布既定退役范围删除。

重复执行不会重复迁移。单条 SQL 超时 60 秒，锁等待超时 5 秒；这些限制不代表整个迁移耗时上限。回退须停止新代码与写入、另存升级后新业务数据，再恢复发布前完整备份和匹配代码；没有自动逆向入口。

## 历史发布验证记录

以下为原发布时的验证记录，不代表本次重新运行全量后端、前端或现用库检查。

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

2026-10-08 新增完整迁移验证：

| 检查 | 实际结果 |
|---|---|
| 完整发布迁移、六表合并与结构检查专项，最终代码，`--no-cov` | 29 passed，33 warnings；pytest 17.19 秒，含启动墙钟 20.02 秒，未超 30 秒 |
| 新增入口加入后的全量后端 | 1798 passed，43 warnings；覆盖率 91.92%；pytest 139.57 秒，含启动与覆盖率墙钟 145.33 秒，未超 5 分钟 |
| Ruff | `src`、`tests` 与三个迁移/检查入口通过 |
| mypy | `src` 与完整迁移、六表入口共 364 个文件通过 |
| 新入口对当前配置库的默认预检 | `already_migrated: true`、`ready: true`、`applied: false` |

全量回归后补充了多成功尝试的来源歧义处理与已迁移库的实际任务状态报告，并以最终代码重跑上述迁移专项。专项的 warnings 来自隔离 schema 中 `public.vector` 的 SQLAlchemy 类型反射；脚本不改写向量类型或维度。没有再次运行未改动的前端、浏览器或真实模型验收，也没有执行生产迁移。
