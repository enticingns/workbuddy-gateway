# 变更记录

本分支（[enticingns/workbuddy-gateway](https://github.com/enticingns/workbuddy-gateway)）的版本变更。
按日期倒序，最新在最上面。安装与升级步骤见 [README.md](README.md)。

---

## 2026-10-28：出站身份对齐官方实测值（真机抓包驱动）

### 背景：之前的身份是**推断**出来的

2026-10-23 的 11-128 修复把 global 归属头改成 `WorkBuddy AI`，理由是「与 UA 平台段一致」。
方向对，但取值是推断的。本轮用两种方式拿到**官方真值**：

1. **安装包静态分析**（`app.asar` 反查客户端自己的头构造代码）；
2. **真机抓包**：把国际版 `product.json` 的 `endpoint` 临时指向本机抓包代理（明文入 / TLS 出），
   完整跑通登录态下的启动序列 + 3 轮对话，抓到 **166 个请求 / 5 条 chat**（含辅助的
   `conversation_topic` 与主对话 `conversation`）。

### 实测身份（两版不同轨）

| | CN | global |
|---|---|---|
| 桌面端 | **5.9.3**（commit `d469242`） | **5.8.4**（commit `73952edb`） |
| 内嵌 CLI | **2.165.0** | **2.161.0** |
| applicationName | `WorkBuddy` | `workbuddy-ai` |
| 出站 UA | `WorkBuddy/5.9.3 WorkBuddy/5.9.3 CLI/2.165.0` | `WorkBuddy/5.8.4 workbuddy-ai/5.8.4 CLI/2.161.0` |

关键纠正：**`WorkBuddy AI` 从不出现在真实 UA 里**（它只是 productName）；UA 第二段是
`applicationName`（global 为小写连字符 `workbuddy-ai`）。`X-IDE-Name`/`X-IDE-Type` 两域都是
`WorkBuddy`，`X-Product` 两域都是 `SaaS`。

### 改动

- `headers.go`：版本常量按 realm 拆分（CN 5.9.3/2.165.0、global 5.8.4/2.161.0）；
  新增 `clientVersionFor` / `cliVersionFor`；UA 第二段改用 `applicationName`；
  归属头改为 `X-IDE-Name/Type=WorkBuddy` + `X-Product=SaaS`，并补
  `X-Private-Data: true` / `X-Agent-Intent: craft` / `X-Agent-Type: main`。
  显式 `user_agent` / `client_version` / `cli_version` / `client_name` 配置仍然优先（零回归）。
- 测试期望值同步（`useragent_test` / `shortua_test` / `global_models_routes_test`）。

### 监控机复现验证（独立探针，不经网关）

用真实账号 + 真机头族在监控机上复跑 8 个场景，**两域各 8/8 通过**：

```text
real / no_stainless / no_acp / no_trace / no_misc / gateway_now / gateway_plus / real_plus
```

结论：上游当前**不校验**这些头（连 `gateway_now` 那套错身份都是 200），所以本次对齐是
「消除被识别为非官方客户端的确定性风险」，不是修某个失败的校验。

> 国内侧第一次跑全挂 `400 / 11102 model [default-model] service info not found`——那是
> **body 里的模型别名**问题（`default-model` 是国际版别名，国内版不认），与头无关；
> 换真实 CN 模型名后 8/8 通过。

---

## 2026-10-27 ~ 10-28

### 巡检误报：单账号探针把「账号被封」报成了「国际版失败」

**现象**：10-27 06:31 / 13:03 / 19:10 三次告警 `🌐 国际版失败: HTTP=403 code=11140 request illegal`，
看起来像上游又改了协议。

**定位**（同一模型、同一天、四组对照）：

| 探针对象 | 结果 |
|---|---|
| `账号 A`（global，探针原用号，凭证为 10-25 保存的旧值） | `403 / 11140 request illegal` |
| 同一账号，改用网关 10-28 06:00 刷新后的凭证 | `403 / 11140` —— **不是凭证过期** |
| `账号 B`（global） | `200` |
| `账号 C`（global） | `200` |
| 网关 `/healthz` | `cn` / `global` 均 servable，当天 global 请求全 `200` |

**结论**：通道正常，是**那一个账号**被上游限制（11140 `request illegal` 在网关侧同样归
`ErrAccountFault` → 硬禁用）。网关近 48h 日志里一条 11140 都没有——它没再选到该号。

**处理**：

- 该号在池里人工禁用（`POST /panel/api/accounts/<uid>/disable`）：`healthy` 9 → 8，
  `global` 仍 servable。后续可在 WorkBuddy 内申诉后 `revive`。
- 探针改为**多账号轮换**：`accounts/<realm>/*.json` 逐个试，任一号成功即视为通道正常；
  全部失败才告警，并按错误码分流文案：
  - 账号级（`11140` / `14017` / `12153` / HTTP 401）→
    `🔑 …探针账号全部不可用（试了 N 个）—— 通道状态未知，换一个可用账号做探针`
  - 其它（网络 / 5xx / 协议）→ `🌐 …通道异常`
- 判定实测：只放被封号 → `kind=account codes=11140`；被封号 + 健康号 → `ok=true used=账号B tried=2`。
- 探针账号：两域各 3 个（文件名 `accounts/<realm>/*.json`，0600，从网关 `auths/` 拷贝）；
  具体账号标识不入库。

### 官方 CLI 2.177.0 → 2.177.1：只记录，不跟进

- npm `@tencent-ai/codebuddy-code` 10-26 升 2.177.0、10-27 升 2.177.1，巡检两次都报了。
- **不跟进**，两条理由：
  1. 网关的 UA 身份是「桌面端 5.9.2」（`WorkBuddy/5.9.2 WorkBuddy/5.9.2 CLI/<ver>`），而 5.9.2
     安装包里内嵌的是 `@genie/agent-cli 2.165.0`；把 CLI 段跟到 npm 最新，只会造出一个官方从未
     存在过的组合，反而不像真客户端。
  2. 这两个值当前不被上游校验（实测改值、空 UA 全部 200），跟了没有功能收益。
- 真正要跟的信号是**桌面端发新版**（巡检的 `desktop_cn_version` 变化）——那才是用户实际装的客户端。

---

## 2026-10-26

### 版本同步：桌面端 5.9.2 / CLI 2.176.0

官方桌面端升到 **5.9.2**（`WorkBuddy-win32-x64-user-5.9.2.42136757-0b5051be.exe`），
官方 CLI 升到 **2.176.0**（npm `@tencent-ai/codebuddy-code`）。

| 位置 | 5.5.4 时代 | 2026-10-24 | 当前 |
|---|---|---|---|
| `defaultClientVersion` | 5.5.4 | 5.8.4 | **5.9.2** |
| `defaultCliVersion` | 2.137.1 | 2.168.2 | **2.176.0** |
| `desktopUA`（CN 桌面端） | 5.5.6 / CLI 2.137.1 | 5.8.3 / CLI 2.168.2 | **5.9.2 / CLI 2.176.0** |

涉及提交：`b385c0e`（headers.go）、`0e51a63`（desktop.go）、`3abcba0`（client.go 注释）、
`784c84e` / `3fc39fe`（测试期望值）、`dde398d`（config.go 注释）。

官方 CN 桌面端解包实测的基线（可用于比对官方是否又改版）：

```text
productName  WorkBuddy            applicationName  WorkBuddy
genieVersion 5.9.2                commit           0b5051be70a4899bb5dc6497cd2275e912abe953
date         2026-10-24T08:44:37.992Z
endpoint     https://www.workbuddy.cn     installChannel.mode  official
```

### 部署：切换到 GHCR 预构建镜像

服务器不再本机编译（首次构建约 25–30 分钟，编译期 load 很高，SSH 反复掉线）。
新增 `docker-compose.ghcr.yml`，部署变成 `pull` + `up -d --force-recreate`（约 30 秒）。

- 新增 `.github/workflows` 的 `docker-ghcr`：推送 `latest` / `main` / `sha-<7 位>`，public 包
- 实测：`sha-bf783a4` 在 7864 临时容器验证通过（`healthy:9`、55 模型、二进制内含新代码）
- 正式切换：旧镜像打 `rollback-20261026` 标签 → `up -d --force-recreate` → 校验容器镜像 ID 一致
- 提交：`eeda19f`（compose）、`b52bec5`（README）

### 修复：`400` 无 model / 无 account 的观测盲区

读请求体失败（客户端发送途中断开 / 中间层掐断 / 体积超限）时网关只回 400，不落任何日志，
事后只剩「400 + 20ms + 无 model」三个线索。现在补一行 WARN，带来源 IP、UA 与原始错误：

```text
WARN: [server] read body failed from 203.0.113.7 ua="deepseek-harness/0.2.1-rc.2": unexpected EOF
```

`unexpected EOF` = 客户端断流；`http: request body too large` = 撞上大小上限。
同一根因的另两种表现（流式写回失败记 `interrupted`、客户端断开导致上游 context 取消记 503）
此前已有记录，这次补齐了最早的那一环。提交：`bf783a4`。

### 运维：独立探针（不经过网关）

独立机器上用真实账号直连上游，四个工具：

| 工具 | 用途 |
|---|---|
| `wb_probe.py` | 任意增删改请求头后发真实请求，观察上游接受 / 拒绝 |
| `wb_ablation.sh` | 逐个头删除，找出硬门槛 |
| `wb_valuetest.sh` | 保留头但改值，判断上游是否校验「值」 |
| `wb_extract.py` | 解包 npm / VSIX / 桌面端安装包，提取版本号与头名清单，与 `baseline.json` 比对 |

systemd timer 每 **6~7 小时随机**（`OnUnitActiveSec=6h` + `RandomizedDelaySec=1h`），异常推 Telegram。

本轮修正：

- `wb_extract.py` 的 NSIS **双层**解包：外层 exe → `$PLUGINSDIR/app-64.7z` → `resources/`。
  内层路径里的 `$` 未加引号会被 shell 展开成空串，7z 静默失败，桌面端基线长期停在
  「app.asar not found」，看起来像「官方没变化」。改为 `shlex.quote` + 优先读
  `app.asar.unpacked/cli/product.json` + 复用已解包目录。
- 桌面端（CN）版本纳入巡检比对（此前只跟 CLI）；差异按 `desktop_cn` 前缀单独告警。
- 探针失败自动重试一次：实测 22:23:29 报 `HTTP 401`，9 秒后复测即恢复，单次失败纯噪声。
- 状态文件改原子写（tmp + rename）：此前 jq 写失败会让告警去重失忆，同一问题每轮重发。

### 文档

README 重构：只保留对原仓库的致谢 + 本维护版的安装部署 + 从原版本升级；变更记录拆到本文件。
提交：`8a28e05`、`726e08d`。

### 实测发现（探针结论，非代码变更）

| 结论 | 证据 |
|---|---|
| 出站身份版本号**不被校验** | `X-IDE-Version=9.9.9`、`X-IDE-Type=Hacked`、`User-Agent=curl/8.13.0`、空 UA 全部 `200` |
| 国际版硬约束 = 三个会话头非空 | `X-Conversation-ID` / `X-Conversation-Request-ID` / `X-Conversation-Message-ID` |
| 国内版不校验会话头 | 只带 `Authorization` 也 `200` |
| `messages[0]` 必须是 `system` | 否则 `400 / 11-128 / first message is not system prompt` |
| 必须 `stream: true` | 否则 `400 / 11101 / Non-stream chat request is currently not supported` |

所以版本同步属于**一致性维护**（降低被识别为非官方客户端的确定性），不是修某个失败的校验。

---

## 2026-10-24

### 修复：DSH 身份句消毒（`5d81941`）

上游对 system prompt 里「自我介绍句式 + 品牌」做大小写不敏感的连续子串匹配，命中即
`400 / code 11-128`。新增 `sanitizeDshRe` 正则：

- 动词覆盖 `powered by` / `built on` / `built by` / `created by` / `developed by` /
  `made by` / `trained by`
- 品牌名支持多词（`DeepSeek Harness`、`deepseek-v4.1-flash` 等）
- 修饰词 0~3 个、名词可选（`agent` / `assistant` / `model` 或省略）
- 分词修饰宾语（`"You are free to use tools built by X"`）不匹配，保持原样

命中后替换为 `"You are a helpful AI assistant."`。

### 配置：CN 上游地址切换（海外服务器）

海外服务器到 `copilot.tencent.com` 的 TLS 握手会被重置，CN 账号的计费 / 上报 / 任务全部超时。
`cn.chat_base` 指向 `https://www.workbuddy.cn` 即可：

```json
{ "cn": { "chat_base": "https://www.workbuddy.cn", "billing_base": "", "enabled": true } }
```

配置项此前已存在于 `cmd/server/config.go`，只是部署文档没提。

### 版本号对齐

`defaultClientVersion` 5.5.4 → **5.8.4**，`defaultCliVersion` 2.137.1 → **2.168.2**，
`desktopUA` → 5.8.3 / CLI 2.168.2（提交 `5d81941`）。

---

## 2026-10-23

### 修复：国际版 `11-128 request illegal`（`dc172a6`）

**现象**：国际版维护后，global 账号 chat 请求返回 `400 / code 11-128 / request illegal`，
`displayTips` 为「This call failed channel verification, possibly because it was not sent from
an official client」。

**根因**：归属头（`X-IDE-Name` / `X-IDE-Type` / `X-Product`）硬编码为 `"WorkBuddy"`，而国际版
出站 UA 是 `"WorkBuddy AI/<ver>"`。上游按 UA 里的产品名与归属头做一致性校验，不匹配即拒。

**修复**：归属头按账号 realm 动态注入——global → `"WorkBuddy AI"`，CN → `"WorkBuddy"`。
涉及 `injectAttribution` / `attributionClientName` / `billingUA`，均改为 realm-aware 并保留
无参兼容包装。`Classify()` 把 11-128 归到 `ErrChannelRefused`（不是账号故障，不罚号）。

**部署教训（`78e1aa8` 写进文档）**：

- `docker restart` 只重启旧容器，**不换镜像**。改了代码必须
  `docker compose up -d --force-recreate`，并用 `docker inspect` 比对镜像 ID。
- 重新登录只覆盖 `auths/*.json`，**不清** `data/state.json` 里的 `disabled=true`；
  重登后还要 `POST /panel/api/accounts/<uid>/revive`。

---

## 2026-09-14

### 吸收上游删库前最后一次更新（`ea8b1e5`）

| 上游改动 | 吸收内容 |
|---|---|
| 净化增强 | `tool_calls.arguments` 盲区修复（`content=null` 的工具调用轮此前完全漏净化）、裸 `11-128` 反探测改写、桌面版身份句（逗号形态）漏网修复、反馈句整句改写 |
| 出站头族 | UA 对齐官方三段式 `WorkBuddy/<ver> WorkBuddy/<ver> CLI/<ver>`；`X-IDE-*` 用量归属四头 + `X-Agent-Purpose`；`X-Device-Token` 设备风控头（auth 每号 / config / 文件三源）；`X-IDE-Version` 补齐 |
| 并发修复 | 客户端 IP 改按请求参数传递（消除共享字段竞态）；billing 单段 UA 形态 |
| 签到幂等 | `IsAlreadyCheckin` 识别「今天已签到」（code 10001 / 14001），调度日志不再把重复签到当失败 |
| 粘性按模型判活 | 绑定账号被 6004 模型级限额后，换模型请求自动解绑重分配；`/healthz` 探活计入模型豁免形态 |
| report 增强 | `ReportChatActivity` 支持独立 `requestID`（同会话多轮上报可区分） |

未吸收（明确不做）：上游脚本体系（task_runner / school，本分支已有更完整的纯 API 实现）、
governance / CI workflow、成本账本选号（依赖 `usage.credit` 观测，收益待验证）。

---

## 更早：fork 基线（`53ee3a1` → `9a87758`，34 个提交）

四类任务独立排程、pool 文件拆分、12153 连续计数才禁用、429 `code=6004` 模型级限流收窄、
11101 不罚号、请求体 413、DeepSeek 思维链、`reasoning_content` 回填、Codex 指纹脱敏、
系统提示词体系、出站 UA 可配。

Web 管理面板（账号 / 配置 / 模型 / 积分 / 请求日志）为本分支在原版之上新增的运维层。
