# 小说量化分析系统

基于Python的中文网络小说量化分析工具，提供文本分析、指标计算、智能标注等功能。

## 技术栈
- Python 3.12+
- FastAPI
- SQLAlchemy + PostgreSQL
- LiteLLM/OpenAI
- jieba分词

## 目录
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [安装部署](#安装部署)
- [使用方法](#使用方法)
- [API文档](#api文档)
- [开发指南](#开发指南)
- [架构设计](#架构设计)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

## 功能特性

### 文本处理
- 文本导入：支持txt文件导入，自动编码检测
- 文本预处理：清洗、分词、分句
- 主题建模：LDA主题分析

### 量化指标
- 情感指标：情感密度、正负比、情感曲线
- 风格指标：词汇丰富度、句长统计、对话比例
- 叙事指标：三幕结构、高潮分析、事件密度
- 人物指标：关系网络、中心性分析、角色功能

### 智能分析
- LLM标注：使用大语言模型进行智能标注
- 实体消歧：人物实体识别和消歧
- 诊断分析：文本质量诊断

### API服务
- RESTful API：完整的API接口
- 实时通信：SSE实时推送
- 任务管理：异步任务处理

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
- 前端：http://localhost:18080
- API文档：http://localhost:8000/api/docs
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

### 基本使用
```python
from src.ingest.reader import ingest_path
from src.workflows.preprocess import preprocess_document

# 导入文本
docs = ingest_path("path/to/novel.txt")

# 预处理
processed = preprocess_document(docs[0])
```

## 安装部署

### 详细安装说明
[预留图片位置：安装流程图]

### 配置说明
配置文件位置：`config/settings.json`

主要配置项：
- `models`: LLM模型配置
- `database`: 数据库连接
- `paths`: 文件路径
- `api`: API服务配置

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

### 配置选项
[预留图片位置：配置选项表格]

## API文档

### 端点说明
- `GET /api/novels` - 获取小说列表
- `POST /api/novels/upload` - 上传小说
- `GET /api/novels/{novel_id}` - 获取小说详情
- `POST /api/novels/{novel_id}/tasks` - 启动分析任务
- `GET /api/novels/{novel_id}/tasks/{task_id}/status` - 获取任务状态
- `GET /api/results/{novel_id}` - 获取分析结果

### 请求/响应格式
[预留图片位置：API文档示例]

### 示例代码
[预留图片位置：API调用示例]

## 开发指南

### 项目架构
[预留图片位置：架构图]

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

### 测试说明
```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_preprocess.py

# 生成覆盖率报告
pytest --cov=src
```

## 架构设计

### 系统架构图
[预留图片位置：系统架构图]

### 模块说明
- `src/ingest`: 文本导入模块
- `src/preprocess`: 预处理模块
- `src/metrics`: 指标计算模块
- `src/models`: LLM模型模块
- `src/workflows`: 工作流模块
- `src/api`: API服务模块
- `src/storage`: 存储模块

### 数据流
[预留图片位置：数据流图]

## 贡献指南

### 如何贡献
1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建Pull Request

### 代码规范
- 使用ruff进行代码格式化
- 使用mypy进行类型检查
- 编写单元测试
- 更新文档

### 提交规范
- feat: 新功能
- fix: 修复bug
- docs: 文档更新
- style: 代码格式
- refactor: 重构
- test: 测试相关
- chore: 构建/工具相关

## 许可证

本项目采用 [MIT许可证](LICENSE)。