# 中文网络小说量化分析 API 文档

## 一、API概述

本项目提供 RESTful API 服务，基于 FastAPI 框架实现。API 服务提供小说上传、分析任务管理、结果查询等功能。

### 服务启动

```bash
# 启动服务（带端口占用检测）
python -m src.api.main --host 0.0.0.0 --port 8000

# 开发模式（支持热重载）
python -m src.api.main --reload

# 指定其他端口
python -m src.api.main --port 8001
```

**启动参数说明**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| --host | 0.0.0.0 | 监听地址 |
| --port | 8000 | 监听端口 |
| --reload | False | 启用开发模式自动重载 |

**端口占用检测**: 使用 `python -m src.api.main` 启动时，会自动检测端口是否被占用，如果被占用会显示友好的错误提示并退出。

### 在线文档

- **Swagger UI**: `http://localhost:8000/api/docs`
- **ReDoc**: `http://localhost:8000/api/redoc`

---

## 二、API端点列表

### 2.1 小说管理接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/novels/upload` | 上传小说文件 |
| GET | `/api/novels/` | 列出所有小说 |
| DELETE | `/api/novels/{novel_id}` | 删除小说 |
| POST | `/api/novels/batch-delete` | 批量删除小说 |

### 2.2 分析任务接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/novels/{novel_id}/tasks` | 创建并启动新任务 |
| POST | `/api/novels/{novel_id}/tasks/{task_id}/resume` | 继续指定任务 |
| POST | `/api/novels/{novel_id}/reanalyze` | 重新分析 |
| GET | `/api/novels/{novel_id}/tasks` | 获取所有分析任务 |
| GET | `/api/novels/{novel_id}/tasks/{task_id}/status` | 查询单任务状态（推荐） |
| GET | `/api/novels/{novel_id}/status` | 兼容状态查询（必须显式提供 task_id） |
| DELETE | `/api/novels/{novel_id}/tasks/{task_id}` | 删除特定分析任务 |
| POST | `/api/novels/{novel_id}/tasks/batch-delete` | 批量删除分析任务 |
| POST | `/api/novels/{novel_id}/tasks/{task_id}/cancel` | 取消正在运行的分析任务 |

**当前版本说明：**
- 旧 `POST /api/novels/{novel_id}/analyze` 已移除，不再作为创建或续跑入口。
- 创建新任务与继续旧任务已拆分为 `POST /tasks` 与 `POST /tasks/{task_id}/resume` 两条链。

### ID 体系说明

系统对外统一使用短 ID，但内部仍兼容历史 run 形态：

| ID 类型 | 格式 | 示例 | 用途 | 使用场景 |
|---------|------|------|------|----------|
| novel_id | 8位字符串 | `10960c77` | 小说唯一标识 | API内外通用 |
| task_id | 8位字符串 | `a1b2c3d4` | 任务标识（外部使用） | API、前端、导出文件 |
| run_id | 内部运行标识 | `a1b2c3d4` / 历史兼容 `a1b2c3d4-1a72-4444-a772-2ddc64334cd2` | 数据隔离键 | Repository、Workflow、日志目录 |

**ID映射关系：**
- 当前新创建任务通常直接以 8 位 `task_id` 作为 `run_id` 落库。
- 历史数据中仍可能存在完整 UUID `run_id`；API 层会兼容按 `task_id` 前缀解析。
- 外部调用方应始终使用 `task_id`，不要假设数据库里的 `run_id` 一定是完整 UUID。

**数据隔离规则：**
- 数据通过 `run_id` 字段在 PostgreSQL 数据库中隔离
- 日志目录：`logs/{run_id}/`
- 结果文件：`outputs/{task_id}.json`

### 2.3 结果查询接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/novels/{novel_id}/results?task_id={task_id}` | 导出完整结果（复盘/测试用） |
| GET | `/api/novels/{novel_id}/chunk-curves?task_id={task_id}` | 获取分块曲线（情绪 + 节奏） |
| GET | `/api/novels/{novel_id}/chunk-annotations?task_id={task_id}` | 获取分块标注与伏笔详情 |
| GET | `/api/novels/{novel_id}/characters?task_id={task_id}` | 获取人物统计 |
| GET | `/api/novels/{novel_id}/topics?task_id={task_id}` | 获取主题分布 |
| GET | `/api/novels/{novel_id}/diagnosis?task_id={task_id}` | 获取诊断结果 |
| GET | `/api/novels/{novel_id}/foreshadowing-threads?task_id={task_id}` | 获取 setup thread 台账 |
| GET | `/api/novels/{novel_id}/graph?task_id={task_id}` | 获取知识图谱快照 |
| GET | `/api/novels/{novel_id}/graph/events?task_id={task_id}` | 获取图谱关系事件分页结果 |

### 2.4 叙事时间轴接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/novels/{novel_id}/timeline?task_id={task_id}` | 获取叙事时间轴 |

