# 中文网络小说量化分析 API 文档

## 一、API概述

本项目提供 RESTful API 服务，基于 FastAPI 框架实现。API 服务提供小说上传、分析任务管理、结果查询等功能。

### 服务启动

```bash
# 方式一：使用模块启动（推荐，带端口占用检测）
python -m src.api.main --host 0.0.0.0 --port 8000

# 方式二：使用启动脚本（带端口占用检测）
python scripts/run_api.py --port 8000

# 开发模式（支持热重载）
python -m src.api.main --reload
# 或
python scripts/run_api.py --reload

# 指定其他端口
python -m src.api.main --port 8001
```

**启动参数说明**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| --host | 0.0.0.0 | 监听地址 |
| --port | 8000 | 监听端口 |
| --reload | False | 启用开发模式自动重载 |

**端口占用检测**: 使用 `python -m src.api.main` 或 `python scripts/run_api.py` 启动时，会自动检测端口是否被占用，如果被占用会显示友好的错误提示并退出。

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
| DELETE | `/api/novels/{id}` | 删除小说 |

### 2.2 分析任务接口

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/novels/{id}/analyze` | 启动分析任务 |
| POST | `/api/novels/{id}/reanalyze` | 重新分析 |
| GET | `/api/novels/{id}/status` | 查询分析进度 |
| GET | `/api/novels/{id}/tasks` | 获取所有分析任务 |
| DELETE | `/api/novels/{id}/tasks/{task_id}` | 删除特定分析任务 |

### ID 体系说明

系统使用两种 ID：

| ID 类型 | 格式 | 示例 | 用途 |
|---------|------|------|------|
| novel_id | UUID前8位 | `10960c77` | 小说唯一标识 |
| run_id | UUID前8位 | `a1b2c3d4` | 分析任务标识 |

**数据隔离规则：**
- 数据通过 `run_id` 字段在 PostgreSQL 数据库中隔离
- 日志目录：`logs/{run_id}/`
- 结果文件：`outputs/{run_id}.json`

### 2.3 结果查询接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/novels/{id}/results?task_id={task_id}` | 导出完整结果（复盘/测试用） |
| GET | `/api/novels/{id}/emotion-curve?task_id={task_id}` | 获取情感曲线 |
| GET | `/api/novels/{id}/rhythm-curve?task_id={task_id}` | 获取节奏曲线 |
| GET | `/api/novels/{id}/characters?task_id={task_id}` | 获取人物统计 |
| GET | `/api/novels/{id}/topics?task_id={task_id}` | 获取主题分布 |
| GET | `/api/novels/{id}/diagnosis?task_id={task_id}` | 获取云端诊断 |

**注意**：所有结果查询接口都需要提供 `task_id` 参数来指定要查询的分析任务。

