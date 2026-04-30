# Docker 部署说明

这套容器方案面向“用 Docker 起完整服务”，不是源码热更新开发容器。

## 结构

- `db`：`pgvector/pgvector:pg17`，提供 PostgreSQL + pgvector。
- `backend`：Python 3.12 + `uv`，直接运行 FastAPI 服务。
- `frontend`：Node 22 构建静态资源，再由 `nginx` 对外提供页面并反代 `/api` 到 `backend`。

## 首次启动

1. 复制环境文件并按需修改：

   ```powershell
   Copy-Item .env.docker.example .env.docker
   ```

2. 启动开发环境：

   ```powershell
   docker compose --env-file .env.docker -f compose.yaml up --build
   ```

## 常用地址

- 前端首页：`http://localhost:18080`
- 后端健康检查：`http://localhost:8000/health`
- 后端 OpenAPI：`http://localhost:8000/api/docs`
- PostgreSQL（宿主机连容器）：`localhost:15432`

## 验证建议

```powershell
docker compose --env-file .env.docker -f compose.yaml ps
docker compose --env-file .env.docker -f compose.yaml logs backend --tail 100
docker compose --env-file .env.docker -f compose.yaml logs frontend --tail 100
```

如果配置无误，`frontend` 应返回 `200`，`backend` 的 `/health` 也应返回 `healthy`。

## 注意事项

- 容器里的后端默认通过 `host.docker.internal` 访问宿主机模型服务；如果模型服务不在宿主机，请改 `.env.docker` 里的各个 `*_BASE_URL`。
- 这套方案默认把数据库端口映射到 `15432`，避免和宿主机已有 PostgreSQL 抢占 `5432`。
- 如果改了 `frontend/package-lock.json` 或后端依赖锁文件，重新执行 `docker compose --env-file .env.docker -f compose.yaml up --build` 让镜像依赖刷新。