**注意**：所有结果查询接口都需要提供 `task_id` 参数来指定要查询的分析任务。

### 2.5 聚合指标接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/novels/{novel_id}/metrics/narrative-structure?task_id={task_id}` | 获取叙事结构指标 |
| GET | `/api/novels/{novel_id}/metrics/emotion-stats?task_id={task_id}` | 获取情感统计指标 |
| GET | `/api/novels/{novel_id}/metrics/character-stats?task_id={task_id}` | 获取人物统计指标 |
| GET | `/api/novels/{novel_id}/metrics/style-stats?task_id={task_id}` | 获取风格统计指标 |

**当前版本说明：**
- public `/metrics/*` 路由当前只有以上 4 个。
- 文化相关聚合（`idiom_density` / `classical_sentence_ratio` / `imagery_density`）仍保留在内部 aggregate / 研究文档中，但当前版本不作为公开 `culture-stats` 路由暴露。

### 2.6 系统接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/events/tasks/{task_id}` | SSE 任务事件流 |

---

## 三、接口详细说明

### 3.1 小说管理

#### POST /api/novels/upload

上传小说文件进行分析。

**请求格式**: `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 小说文本文件（.txt格式） |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "filename": "小说名.txt",
  "status": "uploaded",
  "message": "文件上传成功"
}
```

---

#### GET /api/novels/

列出所有已上传的小说。

**响应示例**:
```json
{
  "items": [
    {
      "novel_id": "10960c77",
      "filename": "小说名.txt",
      "file_path": "data/uploads/10960c77_小说名.txt",
      "status": "completed",
      "title": "小说名.txt",
      "author": "未知作者",
      "upload_time": "2026-04-28T10:00:00",
      "file_size": 123456
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 12,
  "total_pages": 1
}
```

**查询参数**:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | int | 1 | 页码 |
| page_size | int | 12 | 每页数量 |

---

#### DELETE /api/novels/{novel_id}

删除指定小说及其分析数据。

**响应示例**:
```json
{
  "message": "删除成功",
  "novel_id": "10960c77"
}
```

**注意**:
- 若小说下仍有 `pending` / `running` / `cancelling` 任务，接口会返回 `400` 并拒绝删除。
- 删除成功时会一并清理任务数据、日志目录和导出文件。

---

#### POST /api/novels/batch-delete

批量删除小说及其分析数据。

**请求体** (JSON):
```json
{
  "novel_ids": ["10960c77", "a1b2c3d4", "e5f6g7h8"]
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| novel_ids | List[str] | 是 | 要删除的小说ID列表 |

**响应示例（全部成功）**:
```json
{
  "success": true,
  "message": "成功删除 3 本小说",
  "deleted_count": 3,
  "failed_count": 0,
  "deleted_ids": ["10960c77", "a1b2c3d4", "e5f6g7h8"],
  "failed_ids": []
}
```

**响应示例（部分成功）**:
```json
{
  "success": true,
  "message": "部分删除成功: 2 本成功, 1 本失败",
  "deleted_count": 2,
  "failed_count": 1,
  "deleted_ids": ["10960c77", "a1b2c3d4"],
  "failed_ids": [
    {"novel_id": "e5f6g7h8", "reason": "小说不存在: e5f6g7h8"}
  ]
}
```

**说明**:
- 即使部分删除失败，也会继续处理其他小说
- 删除小说时会同时删除其关联的所有任务数据

---

### 3.2 分析任务

#### POST /api/novels/{novel_id}/tasks

创建并启动一个新的分析任务。

**请求体**：无

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4",
  "status": "pending",
  "message": "分析任务已创建并启动"
}
```

**说明**：
- 这是当前版本创建任务的唯一入口。
- 旧 `POST /api/novels/{novel_id}/analyze` 已移除。

---

#### POST /api/novels/{novel_id}/tasks/{task_id}/resume

继续执行指定的 `pending` / `failed` 任务。

**请求体**：无

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4",
  "status": "pending",
  "message": "分析任务已继续执行"
}
```

**说明**：
- 该接口只负责“继续指定任务”，不再承担创建新任务的语义。
- 如果任务不属于当前小说、状态不允许继续或任务不存在，会返回 `400/404`。

---

#### POST /api/novels/{novel_id}/reanalyze

重新分析已上传的小说（强制创建新任务）。

**请求体** (JSON):
```json
{
  "force_preprocess": false,
  "force_annotate": false,
  "force_aggregate": false,
  "force_topic_model": false,
  "force_diagnose": false,
  "num_topics": 20,
  "label": "v2"
}
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| force_preprocess | bool | false | 强制重新预处理 |
| force_annotate | bool | false | 强制重新标注 |
| force_aggregate | bool | false | 强制重新聚合 |
| force_topic_model | bool | false | 强制重新主题建模 |
| force_diagnose | bool | false | 强制重新诊断 |
| num_topics | int | 20 | 主题数量 |
| label | string | null | 分析版本标签 |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "b2c3d4e5",
  "status": "pending",
  "message": "重新分析任务已启动"
}
```

**说明**：
- 每次重新分析都会创建新任务。
- 请求模型默认 `num_topics = 20`；若整个请求体为空，服务层会按当前配置补默认主题数。

---

#### GET /api/novels/{novel_id}/tasks

获取小说的所有分析任务列表。

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "tasks": [
    {
      "task_id": "a1b2c3d4",
      "novel_id": "10960c77",
      "status": "completed",
      "created_at": "2026-04-28T10:00:00"
    },
    {
      "task_id": "b2c3d4e5",
      "novel_id": "10960c77",
      "status": "running",
      "created_at": "2026-04-28T10:05:00"
    }
  ]
}
```

