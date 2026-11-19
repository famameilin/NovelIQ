# 发布迁移入口

每次迁移固定一个文件：`scripts/migrations/migrate_<源版本>_to_<目标版本>.py`，版本号中的点改为下划线。从对应目标发布的项目根目录，通过项目 Python 环境运行 `python -m scripts.migrations.migrate_<源版本>_to_<目标版本>`。

| 源发布 → 目标发布 | 唯一入口 | 使用的项目代码 |
|---|---|---|
| 0.1.0 → 0.1.1 | `scripts.migrations.migrate_0_1_0_to_0_1_1` | 0.1.1 |
| 0.1.1 → 0.2.0 | `scripts.migrations.migrate_0_1_1_to_0_2_0` | 0.2.0 |
| 0.2.0 → 0.2.1 | `scripts.migrations.migrate_0_2_0_to_0_2_1` | 0.2.1 |
| 0.2.1 → 0.3.0 | `scripts.migrations.migrate_0_2_1_to_0_3_0` | 0.3.0 |
| 0.3.0 → 0.4.0 | `scripts.migrations.migrate_0_3_0_to_0_4_0` | 0.4.0 |

每个入口独立包含自己的迁移逻辑，允许使用对应发布的 `src` 模块和项目依赖，禁止导入其他迁移脚本或读取配套 JSON。历史入口只负责对应发布的结构；不能用 0.3.0 ORM 代替旧发布的 ORM 执行旧迁移。整理后的单个脚本可放入对应发布代码的同一路径使用，无需复制其他迁移文件。

## 统一调用

命令行入口固定为 `main()`，加载项目根目录 `.env` 后调用：

```python
migrate(
    database_env="TEST_DATABASE",
    schema="isolated_restore",
    apply=False,
    expect_database=None,
)
```

`migrate()` 的四个公共参数均为关键字参数，不要求调用者创建 Engine；函数自行建立连接并释放。直接调用该函数时，调用方应先加载项目环境变量。Engine 相关实现是文件内部细节，不作为发布入口。

| 命令行参数 | 约定 |
|---|---|
| `--database-env` | `DATABASE` 或 `TEST_DATABASE`，默认 `DATABASE` |
| `--schema` | 显式值优先；否则读取所选环境的 `DATABASE_SCHEMA` / `TEST_DATABASE_SCHEMA`；缺省 `public` |
| `--apply` | 省略时只读预检；提供时单事务执行 |
| `--expect-database` | 执行时必填；只读时填写也会校验数据库名 |

0.3.0 的额外选项为 `--archive-schema` 和 `--report`；前者对应可选关键字参数 `archive_schema`，后者只输出报告，不能作为迁移输入。报告文件不覆盖已有文件，脚本不依赖它再次执行。

0.4.0 的额外选项为 `--archive-schema`、`--drop-unmappable` 和 `--report`。事件组织改为事件树后，旧分组行与旧成员行的部分形状没有对应列：旧包含关系的父/子事件、同一事件出现在多个旧分组、组内成员带单树归属不允许的活动或因果标记、成员缺少所属分组。默认遇到这些行即阻断并逐条列出来源身份，不写入任何数据；`--drop-unmappable` 才允许丢弃它们并在报告的 `dropped_rows` 中按原因计数。旧分组行转成 `event_groups` 的树与结局两类，旧成员行转成 `event_links` 并按树内创建顺序编号 `position`；其余表按源列复制，`novels.word_count` 与 `paragraph_spans` 三个情感列保持为空。

```powershell
python -m scripts.migrations.migrate_0_2_1_to_0_3_0 --database-env TEST_DATABASE --schema isolated_restore
python -m scripts.migrations.migrate_0_2_1_to_0_3_0 --database-env TEST_DATABASE --schema isolated_restore --apply --expect-database novel_analysis_test
python -m scripts.migrations.migrate_0_3_0_to_0_4_0 --database-env TEST_DATABASE --schema isolated_restore --apply --expect-database novel_analysis_test
```

所有入口向标准输出写 JSON 报告。成功退出码为 0，阻断项、配置或数据库错误为 2；0.3.0 与 0.4.0 已提交迁移但另存报告失败时为 3，必须依据标准输出核对提交状态。SQL 或转换失败会回滚整笔迁移。

先保存完整备份与原发布代码、停止业务写入、收口分析任务，再在测试库的隔离恢复 schema 演练。脚本不创建数据库、不自动迁移现用库、不切换服务、不重新运行分析。各发布的数据处理边界见 [升级文档](../../docs/upgrades)。

## 本次整理的验证记录

2026-10-26，分别提取四个目标发布标签的项目源码，每个目录只放入对应的单个迁移文件，使用真实源发布的 ORM DDL 在测试库临时 schema 演练。测试库与现用库的连接目标已核对为不同数据库，临时 schema 在完成后清理；未迁移现用库。

| 迁移 | 隔离检查 | 独立进程耗时（含启动） |
|---|---:|---:|
| 0.1.0 → 0.1.1 | 6 项通过 | 5.43 秒 |
| 0.1.1 → 0.2.0 | 6 项通过 | 7.01 秒 |
| 0.2.0 → 0.2.1 | 13 项通过 | 10.86 秒 |
| 0.2.1 → 0.3.0 | 17 项通过 | 8.66 秒 |

前三段核对目标发布 ORM 的字段、类型、可空性、主键和外键，覆盖只读预检、活动任务阻断、数据保留、重复执行、空源结构和实际模块调用。0.2.1 另覆盖内置合并、审计用量、案例、身份来源、事件主链与跨树因果、伏笔状态保留，以及两阶段之间失败的事务回滚。0.3.0 覆盖完整归档、原表身份和外部外键保留、批量转换、约束失败回滚、归档冲突与源结构漂移。

另完成四个入口的 20 项接口、环境选择和数据库名保护检查；四个文件通过 compileall、Ruff 与对应发布下的单文件 mypy 检查（`--follow-imports=skip`）。验证使用临时脚本，未新增仓库测试文件；未运行全量后端或前端验证。

0.3.0 → 0.4.0 在测试库临时 schema 中按源发布 DDL 建结构并写入样例数据演练，未迁移现用库。执行后 30 张表与目标 ORM 一致，旧分组行转为树与结局两类并保留描述，旧成员行按树内顺序编号，旧包含关系与重复成员按上述规则被识别；`--drop-unmappable` 下这些行进入丢弃计数，其余表行数与源一致，新列与置空列为空。归档 schema 完整保留原表及迁移报告。重复执行返回已迁移状态；不带 `--drop-unmappable` 的执行以退出码 2 阻断，源结构、成员行和归档 schema 均未改变。演练 schema 在完成后清理。
