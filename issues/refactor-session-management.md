# 重构: 代码质量与架构优化

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建时间 | 2026-03-30 |
| 状态 | 待实施 |
| 建议分支 | `refactor/unified-session-management` |
| 前置依赖 | 无（可与业务开发并行） |

---

## 背景

本重构任务整合了以下优化需求：

1. **API 路由层连接管理统一** — 将手动 session 管理改为 FastAPI 依赖注入
2. **CLI 废弃** — API 已完整覆盖 CLI 功能，CLI 维护成本高，建议废弃
3. **metrics 层解耦 API 模型** — 消除跨层依赖，符合依赖倒置原则
4. **四阶段边界逻辑修复** — 确保始终返回 4 个阶段
5. **类型安全强化** — 用 Literal 类型消除 type: ignore
6. **N+1 查询优化** — 批量查询减少数据库往返

---

## 决策：废弃 CLI

### 理由

API 已完全覆盖 CLI 的分析触发能力：

| 功能 | CLI 命令 | API 接口 |
|------|---------|---------|
| 触发完整分析 | `python -m src.cli.main run --source ...` | `POST /{novel_id}/analyze` ✅ |
| 分阶段执行 | `preprocess`/`annotate`/`aggregate`/`diagnose` | ❌ 需 API 支持 |
| 断点续传 | `--resume` | ✅ API 自动判断已完成阶段 |
| 重新分析 | 无 | `POST /{novel_id}/reanalyze` ✅ |
| 上传小说 | 无 | `POST /novels/upload` ✅ |

**CLI 与 API 的核心区别仅是同步 vs 异步执行模式**。

### CLI 废弃影响评估

| 评估项 | 结果 |
|--------|------|
| CLI 独有价值 | 几乎无（仅同步执行模式有差异） |
| CLI 代码量 | ~800 行，11 个文件 |
| API 替代能力 | 完整覆盖 |
| 废弃影响 | **极低** |

### CLI 废弃实施

**废弃范围**：`src/cli/` 目录全部文件

**需补充的 API 功能**（如暂无同步执行需求，可跳过）：

```python
# 新增 API 端点（可选）
@router.post("/{novel_id}/workflow/sync")
async def run_workflow_sync(
    novel_id: str,
    request: WorkflowSyncRequest | None = None,
    novel_service: NovelService = Depends(get_novel_service),
) -> WorkflowSyncResponse:
    """同步执行完整分析 workflow，等待完成并返回结果"""
    ...
```

**废弃后行动**：
- 将 `src/cli/` 移动至 `deprecated/cli/` 目录
- 删除入口点配置（如 `pyproject.toml` 中的 cli 入口）

---

## 一、API 路由层连接管理统一

### 问题

`results.py` 中 12 个路由（不含非 novel_id 路由）全部使用 `_get_session_and_run_id()` 辅助函数获取连接，每个路由体内手写 `try/finally: conn.close()`。

> ⚠️ 注：文档原述为"13 个路由"，经核实实际为 **12 个** `@router.get("/{novel_id}/...")` 路由。

**当前代码模式** (`results.py`)：

```python
def _get_session_and_run_id(task_id: str, novel_service: NovelService) -> tuple[Session, str]:
    session_factory = SessionFactory()
    db_session = session_factory.get_session()
    try:
        run_id = task_id_to_run_id(task_id, db_session.connection)
        return db_session.connection, run_id
    except (ValueError, TaskIDNotFoundError):
        db_session.connection.close()
        raise NovelNotFoundError(f"任务不存在: {task_id}")

# 每个路由重复:
@router.get("/{novel_id}/emotion-curve")
async def get_emotion_curve(novel_id: str, task_id: str = Query(...)):
    conn, run_id = _get_session_and_run_id(task_id, novel_service)
    try:
        stats_repo = StatsRepository(conn)
        return _fetch_emotion_curve(run_id, stats_repo)
    finally:
        conn.close()
```

**风险**：
- 手动 `conn.close()` 容易遗漏（新增路由时忘记写 finally 块）
- `NovelNotFoundError` 路径中已手动 close，但其他未预期异常可能泄漏
- 路由函数签名中没有 session 类型标注，IDE/静态分析无法追踪

### 目标

统一为 FastAPI `Depends()` 注入模式，与 `timeline.py` 保持一致。

### 技术方案