---

#### DELETE /api/novels/{novel_id}/tasks/{task_id}

删除特定分析任务。

**响应示例**:
```json
{
  "message": "任务删除成功",
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4"
}
```

**注意**: 删除任务会删除数据库中该 `run_id`（通过 `task_id` 映射）对应的所有数据，此操作不可恢复。

---

#### POST /api/novels/{novel_id}/tasks/batch-delete

批量删除分析任务。

**请求体** (JSON):
```json
{
  "task_ids": ["a1b2c3d4", "b2c3d4e5", "c3d4e5f6"]
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_ids | List[str] | 是 | 要删除的任务ID列表 |

**响应示例（全部成功）**:
```json
{
  "success": true,
  "message": "成功删除 3 个任务",
  "deleted_count": 3,
  "failed_count": 0,
  "deleted_ids": ["a1b2c3d4", "b2c3d4e5", "c3d4e5f6"],
  "failed_ids": []
}
```

**响应示例（部分成功）**:
```json
{
  "success": true,
  "message": "部分删除成功: 2 个成功, 1 个失败",
  "deleted_count": 2,
  "failed_count": 1,
  "deleted_ids": ["a1b2c3d4", "b2c3d4e5"],
  "failed_ids": [
    {"task_id": "c3d4e5f6", "reason": "任务不存在"}
  ]
}
```

**说明**:
- 只能删除属于指定小说的任务
- 即使部分删除失败，也会继续处理其他任务
- 删除任务会删除数据库中对应 `run_id`（通过 `task_id` 映射）的所有数据，此操作不可恢复

---

#### POST /api/novels/{novel_id}/tasks/{task_id}/cancel

取消正在运行的分析任务。

> **创建时间**: 2026-04-07  
> **说明**: 采用协作式取消，任务将在当前阶段完成后停止，不会强制中断正在执行的 LLM 调用。

**请求**：无请求体

**响应示例**：
```json
{
  "task_id": "a1b2c3d4",
  "status": "cancelling",
  "message": "任务将在当前阶段完成后停止"
}
```

**错误处理**：
| 状态码 | 场景 |
|--------|------|
| 400 | 任务已完成、已取消或正在取消 |
| 404 | 任务不存在 |

**行为说明**：
- 取消请求发出后，任务状态先变为 `cancelling`，当前阶段执行完毕后变为 `cancelled`
- 取消后数据库中已有部分数据（如部分 chunks/annotations），后续可通过 `POST /tasks/{task_id}/resume` 或重新分析继续
- 若任务是“尚未被 worker 领取的 pending 任务”，接口会直接返回 `cancelled`
- 若任务已由其他执行方接手但当前进程无内存句柄，接口会返回 `cancelling`，等待执行方收尾

---

#### GET /api/novels/{novel_id}/tasks/{task_id}/status

查询单个任务状态（推荐入口）。

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4",
  "status": "running",
  "progress": 45.5,
  "stage": "annotate",
  "sub_stage": "phase2",
  "current": 91,
  "total": 200,
  "message": "正在处理第 91 / 200 个分块",
  "llm_outputs": null,
  "error": null
}
```

**说明**：
- 这是当前版本推荐的状态查询入口。
- 当任务不存在或不属于当前小说时返回 `404`。

---

#### GET /api/novels/{novel_id}/status

兼容状态查询入口。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4",
  "status": "running",
  "progress": 45.5,
  "stage": "annotate",
  "sub_stage": "phase2",
  "current": 91,
  "total": 200,
  "message": "正在处理第 91 / 200 个分块",
  "llm_outputs": null,
  "error": null
}
```

**状态值**:
- `pending`: 等待执行
- `running`: 执行中
- `cancelling`: 正在取消（等待当前阶段完成后停止）
- `cancelled`: 已取消
- `completed`: 已完成
- `failed`: 执行失败

**说明**：
- 当前实现要求显式提供 `task_id`；未提供时会返回 `400`。
- 推荐改用 `GET /api/novels/{novel_id}/tasks/{task_id}/status`。

---

### 3.3 结果查询

#### GET /api/novels/{novel_id}/results

📋 **复盘与测试专用接口**

将完整分析数据写入 `outputs/` 目录下的JSON文件，用于：
- 项目复盘与结果审查
- 测试验证与数据对比
- 分析结果归档备份

**前置条件**：
- 任务状态必须属于可读终态：`completed` / `aggregated` / `diagnosed`
- 如果任务未完成，将返回错误

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/results?task_id=a1b2c3d4
```

