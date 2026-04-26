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
| POST | `/api/novels/{novel_id}/analyze` | 启动分析任务 |
| POST | `/api/novels/{novel_id}/reanalyze` | 重新分析 |
| GET | `/api/novels/{novel_id}/status` | 查询分析进度 |
| GET | `/api/novels/{novel_id}/tasks` | 获取所有分析任务 |
| DELETE | `/api/novels/{novel_id}/tasks/{task_id}` | 删除特定分析任务 |
| POST | `/api/novels/{novel_id}/tasks/batch-delete` | 批量删除分析任务 |
| POST | `/api/novels/{novel_id}/tasks/{task_id}/cancel` | 取消正在运行的分析任务 |

### ID 体系说明

系统使用两种 ID：

| ID 类型 | 格式 | 示例 | 用途 | 使用场景 |
|---------|------|------|------|----------|
| novel_id | UUID前8位 | `10960c77` | 小说唯一标识 | API内外通用 |
| task_id | UUID前8位 | `a1b2c3d4` | 分析任务标识（外部使用） | 仅API层使用 |
| run_id | 完整UUID(36位) | `a1b2c3d4-1a72-4444-a772-2ddc64334cd2` | 分析运行标识（内部使用） | 仅内部实现使用 |

**ID映射关系：**
- `task_id` 是 `run_id` 的前8位字符
- 外部API只暴露 `task_id`，完全隐藏 `run_id`
- 内部实现（Repository、Workflow）只使用 `run_id`
- ID转换由API层和Service层负责

**数据隔离规则：**
- 数据通过 `run_id` 字段在 PostgreSQL 数据库中隔离
- 日志目录：`logs/{run_id}/`（内部使用完整run_id）
- 结果文件：`outputs/{task_id}.json`（外部使用task_id）

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
| GET | `/api/novels/{novel_id}/metrics/culture-stats?task_id={task_id}` | 获取文化统计指标 |

### 2.6 系统接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |

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
  "novel_id": "novel_20240308_abc123",
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
[
  {
    "novel_id": "novel_20240308_abc123",
    "filename": "小说名.txt",
    "status": "completed",
    "created_at": "2024-03-08T10:00:00"
  }
]
```

---

#### DELETE /api/novels/{novel_id}

删除指定小说及其分析数据。

**响应示例**:
```json
{
  "message": "小说已删除"
}
```

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

#### POST /api/novels/{novel_id}/analyze

启动或继续分析任务。

**请求体** (JSON):
```json
{
  "task_id": null
}
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| task_id | string | null | 指定任务ID，用于继续失败的任务或多任务时必须提供 |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4",
  "status": "pending",
  "message": "分析任务已启动"
}
```

**多任务判断逻辑**：

当存在多个任务时，系统按以下规则自动判断：

| 任务情况 | 行为 |
|---------|------|
| 无任务 | 创建新任务 |
| 单个任务（pending/running） | 返回该任务 |
| 单个任务（failed） | 重新运行该任务 |
| 1个running + 其他failed | 返回running任务 |
| 多个completed | ❌ 报错，要求指定task_id |
| 多个running | ❌ 报错，要求指定task_id |
| 多个failed | ❌ 报错，要求指定task_id |
| 多个pending | ❌ 报错，要求指定task_id |
| 多个running + 多个failed | ❌ 报错，要求指定task_id |

**断点续传功能**：

系统会检查各阶段数据完整性，自动从中断点继续：

| 中断场景 | 继续点 |
|---------|--------|
| preprocess未完成 | 从preprocess开始 |
| annotate未完成（annotations < chunks） | 从annotate继续（内部支持resume） |
| aggregate未完成 | 从aggregate开始 |
| topic_model未完成 | 从topic_model开始 |
| diagnose未完成 | 从diagnose开始 |
| 所有阶段完成 | 不做操作，直接返回 |

**完整性检查标准**：
- `preprocess`：chunks表有数据
- `annotate`：annotations数量 ≥ chunks数量
- `aggregate`：emotion_curve数量 ≥ chunks数量 且 rhythm_curve数量 ≥ chunks数量
- `topic_model`：chunk_topics表有数据
- `diagnose`：cloud_analysis表有数据

**说明**：
- 每次分析生成唯一的 `task_id`（8位短UUID）和对应的 `run_id`（36位完整UUID）
- `task_id` 是 `run_id` 的前8位字符
- 外部API使用 `task_id`，内部实现使用 `run_id`
- 数据通过 `run_id` 字段在 PostgreSQL 数据库中隔离
- 日志目录为 `logs/{run_id}/`（内部使用）

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
  "num_topics": 25,
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
| num_topics | int | 25 | 主题数量 |
| label | string | null | 分析版本标签 |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "b2c3d4e5"
}
```

