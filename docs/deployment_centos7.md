# CentOS 7 Docker 部署

CentOS 7 保持不变。应用运行在 Docker 容器中：Python 3.11 API、PostgreSQL 16 和 Nginx 都不依赖宿主机的 Python 或数据库版本。

## 1. 准备环境变量

在项目根目录创建生产 `.env`，保留已有的 Qwen、OCR 和 RAGFlow 配置，并至少补充：

```env
POSTGRES_DB=ai_design_review
POSTGRES_USER=ai_design_review
POSTGRES_PASSWORD=replace-with-a-long-random-password
AI_REVIEW_WEB_PORT=8088
AI_REVIEW_API_PORT=8770
DEBIAN_APT_MIRROR=mirrors.aliyun.com
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
RECOGNITION_WORKER_CONCURRENCY=2
RECOGNITION_JOB_POLL_SECONDS=1
RECOGNITION_JOB_LEASE_SECONDS=900
GENERATION_WORKER_API_KEY=replace-with-a-different-long-random-key
GENERATION_ADMIN_API_KEY=replace-with-another-long-random-key
GENERATION_JOB_LEASE_SECONDS=300
GENERATION_MAX_ARTIFACT_MB=50
MOCK_SOLIDWORKS_ENABLED=false
```

`DATABASE_URL` 可以留空，Compose 会自动连接内部 PostgreSQL。若使用公司已有 PostgreSQL，再显式配置：

```env
DATABASE_URL=postgresql+psycopg://user:password@database-host:5432/ai_design_review
```

密码若含 `@`、`:`、`/` 等 URL 保留字符，请对密码进行 URL 编码后再写入 `DATABASE_URL`。

首次构建默认使用国内 Debian 与 PyPI 镜像源；网络环境不同可在 `.env` 覆盖 `DEBIAN_APT_MIRROR` 和 `PIP_INDEX_URL`，或置空使用基础镜像默认源。

RAGFlow 位于其他服务器时，`RAGFLOW_BASE_URL` 必须是 API 容器可访问的服务器 IP 或域名，不能写宿主机 `127.0.0.1`。

## 2. 首次启动

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose up -d api worker web
docker compose ps
curl http://127.0.0.1:8088/api/health
```

`worker` 是识别队列的必需服务，没有对外端口；它从 PostgreSQL 领取图纸任务。
首期保持一个 Worker 服务和 `RECOGNITION_WORKER_CONCURRENCY=2`，即可同时识别两份图纸。
可通过 `docker compose logs -f worker` 查看排队、失败或取消的识别任务。

浏览器访问 `http://服务器地址:8088`。API 只绑定到宿主机 `127.0.0.1:8770`，外部访问统一经 Nginx 的 8088 端口；公司现有反向代理可再转发到这个端口。

中文增强接口文档可通过 `http://服务器地址:8088/api/docs` 访问，原 Swagger UI 位于 `/api/swagger`，OpenAPI JSON 位于 `/api/openapi.json`。生产环境不要启动 `mock-solidworks` profile；它仅用于本地联调。若要在本地验证完整闭环，可执行：

```bash
docker compose --profile mock-solidworks up -d mock-solidworks
```

模拟 Worker 使用正式 Worker API 和独立 Bearer Key，不挂载数据库卷或输出卷。未来真实 SolidWorks Worker 按同一协议替换其内部绘图逻辑即可。

健康检查中的 `persistence_runtime.status=available` 表示 PostgreSQL 和迁移均可用。`not_configured` 表示仍在 JSON 兼容模式，生产环境不应停留在该状态。

## 3. 数据与备份

- `postgres_data`：审查快照、参数修改留痕和标准化/对话事件。
- `review_outputs`：上传图纸、预览图、JSON 调试副本和 generation 产物文件。
- 两个卷都是 Docker 命名卷，升级容器不会删除它们。

每日备份 PostgreSQL：

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "backups/ai_design_review_$(date +%F).sql"
```

文件副本可按公司的备份策略导出 `review_outputs` 卷。上线前需要把卷备份与恢复演练纳入运维流程。

## 4. 更新与回滚

```bash
docker compose build api worker
docker compose run --rm api alembic upgrade head
docker compose up -d api worker web
docker compose logs -f api
```

先备份数据库再执行迁移。应用代码可回滚到上一镜像；数据库迁移若需要回退，必须先确认对应 Alembic `downgrade` 脚本已经过演练。

## 5. ERP 对接边界

本项目不创建本地账号和权限。ERP 网关后续调用审查 API 时，传入 `erp_user_id`、`username`、`department_id`，它们会写入参数修改审计事件。生产环境应由 ERP 网关鉴权并注入这些字段，浏览器端不应自行伪造用户身份。