**响应示例（成功）**:
```json
{
  "success": true,
  "message": "分析结果已写入文件",
  "file_path": "outputs/a1b2c3d4.json",
  "novel_id": "10960c77",
  "novel_name": "重明传",
  "missing_fields": null
}
```

**响应示例（任务未完成）**:
```json
{
  "detail": "分析任务未完成，当前状态: running"
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 写入是否成功 |
| message | str | 状态消息 |
| file_path | str | 结果文件路径 |
| novel_id | str | 小说ID |
| novel_name | str | 小说名称 |
| missing_fields | list | 缺失字段列表（如有） |

**错误码**:
| 状态码 | 说明 |
|--------|------|
| 400 | 任务未完成或 run 不可读 |
| 404 | 任务不存在 |
| 409 | diagnosis 焦点合同失效，需重跑 |

---

#### GET /api/novels/{novel_id}/chunk-curves

获取分块曲线数据（情绪 + 节奏）。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/chunk-curves?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "chunk_id": 0,
    "pos_density": 0.0,
    "neg_density": 0.002638,
    "net_density": -0.002638,
    "smoothed_density": -0.002638,
    "tension_proxy": 5.578,
    "tension_composite": 0.21,
    "surface_tension": 0.18
  }
]
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| chunk_id | int | 分块编号 |
| pos_density | float | 正向情绪密度 |
| neg_density | float | 负向情绪密度 |
| net_density | float | 情绪净密度 |
| smoothed_density | float | 平滑后的情绪曲线值 |
| tension_proxy | float | 张力代理值 |
| tension_composite | float | 融合张力值 |
| surface_tension | float | 展示层 surface tension 值 |

---

#### GET /api/novels/{novel_id}/chunk-annotations

获取分块标注与强伏笔细节。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/chunk-annotations?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "chunk_id": 18,
    "emotional_valence": "mild_negative",
    "event_type": "转折",
    "pivot_moment": true,
    "cliffhanger": false,
    "has_foreshadowing": true,
    "is_strong_setup": true,
    "foreshadowing_type": "物件",
    "setup_kind": "异常物件",
    "foreshadowing_desc": "铜铃异响暗示旧案未结",
    "setup_summary": "铜铃异响反复指向山门旧案",
    "why_unresolved_now": "真相尚未揭露",
    "expected_payoff_family": "真相揭露",
    "payoff_likelihood": "high",
    "linked_setup_id": "setup-001",
    "characters": [
      {
        "name": "贺伯安",
        "role_function": "主体",
        "action": "追查铜铃异响",
        "emotion_score": "mild_negative"
      }
    ],
    "relations": [
      {
        "from_char": "贺伯安",
        "to_char": "柳婉儿",
        "type": "盟友",
        "change": "强化"
      }
    ],
    "dialogues": [
      {
        "speaker": ["贺伯安"],
        "length": 34
      }
    ]
  }
]
```

**说明**：
- 这是当前对外公开的结构化分块结果接口。
- 返回中既包含基础 chunk 标注，也包含强伏笔相关字段和嵌套的人物/关系/对话摘要。

---

#### GET /api/novels/{novel_id}/characters

获取人物统计数据。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/characters?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "name": "主角名",
    "appearance_count": 35,
    "dominant_role_function": "主体",
    "role_function_distribution": {
      "主体": 30,
      "帮助者": 5
    },
    "dominant_role_ratio": 0.86,
    "narrative_focus_score": 0.95,
    "is_focus_character": true,
    "avg_emotion_score": -0.83
  }
]
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| name | str | 角色名称 |
| appearance_count | int | 出场次数 |
| dominant_role_function | str | 主导角色功能（Greimas 六元素，如 `主体/帮助者/反对者`） |
| role_function_distribution | dict | 角色功能分布统计 |
| dominant_role_ratio | float | 主导角色占比 |
| narrative_focus_score | float | 叙事中心度得分（四因子融合） |
| is_focus_character | bool | 是否属于 diagnosis 输出的焦点人物 |
| avg_emotion_score | float | 平均情感得分 |

---

#### GET /api/novels/{novel_id}/topics

获取主题分布数据。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/topics?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "topic_id": 11,
    "words": ["关键词1", "关键词2", "关键词3"],
    "weight": 6.14
  }
]
```

---

#### GET /api/novels/{novel_id}/diagnosis

获取诊断结果。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/diagnosis?task_id=a1b2c3d4
```

