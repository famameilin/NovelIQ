# 小说量化分析系统

## 项目简介

小说量化分析系统是一个基于Python的中文网络小说智能分析平台，旨在通过自然语言处理和机器学习技术，对小说文本进行全方位的量化分析。系统采用模块化架构，集成了文本预处理、多维度指标计算、大语言模型智能标注、检索增强生成（RAG）等核心功能，为文学研究、创作辅助和内容评估提供数据支持。

### 核心能力

**文本分析引擎**

- 支持txt格式小说导入，自动处理UTF-8、GBK等多种编码
- 集成jieba分词，支持中文文本精准分词和词性标注
- 提供文本清洗、分句、段落划分等预处理功能
- 智能分块系统，支持语义分块和索引管理

**多维度量化指标**

- 情感分析：情感密度、正负情感比、情感曲线、情感恢复速度等
- 风格分析：词汇丰富度（TTR、MTLD）、句长统计、对话比例、比喻密度等
- 叙事分析：三幕结构识别、高潮分析、事件密度、悬崖率等
- 人物分析：关系网络密度、中心性分析、角色功能覆盖、Greimas符号学分析

**智能标注系统**

- 基于大语言模型（LLM）的智能标注，支持本地和云端模型
- 多阶段标注流程，支持流式输出和结构化输出
- 实体消歧系统，自动识别人物别名和匿名人物
- 上下文管理：实体注册、全局上下文、滚动记忆

**检索增强生成（RAG）**

- 三级证据检索：别名匹配、活跃实体、向量相似度
- 智能重排机制，支持LLM辅助重排
- 证据包构建，为标注提供上下文支持
- 查询示例规划和LLM辅助查询

**知识图谱与词典**

- 人物关系网络构建和可视化
- 情感词典、文化词典、题材检测词典
- 支持自定义词典扩展
- 权威知识图谱构建

**诊断与评估**

- 小说整体质量诊断，包括叙事类型、主题、价值观分析
- 多维度评估指标，支持横向对比
- 详细的分析报告生成
- 消歧评估指标，支持模型效果评估

## 技术栈

### 后端技术

- **Python 3.12+**：核心开发语言
- **FastAPI**：高性能异步Web框架
- **SQLAlchemy + PostgreSQL**：关系型数据库，支持pgvector向量存储
- **LiteLLM/OpenAI**：大语言模型调用框架
- **jieba**：中文分词库
- **gensim**：主题建模（LDA）
- **NetworkX**：图分析和网络计算
- **Pydantic**：数据验证和序列化
- **alembic**：数据库迁移工具

### 前端技术

- **React 19**：前端框架
- **TypeScript**：类型安全的JavaScript超集
- **Tailwind CSS**：实用优先的CSS框架
- **Radix UI**：无样式、可访问的UI组件库
- **ECharts**：数据可视化图表库
- **AntV G6**：关系图可视化
- **Zustand**：轻量级状态管理
- **React Query**：数据获取和缓存
- **Vite**：下一代前端构建工具

### 部署技术

- **Docker + Docker Compose**：容器化部署
- **PostgreSQL 17 + pgvector**：数据库和向量存储
- **Nginx**：反向代理和静态资源服务

## 快速开始

### Docker部署（推荐）

#### 环境要求

- Docker 20.10+
- Docker Compose 2.0+

#### 快速启动

1. 克隆项目

```bash
git clone <repository-url>
cd novel-quantitative-analysis
```

2. 配置环境变量

```bash
cp .env.docker.example .env.docker
# 编辑 .env.docker 文件，配置模型API等
```

3. 启动服务

```bash
docker compose up -d --build
```

4. 访问服务

- 前端：<http://localhost:18080>
- API文档：<http://localhost:8000/api/docs>
- 数据库：localhost:15432

#### 常用命令

```bash
# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 重启服务
docker compose restart
```

### 手动安装

#### 环境要求

- Python 3.12+
- PostgreSQL 14+
- Node.js 18+ (可选，用于前端)

#### 安装步骤

1. 克隆项目

```bash
git clone <repository-url>
cd novel-quantitative-analysis
```

2. 安装依赖

```bash
pip install -e .
```

3. 配置环境

```bash
# 编辑配置文件
config/settings.json
```

4. 初始化数据库

```bash
alembic upgrade head
```

5. 启动服务

```bash
python -m src.api.main
```

## 安装部署

