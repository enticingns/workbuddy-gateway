<p align="center">
  <img src="https://raw.githubusercontent.com/DGZSbot/ai-icon/refs/heads/main/WorkBuddy.png" alt="WorkBuddy2API" width="110">
</p>

<h1 align="center">WorkBuddy2API Panel · 维护分支</h1>

<p align="center">
  把 WorkBuddy / CodeBuddy 账号变成 OpenAI 兼容 API 的多账号网关<br>
  <sub>Go 单文件二进制 / Docker 镜像 · 附带 Web 管理面板</sub>
</p>

---

## 致谢

本项目是 **[Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)** 的增强分支（fork）。

- 上游仓库现已删除。本分支已完整吸收其删库前最后一次更新（`ea8b1e5`），此后独立演进，
  与上游不再有同步关系。
- 上游的设计——账号池调度与加权、错误分类、提示词体系、出站头族与归属头——原样保留；
  本分支只在其上做运维层重构（Web 面板、请求级日志、面板化配置）与上游协议跟进。
- 感谢原作者把这套东西开源出来。原项目以 MIT 协议发布，本分支沿用同一协议，见 [LICENSE](LICENSE)。

维护者：`enticingns` · 版本变更记录见 **[CHANGELOG.md](CHANGELOG.md)**

> ⚠️ 仅限自用账号（签到 / 保活 / 个人工具接入）。禁止批量注册小号、对外售卖额度、
> 二次加壳或卡密分发。由此产生的账号风控与封禁由使用者自行承担。

## 安装部署

### 环境要求

- **Docker + Docker Compose**（推荐），或 Windows / macOS / Linux 直接跑单文件二进制
- 一个或多个 WorkBuddy 账号，用于 OAuth 登录
- 宿主机 Go ≥ 1.22（仅从源码构建时需要）

### 方式 A：GHCR 预构建镜像（推荐，免编译）

```bash
mkdir -p auths data
cp config.example.json config.json      # 建议编辑 api_key；留空 = 不鉴权（公网必须设）

curl -fsSLO https://raw.githubusercontent.com/enticingns/workbuddy-gateway/main/docker-compose.ghcr.yml
docker compose -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.ghcr.yml up -d
```

镜像：`ghcr.io/enticingns/workbuddy-gateway:latest`（public 包，可匿名拉取）。

| tag | 来源 |
|---|---|
| `latest` / `main` | `main` 分支每次推送 |
| `sha-<7 位>` | 对应 commit，**生产建议钉这个**（回滚就是换 tag） |
| `1.2.3` / `1.2` / `1` | 打 `v*` tag 时发布 |

### 方式 B：源码构建（服务器本地编译）

```bash
git clone https://github.com/enticingns/workbuddy-gateway.git
cd workbuddy-gateway
cp config.example.json config.json
docker compose up -d --build            # 首次约 25–30 分钟（全量 Go 编译）
```

`docker-compose.yml` 用 `build: .`；`docker-compose.ghcr.yml` 用预构建镜像。两者容器名、端口、
卷、uid 完全一致，可随时互换。

### 方式 C：Windows 单文件（无需 Docker）

```powershell
go build -trimpath -ldflags="-s -w" -o wb2api.exe ./cmd/server
.\wb2api.exe -config config.json        # 首次自动生成 config.json（随机 api_key 打印一次）
```

exe 为单文件自包含（面板前端已 embed），拷到任意 Windows 机器即可运行，只需 `auths/` 与
`data/` 可写。

### 配置

`config.example.json` 是字段最完整的参考（示例值全是占位符，不含真实密钥）。最少要关心的几项：

| 字段 | 默认 | 说明 |
|---|---|---|
| `listen` | `:7863` | 监听地址 |
| `api_key` | 空 | 网关鉴权密钥；**空 = 不鉴权直接放行**，公网必须设置 |
| `auth_dir` / `state_file` | `./auths` / `./data/state.json` | 凭证目录 / 池状态 |
| `upstream.client_version` | `5.9.3` / `5.8.4` | 出站身份版本（跟随官方桌面端；缺省按域分档：CN / 国际） |
| `upstream.cli_version` | `2.165.0` / `2.161.0` | 出站身份版本（跟随官方内嵌 CLI；缺省按域分档） |
| `upstream.gzip_request_body` | `true` | chat 请求体 gzip（官方恒压；`false` 还原明文 body，排障用） |
| `upstream.timeout_seconds` | `120` | 短 RPC（刷新 / 签到 / 余额 / 模型列表）上限 |
| `upstream.header_timeout_seconds` | 回落上一项 | 聊天首字节前上限 |
| `upstream.idle_timeout_seconds` | `300` | 聊天流中空闲上限（活跃吐数据不掐） |
| `pool.max_in_flight` / `max_in_flight_global` | `3` / `2` | 单账号在途上限（国际版风控更紧，压低） |
| `pool.credit_floor` | `100` | 余额保底：低于此值的账号不接实测收费模型 |
| `prompt.mode` | `custom` | `custom` 替换客户端 system / `append` 追加 / `passthrough` 透传 |
| `logging.request_archive_enabled` | `true` | 请求元数据 JSONL 归档（不含提示词与正文） |