**响应示例（有数据）**:
```json
{
  "rerun_required": false,
  "rerun_reason": null,
  "foreshadow_expectation": 0.6,
  "arc_scores": {"主角A": 8.0, "主角B": 7.0},
  "narrative_type": "寓言",
  "topic_labels": ["抗争", "宿命"],
  "diagnosis": "该叙事以寓言形式探索人类面对困境的成长历程...",
  "value_logic_type": "善义有价值",
  "value_logic_reason": "...",
  "power_stance_score": 3,
  "power_stance_reason": "...",
  "common_people_dignity": 4,
  "dignity_reason": "...",
  "cultural_depth_score": 4,
  "cultural_depth_reason": "传统文化词汇深度参与叙事，儒家伦理观念推动主角行为选择...",
  "narrative_arc_type": "白手起家",
  "focus_structure": "dual",
  "focus_characters": ["主角A", "主角B"],
  "main_characters": ["主角A", "主角B", "配角C"],
  "core_cast": ["主角A", "主角B"],
  "theme_color": "#4A90D9"
}
```

**响应示例（需要重跑 diagnosis）**:
```json
{
  "rerun_required": true,
  "rerun_reason": "focus_contract_incomplete"
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| rerun_required | bool | 当前 diagnosis 合同是否要求重新分析 |
| rerun_reason | str \| null | 需要重跑的原因 |
| foreshadow_expectation | float \| null | 伏笔回收预期（0-1，基于 setup thread ledger 加权估算的近似值） |
| arc_scores | dict[str, float] | 各角色弧线得分 |
| narrative_type | str | 叙事类型 |
| topic_labels | list[str] | 主题标签 |
| diagnosis | str | 诊断分析文本 |
| value_logic_type | str | 价值逻辑类型 |
| value_logic_reason | str | 价值逻辑说明 |
| power_stance_score | int | 权力立场评分（0-5） |
| power_stance_reason | str | 权力立场说明 |
| common_people_dignity | int | 平民尊严评分（0-5） |
| dignity_reason | str | 尊严评分说明 |
| cultural_depth_score | int | 文化内涵真实性评分（0-5分） |
| cultural_depth_reason | str | 评分说明 |
| narrative_arc_type | str | 叙事弧线类型 |
| focus_structure | str | 焦点结构，`single` / `dual` / `ensemble` |
| focus_characters | list[str] | 焦点人物列表 |
| main_characters | list[str] | 主要角色列表 |
| core_cast | list[str] | 核心演员列表 |
| theme_color | str | 小说主题色，十六进制格式，如 `#4A90D9` |

**当前合同说明**：
- 当前 `/diagnosis` 不再把 `null` 或半成品对象当作正常成功结果。
- 当焦点合同缺失或失效时，会返回 `rerun_required=true` 的对象，提示调用方重跑分析。

---

#### GET /api/novels/{novel_id}/foreshadowing-threads

获取 setup thread 台账数据。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/foreshadowing-threads?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "setup_id": "setup-001",
    "first_chunk_id": 3,
    "last_chunk_id": 18,
    "anchor_chunk_ids": [3, 8, 18],
    "setup_summary": "铜铃异响反复指向山门旧案",
    "setup_kind": "异常物件",
    "expected_payoff_family": "真相揭露",
    "payoff_likelihood": "high",
    "strength": "high",
    "status": "reinforced",
    "active": true,
    "latest_reason": "第18块再次强化铜铃与旧案的隐含关联",
    "latest_why_unresolved_now": "真相尚未揭露"
  }
]
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| setup_id | str | setup thread 唯一 ID |
| first_chunk_id | int | 首次出现的 chunk |
| last_chunk_id | int | 最近一次命中的 chunk |
| anchor_chunk_ids | list[int] | 支撑该 thread 的锚点 chunk 列表 |
| setup_summary | str | setup 摘要 |
| setup_kind | str | setup 类型 |
| expected_payoff_family | str | 预期回收家族 |
| payoff_likelihood | str | 回收预期强度（如 `high/medium/low`） |
| strength | str | 当前 thread 强度 |
| status | str | thread 语义状态（如 `open/reinforced/likely_paid_off`） |
| active | bool | 是否仍在 active setup pool 中；出池后为 `false` |
| latest_reason | str | 最近一次命中的说明 |
| latest_why_unresolved_now | str | 当前仍未完全回收的原因 |

---

#### GET /api/novels/{novel_id}/graph

