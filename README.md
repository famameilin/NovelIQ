# NovelIQ - 中文网络小说量化分析系统

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

NovelIQ 是一套面向中文长篇网络小说的智能量化分析系统，围绕文本预处理、分块标注、人物消歧、关系抽取、主题建模和综合诊断，形成从原始文本到结构化结果、再到可视化展示的完整分析流程。

## 作品特色

- **双模型协作**：本地小模型（Qwen3.5-9B-Q6_K）处理高频块级提取，云端大模型（通过 LiteLLM 统一代理）负责低频全局推理
- **七维分析**：叙事结构、人物关系、情感曲线、语言风格、节奏韵律、文化元素、主题内容
- **数据库优先**：PostgreSQL 作为真相源，图谱、时间轴和导出模块共享同一版事实视图
- **人名消歧**：嵌入标注主链的增量消歧系统，处理中文小说复杂的别名映射
- **RAG 增强**：三级证据召回（别名层、活跃实体层、向量层），支持伏笔候选与段落级语义检索
- **前后端一体化**：从工作流、数据库、接口到页面展示形成完整闭环

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      前端展示层                              │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
│  │ 首页 │ │ 详情 │ │ 曲线 │ │ 人物 │ │ 图谱 │ │ 诊断 │    │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      API 接口层                              │
│  FastAPI + uvicorn + SSE 进度流                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    工作流编排层                               │
│  预处理 → 分块 → 标注 → 消歧 → 聚合 → 主题 → 诊断          │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   本地小模型     │ │   云端大模型     │ │   数据库层       │
│  Qwen3.5-9B     │ │  LiteLLM 代理    │ │  PostgreSQL     │
│  llama.cpp      │ │  (DeepSeek等)    │ │  + pgvector     │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 快速开始

### 环境要求

- Python 3.12+
- PostgreSQL 14+（带 pgvector 扩展）
- Node.js 18+（前端开发）
- llama.cpp 本地模型服务器（可选，用于本地标注）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/famameilin/novel-quantitive-analysis.git
cd novel-quantitive-analysis

# 2. 创建虚拟环境并安装依赖
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置数据库连接和模型 API Key

# 4. 初始化数据库
uv run python scripts/db/init_db.py

# 5. 启动 API 服务
uv run python -m src.api.main --port 8000
```

### 环境变量配置

在 `.env` 文件中配置以下变量（完整模板见 `.env.example`）：

```env
# 数据库连接（用户名密码单独配置）
DATABASE_URL=postgresql+psycopg://localhost:5432/novel_analysis
DATABASE_USERNAME=postgres
DATABASE_PASSWORD=your_password

# 本地标注模型（llama.cpp）
ANNOTATION_BASE_URL=http://127.0.0.1:8111/v1
ANNOTATION_MODEL=Qwen3.5-9B-Q6_K
ANNOTATION_API_KEY=sk-no-key-required

# 语义分块嵌入模型（本地）
SEMANTIC_CHUNKING_BASE_URL=http://127.0.0.1:8081/v1
SEMANTIC_CHUNKING_MODEL=Qwen3-Embedding-0.6B

# 云端模型（通过 LiteLLM 统一代理，按任务分别配置）
DIAGNOSIS_BASE_URL=https://your-api-endpoint/v1
DIAGNOSIS_MODEL=your-model-name
DIAGNOSIS_API_KEY=your-api-key-here
```

## 使用指南

### API 服务

```bash
# 启动服务（默认端口 8000）
uv run python -m src.api.main

# 开发模式（热重载）
uv run python -m src.api.main --reload

# 指定端口
uv run python -m src.api.main --port 8001