**说明**：
- 每次重新分析生成新的 `task_id`（8位短UUID）和对应的 `run_id`（36位完整UUID）
- `task_id` 是 `run_id` 的前8位字符
- 新的分析结果通过 `run_id` 在数据库中隔离
- 与analyze不同，reanalyze总是会创建新任务

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
      "status": "completed"
    },
    {
      "task_id": "b2c3d4e5",
      "novel_id": "10960c77",
      "status": "running"
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
- 取消后数据库中已有部分数据（如部分 chunks/annotations），后续可通过 `POST /analyze` 利用断点续传功能继续
- 任务不在内存中时（服务重启后），直接更新数据库状态为 `cancelled`

---

#### GET /api/novels/{novel_id}/status

查询分析任务进度。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 否 | 分析任务ID，多任务时必须提供 |

**多任务判断逻辑**：
与analyze接口相同，当存在多个任务时：
- 单个任务：返回该任务状态
- 1个running + 其他failed：返回running任务状态
- 多个completed/running/failed/pending：报错，要求指定task_id

**响应示例（成功）**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4",
  "status": "running",
  "progress": 45.5,
  "stage": "annotate",
  "error": null,
  "started_at": "2024-03-08T10:00:00",
  "completed_at": null
}
```

**响应示例（多任务报错）**:
```json
{
  "detail": "存在多个已完成任务(2个)，请指定task_id"
}
```

**状态值**:
- `pending`: 等待执行
- `running`: 执行中
- `cancelling`: 正在取消（等待当前阶段完成后停止）
- `cancelled`: 已取消
- `completed`: 已完成
- `failed`: 执行失败

---

### 3.3 结果查询

#### GET /api/novels/{novel_id}/results

📋 **复盘与测试专用接口**

将完整分析数据写入 `outputs/` 目录下的JSON文件，用于：
- 项目复盘与结果审查
- 测试验证与数据对比
- 分析结果归档备份

**前置条件**：
- 任务必须已完成（status = "completed"）
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
  "missing_fields": []
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
| 400 | 任务未完成（pending/running/failed） |
| 404 | 任务不存在 |

---

#### GET /api/novels/{novel_id}/emotion-curve

获取情感曲线数据。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/emotion-curve?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "chunk_id": 0,
    "pos_density": 0.0,
    "neg_density": 0.002638,
    "net_density": -0.002638,
    "smoothed_density": -0.002638
  }
]
```

---

#### GET /api/novels/{novel_id}/rhythm-curve