获取知识图谱快照。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**响应示例**:
```json
{
  "nodes": [
    {
      "entity_id": "1",
      "name": "贺伯安",
      "entity_type": "character",
      "first_seen_chunk": 1,
      "last_seen_chunk": 18,
      "role": "主体",
      "status": "active"
    }
  ],
  "edges": [
    {
      "source": "1",
      "target": "2",
      "relation_type": "盟友",
      "weight": 3,
      "from_name": "贺伯安",
      "to_name": "柳婉儿",
      "change_count": 2,
      "tension_index": 0.38,
      "is_active": true
    }
  ],
  "events": [
    {
      "relation_event_id": 11,
      "chunk_id": 18,
      "from_entity_id": 1,
      "to_entity_id": 2,
      "from_name": "贺伯安",
      "to_name": "柳婉儿",
      "relation_type": "盟友",
      "change_type": "强化",
      "evidence": "二人再次结盟",
      "confidence": 0.88,
      "source_relation_row_id": 99,
      "directionality": "directed"
    }
  ],
  "events_page": {
    "limit": 200,
    "returned_count": 1,
    "total": 1,
    "has_more": false,
    "next_cursor": null
  },
  "summary": {
    "node_count": 2,
    "edge_count": 1,
    "density": 0.5,
    "core_characters": ["贺伯安", "柳婉儿"],
    "key_relations": [
      {
        "from": "贺伯安",
        "to": "柳婉儿",
        "type": "盟友",
        "support_count": 3
      }
    ]
  },
  "quality": {
    "conflict_count": 0,
    "low_confidence_count": 0,
    "conflicts": [],
    "low_confidence_samples": []
  }
}
```

---

#### GET /api/novels/{novel_id}/graph/events

获取图谱关系事件的分页结果。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |
| events_cursor | str | 否 | 分页游标 |
| events_limit | int | 否 | 返回数量上限，范围 1-200 |

**响应示例**:
```json
{
  "events": [
    {
      "relation_event_id": 11,
      "chunk_id": 18,
      "from_entity_id": 1,
      "to_entity_id": 2,
      "from_name": "贺伯安",
      "to_name": "柳婉儿",
      "relation_type": "盟友",
      "change_type": "强化",
      "evidence": "二人再次结盟",
      "confidence": 0.88,
      "source_relation_row_id": 99,
      "directionality": "directed"
    }
  ],
  "page_info": {
    "limit": 50,
    "returned_count": 1,
    "total": 1,
    "has_more": false,
    "next_cursor": null
  }
}
```

---

### 3.4 叙事时间轴

#### GET /api/novels/{novel_id}/timeline

获取叙事时间轴数据。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |
| include_curve | bool | 否 | 是否包含张力曲线数据（默认 false） |

**响应示例**:
```json
{
  "meta": {
    "novel_id": "novel_001",
    "novel_name": "重明传",
    "total_chunks": 500
  },
  "phases": [
    {"name": "引入期", "start": 1, "end": 75, "ratio": 0.15},
    {"name": "发展期", "start": 76, "end": 350, "ratio": 0.55},
    {"name": "高潮期", "start": 351, "end": 420, "ratio": 0.14},
    {"name": "收束期", "start": 421, "end": 500, "ratio": 0.16}
  ],
  "composite_nodes": [
    {
      "node_id": "plot:18:0",
      "anchor_chunk_id": 18,
      "start_chunk_id": 18,
      "end_chunk_id": 18,
      "progress": 0.0,
      "start_progress": 0.0,
      "end_progress": 0.0,
      "importance_score": 6.0,
      "level": 1,
      "summary": "铜铃异响再次强化旧案悬念",
      "characters": ["贺伯安", "柳婉儿"],
      "phase_name": "发展期",
      "node_type": "plot",
      "node_subtypes": ["pivot"],
      "representative_node_id": "plot:18:0",
      "child_node_ids": ["plot:18:0", "relation:18:0"]
    }
  ],
  "atomic_nodes": [
    {
      "node_id": "plot:18:0",
      "anchor_chunk_id": 18,
      "progress": 0.0,
      "importance_score": 6.0,
      "level": 1,
      "summary": "铜铃异响再次强化旧案悬念",
      "characters": ["贺伯安", "柳婉儿"],
      "phase_name": "发展期",
      "node_type": "plot",
      "node_subtype": "pivot",
      "score_breakdown": {"tension": 2.5, "relation": 1.0},
      "plot_flags": {
        "is_pivot": true,
        "is_cliffhanger": false,
        "tension_percentile": 86
      },
      "relation_events": null,
      "lifecycle_events": null
    }
  ],
  "tension_curve": null
}
```

**当前合同说明**：
- 后端始终返回 `composite_nodes + atomic_nodes` 双层结构。
- `max_level` 已降为前端本地筛选状态，不再作为后端请求参数。

---

### 3.6 聚合指标

#### GET /api/novels/{novel_id}/metrics/narrative-structure

获取叙事结构聚合指标。

说明：接口响应形状保持不变，`act1_ratio / act2_ratio / act3_ratio` 仍表示三幕比例；
当前实现已从“单峰 + 峰前最低谷”升级为“主高潮区 + 结构切分点”，
用于降低多峰长篇里第一幕被异常拖长的风险。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/metrics/narrative-structure?task_id=a1b2c3d4
```

**响应示例**:
```json
{
  "act1_ratio": 0.6,
  "act2_ratio": 0.38,
  "act3_ratio": 0.02,
  "climax_spacing": 0.0,
  "middle_collapse_index": 1.76,
  "event_density": {
    "冲突": 0.10,
    "转折": 0.29,
    "铺垫": 0.61
  },
  "cliffhanger_rate": 0.29,
  "climax_count": 3,
  "climax_positions": [0.25, 0.65, 0.85],
  "climax_heights": [0.8, 0.9, 0.95],
  "peak_escalation": "rising",
  "dominant_climax_pos": 0.85
}
```

---

#### GET /api/novels/{novel_id}/metrics/emotion-stats

获取情感统计聚合指标。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/metrics/emotion-stats?task_id=a1b2c3d4
```