# 使用启动脚本（带端口冲突检测）
uv run python scripts/run_api.py --port 8000
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build
```

### 开发辅助脚本

```bash
# PowerShell 辅助脚本（推荐）
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 setup    # 环境初始化
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 api      # 启动 API
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 test     # 运行测试
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 lint     # 代码检查
```

## 项目结构

```
novel quantitative analysis/
├── src/                          # 核心源码
│   ├── api/                      # FastAPI 接口层
│   │   ├── main.py               # 应用入口
│   │   ├── routes/               # 路由定义（novels, analysis, results, timeline, sse）
│   │   └── services/             # 业务逻辑（analysis_service, novel_service, task_manager）
│   ├── config/                   # 配置管理（settings.py）
│   ├── ingest/                   # 文本导入（编码检测：GB18030/UTF-8）
│   ├── preprocess/               # 预处理（文本清洗、段落切分）
│   ├── chunking/                 # 分块处理（语义分块，约2000字/块）
│   ├── models/                   # 模型客户端
│   │   ├── local/                # 本地模型（Qwen3.5-9B-Q6_K via llama.cpp）
│   │   │   └── annotation/       # 4阶段标注（Phase1-4）
│   │   ├── cloud/                # 云端模型（通过 LiteLLM 代理）
│   │   ├── disambiguation.py     # 人名消歧主客户端
│   │   ├── diagnosis.py          # 云端诊断客户端
│   │   ├── interactions/         # 模型交互记录
│   │   └── structured_output/    # 结构化输出适配
│   ├── workflows/                # 工作流编排
│   │   ├── preprocess.py         # 预处理工作流
│   │   ├── annotate.py           # 标注工作流
│   │   ├── annotate_helpers/     # 标注辅助（消歧、图谱投影）
│   │   ├── aggregate.py          # 聚合工作流
│   │   ├── topic.py              # 主题建模工作流
│   │   ├── diagnose.py           # 诊断工作流
│   │   └── curve_metrics.py      # 曲线指标计算
│   ├── metrics/                  # 指标计算
│   │   ├── narrative_metrics.py  # 叙事结构指标
│   │   ├── character_metrics.py  # 人物关系指标
│   │   ├── emotion_metrics.py    # 情感曲线指标
│   │   ├── style_metrics.py      # 语言风格指标
│   │   ├── rhythm_metrics.py     # 节奏韵律指标
│   │   ├── lexicon_metrics.py    # 文化元素指标
│   │   ├── timeline_metrics.py   # 时间轴指标
│   │   └── aggregate/            # 聚合计算
│   ├── rag/                      # RAG 检索增强
│   │   ├── retriever.py          # 检索器（核心检索逻辑）
│   │   ├── level1_alias.py       # Level1: 别名层召回
│   │   ├── level2_active_entities.py  # Level2: 活跃实体层召回
│   │   ├── level3_vector.py      # Level3: 向量层召回（pgvector）
│   │   ├── mention_extraction.py # 提及抽取
│   │   ├── mention_rerank.py     # 提及重排序
│   │   ├── model_rerank.py       # 模型重排序
│   │   ├── evidence_bundle_builder.py # 证据束构建
│   │   └── evidence_contracts.py # 证据契约
│   ├── context/                  # 上下文管理
│   │   ├── entity_registry.py    # 实体注册表
│   │   ├── global_context.py     # 全局上下文
│   │   └── rolling_memory.py     # 滚动记忆
│   ├── knowledge/                # 知识图谱
│   │   ├── graph.py              # 图谱操作
│   │   └── authority/            # 权威层（实体、别名、关系、参与者）
│   ├── storage/                  # 数据存储
│   │   ├── db.py                 # 数据库引擎与会话
│   │   ├── models/               # ORM 模型定义
│   │   ├── repositories/         # 数据仓储层
│   │   ├── vector_schema.py      # 向量表结构（pgvector）
│   │   └── session.py            # 会话管理
│   ├── topic/                    # 主题建模
│   │   ├── lda_model.py          # LDA 模型
│   │   ├── preprocessor.py       # 主题预处理
│   │   └── schema.py             # 主题 schema
│   ├── eval/                     # 评测模块
│   │   └── disambig_metrics.py   # 消歧评测指标
│   ├── report/                   # 报告生成
│   │   └── schema.py             # 报告 schema
│   ├── lexicons/                 # 词典管理
│   ├── utils/                    # 工具函数
│   └── relation_network_metrics.py # 关系网络指标
├── frontend/                     # 前端应用（React + TypeScript）
│   ├── src/
│   │   ├── pages/                # 页面组件
│   │   │   ├── HomePage.tsx      # 首页
│   │   │   ├── NovelDetailPage.tsx # 小说详情
│   │   │   ├── CurvesPage.tsx    # 曲线展示
│   │   │   ├── CharactersPage.tsx # 人物分析
│   │   │   ├── GraphPage.tsx     # 关系图谱
│   │   │   ├── TopicsPage.tsx    # 主题分布
│   │   │   ├── TimelinePage.tsx  # 叙事时间轴
│   │   │   └── DiagnosisPage.tsx # 综合诊断
│   │   ├── components/           # 通用组件
│   │   ├── api/                  # API 客户端
│   │   ├── hooks/                # 自定义 Hooks
│   │   ├── store/                # 状态管理（Zustand）
│   │   ├── lib/                  # 工具库
│   │   └── router.tsx            # 路由配置
│   └── package.json
├── scripts/                      # 脚本工具
│   ├── dev.ps1                   # 开发辅助脚本
│   ├── run_api.py                # API 启动脚本
│   ├── db/                       # 数据库脚本（init_db, setup_test_db, repair_schema_drift）
│   ├── tools/                    # 开发工具（评测、监控、词典工具）
│   └── manual/                   # 手动调试脚本
├── tests/                        # 测试代码
├── config/                       # 配置文件
│   ├── settings.json             # 运行时配置
│   ├── logging_config.json       # 日志配置
│   └── prompts/                  # 模型提示词（Phase1-4、消歧、诊断）
├── data/                         # 数据文件
│   ├── lexicons/                 # 词典文件（idioms, positive, negative, stopwords 等）
│   └── gold_standards/           # 金标评测集
├── alembic.ini                   # 数据库迁移配置
├── compose.yaml                  # Docker Compose 配置
├── Dockerfile.backend            # 后端 Docker 镜像
├── .env.example                  # 环境变量模板
├── pyproject.toml                # Python 项目配置
├── uv.lock                       # 依赖锁文件
└── README.md                     # 本文件
```

## 七大分析维度

| 维度 | 说明 | 核心指标 |
|------|------|----------|
| 叙事结构 | 情节节奏、章节推进、冲突密度 | 三幕结构、高潮分布、冲突频率 |
| 人物关系 | 实体抽取、关系图谱 | 角色网络、关系强度、社区发现 |
| 情感曲线 | 随时间变化的情感走势 | 情感极性、转折点、波动幅度 |
| 语言风格 | 词汇多样性、句式复杂度 | MTLD、TTR、句长分布 |
| 节奏韵律 | 对话比例、叙述节奏 | 对话密度、场景切换频率 |
| 文化元素 | 传统文化引用识别 | 成语密度、典故频率、意象分布 |
| 主题内容 | LDA 主题建模 | 主题分布、主题演化、关键词提取 |

## 标注流程

系统采用 4 阶段标注流水线：

1. **Phase1 - 实体抽取**：提取人物名称、对话、动作
2. **Phase2 - 伏笔检测**：识别暗示、预兆、情节铺垫
3. **Phase3 - 场景描写**：提取环境、氛围、细节描写
4. **Phase4 - 情感分析**：分析情感极性、强度、变化

## RAG 检索系统

系统采用三级证据召回机制：

| 层级 | 说明 | 技术 |
|------|------|------|
| Level 1 | 别名层召回 | 基于消歧后的别名映射快速匹配 |
| Level 2 | 活跃实体层召回 | 基于实体活跃度和上下文相关性 |
| Level 3 | 向量层召回 | 基于 pgvector 的语义相似度检索 |

## 开发计划

### 已完成

- [x] 核心分析流水线（预处理→标注→聚合→诊断）
- [x] 人名消歧系统（增量消歧 + 最终消歧）
- [x] 图谱权威层（实体、别名、关系、参与者）
- [x] 前端可视化页面（首页、详情、曲线、人物、图谱、主题、时间轴、诊断）
- [x] 数据库持久化与模型交互记录
- [x] API 接口与 SSE 进度流
- [x] RAG 三级证据召回系统
- [x] 向量存储与语义检索（pgvector）
- [x] 消歧评测系统（金标集、基线对比）
- [x] Docker 部署配置（compose.yaml + Dockerfile）

### 进行中

- [ ] 性能优化与大规模测试
- [ ] 多作品横向对比分析
- [ ] 评测集与标注标准完善

### 计划中

- [ ] CI/CD 流水线
- [ ] 用户认证与权限管理
- [ ] 批量任务队列（Celery/Redis）
- [ ] 更多可视化图表（热力图、桑基图）
- [ ] 导出功能增强（PDF、Word、Excel）

## 测试

```bash
# 运行所有测试
uv run python -m pytest tests/