### 2.4 聚合指标接口

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/novels/{id}/metrics/narrative-structure?task_id={task_id}` | 获取叙事结构指标 |
| GET | `/api/novels/{id}/metrics/emotion-stats?task_id={task_id}` | 获取情感统计指标 |
| GET | `/api/novels/{id}/metrics/character-stats?task_id={task_id}` | 获取人物统计指标 |
| GET | `/api/novels/{id}/metrics/style-stats?task_id={task_id}` | 获取风格统计指标 |
| GET | `/api/novels/{id}/metrics/culture-stats?task_id={task_id}` | 获取文化统计指标 |

### 2.5 系统接口

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

#### DELETE /api/novels/{id}

删除指定小说及其分析数据。

**响应示例**:
```json
{
  "message": "小说已删除"
}
```

---

### 3.2 分析任务

#### POST /api/novels/{id}/analyze

启动分析任务。

**请求体** (JSON):
```json
{
  "task_id": null,
  "skip_preprocess": false,
  "skip_annotate": false,
  "skip_aggregate": false,
  "skip_topic_model": false,
  "skip_diagnose": false,
  "num_topics": 25,
  "max_chars": 2000,
  "overlap": 200
}
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| task_id | string | null | 指定任务ID，多任务时必须提供 |
| skip_preprocess | bool | false | 跳过预处理阶段 |
| skip_annotate | bool | false | 跳过标注阶段 |
| skip_aggregate | bool | false | 跳过聚合阶段 |
| skip_topic_model | bool | false | 跳过主题建模 |
| skip_diagnose | bool | false | 跳过云端诊断 |
| num_topics | int | 25 | 主题数量 |
| max_chars | int | 2000 | 每个chunk最大字符数 |
| overlap | int | 200 | 相邻chunk重叠字符数 |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4"
}
```

**多任务判断逻辑**：

当存在多个任务时，系统按以下规则自动判断：

| 任务情况 | 行为 |
|---------|------|
| 无任务 | 创建新任务 |
| 单个任务（任何状态） | 返回该任务 |
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
- 每次分析生成唯一的 `task_id`（即 `run_id`）
- 数据通过 `run_id` 字段在 PostgreSQL 数据库中隔离
- 日志目录为 `logs/{run_id}/`

---

#### POST /api/novels/{id}/reanalyze

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
  "label": "v2",
  "use_semantic_chunking": false
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
| use_semantic_chunking | bool | false | 是否启用语义分块 |

**响应示例**:
```json
{
  "novel_id": "10960c77",
  "task_id": "b2c3d4e5"
}
```

**说明**：
- 每次重新分析生成新的 `task_id`（即 `run_id`）
- 新的分析结果通过 `run_id` 在数据库中隔离
- 与analyze不同，reanalyze总是会创建新任务

---

#### GET /api/novels/{id}/tasks

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

#### DELETE /api/novels/{id}/tasks/{task_id}

删除特定分析任务。

**响应示例**:
```json
{
  "message": "任务删除成功",
  "novel_id": "10960c77",
  "task_id": "a1b2c3d4"
}
```

**注意**: 删除任务会删除数据库中该 `run_id` 对应的所有数据，此操作不可恢复。

---

#### GET /api/novels/{id}/status

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
- `completed`: 已完成
- `failed`: 执行失败

---

### 3.3 结果查询

#### GET /api/novels/{id}/results

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

#### GET /api/novels/{id}/emotion-curve

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

#### GET /api/novels/{id}/rhythm-curve

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

#### GET /api/novels/{id}/characters

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
    "role_function": "protagonist",
    "avg_emotion_score": -0.83
  }
]
```

---

#### GET /api/novels/{id}/topics

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

#### GET /api/novels/{id}/diagnosis

获取云端诊断结果。

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
  "foreshadow_rate": 0.6,
  "arc_scores": [8.0, 7.0, 6.0],
  "narrative_type": "寓言",
  "topic_labels": ["抗争", "宿命"],
  "diagnosis": "该叙事以寓言形式探索人类面对困境的成长历程...",
  "value_logic_type": "价值冲突",
  "value_logic_reason": "...",
  "power_stance_score": 3,
  "power_stance_reason": "...",
  "common_people_dignity": 4,
  "dignity_reason": "...",
  "cultural_depth_score": 4,
  "cultural_depth_reason": "传统文化词汇深度参与叙事，儒家伦理观念推动主角行为选择..."
}
```

**新增字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| cultural_depth_score | int | 文化内涵真实性评分（0-5分），判断传统文化词汇是核心叙事逻辑还是背景装饰 |
| cultural_depth_reason | str | 评分说明，引用具体段落或情节 |

---

### 3.4 聚合指标

#### GET /api/novels/{id}/metrics/narrative-structure

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
  "cliffhanger_rate": 0.29
}
```

---

