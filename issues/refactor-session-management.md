# Refactor: 数据库连接管理统一

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建时间 | 2026-03-30 |
| 状态 | 待实施 |
| 涉及分支 | `refactor/api-session-dependencies`, `refactor/cli-session-management` |
| 前置依赖 | 无（可与业务开发并行） |

---

## 现状：三种连接管理模式并存

| 模式 | 使用位置 | 评价 |
|------|----------|------|
| `Depends(get_db_session)` | `timeline.py` | ✅ 最佳实践：FastAPI 生命周期自动管理 |
| `_get_session_and_run_id()` + 手动 `conn.close()` | `results.py` 12+ 路由 | ❌ 每个路由手动 try/finally，泄漏风险高 |
| `with session_factory() as session:` | `analysis.py` | ✅ 安全，但与 Depends 模式不一致 |
| `get_session().__enter__()` 无 with 保护 | `cli/workflow_helpers.py` | ❌ 异常时连接不会释放 |

---

## Refactor-1: API 路由层连接管理统一

### 问题

`results.py` 中 13 个路由全部使用 `_get_session_and_run_id()` 辅助函数获取连接，每个路由体内手写 `try/finally: conn.close()`。

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
| `src/api/routes/results.py` | 13 个路由重写参数注入，删除 `_get_session_and_run_id` |
| `src/api/routes/results_fetchers/fetchers.py` | 函数签名从 `conn: Connection` 改为 `session: Session`（如需要） |
| `src/api/routes/analysis.py` | 从 `with session_factory()` 迁移到 `Depends()` 模式（可选，保持一致性） |
| `src/api/dependencies.py`（新建或扩展） | 新增 `resolve_run_id` 依赖 |

### 建议分支

`refactor/api-session-dependencies`，分步提交：

1. 提交 A：提取 `resolve_run_id` 依赖 + `timeline.py` 验证
2. 提交 B：逐路由迁移 `results.py`（可按功能分组：曲线类 / 角色类 / 指标类 / 时间轴）
3. 提交 C：迁移 `analysis.py`（可选）
4. 提交 D：删除 `_get_session_and_run_id`，清理 import

---

## Refactor-2: CLI 层连接管理统一

### 问题

`cli/workflow_helpers.py` 中的 `run_full_workflow` 使用 `get_session().__enter__()` 获取连接，没有 `with` 保护：

```python
# workflow_helpers.py L301-302
session_factory = get_session()
conn = session_factory.__enter__()
```

如果后续代码抛出异常，`__exit__` 不会被调用，连接将泄漏。

注意：同文件中其他调用点（`cli/parser.py`）已经使用正确的 `with get_session() as conn:` 模式。

### 目标

将 `workflow_helpers.py` 改为 `with` 语句保护，确保异常安全。

### 技术方案

**直接修复**：

```python
# 修改前
session_factory = get_session()
conn = session_factory.__enter__()

# 修改后
with get_session() as conn:
    ...
```

**但需要注意**：当前 CLI 的"长 session"模式在一个 session 内贯穿整个 workflow（preprocess → annotate → aggregate → diagnose），中间有多次 commit。需确认：

1. `get_session()` 的 `__exit__` 行为：是否在 with 退出时自动 commit/rollback？
2. 如果 `__exit__` 会 rollback 未提交的事务，而 CLI workflow 需要在中间 commit，可能需要：
   - 保持 `with` 块覆盖整个 workflow
   - 或为 CLI 场景提供手动 commit 控制的 variant

### 改动面

| 文件 | 改动 |
|------|------|
| `src/cli/workflow_helpers.py` | `get_session().__enter__()` → `with get_session() as conn:` |
| `src/cli/main.py` | 如有直接调用 `run_full_workflow` 的地方，确认连接生命周期 |

### 与 Refactor-1 的关系

两个 Refactor 共享 session 基础设施。如果 Refactor-1 中修改了 `get_session` / `SessionFactory` 的行为，需同步评估对 CLI 的影响。建议 Refactor-1 先行，Refactor-2 紧随其后。

### 建议分支

`refactor/cli-session-management`

---

## 执行顺序建议

```
Refactor-1 (API)  ──→  测试验证  ──→  Refactor-2 (CLI)
                                          │
                                    确认 session 生命周期
                                    对长 workflow 的影响
```

Refactor-1 完成后，`get_session` 的行为变更可能影响 CLI，因此 Refactor-2 应在 Refactor-1 之后执行并验证。

---

## 验证标准

- [ ] `results.py` 中不再有手动 `conn.close()` 调用
- [ ] `results.py` 中不再有 `_get_session_and_run_id` 函数
- [ ] 所有 API 路由使用 `Depends()` 注入 session 和 run_id
- [ ] `workflow_helpers.py` 使用 `with` 语句管理连接
- [ ] `uv run pytest tests/ -v` 全部通过
- [ ] `uv run ruff check src` 零错误
- [ ] 手动验证：无效 task_id 仍返回 404