获取节奏曲线数据。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/rhythm-curve?task_id=a1b2c3d4
```

**响应示例**:
```json
[
  {
    "chunk_id": 0,
    "tension_proxy": 5.578,
    "tension_composite": 0.21
  }
]
```

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
    "dominant_role_function": "protagonist",
    "role_function_distribution": {
      "protagonist": 30,
      "helper": 5
    },
    "dominant_role_ratio": 0.86,
    "protagonist_score": 0.95,
    "is_protagonist": true,
    "avg_emotion_score": -0.83
  }
]
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| name | str | 角色名称 |
| appearance_count | int | 出场次数 |
| dominant_role_function | str | 主导角色功能（如 protagonist/antagonist/helper 等） |
| role_function_distribution | dict | 角色功能分布统计 |
| dominant_role_ratio | float | 主导角色占比 |
| protagonist_score | float | 主角得分（综合评估） |
| is_protagonist | bool | 是否为主角 |
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

**响应示例**:
```json
{
  "foreshadow_expectation": 0.6,
  "foreshadow_rate": 0.6,
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
  "protagonist": "主角名",
  "main_characters": ["主角A", "主角B", "配角C"],
  "core_cast": ["主角A", "主角B"],
  "theme_color": "#4A90D9"
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| foreshadow_expectation | float | 伏笔回收预期（0-1，基于 setup thread ledger 加权估算的近似值） |
| foreshadow_rate | float | 兼容字段：新 run 下一般与 foreshadow_expectation 同值；旧 run 若无 setup ledger，则回退为历史 diagnosis 值 |
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
| protagonist | str | 主角名称 |
| main_characters | list[str] | 主要角色列表 |
| core_cast | list[str] | 核心演员列表 |
| theme_color | str | 小说主题色，十六进制格式，如 `#4A90D9` |

**兼容说明**:
- 新 run 且 setup ledger 已存在时，`foreshadow_expectation` 是正式展示值，`foreshadow_rate` 仅作兼容镜像。
- 旧 run 或尚未生成 setup ledger 时，`foreshadow_expectation` 可能为 `null`，而 `foreshadow_rate` 会回退为历史 diagnosis 存储值。

**实体关系数据**:

分析结果中包含实体层级关系数据，存储在 `entity_relations` 表中：

| 字段 | 类型 | 说明 |
|------|------|------|
| from_entity | int | 源实体ID |
| to_entity | int | 目标实体ID |
| rel_type | str | 关系类型：belongs_to/member_of/leader_of/affiliated_with |
| rel_category | str | 关系类别：hierarchical（层级关系）|

**实体类型**：

| 类型 | 说明 | 示例 |
|------|------|------|
| character | 具体人物角色 | 伯安、贺重明 |
| group | 群体/队伍统称 | 赤甲卫、禁军 |
| organization | 组织/门派/家族 | 贺家、玄天道宗 |

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
    {"id": "节点1", "type": "character"},
    {"id": "节点2", "type": "organization"}
  ],
  "edges": [
    {"source": "节点1", "target": "节点2", "relation": "belongs_to"}
  ]
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
| max_level | int | 否 | 显示重要性级别 ≤ 此值的节点（默认 3，范围 1-3） |

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
  "nodes": [
    {
      "chunk_id": 1,
      "progress": 0.0,
      "importance_score": 6.0,
      "level": 1,
      "event": "贺重明在宗门试炼中展露天赋",
      "characters": ["贺重明", "长老"],
      "is_pivot": false,
      "is_cliffhanger": false,
      "tension_percentile": 45,
      "node_type": "character_entry",
      "relation_changes": null,
      "character_entries": ["贺重明"],
      "character_exits": null
    }
  ],
  "tension_curve": null
}
```

**max_level 说明**:
- 1: 仅显示重要节点
- 2: 显示重要 + 较重要节点
- 3: 显示全部节点

---

### 3.6 聚合指标

#### GET /api/novels/{novel_id}/metrics/narrative-structure

获取叙事结构聚合指标。

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
    "高潮": 0.02,
    "冲突": 0.10,
    "转折": 0.29,
    "铺垫": 0.33,
    "日常": 0.26
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

**lexical_emotion_trend 可选值**（词表情感趋势）:
- `rising`: 情感上升（后段平均值 - 前段平均值 > 0.002）
- `falling`: 情感下降（后段平均值 - 前段平均值 < -0.002）
- `stable`: 情感稳定（|后段 - 前段| <= 0.002 且标准差 < 0.003）
- `volatile`: 情感波动（标准差 >= 0.003）

---

#### GET /api/novels/{novel_id}/metrics/character-stats

获取人物统计聚合指标。

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
  "network_density": 0.32,
  "protagonist_betweenness": 0.23,
  "degree_centrality": {
    "贺重明": 0.85,
    "侯飞白": 0.72,
    "林立果": 0.65
  },
  "greimas_coverage": 0.73,
  "function_coverage_distribution": {
    "protagonist": 0.47,
    "antagonist": 0.08,
    "helper": 0.09,
    "mentor": 0.09
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
  "avg_word_len": 8.64,
  "sent_len_std": 21.42,
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

#### GET /api/novels/{novel_id}/metrics/culture-stats

获取文化统计聚合指标。

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | str | 是 | 分析任务ID |

**请求示例**:
```
GET /api/novels/10960c77/metrics/culture-stats?task_id=a1b2c3d4
```

**响应示例**:
```json
{
  "idiom_density": 0.69,
  "classical_sentence_ratio": 0.0,
  "imagery_density": 0.012
}
```

**字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| idiom_density | float | 成语密度 |
| classical_sentence_ratio | float | 文言句式比例 |
| imagery_density | float | 整书级古典意象字符密度（按全文字符占比统计，不受 chunk 切分影响） |

---

## 五、错误响应

所有错误响应遵循统一格式：

```json
{
  "detail": "错误描述信息",
  "error_type": "ErrorTypeName",
  "status_code": 400
}
```

### 错误类型

| 错误类型 | 状态码 | 说明 |
|----------|--------|------|
| `NovelNotFoundError` | 404 | 小说不存在 |
| `AnalysisNotCompleteError` | 400 | 分析未完成 |
| `FileUploadError` | 400 | 文件上传失败 |
| `AnalysisError` | 500 | 分析过程出错 |

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
    "style_stats": {...},
    "culture_stats": {...}
  },
  "token_usage_stats": {...},
  "graph_summary": {...},
  "graph_quality_report": {...},
  "timeline": {...}
}
```