**Step 1: 新增 `resolve_run_id` 依赖函数**

```python
# src/api/dependencies.py（新建或扩展现有 deps 模块）

async def resolve_run_id(
    task_id: str = Query(..., description="分析任务ID"),
    novel_service: NovelService = Depends(get_novel_service),
) -> str:
    """从 task_id 解析出 run_id，无效时抛 NovelNotFoundError (404)。"""
    run_id = novel_service.get_run_id(task_id)  # 内部已处理异常
    return run_id
```

**Step 2: 逐路由迁移**

```python
# 迁移后
@router.get("/{novel_id}/emotion-curve")
async def get_emotion_curve(
    novel_id: str,
    run_id: str = Depends(resolve_run_id),
    session: Session = Depends(get_db_session),
):
    stats_repo = StatsRepository(session)
    return _fetch_emotion_curve(run_id, stats_repo)
```

**Step 3: 清理**

- 删除 `_get_session_and_run_id` 函数
- 删除所有路由中的 `try/finally: conn.close()` 块
- 更新 `fetchers.py` 中接受裸 `conn` 参数的函数签名

### 改动面

| 文件 | 改动 |
|------|------|
| `src/api/routes/results.py` | 12 个路由重写参数注入，删除 `_get_session_and_run_id` |
| `src/api/routes/results_fetchers/fetchers.py` | 函数签名从 `conn: Connection` 改为 `session: Session`（如需要） |
| `src/api/routes/analysis.py` | 从 `with session_factory()` 迁移到 `Depends()` 模式（可选，保持一致性） |
| `src/api/dependencies.py`（新建或扩展） | 新增 `resolve_run_id` 依赖 |

---

## 二、metrics 层解耦 API 模型

> 来源：Code Review `main` 分支最近提交 — Issue 1

### 问题

`src/metrics/timeline_metrics.py` 属于领域层，但直接 import 了 `src/api/models/timeline.py` 中的 `RelationChangeEvent`、`TimelineNode`、`TimelinePhase`。这违反依赖倒置原则：

```
src.api.models.timeline  ←──  src.metrics.timeline_metrics  ←──  src.api.routes.timeline
       ↑                                                                      ↑
       └──── 依赖方向倒置：底层不应依赖顶层 ────────────────────────────────────┘
```

**影响：**
- API 响应格式变更时，metrics 层被迫修改
- `src/workflows/` 使用 timeline 逻辑时会连带引入 API 依赖
- `TimelineCandidate` 中包含 `list[RelationChangeEvent]`，所有使用方都被迫依赖 API 模型

### 目标

metrics 层定义独立的数据传输对象（DTO），API 层负责 DTO → Pydantic 模型的转换。

### 技术方案

**Step 1: 在 metrics 层定义独立 DTO**

在 `src/metrics/timeline_metrics.py` 中定义纯 dataclass（不依赖 Pydantic）：

```python
from dataclasses import dataclass, field
from typing import Literal

TimelineNodeType = Literal["plot", "character_entry", "character_exit", "relation_change"]

@dataclass
class RelationChangeEventDTO:
    from_char: str
    to_char: str
    relation_type: str
    change_type: str
    evidence: str | None = None

@dataclass
class TimelinePhaseDTO:
    name: str
    start: int
    end: int
    ratio: float

@dataclass
class TimelineNodeDTO:
    chunk_id: int
    progress: float
    importance_score: float
    level: Literal[1, 2, 3]
    event: str
    characters: list[str] = field(default_factory=list)
    is_pivot: bool = False
    is_cliffhanger: bool = False
    tension_percentile: int = 50
    node_type: TimelineNodeType = "plot"
    relation_changes: list[RelationChangeEventDTO] | None = None
    character_entries: list[str] | None = None
    character_exits: list[str] | None = None
```

**Step 2: 替换所有内部类型引用**

- `TimelineCandidate.relation_changes`: `list[RelationChangeEvent]` → `list[RelationChangeEventDTO]`
- `TimelineCandidate.node_type`: `str` → `TimelineNodeType`
- `TimelineCandidate.level`: `int` → `Literal[1, 2, 3]`
- `compute_four_phases` 返回 `list[NarrativePhase]`（保持不变，已经是内部 dataclass）
- `convert_to_timeline_nodes` 返回 `list[TimelineNodeDTO]`（不再是 API 模型）
- `convert_to_timeline_phases` 返回 `list[TimelinePhaseDTO]`（不再是 API 模型）

