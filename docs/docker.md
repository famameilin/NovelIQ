# Docker 部署说明

本文档只覆盖部署态 Docker 方案，不替代仓库现有的源码开发启动方式。

## 1. 源码启动 vs Docker 部署

### 源码启动

- 后端继续使用仓库脚本，例如：
  - `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 setup`
  - `powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 api --reload --port 8000`
- 前端继续在 `frontend/` 目录执行：
  - `npm install`
  - `npm run dev`
- 源码启动默认使用仓库根目录的 `.env`。

### Docker 部署

- Docker 方案只面向部署态，不提供开发态热更新。
- Compose 只编排 `db`、`backend`、`frontend` 三个服务。
- 容器环境单独使用 `.env.docker`，不要直接复用源码开发时的 `.env`。
- 后端容器启动命令保持为：
  - `uv run python -m src.api.main --host 0.0.0.0 --port 8000`
- 应用启动时会自行执行 `init_db()`，因此不需要额外 migration service。

## 2. 生成 `.env.docker`

1. 在仓库根目录复制示例文件：

```powershell
Copy-Item .env.docker.example .env.docker
```

2. 打开 `.env.docker`，至少修改以下内容：
   - `POSTGRES_PASSWORD`
   - 各类模型服务地址与密钥
   - `FRONTEND_PORT` / `BACKEND_PORT`（如果宿主机端口冲突）

3. 如果模型服务运行在宿主机而不是容器内：
   - Windows / Docker Desktop 下优先使用 `host.docker.internal`
   - 不要在 `.env.docker` 里继续写 `127.0.0.1` 或 `localhost`，否则容器内会指向它自己

## 3. 部署命令

### 启动

```powershell
docker compose --env-file .env.docker up -d --build
```

启动后默认访问地址：

- 前端：`http://localhost:8080`（或你在 `.env.docker` 中配置的 `FRONTEND_PORT`）
- OpenAPI 文档：`http://localhost:8080/api/docs`
- 健康检查：`http://localhost:8080/api/health`

### 查看状态

```powershell
docker compose --env-file .env.docker ps
docker compose --env-file .env.docker logs -f backend
docker compose --env-file .env.docker logs -f frontend
```

### 停止

```powershell
docker compose --env-file .env.docker down
```

如果你还想同时删除数据库卷：

```powershell
docker compose --env-file .env.docker down -v
```

如果你还想同时清理宿主机侧产物目录，再手动删除：

- `data/uploads`
- `outputs`
- `logs`
- `models`

## 4. 持久化目录

Compose 默认会把以下目录持久化到宿主机：

- `postgres_data`
  - PostgreSQL Docker 命名卷，使用带 `pgvector` 的数据库镜像。
- `data/uploads`
  - 上传的原始小说文本。
- `outputs`
  - 后端分析输出结果。
- `logs`
  - 后端日志文件。
- `models`
  - 主题模型等磁盘产物，当前仓库会把 topic 模型写到 `models/topic/<run_id>`。

`config/`、`data/lexicons/`、`src/` 等代码与静态资源会直接打包进镜像，不依赖运行期挂载。

## 5. 前端部署说明

- 前端镜像使用 Nginx 托管 `frontend/dist` 静态文件。
- Nginx 会把 `/api` 反代到 `backend:8000`。
- `/api/events/` 这类 SSE 路径已关闭代理缓冲，并拉长读取与发送超时，避免流式分析过程被 Nginx 提前截断。
- 当前前端源码已经改成同源优先策略：
  - 源码启动时由 Vite 代理 `/api` 到本机后端
  - Docker 部署时由 Nginx 同源反代 `/api`
