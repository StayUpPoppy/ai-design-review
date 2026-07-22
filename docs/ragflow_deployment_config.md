# RAGFlow 服务器部署配置说明

适用版本：RAGFlow `v0.26.0`（CPU + Elasticsearch）

## 目录与启动方式

- 部署配置目录：`~/ragflow-0.26.0/docker`
- 启动命令：`docker compose -p ragflow -f docker-compose.yml up -d`
- 查看运行状态：`docker compose -p ragflow -f docker-compose.yml ps`

使用 `-p ragflow` 为本次部署创建独立的容器、网络和数据卷命名空间，避免与服务器上已有应用混用。

## `.env` 关键配置

```ini
DOC_ENGINE=${DOC_ENGINE:-elasticsearch}
DEVICE=${DEVICE:-cpu}

RAGFLOW_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/infiniflow/ragflow:v0.26.0

# RAGFlow 网页与接口端口
SVR_WEB_HTTP_PORT=18080
SVR_WEB_HTTPS_PORT=18443
SVR_HTTP_PORT=19380
ADMIN_SVR_HTTP_PORT=19381
SVR_MCP_PORT=19382
GO_ADMIN_PORT=19383
GO_HTTP_PORT=19384

# 内部依赖：仅允许宿主服务器本机访问
ES_PORT=127.0.0.1:11200
EXPOSE_MYSQL_PORT=127.0.0.1:13306
MINIO_PORT=127.0.0.1:19000
MINIO_CONSOLE_PORT=127.0.0.1:19001
REDIS_PORT=127.0.0.1:16379
```

其中 `127.0.0.1:端口` 表示仅绑定到服务器本机；RAGFlow 容器之间仍通过 Docker 内部网络访问 MySQL、MinIO、Redis 和 Elasticsearch，不受影响。

## 对外访问规则

| 服务 | 宿主机端口 | 是否公网开放 | 用途 |
| --- | ---: | --- | --- |
| RAGFlow Web | 18080 | 是（验证阶段） | 浏览器登录：`http://服务器公网IP:18080` |
| RAGFlow HTTPS | 18443 | 后续按证书配置 | 正式环境建议通过域名和反向代理提供 HTTPS |
| RAGFlow API | 19380 | 按需 | 仅在业务后端需要跨服务器调用时开放，并限制来源 IP |
| Elasticsearch / MySQL / MinIO / Redis | 本机端口 | 否 | 仅用于本机排查，禁止安全组和防火墙对公网开放 |

正式上线时，建议由现有 OpenResty / 1Panel 反向代理对外提供 HTTPS，只开放 `443`，并关闭裸 `18080` 的公网访问。

## 密码与安全要求

以下变量必须设置为**四个不同的高强度随机密码**，但不得写入 Git、部署说明、聊天记录或截图：

```ini
ELASTIC_PASSWORD=<单独保存的随机密码>
MYSQL_PASSWORD=<单独保存的随机密码>
MINIO_PASSWORD=<单独保存的随机密码>
REDIS_PASSWORD=<单独保存的随机密码>
```

生成密码：

```bash
openssl rand -hex 32
```

当前若四项使用相同的短密码，仅适用于临时本地测试；在开放公网前必须更换为不同随机密码，并执行：

```bash
chmod 600 .env
```

首次创建管理员账号时可保留：

```ini
REGISTER_ENABLED=1
```

管理员账号创建完成后，改为：

```ini
REGISTER_ENABLED=0
```

## 启动前检查

```bash
docker compose -p ragflow -f docker-compose.yml config --quiet
docker compose -p ragflow -f docker-compose.yml config --images
sysctl vm.max_map_count
```

`vm.max_map_count` 必须不小于 `262144`。确认依赖镜像均可取得后，再启动服务。