#### GET /api/novels/{id}/metrics/emotion-stats

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
  "emotion_curve_type": "白手起家"
}
```

**emotion_curve_type 可选值**（规范六种原型）:
- `白手起家`: 情感从低谷逐渐上升
- `伊卡洛斯`: 情感先升后降
- `落坑爬出`: 情感先降后升
- `持续下降`: 情感持续走低
- `灰姑娘`: 情感先降后升再降
- `俄狄浦斯`: 情感先升后降再升

---

#### GET /api/novels/{id}/metrics/character-stats

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
  "max_degree_character": "贺重明",
  "max_degree_value": 0.85,
  "degree_centrality": {
    "贺重明": 0.85,
    "侯飞白": 0.72,
    "林立果": 0.65
  },
  "greimas_coverage": {
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

#### GET /api/novels/{id}/metrics/style-stats

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

#### GET /api/novels/{id}/metrics/culture-stats

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
  "confucian_density": 0.001,
  "taoist_density": 0.002,
  "buddhist_density": 0.001,
  "folk_density": 0.003,
  "allusion_density": 0.005,
  "idiom_density": 0.69,
  "classical_sentence_ratio": 0.0,
  "imagery_density": 0.012
}
```

**新增字段说明**:
| 字段 | 类型 | 说明 |
|------|------|------|
| imagery_density | float | 古典意象词密度（山水、月色、梅兰竹菊等） |

---

## 四、错误响应

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

## 五、结果文件存储

调用 `GET /api/novels/{id}/results` 接口后，结果文件存储在：

```
log/results/
├── novel_123_重明传.json
├── novel_456_人祖传.json
└── ...
```

### 文件内容结构

```json
{
  "novel_id": "novel_123",
  "novel_name": "重明传",
  "generated_at": "2024-03-08T10:30:00",
  "total_chunks": 42,
  "total_chars": 21451,
  "emotion_curve": [...],
  "rhythm_curve": [...],
  "characters": [...],
  "topics": [...],
  "diagnosis": {...},
  "chunk_styles": [...],
  "chunk_annotations": [...],
  "character_relations": [...],
  "global_stats": {...},
  "chunk_cultures": [...],
  "aggregate_metrics": {
    "narrative_structure": {...},
    "emotion_stats": {...},
    "character_stats": {...},
    "style_stats": {...},
    "culture_stats": {...}
  }
}
```

---

## 六、使用示例

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
curl http://localhost:8000/api/novels/{novel_id}/status

# 获取所有分析版本
curl http://localhost:8000/api/novels/{novel_id}/analyses

# 删除特定分析版本
curl -X DELETE http://localhost:8000/api/novels/{novel_id}/analyses/{analysis_id}

# 导出完整结果
curl http://localhost:8000/api/novels/{novel_id}/results

# 获取情感曲线
curl http://localhost:8000/api/novels/{novel_id}/emotion-curve
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
requests.post(f"{BASE_URL}/novels/{novel_id}/analyze")

# 重新分析（创建新版本）
response = requests.post(
    f"{BASE_URL}/novels/{novel_id}/reanalyze",
    json={"label": "修正版", "num_topics": 30}
)
analysis_id = response.json()["analysis_id"]
print(f"新分析版本: {analysis_id}")

# 查询状态
status = requests.get(f"{BASE_URL}/novels/{novel_id}/status").json()
print(f"进度: {status['progress']}%")

# 获取所有分析版本
analyses = requests.get(f"{BASE_URL}/novels/{novel_id}/analyses").json()
for a in analyses["analyses"]:
    print(f"版本: {a['analysis_id']}, 状态: {a['status']}")

# 删除特定分析版本
requests.delete(f"{BASE_URL}/novels/{novel_id}/analyses/{analysis_id}")

# 导出结果
result = requests.get(f"{BASE_URL}/novels/{novel_id}/results").json()
print(f"文件路径: {result['file_path']}")

# 获取情感曲线
emotion_curve = requests.get(f"{BASE_URL}/novels/{novel_id}/emotion-curve").json()
```