### 配置说明

配置文件位置：`config/settings.json`

主要配置项：

- `models`: LLM模型配置（标注、消歧、诊断等）
- `database`: 数据库连接配置
- `paths`: 文件路径配置（上传、输出、日志等）
- `api`: API服务配置（端口、CORS等）
- `chunking`: 分块配置（块大小、重叠等）
- `metrics`: 指标计算配置

### 环境变量说明

Docker部署使用 `.env.docker` 文件配置环境变量，主要配置项：

- `UPLOAD_DIR`: 上传文件目录
- `RESULTS_DIR`: 分析结果目录
- `LOG_DIR`: 日志目录
- `DB_*`: 数据库连接池配置
- `*_BASE_URL`: 各模型API地址
- `*_MODEL`: 各模型名称
- `*_API_KEY`: 各模型API密钥

### 数据库设置

1. 创建数据库

```sql
CREATE DATABASE novel_analysis;
```

2. 运行迁移

```bash
alembic upgrade head
```

3. 验证连接

```bash
python -c "from src.storage.db import get_session; get_session()"
```

## 使用方法

### API调用示例

```python
import requests

# 上传小说
response = requests.post(
    "http://localhost:8000/api/novels/upload",
    files={"file": open("novel.txt", "rb")}
)

# 启动分析
novel_id = response.json()["novel_id"]
analysis_response = requests.post(
    f"http://localhost:8000/api/novels/{novel_id}/tasks"
)
```

### 前端使用

访问 <http://localhost:18080> 使用前端界面：

1. 上传小说文件
2. 选择分析配置
3. 启动分析任务
4. 查看分析结果和可视化图表

## API文档

### 端点说明

- `GET /api/novels` - 获取小说列表
- `POST /api/novels/upload` - 上传小说
- `GET /api/novels/{novel_id}` - 获取小说详情
- `POST /api/novels/{novel_id}/tasks` - 启动分析任务
- `GET /api/novels/{novel_id}/tasks/{task_id}/status` - 获取任务状态
- `GET /api/results/{novel_id}` - 获取分析结果

### 详细文档

启动服务后访问：

- Swagger UI：<http://localhost:8000/api/docs>
- ReDoc：<http://localhost:8000/api/redoc>

## 架构设计

### 系统架构图

[预留图片位置：系统架构图]

### 模块说明

- `src/ingest`: 文本导入模块，支持多编码格式
- `src/preprocess`: 预处理模块，包含清洗、分词、分句
- `src/chunking`: 分块模块，支持语义分块和索引管理
- `src/metrics`: 指标计算模块，包含情感、风格、叙事、人物等指标
- `src/models`: LLM模型模块，支持标注、消歧、诊断
- `src/workflows`: 工作流模块，编排分析流程
- `src/rag`: 检索增强生成模块，三级证据检索
- `src/context`: 上下文管理模块，实体注册和全局上下文
- `src/knowledge`: 知识图谱模块，权威知识图谱构建
- `src/lexicons`: 词典模块，情感词典、文化词典、题材检测
- `src/eval`: 评估模块，消歧评估指标
- `src/topic`: 主题建模模块，LDA主题分析
- `src/api`: API服务模块，RESTful API接口
- `src/storage`: 存储模块，数据库和向量存储
- `src/report`: 报告模块，分析报告生成

### 数据流

[预留图片位置：数据流图]

## 开发指南

### 开发环境搭建

1. 安装开发依赖

```bash
pip install -e ".[dev]"
```

2. 配置开发环境

```bash
# 编辑配置文件
config/settings.json
```

3. 运行测试

```bash
pytest
```

### 代码规范

- 使用ruff进行代码格式化
- 使用mypy进行类型检查
- 遵循PEP 8规范
- 使用中文注释和文档

### 测试说明

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_preprocess.py

# 生成覆盖率报告
pytest --cov=src
```

## 贡献指南

### 如何贡献

1. Fork项目
2. 创建功能分支 (`git checkout -b feature/your-feature`)
3. 提交更改 (`git commit -m 'Add some feature'`)
4. 推送到分支 (`git push origin feature/your-feature`)
5. 创建Pull Request

### 提交规范

使用约定式提交格式：

- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具相关

### 代码审查

- 所有提交需要经过代码审查
- 确保测试通过
- 更新相关文档

## 许可证

本项目采用 [MIT许可证](LICENSE)。