完整字段表见 `config.example.json` 内注释。环境变量 `WB2A_*`（非空才生效）可覆盖文件配置：
`WB2A_LISTEN` / `WB2A_API_KEY` / `WB2A_AUTH_DIR` / `WB2A_STATE_FILE` / `WB2A_TIMEOUT_SECONDS` 等。

> **出站身份**：默认值即「官方桌面端逐头对齐」（UA / `X-IDE-*` / `X-Product` / 会话头族 /
> `x-stainless-*` / `traceparent`+`b3` / `acp-connection-id` / gzip body），且**不再发送**
> 官方客户端从不发送的头（`Origin` / `Referer` / `Accept-Language` / `X-Machine-ID` /
> `X-Session-ID` / IP 透传）。改 `client_version` / `cli_version` / `user_agent` 之前请先看
> `CHANGELOG.md` 的实测记录——版本号不是越新越好，要与安装包内嵌 CLI 同轨。

> **海外服务器 + 国内版账号**：到 `copilot.tencent.com` 的 TLS 握手可能被重置，把
> `cn.chat_base` 指到 `https://www.workbuddy.cn` 即可（`billing_base` 留空走默认）。

### 添加账号

**Web 面板（推荐，全平台）**：打开 `http://<host>:7863/panel/` → 右上「添加账号」→ 浏览器完成
授权 → 凭证自动落盘 `auths/workbuddy-<uid>.json` → **热加载进池，无需重启**，顺带完成首次签到。

**命令行（Linux / macOS，需 bash + python3）**：

```bash
./login.sh     # 按提示授权，凭证落盘后自动重启容器
```

新增凭证文件即被自动发现；池在启动时也会用 `auths/` 目录自动对齐。

### 验证

```bash
# 健康检查（无可用账号返回 503）
curl -s http://localhost:7863/healthz
# {"healthy":9,"realm_servable":{"cn":true,"global":true},"total":9}

curl -s http://localhost:7863/v1/models -H "Authorization: Bearer <api_key>"
curl -s http://localhost:7863/status   -H "Authorization: Bearer <api_key>"

# 流式（注意：上游要求 messages[0] 为 system 且 stream=true，网关会按需补齐）
curl -sN http://localhost:7863/v1/chat/completions \
  -H "Authorization: Bearer <api_key>" -H 'Content-Type: application/json' \
  -d '{"model":"cn:deepseek-v4-flash","messages":[{"role":"user","content":"hi"}],"stream":true}'

# 非流式（网关本地聚合）
curl -s http://localhost:7863/v1/chat/completions \
  -H "Authorization: Bearer <api_key>" -H 'Content-Type: application/json' \
  -d '{"model":"global:deepseek-v4.1-flash","messages":[{"role":"user","content":"hi"}],"stream":false}'
```

模型名前缀：`cn:` 走国内版，`global:` 走国际版，不带前缀等价 `cn:`。

### 常用运维

```bash
docker compose logs -f                       # 跟踪日志
docker compose -f docker-compose.ghcr.yml pull && \
  docker compose -f docker-compose.ghcr.yml up -d --force-recreate   # 升级
docker compose down                          # 停止（auths/ 与 data/ 不受影响）
```

**部署后必须确认容器真的换了镜像**（`docker restart` 只重启旧容器，不换镜像）：

```bash
docker inspect workbuddy2api --format '{{.Image}}'
docker inspect ghcr.io/enticingns/workbuddy-gateway:sha-<commit> --format '{{.Id}}'   # 两者应一致
```

### 回滚

```bash
# 升级前先把旧镜像存住
docker tag workbuddy-gateway-wb2api:latest workbuddy-gateway-wb2api:rollback-$(date +%Y%m%d)

# 回滚到旧镜像（复用本地镜像，不重新编译）
docker compose -f docker-compose.yml up -d --force-recreate

# 或回滚到指定 commit 的 GHCR 镜像
sed -i 's|:latest|:sha-<commit>|' docker-compose.ghcr.yml
docker compose -f docker-compose.ghcr.yml up -d --force-recreate
```

数据全在宿主机挂载卷（`./auths`、`./data`、`./config.json`），换镜像不动数据。

## 从原版本升级

适用于：你正在跑原版（`Sliverkiss/workbuddy2api`）或本仓库更早的提交，要换到当前维护版。

### 1. 备份（三样东西）

