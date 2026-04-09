# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

## 常用命令

- `uv sync --all-groups`  
  安装运行与开发依赖。首次进入仓库或依赖变更后优先执行；`scripts/dev.ps1 setup` 内部也会执行这一步，并确保存在 `.venv`。

- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 setup`  
  Windows 下的推荐初始化方式：检查 `uv`、创建 `.venv`、同步所有依赖组，适合新环境快速拉起。

- `uv run python -m src.api.main --reload --port 8000`  
  启动 FastAPI 服务；开发时常用 `--reload`。入口自带端口占用检测，文档页位于 `/api/docs`。

- `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 api --reload --port 8000`  
  PowerShell 封装的 API 启动方式，等价于直接运行 `src.api.main`，适合本仓库的 Windows 开发环境。

- `uv run python -m src.cli.main run --source <path>`  
  运行完整 CLI 工作流：预处理 → 标注 → 聚合 → 诊断。适合从原始小说文本直接走通主流程。

- `uv run python -m src.cli.main preprocess --source <path>`  
  只执行预处理阶段；会创建新的 `run_id`，完成读取、清洗、分块与部分基础指标计算。

- `uv run python -m src.cli.main annotate --run-id <run_id> --resume`  
  对已有运行执行本地模型标注；`--resume` 用于断点续跑，避免重复处理已标注分块。

- `uv run python -m src.cli.main aggregate --run-id <run_id>`  
  基于已落库的标注结果计算聚合指标、曲线与图谱相关统计。

- `uv run python -m src.cli.main diagnose --run-id <run_id>`  
  对聚合后的运行执行云端诊断；适合只重跑最终推理阶段。

- `uv run python -m src.cli.main topic-model --run-id <run_id> --num-topics 25`  
  执行 LDA 主题建模；常用于在主分析之外单独刷新主题结果。

- `uv run python -m pytest tests/ -v`  
  运行测试。测试依赖 PostgreSQL 与 `pgvector`，需先配置 `TEST_DATABASE_URL`，并确保测试库可安装 `vector` 扩展。

- `uv run python -m pytest tests/<path_to_file>.py -v`  
  运行单个测试文件，适合定点回归某一模块。

- `uv run python -m pytest tests/<path_to_file>.py -k <expr> -v`  
  运行单个测试文件中的部分用例；`-k` 可按测试名子串过滤。

- `uv run ruff check src tests scripts`  
  运行静态检查。默认排除 `deprecated/`、`scripts/manual/`、`scripts/legacy/`，新增可复用脚本应放在 `scripts/db/` 或 `scripts/tools/`。

- `uv run mypy src`  
  运行类型检查，仅覆盖 `src/`。当前配置同样排除了部分历史目录与 `scripts/run_api.py`。

- `uv run python scripts/db/setup_test_db.py`  
  初始化测试数据库：创建测试库、安装 `pgvector`、建表。适合首次配置本地测试环境。

## 高层架构

这是一个面向中文网络小说的量化分析系统，核心思路是“统一工作流 + 双模型协作 + PostgreSQL 持久化”。输入通常是一部小说文本或目录，系统先做预处理与切块，再用本地模型完成高吞吐标注，随后把分块级结果聚合为全书级指标，最后再使用云端模型做较重的诊断与主题命名。

### 1. 入口层：CLI 与 API 共用同一套核心流程

仓库有两个正式入口：`src/cli/` 和 `src/api/`。CLI 通过 `src.cli.main` / `src.cli.parser` 暴露 `preprocess`、`annotate`、`aggregate`、`diagnose`、`topic-model`、`run` 等命令；API 通过 `src.api.main` 挂载 `novels`、`analysis`、`results` 路由。真正的业务编排不要优先在路由或命令处理器里找，而应先看 `src/workflows/`：这里才是 API 与 CLI 共享的主工作流边界。

### 2. 配置与运行前提

配置由 `src.config` 统一加载：JSON 配置来自 `config/settings.json`，环境变量再覆盖其中的关键字段。数据库不是可选项，运行时代码依赖 `DATABASE_URL` 指向 PostgreSQL；测试依赖 `TEST_DATABASE_URL` 指向独立测试库，并要求启用 `pgvector`。如果新增入口脚本，保持通过 `src.config` 统一读取环境，不要各处散落加载逻辑。

### 3. 主流程：从文本到可分析运行

主流程从 `src/ingest/`、`src/preprocess/`、`src/chunking/` 开始：读取文本、做清洗、按语义友好的方式切成 chunk，并在预处理阶段计算部分基础文本特征。`run_preprocess` 负责把这些结果落库，并创建后续阶段共享的 `run_id`。这意味着后面大多数任务不是直接传文件，而是围绕一个已有运行继续推进。

### 4. 标注层：本地模型、多阶段抽取、上下文与消歧

标注是仓库最复杂的部分。核心入口是 `src/workflows/annotate.py`，但真正的能力分散在 `src/models/local/`、`src/context/`、`src/rag/` 与 `src/workflows/annotate_helpers/`。

这里的关键设计不是“对每个 chunk 单独调用模型”，而是“带全局状态的增量标注”：

- `src/models/local/schema.py` 定义 chunk 级结构化输出，如角色、对话、关系变化、伏笔等对象。
- `src/context/global_context.py` 与 `src/context/entity_registry.py` 维护跨 chunk 的人物/实体上下文。
- `src/rag/retriever.py` 从既有内容中检索相关上下文，补充给标注提示词。
- `src/workflows/annotate_helpers/disambiguation/` 处理人名别名与阶段性消歧，避免同一角色在长篇文本里被重复裂变为多个实体。
- `src/workflows/annotate_helpers/graph_projection.py` 把标注结果投影为可持久化的图谱事件和当前关系状态。

理解这一层时，要把它看成“分块标注 + 全局记忆 + 图谱更新”的组合，而不是单纯的 LLM 调用封装。

### 5. 聚合与指标层：把 chunk 结果提升为全书指标

`src/workflows/aggregate.py` 负责把分块标注结果转换成更稳定的全局分析结果。实现细节主要位于 `src/metrics/`，其中 `src/metrics/aggregate/` 扮演新的聚合骨架：它从仓储层取数，再由不同 computer/fetcher 计算情绪曲线、节奏曲线、角色关系、语言风格、文化元素等维度指标。修改指标逻辑时，优先沿着“fetchers -> computers -> types/汇总结果”的方向阅读，而不是在 API 返回模型里反推。

### 6. 主题建模与云端诊断：后处理阶段

主题建模与云端诊断是两个相对独立的后处理阶段。

- `src/workflows/topic.py` 联动 `src/topic/preprocessor.py` 与 `src/topic/lda_model.py`，以 LDA 方式从文本块中提取主题分布。
- `src/workflows/diagnose.py` 读取数据库中的聚合结果，组装 payload，再调用 `src/models/diagnosis.py` 与 `src/models/cloud/` 下的 schema/client 生成更高层的分析结论。

因此，如果问题出现在“指标算对了但最终解释不对”，优先查诊断 payload 组装与云端 schema；如果问题出现在“主题分布本身异常”，则看 topic 子系统，而不是 aggregate。

### 7. 存储层：Repository 模式 + ORM + 统一 ID 语义

存储层位于 `src/storage/`，采用 SQLAlchemy ORM + Repository 模式。ORM 模型集中在 `src/storage/models/`，仓储导出集中在 `src/storage/repositories/__init__.py`。常见仓储包括运行、分块、标注、统计、实体、图谱与诊断相关仓储。

这个仓库有两个常见 ID 语义：

- `run_id`：内部分析运行主键，贯穿预处理、标注、聚合、主题、诊断全流程。
- `task_id`：偏 API 对外暴露的短 ID；与 `run_id` 的映射逻辑在 `src/storage/id_mapping.py`。

排查 API 结果错位、任务查询不到、或跨阶段数据串线时，先确认自己处理的是哪一种 ID。

### 8. 服务层：API 的异步编排桥

API 不是直接调用底层仓储，而是通过 `src/api/services/analysis_service.py`、`novel_service.py`、`task_manager.py` 组织文件上传、任务状态、后台执行与结果读取。也就是说：工作流定义“做什么”，服务层定义“以什么 API 生命周期和任务状态去做”。如果改动某个 workflow 后 API 表现异常，通常还要检查 service 层是否需要同步更新进度状态或结果装配。

### 9. 测试组织方式

`tests/` 基本按能力域镜像源码结构，包含 `api`、`cli`、`context`、`metrics`、`models`、`storage`、`topic`、`workflows` 等目录。`tests/conftest.py` 会创建 PostgreSQL 测试引擎、安装 `vector` 扩展并重建表，因此测试失败如果集中出现在建库阶段，先检查数据库环境，而不是业务代码。CLI 与 API 测试广泛使用替身和 fixture 来隔离真实模型调用。

## 仓库内约定

- `src/workflows/` 是共享业务编排边界；同一业务优先复用 workflow，不要在 CLI 与 API 各自复制流程。
- 项目明确面向中文小说文本；词表、停用词和文化/风格相关资源在 `data/` 下，对指标结果影响很大。
- 默认静态检查不会覆盖 `deprecated/`、`scripts/manual/`、`scripts/legacy/`；修改这些目录前先确认它们是否仍属于活跃代码路径。
- 新脚本若是可复用开发工具，放 `scripts/db/` 或 `scripts/tools/`；一次性人工核查脚本放在 `scripts/manual/`。