**Step 3: API 层添加 DTO → Pydantic 转换**

在 `src/api/routes/timeline.py` 中：

```python
def _dto_to_timeline_node(dto: TimelineNodeDTO) -> TimelineNode:
    return TimelineNode(
        chunk_id=dto.chunk_id,
        # ... 字段映射
        relation_changes=[_dto_to_relation_change(rc) for rc in dto.relation_changes] if dto.relation_changes else None,
    )
```

### 改动面

| 文件 | 改动 |
|------|------|
| `src/metrics/timeline_metrics.py` | 新增 DTO dataclass，替换所有 `from src.api.models.timeline` import |
| `src/api/routes/timeline.py` | 添加 DTO → Pydantic 转换函数 |
| `src/api/services/results_export_service.py` | `_fetch_timeline_data` 返回 DTO 而非 Pydantic 模型 |
| `tests/metrics/test_timeline_metrics.py` | 测试中的 `TimelineNode` 改为 `TimelineNodeDTO` |

---

## 三、四阶段边界逻辑修复

> 来源：Code Review `main` 分支最近提交 — Issue 3

### 问题

`src/metrics/timeline_metrics.py` 的 `compute_four_phases` 长小说路径（≥20 chunks）存在边界逻辑问题：

**1. 边界保护逻辑冗余（L170-L189）：**

对 `valley_idx` 进行了多次调整，其中 L181 的 `if valley_idx >= MIN_PHASE_LENGTH` 分支在某些情况下是冗余的。具体分析：

- L177 `valley_idx = max(valley_idx, MIN_PHASE_LENGTH)` 之后，valley_idx 必然 >= MIN_PHASE_LENGTH
- L181 的条件 `1 >= 1`（MIN_PHASE_LENGTH=1）永远为 True，else 分支（L186-188）仅在 valley_idx 初始值 < MIN_PHASE_LENGTH 时执行
- 实际上，由于 `NarrativePhase` 构造需要 `chunk_ids[valley_idx]` 索引，当 valley_idx < MIN_PHASE_LENGTH 时访问会越界，所以 else 分支实际上不可达

> ⚠️ 注：文档原述"第 181 行的 else 分支永远不会执行"不完全准确。经核实，当 valley_idx 初始值为 0 时，else 分支中的 `NarrativePhase("引入期", chunk_ids[0], chunk_ids[0], ...)` 是合法的，不会越界。因此 else 分支**可能执行**，只是其内的 valley_idx 重算逻辑与 L177 重复。

**2. 阶段可能少于 4 个（隐性违反契约）：**

当 `valley_idx == climax_start - MIN_PHASE_LENGTH` 时，发展期长度为 0 被跳过（L191 条件不满足），`phases` 可能只有 3 个元素。但 API 契约（`TimelineResponse.phases` 文档和 OpenAPI 描述）承诺「四阶段划分」。

### 目标

- 消除冗余的边界保护代码
- 确保始终返回 4 个阶段（极端情况下用告警标记退化阶段）

### 技术方案

```python
# 简化后的长小说路径
# 确保 valley_idx < climax_start，保留至少 MIN_PHASE_LENGTH 给发展期
valley_idx = min(valley_idx, climax_start - MIN_PHASE_LENGTH)
valley_idx = max(valley_idx, MIN_PHASE_LENGTH)

phases: list[NarrativePhase] = []

# 引入期（始终存在）
phases.append(
    NarrativePhase("引入期", chunk_ids[0], chunk_ids[valley_idx], (valley_idx + 1) / total)
)

# 发展期
dev_start_idx = valley_idx + 1
dev_end_idx = climax_start - 1
if dev_end_idx >= dev_start_idx:
    phases.append(
        NarrativePhase("发展期", chunk_ids[dev_start_idx], chunk_ids[dev_end_idx],
                       (dev_end_idx - dev_start_idx + 1) / total)
    )
else:
    logger.warning(f"发展期被跳过: valley_idx={valley_idx}, climax_start={climax_start}, total={total}")
    # 退化处理：在引入期和高潮期之间插入空发展期
    phases.append(NarrativePhase("发展期", chunk_ids[valley_idx], chunk_ids[valley_idx], 0.0))

# 高潮期和收束期保持不变
```