# 运行特定测试文件
uv run python -m pytest tests/test_e2e_integration.py

# 运行带详细输出
uv run python -m pytest -v tests/

# 运行覆盖率报告
uv run python -m pytest --cov=src tests/
```

## 代码质量

```bash
# Ruff 代码检查
uv run ruff check src/

# Ruff 代码格式化
uv run ruff format src/

# MyPy 类型检查
uv run mypy src/
```

## 词典文件

系统使用以下词典文件进行中文文本分析：

| 文件 | 说明 | 词条数 |
|------|------|--------|
| idioms.txt | 成语词典 | 30,895 |
| positive.txt | 正面情感词 | 1,079 |
| negative.txt | 负面情感词 | 1,024 |
| stopwords.txt | 停用词 | 227 |
| semantic_category.txt | 语义类别词 | 1,185 |
| function_words.txt | 虚词 | 434 |
| imagery.txt | 意象词 | 351 |

## 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/your-feature`)
3. 提交更改 (`git commit -m 'feat: 添加某功能'`)
4. 推送到分支 (`git push origin feature/your-feature`)
5. 创建 Pull Request

### Commit 规范

```
<type>(<scope>): <subject>

类型：
- feat: 新功能
- fix: 修复 bug
- docs: 文档更新
- style: 代码格式（不影响逻辑）
- refactor: 重构
- test: 测试相关
- chore: 构建/工具链
```

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 致谢

- [Qwen](https://github.com/QwenLM) - 本地标注与嵌入模型
- [LiteLLM](https://github.com/BerriAI/litellm) - 统一模型代理
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [SQLAlchemy](https://www.sqlalchemy.org/) - ORM 框架
- [NetworkX](https://networkx.org/) - 图论库
- [Gensim](https://radimrehurek.com/gensim/) - 主题建模
- [jieba](https://github.com/fxsjy/jieba) - 中文分词
- [React](https://react.dev/) - 前端框架
- [ECharts](https://echarts.apache.org/) - 可视化库
- [@antv/g6](https://g6.antv.antgroup.com/) - 关系图谱可视化
- [pgvector](https://github.com/pgvector/pgvector) - 向量检索

## 联系方式

- 项目地址：https://github.com/famameilin/novel-quantitive-analysis
- 问题反馈：https://github.com/famameilin/novel-quantitive-analysis/issues

---

**NovelIQ** - 让网络小说分析从艺术走向科学