**响应示例**:
```json
{
  "pos_neg_ratio": 0.49,
  "positive_ratio": 0.21,
  "negative_ratio": 0.40,
  "neutral_ratio": 0.38,
  "recovery_speed": 3.5,
  "pivot_moment_density": 0.38,
  "lexical_emotion_trend": "rising"
}
```

**lexical_emotion_trend 可选值**（词表情感趋势）:
- `rising`: 情感上升（后段平均值 - 前段平均值 > 0.002）
- `falling`: 情感下降（后段平均值 - 前段平均值 < -0.002）
- `stable`: 情感稳定（|后段 - 前段| <= 0.002 且标准差 < 0.003）
- `volatile`: 情感波动（标准差 >= 0.003）

---

#### GET /api/novels/{novel_id}/metrics/character-stats

获取人物统计聚合指标。

> 说明：`network_density` 字段名保持兼容，但当前口径表示**关系集中度**（degree centralization），
> 基于图谱当前参与者与当前有效关系计算，不再表示旧版 `networkx.density(G)` 图论密度。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/metrics/character-stats?task_id=a1b2c3d4
```

**响应示例**:
```json
{
  "network_density": 0.25,
  "degree_centrality": {
    "贺重明": 0.85,
    "侯飞白": 0.72,
    "林立果": 0.65
  },
  "greimas_coverage": 0.73,
  "function_coverage_distribution": {
    "主体": 0.47,
    "反对者": 0.08,
    "帮助者": 0.09,
    "发送者": 0.09
  },
  "antagonist_strength_gap": 1.72,
  "relation_change_freq": 2.21
}
```

---

#### GET /api/novels/{novel_id}/metrics/style-stats

获取风格统计聚合指标。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/metrics/style-stats?task_id=a1b2c3d4
```

**响应示例**:
```json
{
  "tone_distribution": {
    "强硬": 0.11,
    "温和": 0.25,
    "恐惧": 0.14
  },
  "vocab_breadth": 0.94,
  "avg_sent_len": 18.6,
  "avg_word_len": 8.64,
  "sent_len_std": 21.42,
  "dialogue_ratio": 0.31,
  "function_word_vector": {
    "的": 0.035,
    "了": 0.028,
    "是": 0.022,
    "在": 0.018
  },
  "category_density": {
    "combat": 0.012,
    "body": 0.008,
    "relation": 0.015,
    "faction": 0.010,
    "command": 0.006,
    "action": 0.025,
    "psychology": 0.018,
    "measure": 0.009,
    "emotion": 0.014,
    "color": 0.007
  }
}
```

**新增字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| function_word_vector | Dict[str, float] | 高频虚词分布，各虚词相对频率 |
| category_density | Dict[str, float] | 语义类别词密度（10类） |

---

#### 文化指标说明（研究保留，当前未开放 public route）

当前仓库内部 aggregate 仍会计算以下文化指标，但它们不再通过单独的 `/metrics/culture-stats` 公开接口返回：

| 字段 | 类型 | 说明 |
|------|------|------|
| idiom_density | float | 成语密度 |
| classical_sentence_ratio | float | 古典句式比例 |
| imagery_density | float | 整书级古典意象字符密度（按全文字符占比统计，不受 chunk 切分影响） |

---

## 五、错误响应

大多数中间件/异常处理器返回以下统一格式：

```json
{
  "detail": "错误描述信息",
  "error_type": "ErrorTypeName",
  "status_code": 400
}
```

部分 route-level 业务冲突（当前主要是 diagnosis 焦点合同失效）会返回 `409`，其 `detail` 为结构化对象：

```json
{
  "detail": {
    "code": "diagnosis_rerun_required",
    "message": "当前任务的 diagnosis 焦点合同已失效，请重新分析。",
    "reason": "focus_contract_incomplete"
  }
}
```

### 常见错误类型

| 错误类型 | 状态码 | 说明 |
|----------|--------|------|
| `NovelNotFoundError` | 404 | 小说不存在 |
| `AnalysisNotCompleteError` | 400 | 分析未完成 |
| `InvalidFileError` | 400 | 上传文件类型不合法 |
| `FileStorageError` | 500 | 文件保存失败 |
| `GraphReadinessError` | 409 | 图谱投影未就绪，当前结果不可读 |
| `InternalServerError` | 500 | 未预期的内部错误 |

---

## 六、结果文件存储

调用 `GET /api/novels/{novel_id}/results` 接口后，结果文件存储在：

```
outputs/
├── a1b2c3d4.json
├── b2c3d4e5.json
└── ...
```