```bash
tar czf wb2a-backup-$(date +%s).tgz auths data config.json
```

`auths/` 是明文凭证，`data/state.json` 是池状态（积分 / 冷却 / 计数 / 禁用标志），`config.json`
是配置。三者都已在 `.gitignore` 里，**不要提交 git**。

### 2. 部署新版（新目录，别覆盖旧目录）

```bash
git clone https://github.com/enticingns/workbuddy-gateway.git wb2a-new
cd wb2a-new
cp ../<旧目录>/config.json config.json     # 旧配置可直接用；没有就 cp config.example.json
```

旧 `config.json` 可以直接用：缺失的新字段走代码默认值，未知字段被忽略。若旧版 `config.json`
里没有 `upstream.client_version` / `cli_version`，新版按 5.9.2 / 2.176.0 出站。

### 3. 迁移数据

```bash
cp -a ../<旧目录>/auths/. ./auths/
cp -a ../<旧目录>/data/.  ./data/
chown -R 10001:10001 ./auths ./data && chmod 600 ./auths/*.json
```

### 4. 起新版并重建容器

```bash
docker compose up -d --build            # 或 -f docker-compose.ghcr.yml up -d
```

旧容器同名会被替换。**不要用 `docker restart`** —— 它不会换镜像，改了代码也照旧跑旧二进制。

### 5. 复活被禁用账号

旧版把 `disabled=true` 持久化在 `data/state.json`；重新登录**只覆盖凭证、不清这个标志**，
所以要显式复活：

```bash
curl -X POST http://127.0.0.1:7863/panel/api/accounts/<uid>/revive \
  -H "Authorization: Bearer <api_key>"
```

面板账号列表里点「复活 / 启用」等效。`<uid>` 是 `auths/workbuddy-<uid>.json` 文件名里那一段。

### 6. 验证

```bash
curl -s http://127.0.0.1:7863/healthz
# 期望 realm_servable 里 cn / global 都是 true

curl -s http://127.0.0.1:7863/v1/chat/completions \
  -H "Authorization: Bearer <api_key>" -H 'Content-Type: application/json' \
  -d '{"model":"global:deepseek-v4.1-flash","messages":[{"role":"user","content":"hi"}],"stream":false}'
```

`400 / code 11-128 / request illegal` = 归属头与 UA 平台名不一致（旧版国际版的已知问题，
本分支已修，见 [CHANGELOG.md](CHANGELOG.md)）；`400 / 11140` = 账号被上游封禁，需重新登录。

### 7. 升级后能感知到的行为差异

| 行为 | 旧版 | 本分支 |
|---|---|---|
| `stream` | 原样透传 | 上游要求 `stream:true`，网关按需补齐，`stream:false` 本地聚合 |
| 系统提示词 | 透传 | 默认 `custom` 替换为网关提示词（`prompt.mode` 可切回 `passthrough`） |
| 归属头 | 固定 `WorkBuddy` | 按账号 realm 注入（global → `WorkBuddy AI`） |
| 请求体大小 | 有上限 | 无预拦截，交给上游自然报错 |
| 日志 | 无请求级日志 | 每请求一行表格日志 + JSONL 归档（`data/request-logs/`） |

### 跟随官方客户端版本升级（可选）

官方桌面端 / CLI 发版后，把出站身份版本号跟着改一下即可，**无需重新构建**：

```bash
npm view @tencent-ai/codebuddy-code version      # 官方 CLI 版本
# 桌面端版本看安装包文件名，或解包 resources/app.asar.unpacked/cli/product.json 的 genieVersion
```

改 `config.json`：

```json
{ "upstream": { "client_version": "5.9.2", "cli_version": "2.176.0" } }
```

重启容器生效。这两个值当前**不被上游校验**（实测改值、空 UA 都能通过），同步只是为了降低
被识别为非官方客户端的确定性；真正的硬约束是国际版三个会话头非空
（`X-Conversation-ID` / `X-Conversation-Request-ID` / `X-Conversation-Message-ID`）。

> **别盲跟 npm 上的最新 CLI**：网关的 UA 身份是「桌面端 5.9.2 + 其内嵌 CLI」，而 5.9.2 安装包
> 内嵌的是 `@genie/agent-cli 2.165.0`。CLI 包单独发版并不代表桌面端身份变了，把 `cli_version`
> 跟到最新反而拼出官方不存在的组合。要跟的是**桌面端版本**（安装包的 `genieVersion`）。

用 GHCR 镜像时，镜像内的代码默认值由 CI 构建时的源码决定；配置项优先级高于代码默认值。

## 文档

| 文件 | 内容 |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录（按日期倒序） |
| `config.example.json` | 全部配置项与默认值 |
| `README.md` | 本文（致谢 / 安装部署 / 从原版本升级） |