### 改动面

| 文件 | 改动 |
|------|------|
| `src/metrics/timeline_metrics.py` | 重写 L155-L220 的边界逻辑 |
| `tests/metrics/test_timeline_metrics.py` | 新增「发展阶段退化」测试用例 |

---

## 四、类型安全强化 — 消除 `# type: ignore`

> 来源：Code Review `main` 分支最近提交 — Issue 7

### 问题

`timeline_metrics.py` 中 `TimelineCandidate` 的 `level: int` 和 `node_type: str` 使用宽泛类型，在 `convert_to_timeline_nodes` 中需要 `# type: ignore[arg-type]` 绕过检查。如果内部逻辑产生了无效值（如 `level=4` 或 `node_type="typo"`），类型检查器无法提前发现，Pydantic 在运行时才报错。

### 目标

用 `Literal` 类型替代宽泛类型，消除 `type: ignore`，让类型检查器在编译期捕获错误。

### 技术方案

```python
# timeline_metrics.py
TimelineNodeType = Literal["plot", "character_entry", "character_exit", "relation_change"]

@dataclass
class TimelineCandidate:
    ...
    level: Literal[1, 2, 3]
    ...
    node_type: TimelineNodeType
    ...
```

消除 `convert_to_timeline_nodes` 和 `convert_to_timeline_phases` 中的 `# type: ignore`。

### 改动面

| 文件 | 改动 |
|------|------|
| `src/metrics/timeline_metrics.py` | `TimelineCandidate` 字段类型收窄 |
| `src/metrics/timeline_metrics.py` | 移除 `convert_to_timeline_*` 中的 `# type: ignore` |

### 与任务二的关系

此任务与「metrics 层解耦 API 模型」合并处理，因为 DTO 定义时直接使用 `Literal` 类型。

---

## 五、N+1 查询优化

> 来源：Code Review `main` 分支最近提交 — Issue 4 / Issue 9

### 问题

**`ensure_canonical_entities`**（`src/storage/repositories/annotation/characters.py` L131-167）：

对每个 `canonical_name` 执行一次 `SELECT` 查询，N 个角色产生 N 次数据库往返。

**`apply_alias_merges`**（同文件 L196-218）：

对每个 `alias → canonical` 执行 3 次 `UPDATE`（ChunkCharacter、ChunkDialogue、CharacterAppearance），M个别名产生 3M 次往返。

### 目标

- `ensure_canonical_entities`: 单次 `SELECT ... WHERE canonical IN (...)` 批量查询
- `apply_alias_merges`: 评估是否可通过 `CASE WHEN` 或 `executemany` 减少往返

### 技术方案

**`ensure_canonical_entities` 批量化：**

```python
# 一次查询所有已有实体
stmt = select(Entity.entity_id, Entity.canonical, Entity.entity_type).where(
    Entity.novel_id == novel_id,
    Entity.run_id == run_id,
    Entity.canonical.in_(known_canonical_names),
)
existing_map = {row.canonical: (row.entity_id, row.entity_type) for row in session.execute(stmt)}

for canonical in known_canonical_names:
    if canonical in existing_map:
        # 已存在：更新 entity_type（如需要）
        ...
    else:
        # 不存在：创建
        ...
```

**`apply_alias_merges` 优化（可选）：**

由于每个 alias 映射到不同的 canonical 值，难以用单条 SQL 合并。可考虑：
- 使用 SQLAlchemy `executemany` 批量发送
- 或接受当前逐行模式（标注流程非 API 热路径）

### 改动面

| 文件 | 改动 |
|------|------|
| `src/storage/repositories/annotation/characters.py` | `ensure_canonical_entities` 批量化 |
| `src/storage/repositories/annotation/characters.py` | `apply_alias_merges`（评估后决定是否优化） |

---

## 六、废弃 CLI

### 问题

CLI 与 API 功能完全重叠，但 CLI 维护成本高：

| 检查项 | 结果 |
|--------|------|
| API `AnalysisService` 是否完整 | 是，已封装完整 workflow |
| API 是否支持断点续传 | 是，`_check_stage_completion_status` |
| API 是否支持增量分析 | 是，`reanalyze` 接口 |
| CLI 连接管理复杂度 | 高，存在 Refactor-2 Session 泄漏风险 |
| CLI 代码量 | ~800 行，11 个文件 |