### 文件内容结构

```json
{
  "task_id": "a1b2c3d4",
  "novel_id": "novel_123",
  "novel_name": "重明传",
  "generated_at": "2024-03-08T10:30:00",
  "total_chunks": 42,
  "chunk_curves": [...],
  "characters": [...],
  "topics": [...],
  "diagnosis": {...},
  "chunk_styles": [...],
  "chunk_annotations": [...],
  "foreshadowing_threads": [...],
  "character_relations": [...],
  "hierarchical_relations": [...],
  "global_stats": {...},
  "aggregate_metrics": {
    "narrative_structure": {...},
    "emotion_stats": {...},
    "character_stats": {...},
    "style_stats": {...}
  },
  "token_usage_stats": {...},
  "graph_summary": {...},
  "graph_quality_report": {...},
  "timeline": {...}
}
```

其中与文化相关的 chunk 级字段位于 `chunk_styles` 中，其单项结构可包含：

```json
{
  "chunk_id": 0,
  "imagery_lexicon_density": 0.18
}
```

- `imagery_lexicon_density`：chunk 级意象词表命中密度
- 文化指标不再作为 public `aggregate_metrics` 子组单独暴露

---

## 七、使用示例

### cURL 示例

```bash
# 上传小说
curl -X POST http://localhost:8000/api/novels/upload -F "file=@小说.txt"

# 创建并启动新任务
curl -X POST http://localhost:8000/api/novels/{novel_id}/tasks

# 重新分析（创建新版本）
curl -X POST http://localhost:8000/api/novels/{novel_id}/reanalyze \
  -H "Content-Type: application/json" \
  -d '{"label": "修正版", "num_topics": 30}'

# 继续指定任务
curl -X POST http://localhost:8000/api/novels/{novel_id}/tasks/{task_id}/resume

# 查询单任务状态（推荐）
curl "http://localhost:8000/api/novels/{novel_id}/tasks/{task_id}/status"

# 获取所有分析任务
curl http://localhost:8000/api/novels/{novel_id}/tasks

# 删除特定分析任务
curl -X DELETE http://localhost:8000/api/novels/{novel_id}/tasks/{task_id}

# 导出完整结果（必须指定 task_id）
curl "http://localhost:8000/api/novels/{novel_id}/results?task_id={task_id}"

# 获取分块曲线（情绪 + 节奏）
curl "http://localhost:8000/api/novels/{novel_id}/chunk-curves?task_id={task_id}"

# 获取图谱事件分页
curl "http://localhost:8000/api/novels/{novel_id}/graph/events?task_id={task_id}&events_limit=50"

# 获取叙事时间轴
curl "http://localhost:8000/api/novels/{novel_id}/timeline?task_id={task_id}"
```

### Python 示例

```python
import requests

BASE_URL = "http://localhost:8000/api"

# 上传小说
with open("小说.txt", "rb") as f:
    response = requests.post(f"{BASE_URL}/novels/upload", files={"file": f})
    novel_id = response.json()["novel_id"]

# 创建并启动新任务
response = requests.post(f"{BASE_URL}/novels/{novel_id}/tasks")
task_id = response.json()["task_id"]
print(f"分析任务ID: {task_id}")

# 重新分析（创建新版本）
response = requests.post(
    f"{BASE_URL}/novels/{novel_id}/reanalyze",
    json={"label": "修正版", "num_topics": 30}
)
task_id = response.json()["task_id"]
print(f"新分析任务ID: {task_id}")

# 继续指定任务
requests.post(f"{BASE_URL}/novels/{novel_id}/tasks/{task_id}/resume")

# 查询状态（推荐入口）
status = requests.get(
    f"{BASE_URL}/novels/{novel_id}/tasks/{task_id}/status"
).json()
print(f"进度: {status['progress']}%")

# 获取所有分析任务
tasks = requests.get(f"{BASE_URL}/novels/{novel_id}/tasks").json()
for t in tasks["tasks"]:
    print(f"任务: {t['task_id']}, 状态: {t['status']}")

# 删除特定分析任务
requests.delete(f"{BASE_URL}/novels/{novel_id}/tasks/{task_id}")

# 导出结果（必须指定 task_id）
result = requests.get(
    f"{BASE_URL}/novels/{novel_id}/results",
    params={"task_id": task_id}
).json()
print(f"文件路径: {result['file_path']}")

# 获取分块曲线（情绪 + 节奏）
chunk_curves = requests.get(
    f"{BASE_URL}/novels/{novel_id}/chunk-curves",
    params={"task_id": task_id}
).json()

# 获取图谱事件分页
graph_events = requests.get(
    f"{BASE_URL}/novels/{novel_id}/graph/events",
    params={"task_id": task_id, "events_limit": 50}
).json()

# 获取叙事时间轴
timeline = requests.get(
    f"{BASE_URL}/novels/{novel_id}/timeline",
    params={"task_id": task_id, "include_curve": "true"}
).json()
```