其中 `chunk_cultures` 的单项结构为：

```json
{
  "chunk_id": 0,
  "imagery_lexicon_density": 0.18
}
```

- `imagery_lexicon_density`：chunk 级意象词表命中密度
- `aggregate_metrics.culture_stats.imagery_density`：整书级古典意象字符密度

---

## 七、使用示例

### cURL 示例

```bash
# 上传小说
curl -X POST http://localhost:8000/api/novels/upload -F "file=@小说.txt"

# 启动分析
curl -X POST http://localhost:8000/api/novels/{novel_id}/analyze

# 重新分析（创建新版本）
curl -X POST http://localhost:8000/api/novels/{novel_id}/reanalyze \
  -H "Content-Type: application/json" \
  -d '{"label": "修正版", "num_topics": 30}'

# 查询状态
curl "http://localhost:8000/api/novels/{novel_id}/status?task_id={task_id}"

# 获取所有分析任务
curl http://localhost:8000/api/novels/{novel_id}/tasks

# 删除特定分析任务
curl -X DELETE http://localhost:8000/api/novels/{novel_id}/tasks/{task_id}

# 导出完整结果（必须指定 task_id）
curl "http://localhost:8000/api/novels/{novel_id}/results?task_id={task_id}"

# 获取情感曲线
curl "http://localhost:8000/api/novels/{novel_id}/emotion-curve?task_id={task_id}"

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

# 启动分析
response = requests.post(f"{BASE_URL}/novels/{novel_id}/analyze")
task_id = response.json()["task_id"]
print(f"分析任务ID: {task_id}")

# 重新分析（创建新版本）
response = requests.post(
    f"{BASE_URL}/novels/{novel_id}/reanalyze",
    json={"label": "修正版", "num_topics": 30}
)
task_id = response.json()["task_id"]
print(f"新分析任务ID: {task_id}")

# 查询状态
status = requests.get(
    f"{BASE_URL}/novels/{novel_id}/status",
    params={"task_id": task_id}
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

# 获取情感曲线
emotion_curve = requests.get(
    f"{BASE_URL}/novels/{novel_id}/emotion-curve",
    params={"task_id": task_id}
).json()

# 获取叙事时间轴
timeline = requests.get(
    f"{BASE_URL}/novels/{novel_id}/timeline",
    params={"task_id": task_id, "include_curve": "true"}
).json()
```