### 目标

废弃 CLI，统一使用 API 触发分析。

### 技术方案

**Step 1: 确认 API 能力**

- `POST /{novel_id}/analyze` — 异步触发完整分析
- `POST /{novel_id}/reanalyze` — 重新分析
- `POST /novels/upload` — 上传并自动触发分析

**Step 2: 创建 CLI 废弃目录**

```bash
mkdir -p deprecated/cli
git mv src/cli/* deprecated/cli/
rmdir src/cli
```

**Step 3: 清理入口点**

- 删除 `pyproject.toml` 中的 `src.cli.main:main` 入口
- 删除 `setup.py` 或 `setup.cfg` 中的 cli 入口（如有）

**Step 4: 补充 API 端点（可选）**

如需同步执行模式：

```python
@router.post("/{novel_id}/workflow/sync")
async def run_workflow_sync(
    novel_id: str,
    request: WorkflowSyncRequest | None = None,
    novel_service: NovelService = Depends(get_novel_service),
) -> WorkflowSyncResponse:
    """同步执行完整分析 workflow，等待完成并返回结果"""
    ...
```

### 改动面

| 文件/目录 | 改动 |
|----------|------|
| `src/cli/` | 移动至 `deprecated/cli/` |
| `pyproject.toml` | 删除 cli 入口点 |
| `src/api/routes/workflow.py`（新建） | 同步执行 workflow 端点（如需要） |

---

## 验证标准

- [ ] `results.py` 中不再有手动 `conn.close()` 调用
- [ ] `results.py` 中不再有 `_get_session_and_run_id` 函数
- [ ] 所有 API 路由使用 `Depends()` 注入 session 和 run_id
- [ ] `src/cli/` 目录已移至 `deprecated/cli/`
- [ ] `uv run pytest tests/ -v` 全部通过
- [ ] `uv run ruff check src` 零错误
- [ ] `uv run mypy src/` 零错误
- [ ] 手动验证：无效 task_id 仍返回 404

---

## 已完成的零散修复

> 来源：Code Review `main` 分支最近提交 — Issue 2/6/8/10/11
> 日期：2026-03-30

以下问题已在审查后直接修复，无需额外重构任务：

| Issue | 修复内容 | 涉及文件 | 核实状态 |
|-------|---------|----------|---------|
| Issue 2 | ~~删除 `results.py` 中与 `timeline.py` URL 冲突的重复路由~~ | `results.py` | ⚠️ **描述不准确**：经核实 `results.py` 中不存在 timeline 相关路由，需重新确认原始 Issue 描述 |
| Issue 6 | ~~移除 `_fetch_timeline_data` 的 `session` 死参数~~ | `results_export_service.py` | ⚠️ **已修复**：经核实当前函数签名中 `session` 参数已不存在（参数已移除），但文档描述与实际修复状态混淆 |
| Issue 8 | `importance_score` 上限从 `le=11` 修正为 `le=13` | `timeline.py` (API model) | ✅ 已确认 |
| Issue 10 | `get_results` 状态检查从 `== "completed"` 扩展为 `in ("completed", "aggregated", "diagnosed")` | `results.py` | ✅ 已确认 |
| Issue 11 | `max(rf_counts, key=rf_counts.get)` 改为 `key=lambda k: rf_counts[k] or 0`，防止隐式 None | `fetchers.py` | ✅ 已确认 |

---

## 执行顺序建议

```
Phase 1 (低成本高收益):
├── 任务三 (四阶段边界) — 1 人天，影响范围小
└── 任务四 (类型安全)   — 0.5 人天，合并到任务二

Phase 2 (核心重构):
├── 任务一 (API Session)  — 2-3 人天，需逐路由测试
└── 任务五 (N+1优化)     — 1-2 人天，独立分支

Phase 3 (架构优化):
├── 任务二 (Metrics解耦)  — 3-5 人天，复杂度最高
└── 任务六 (废弃 CLI)     — 0.5 人天，风险低

推荐分支策略:
- refactor/unified-session-management (任务一)
- refactor/metrics-decouple-api-models (任务二 + 任务四)
- fix/timeline-four-phases-boundary (任务三)
- perf/batch-entity-queries (任务五)
- chore/deprecate-cli (任务六，可最后执行)
```
