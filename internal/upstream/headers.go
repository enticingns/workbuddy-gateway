// Package headers 构造三类上游请求头（common / chat / billing / refresh）。
// 规则来自 docs/api-reference.md §0/§4/§6，出站头族以真机抓包（2026-10-28，
// CN 5.9.3 / intl 5.8.4 双域全量请求）为唯一基准。
package upstream

import (
	"net/http"
	"strings"
	"sync"

	"github.com/enticingns/workbuddy-gateway/internal/auth"
	"github.com/enticingns/workbuddy-gateway/internal/session"
)

const (
	// 官方分发包实测版本（2026-10-28：安装包解包 + 真机抓包）——两版**不同轨**：
	//   CN     桌面 5.9.3（commit d469242）/ 内嵌 CLI 2.165.0
	//   global 桌面 5.8.4（commit 73952edb）/ 内嵌 CLI 2.161.0
	// config upstream.client_version / cli_version 非空时**同时覆盖两域**（兼容旧配置）。
	defaultClientVersionCN     = "5.9.3"
	defaultCliVersionCN        = "2.165.0"
	defaultClientVersionGlobal = "5.8.4"
	defaultCliVersionGlobal    = "2.161.0"

	// 旧名保留：默认账号形态即 CN，零回归兼容既有调用点/测试。
	defaultClientVersion = defaultClientVersionCN
	defaultCliVersion    = defaultCliVersionCN

	// X-Domain 声明头取值（两域真机抓包实测：所有出站请求都带且等于该域主机名）。
	domainCN     = "www.workbuddy.cn"
	domainGlobal = "www.workbuddy.ai"

	// 官方内置 CLI 的 openai-node 运行时指纹（x-stainless-* 头族，真机抓包实测，
	// 两域同值、逐请求恒定）：node v22.21.1 + openai SDK 6.25.0 + Windows x64。
	// 官方客户端不做任何随机化，故这里也取确定值。
	stainlessArch           = "x64"
	stainlessLang           = "js"
	stainlessOS             = "Windows"
	stainlessPackageVersion = "6.25.0"
	stainlessRuntime        = "node"
	stainlessRuntimeVersion = "v22.21.1"
)

// realmDomain 返回账号 realm 对应的 X-Domain 声明值：global → www.workbuddy.ai，
// cn → www.workbuddy.cn。登录会话带自定义 Domain 时以会话值为准（DomainValue）。
func realmDomain(a *auth.Auth) string {
	if a != nil {
		if d := strings.TrimSpace(a.DomainValue()); d != "" {
			return d
		}
		if a.IsGlobal() {
			return domainGlobal
		}
	}
	return domainCN
}

// clientVersion 生效的 WorkBuddy 客户端版本：Client.ClientVersion 非空则取之，
// 否则内置默认 defaultClientVersion。
func (c *Client) clientVersion() string {
	return c.clientVersionFor(nil)
}

// clientVersionFor 按账号 realm 取桌面端版本：显式 ClientVersion 优先（同时作用于两域），
// 否则 CN 5.9.3 / global 5.8.4（官方两个分发包不同轨，实测值）。
func (c *Client) clientVersionFor(a *auth.Auth) string {
	if c != nil && c.ClientVersion != "" {
		return c.ClientVersion
	}
	if a != nil && a.IsGlobal() {
		return defaultClientVersionGlobal
	}
	return defaultClientVersionCN
}

// cliVersion 生效的 CLI 版本：Client.CliVersion 非空则取之，否则内置默认 defaultCliVersion。
func (c *Client) cliVersion() string {
	return c.cliVersionFor(nil)
}

// cliVersionFor 按账号 realm 取内嵌 CLI 版本：显式 CliVersion 优先，
// 否则 CN 2.165.0 / global 2.161.0（取自各自安装包 package.json / customPackage）。
func (c *Client) cliVersionFor(a *auth.Auth) string {
	if c != nil && c.CliVersion != "" {
		return c.CliVersion
	}
	if a != nil && a.IsGlobal() {
		return defaultCliVersionGlobal
	}
	return defaultCliVersionCN
}

// defaultWorkBuddyUAFor 组装默认客户端出站 UA（官方桌面端 RestOperations 层形状）：
// `WorkBuddy/<clientVersion> <platform>/<clientVersion> CLI/<cliVersion>`。
// 平台段（第二段）品牌按 realm 切换——CN 用 applicationName 同值 `WorkBuddy`，
// global 用官方国际版 productName `WorkBuddy AI`（intl 项目逆向证据：
// `WorkBuddy/5.5.2 WorkBuddy AI/5.5.2 CLI/5.5.2`）。
// global 账号送错平台段（`WorkBuddy` 非 `WorkBuddy AI`）可能触发上游 403 code 11140
// "request illegal" 风控。官方无任何 UA 随机化，故默认确定性。
func (c *Client) defaultWorkBuddyUAFor(a *auth.Auth) string {
	// 真机抓包实测（2026-10-28，global 5.8.4）：
	//   `WorkBuddy/5.8.4 workbuddy-ai/5.8.4 CLI/2.161.0`
	// 第二段是 applicationName（global=`workbuddy-ai`、CN=`WorkBuddy`），**不是** productName
	// （`WorkBuddy AI` 只是 productName，实测不出现在 UA 里）。两段版本号同源但按 realm 取值。
	platform := "WorkBuddy"
	if a != nil && a.IsGlobal() {
		platform = "workbuddy-ai"
	}
	ver, cli := c.clientVersionFor(a), c.cliVersionFor(a)
	return "WorkBuddy/" + ver + " " + platform + "/" + ver + " CLI/" + cli
}

// defaultWorkBuddyUA 返回 CN 形态的默认 UA（默认账号形态即 CN，零回归兼容既有调用/测试）。
func (c *Client) defaultWorkBuddyUA() string {
	return c.defaultWorkBuddyUAFor(nil)
}

// userAgent 返回当前出站 UA（客户端出站路径：chat/refresh/FetchModels）。
// 优先级：Client.UserAgent（config user_agent）显式覆盖 > 按账号 realm 的默认 WorkBuddy 三段式。
// 显式覆盖兼容既有覆盖逻辑：用户配了即以用户值为准（自定义品牌/版本），
// 未配则走官方桌面端默认形态（global 换 `WorkBuddy AI` 平台段）。
func (c *Client) userAgent(a *auth.Auth) string {
	if c != nil && c.UserAgent != "" {
		return c.UserAgent
	}
	return c.defaultWorkBuddyUAFor(a)
}

// billingUA 白名单类（billing/checkin/banner）出站 UA：单段 `WorkBuddy/<clientVersion>`
// （官方 banner 显式覆写形态，不带 CLI 段）。默认生效（伪造官方桌面端指纹）；
// 显式 client_name="SaaS" 才不设 UA（还原旧行为，Go 默认 UA）。
// global 账号用 `WorkBuddy AI/` 平台段（对齐国际版 productName，通道校验一致性）。
func (c *Client) billingUA() string {
	return c.billingUAFor(nil)
}

// billingUAFor 按账号 realm 返回 billing UA：global → "WorkBuddy AI/<ver>"，CN → "WorkBuddy/<ver>"。
func (c *Client) billingUAFor(a *auth.Auth) string {
	if c == nil || c.attributionClientNameFor(a) == "SaaS" {
		return ""
	}
	if a != nil && a.IsGlobal() {
		return "WorkBuddy AI/" + c.clientVersion()
	}
	return "WorkBuddy/" + c.clientVersion()
}

// resolveDeviceToken 解析本次请求的 X-Device-Token 取值。
// 优先级：auth.Auth.DeviceToken（每号）> Client.DeviceToken（config 全局）> 文件兜底。
// 三者皆空/读失败则返回空串（调用方不注入该头，优雅降级）。
func (c *Client) resolveDeviceToken(a *auth.Auth) string {
	if a != nil && a.DeviceToken != "" {
		return a.DeviceToken
	}
	if c != nil && c.DeviceToken != "" {
		return c.DeviceToken
	}
	if c != nil && c.DeviceTokenFile != "" {
		return readDeviceTokenFile(c.DeviceTokenFile)
	}
	return ""
}

// injectDeviceToken 在 req 注入 X-Device-Token 头（仅当取到非空 token）。
func (c *Client) injectDeviceToken(req *http.Request, a *auth.Auth) {
	if tok := c.resolveDeviceToken(a); tok != "" {
		req.Header.Set("X-Device-Token", tok)
	}
}

// injectStainless 注入官方 openai-node SDK 的运行时指纹头（x-stainless-* 七头）。
// 真机抓包（2026-10-28，两域 chat 请求逐请求恒定）：
//
//	x-stainless-arch: x64 / lang: js / os: Windows / package-version: 6.25.0
//	x-stainless-retry-count: 0 / runtime: node / runtime-version: v22.21.1
//
// 这是「请求来自官方内置 CLI 的 Node 运行时」的正面证据；缺这一族头等于自报
// 「非官方客户端」，属额外指纹面（P1 减法/补正：官方发什么就发什么）。
func injectStainless(req *http.Request) {
	req.Header.Set("x-stainless-arch", stainlessArch)
	req.Header.Set("x-stainless-lang", stainlessLang)
	req.Header.Set("x-stainless-os", stainlessOS)
	req.Header.Set("x-stainless-package-version", stainlessPackageVersion)
	req.Header.Set("x-stainless-retry-count", "0")
	req.Header.Set("x-stainless-runtime", stainlessRuntime)
	req.Header.Set("x-stainless-runtime-version", stainlessRuntimeVersion)
}

// acpOnce/acpID 本进程的 acp-connection-id（进程级惰性生成一次：一次部署=一个
// 网关连接，语义上比逐请求新值更贴近官方——官方每个连接内恒定，不会每请求换）。
// 包级而非 Client 实例字段：同一网关进程内 CN/global 双域 Client 共享同一 ID，
// 对齐官方"一个 agent 连接一个 ID"；sync.Once 保证并发安全且只生成一次。
var (
	acpOnce sync.Once
	acpID   string
)

// acpConnID 返回本进程的 acp-connection-id（ACP = agent-client-protocol 连接标识，
// 官方桌面端每个本地 agent 连接一个 UUIDv7，形如
// `01a180b4-1035-76a0-9af0-60e38e012500`）。进程级惰性生成一次。
func acpConnID() string {
	acpOnce.Do(func() {
		acpID = session.NewUUIDv7()
	})
	return acpID
}

// injectACP 注入 acp-connection-id（仅 chat 路径；官方其他端点不带）。
func (c *Client) injectACP(req *http.Request) {
	if id := acpConnID(); id != "" {
		req.Header.Set("acp-connection-id", id)
	}
}

// CommonHeaders 设置所有 API 共享的请求头。
//
// **减法原则（2026-10-28 真机抓包基线）**：官方桌面端是 Electron/Node 层出站，
// 不是浏览器 fetch——Origin / Referer / Accept-Language **一个都不发**（全量抓包
// 134+166 条请求零命中）。此前网关代为补这三头，等于给上游一个「非官方客户端」
// 的额外指纹面；已按实测移除。需要 Origin/Referer 的站点域请求（领奖 Web 域、
// 个人资料页、注册链路）各自显式设置（tasks.go / profile.go / global_register.go）。
func (c *Client) CommonHeaders(req *http.Request, a *auth.Auth) {
	req.Header.Set("Content-Type", "application/json")
	// Accept 非流式默认 application/json（D6：去掉宽松的 text/plain, */*）。
	// chat 路径恒 application/json（实测：官方聊天请求也发 application/json，
	// 上游只看 body.stream 决定是否 SSE），见 ChatHeaders。
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", c.userAgent(a))
	// X-CodeBuddy-Request: 1（官方客户端风控闸门头，所有 API 请求必带，D1）。
	req.Header.Set("X-CodeBuddy-Request", "1")
	// X-Product: SaaS（= deploymentType，官方全量请求 111/134 命中，恒 SaaS）。
	req.Header.Set("X-Product", "SaaS")
	// X-Domain 声明域（官方全量请求 166/166 命中）。
	req.Header.Set("X-Domain", realmDomain(a))
}

// acceptLanguageFor 按账号 realm 返回 Accept-Language：global → en-US，cn → zh-CN。
// **仅 billing 域使用**：官方 chat 路径不发该头（实测），billing/console 路径按域
// 发 en(-US) / zh(-CN)。
func acceptLanguageFor(a *auth.Auth) string {
	if a != nil && a.IsGlobal() {
		return "en-US"
	}
	return "zh-CN"
}

// injectCodeBuddyRequest 在 req 注入 X-CodeBuddy-Request: 1。
// billing 域未走 CommonHeaders，单独注入保证全出站覆盖（D1）。
func (c *Client) injectCodeBuddyRequest(req *http.Request) {
	req.Header.Set("X-CodeBuddy-Request", "1")
}

// ChatMeta 一次 chat 出站的会话头族元数据（issue #35：后台按 X-Conversation-Request-ID
// 聚合请求，官方客户端一次 user send 内所有 tool call/重试/换号复用同一个 ID）。
// handler 在轮转循环外生成 conversationID / conversationRequestID，循环内每次出站
// 复用同值；TraceID 透传入站值（空 = 回落 conversationRequestID）。
// messageID（消息级，每条独立）由 ChatHeaders 内部生成，无需外部可见。
type ChatMeta struct {
	ConversationID        string // X-Conversation-ID：body 提取的入站值，空则不发（透传优先，不伪造）
	ConversationRequestID string // X-Conversation-Request-ID / X-Root-Request-ID：聚合主键，必发
	TraceID               string // X-Trace-ID：入站透传值，空则回落 conversationRequestID
}

// ChatHeaders 在 common 之上加 chat 专属的账号头。
// 缺省字段用 X-No-* 约定（与 CodeBuddy 官方 CLI 一致）。
//
// clientIP **已废弃**（保留参数仅为签名兼容）：官方客户端从不发
// X-Forwarded-For / X-Real-IP / X-Client-IP，上游 IP 透传属额外指纹面，
// 见 config upstream.passthrough_ip 的废弃说明。
// meta 为会话头族元数据（纯新增，不改既有头），见 injectConversationHeaders。
func (c *Client) ChatHeaders(req *http.Request, a *auth.Auth, clientIP string, meta ChatMeta) {
	_ = clientIP // 废弃：不再透传客户端 IP（官方不发，见 config passthrough_ip）
	c.CommonHeaders(req, a)
	// 实测：官方 chat 请求 Accept 恒 application/json（上游按 body.stream 决定 SSE），
	// 且只有 chat 路径带 X-Requested-With: XMLHttpRequest。
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	// AccessToken 加锁快照：keepalive 定时刷新会在 a.mu 内改写它，锁外直读构成数据竞争
	// （见 auth.AccessTokenValue 注释）。
	if at := a.AccessTokenValue(); at != "" {
		req.Header.Set("Authorization", "Bearer "+at)
	} else {
		req.Header.Set("X-No-Authorization", "1")
	}
	if a.UID != "" {
		req.Header.Set("X-User-Id", a.UID)
	} else {
		req.Header.Set("X-No-User-Id", "1")
	}
	// 安全红线：绝不在 chat 请求里携带 X-Refresh-Token。
	// 企业与域头按 realm 分发：CN 走既有分支（EnterpriseID 原样透传，缺省 X-No-*）；
	// global 账号由 injectGlobalChatHeaders 统一覆写为国际客户端形态
	// （X-No-Enterprise-Id=1 声明无企业），X-Domain 由 CommonHeaders 统一按域声明
	// （alignment 后不再按 EnterpriseID 缺省改写域头的语义分支）。
	if a != nil && !a.IsGlobal() {
		if a.EnterpriseID != "" {
			req.Header.Set("X-Enterprise-Id", a.EnterpriseID)
		} else {
			req.Header.Set("X-No-Enterprise-Id", "1")
		}
	} else {
		c.injectGlobalChatHeaders(req, a)
	}
	// 官方 openai-node 运行时指纹族 + ACP 连接标识（实测 chat 必带）。
	injectStainless(req)
	c.injectACP(req)
	// 用量归属头：默认伪造桌面端指纹（ClientName 空按 realm 取 "WorkBuddy"/"WorkBuddy AI"）。
	c.injectAttribution(req, a)
	// 设备风控头：auth 每号 > config 全局 > 文件兜底；空则不注入。
	c.injectDeviceToken(req, a)
	// 会话头族（对话/请求/消息/B3 链路/traceparent/baggage），见 injectConversationHeaders。
	c.injectConversationHeaders(req, a, meta)
}

// injectGlobalChatHeaders global 账号（无企业 ID）的 chat 专属声明头，对齐 intl 项目
// （ANALYSIS-global-chat-solutions.md）：
//   - X-No-Enterprise-Id: 1  个人账号无企业 ID，显式声明（避免上游按缺省/可疑判定）
//
// X-Domain / Origin / Referer 不在此处：X-Domain 由 CommonHeaders 全出站声明，
// Origin/Referer 官方客户端从不发送（已移除）。
//
// 仅 global realm 注入；CN 账号走既有 X-No-Department-Info 等分支，零回归。
func (c *Client) injectGlobalChatHeaders(req *http.Request, a *auth.Auth) {
	if a == nil || !a.IsGlobal() {
		return
	}
	req.Header.Set("X-No-Enterprise-Id", "1")
}

// injectConversationHeaders 注入官方客户端会话头族（issue #35 后台聚合）。
// 头族分五层，各司其职：
//   - X-Conversation-ID：会话级，多轮稳定（body 的 conversationId）；缺省补 UUIDv7
//     （官方形态带横线；国际端点缺该头直接 400 / 11-128）。
//   - X-Conversation-Request-ID：**对话轮级聚合主键**，必发。一次 user send 内的
//     所有 tool call/重试/换号/降级复用同一个 → 后台按它聚合成一条（不再碎片化）。
//   - X-Conversation-Message-ID = X-Request-ID：消息级，每条独立（32 位 hex）。
//   - X-Root-Request-ID：= conversationRequestID（根请求追踪）。
//   - X-Trace-ID：入站透传或 = conversationRequestID。
//   - X-B3-TraceId / X-B3-SpanId / X-B3-Sampled：链路族。B3 规范只认 16/32 hex
//     TraceId 与 16 hex SpanId；入站 conversationRequestID 非法时 TraceId 回落
//     messageID（恒 32 hex），SpanId 取 messageID[:16]（每消息新）。
//   - traceparent / b3（单头）/ baggage：同一 TraceId/SpanId 的 W3C + Zipkin 双格式
//     与上游 baggage 语义（baggage、X-Agent-Runtime 仅 CN 携带，见函数尾）。
func (c *Client) injectConversationHeaders(req *http.Request, a *auth.Auth, meta ChatMeta) {
	convReqID := meta.ConversationRequestID
	if convReqID == "" {
		// 零值 meta（直接调 ChatHeaders 的调用方/测试）也要保证聚合主键必发：
		// 本级补一个 32 hex，调用方（handler）已生成稳定的不走到这里。
		convReqID = session.NewMessageID()
	}
	messageID := session.NewMessageID()
	// 会话头三元组必须齐全：国际端点收紧通道校验后，缺 X-Conversation-ID 的
	// 请求会直接 400 / 11128（conversation id missing）。入站没带会话 ID 时
	// 本级补一个 32 hex（与 X-Conversation-Request-ID 的零值兜底同口径），
	// 不再因为「透传优先」而漏发该头（issue #190）。
	conversationID := meta.ConversationID
	if conversationID == "" {
		// 官方形态是带横线 UUIDv7（36 字符），与 32 hex 的消息级 ID 不同轨。
		conversationID = session.NewUUIDv7()
	}
	req.Header.Set("X-Conversation-ID", conversationID)
	req.Header.Set("X-Conversation-Request-ID", convReqID)
	req.Header.Set("X-Conversation-Message-ID", messageID)
	req.Header.Set("X-Request-ID", messageID)
	req.Header.Set("X-Root-Request-ID", convReqID)
	traceID := meta.TraceID
	if traceID == "" {
		traceID = convReqID
	}
	req.Header.Set("X-Trace-ID", traceID)
	b3Trace := convReqID
	if !validTraceID(b3Trace) {
		b3Trace = messageID // 非法 B3 TraceId → 回落恒 32 hex 的消息级 ID
	}
	span := messageID[:16]
	req.Header.Set("X-B3-TraceId", b3Trace)
	req.Header.Set("X-B3-SpanId", span)
	req.Header.Set("X-B3-Sampled", "1")
	// traceparent（W3C）/ b3（Zipkin 单头）与 X-B3-* 同源：官方实测三套格式并存，
	// 只发其中一套本身就是「非官方链路」的指纹。
	req.Header.Set("traceparent", "00-"+b3Trace+"-"+span+"-01")
	req.Header.Set("b3", b3Trace+"-"+span+"-1")
	// baggage / X-Agent-Runtime 仅 CN 分档：官方 5.9.3（CN）带、5.8.4（intl）不带。
	// baggage 的 buddyId/buddyName 官方置空串，两个 id 取自会话头族。
	if a == nil || !a.IsGlobal() {
		req.Header.Set("baggage", "buddyId=,buddyName=,codebuddy.session_id="+conversationID+
			",codebuddy.conversation_request_id="+convReqID)
		req.Header.Set("X-Agent-Runtime", "local-agent")
	}
}

// validTraceID 判断 B3 TraceId 是否合法：16 或 32 位 hex（大小写均可）。
// 官方客户端生成的 conversationRequestId 是 32 位 hex（UUID 去横线），入站透传值
// 可能是任意形状（含横线/超长/非 hex），直接塞进 B3 头会破坏链路关联（issue #35）。
func validTraceID(s string) bool {
	if len(s) != 16 && len(s) != 32 {
		return false
	}
	for i := 0; i < len(s); i++ {
		ch := s[i]
		if !((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F')) {
			return false
		}
	}
	return true
}

// attributionClientName 生效的用量归属名：ClientName 非空取之；
// 空默认 "WorkBuddy"（伪造官方桌面端指纹；显式配 "SaaS" 可还原旧行为）。
func (c *Client) attributionClientName() string {
	return c.attributionClientNameFor(nil)
}

// attributionClientNameFor 按账号 realm 返回归属名：global → "WorkBuddy AI"，CN → "WorkBuddy"。
// 显式 ClientName 覆盖优先（兼容既有配置）。
func (c *Client) attributionClientNameFor(a *auth.Auth) string {
	if c != nil && c.ClientName != "" {
		return c.ClientName
	}
	if a != nil && a.IsGlobal() {
		return "WorkBuddy AI"
	}
	return "WorkBuddy"
}

// injectAttribution 注入用量归属头（X-Agent-Purpose / X-IDE-* / X-Product）。
// 仅在 chat/completions 路径生效（ChatHeaders 调用）。
//
// 默认（ClientName 空）即对齐官方桌面端指纹：X-Agent-Purpose="conversation"
// + X-IDE-Name/Type/Product="WorkBuddy"（CN）或 "WorkBuddy AI"（global）
// + X-IDE-Version=client_version，上游用量归因不再出现 client/agentPurpose 为空的
// 「网关特征」。global 账号的归属名必须与 UA 平台段（`WorkBuddy AI`）一致——
// 国际版维护后通道校验（11128）会检查此一致性。
// 显式 ClientName="SaaS" 还原旧行为（仅 X-Product="SaaS"，不设 X-IDE-*）；
// 配其他值则四头跟随该值。
func (c *Client) injectAttribution(req *http.Request, a *auth.Auth) {
	name := c.attributionClientNameFor(a)
	if name == "SaaS" {
		req.Header.Set("X-Product", "SaaS")
		return
	}
	// 真机抓包实测（global 5.8.4 chat）：X-IDE-Name/Type 恒为 `WorkBuddy`（两域一致），
	// X-Product 取 deploymentType = `SaaS`，另带 X-Private-Data/X-Agent-Intent/X-Agent-Type。
	// 此前把 global 的归属名写成 `WorkBuddy AI` 是**推断值**，官方从不这样发。
	ideName := name
	if c == nil || c.ClientName == "" {
		ideName = "WorkBuddy"
	}
	req.Header.Set("X-Agent-Purpose", "conversation")
	req.Header.Set("X-Agent-Intent", "craft")
	req.Header.Set("X-Agent-Type", "main")
	req.Header.Set("X-IDE-Name", ideName)
	req.Header.Set("X-IDE-Type", ideName)
	req.Header.Set("X-IDE-Version", c.clientVersionFor(a))
	req.Header.Set("X-Product", "SaaS")
	// X-Private-Data 按 realm 分档（实测差异）：intl 5.8.4 恒 `true`，CN 5.9.3 恒
	// `false`。这是两版客户端隐私开关的默认值差异，两域一致写死会与真机不符。
	if a != nil && a.IsGlobal() {
		req.Header.Set("X-Private-Data", "true")
	} else {
		req.Header.Set("X-Private-Data", "false")
	}
}

// ExtractClientIP 从入站请求提取客户端 IP 首段（X-Forwarded-For 首段，回落 X-Real-IP）。
// 仅用于**本地日志/审计**（internal/server/logging）；出站不再透传该 IP（官方客户端
// 从不发 X-Forwarded-For / X-Real-IP / X-Client-IP，见 config passthrough_ip 废弃说明）。
func ExtractClientIP(r *http.Request) string {
	if r == nil {
		return ""
	}
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		for i := 0; i < len(xff); i++ {
			if xff[i] == ',' {
				return strings.TrimSpace(xff[:i])
			}
		}
		return strings.TrimSpace(xff)
	}
	if real := strings.TrimSpace(r.Header.Get("X-Real-IP")); real != "" {
		return real
	}
	return ""
}

// BillingHeaders billing 接口请求头（report / travel / 任务领奖 / 余额签到等）。
// UA 语义：默认**不设置**（保持现状，Go 客户端自带默认 UA）；仅当显式配置
// c.UserAgent 非空才覆盖——避免默认路径给 billing 引入新的 UA 指纹。
func (c *Client) BillingHeaders(req *http.Request, a *auth.Auth) {
	// AccessToken 加锁快照（同 ChatHeaders：keepalive 可在 a.mu 内改写）。
	req.Header.Set("Authorization", "Bearer "+a.AccessTokenValue())
	// 官方 plugin/console 层请求实测 Accept 为宽松形态（application/json, text/plain, */*），
	// 与 chat 的严格 application/json 不同轨。
	req.Header.Set("Accept", "application/json, text/plain, */*")
	req.Header.Set("Content-Type", "application/json")
	c.injectCodeBuddyRequest(req)
	// Accept-Language 按 realm 切（D5，billing 域未走 CommonHeaders，单独注入）。
	// 实测 billing/console 路径带该头（CN `zh`/`zh-CN`，intl `en`/`en-US`），chat 不带。
	req.Header.Set("Accept-Language", acceptLanguageFor(a))
	if c != nil && c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	} else if ua := c.billingUAFor(a); ua != "" {
		req.Header.Set("User-Agent", ua)
	}
	// X-Product / X-Domain：官方全量请求恒带（见 CommonHeaders），billing 域单独注入。
	req.Header.Set("X-Product", "SaaS")
	req.Header.Set("X-Domain", realmDomain(a))
	if a.UID != "" {
		req.Header.Set("X-User-Id", a.UID)
	}
	if a.EnterpriseID != "" {
		req.Header.Set("X-Enterprise-Id", a.EnterpriseID)
		req.Header.Set("X-Tenant-Id", a.EnterpriseID)
	}
	// 设备风控头：billing 域（report/travel/balance/checkin）同样注入。
	c.injectDeviceToken(req, a)
}

// RefreshHeaders refresh 端点专属头（X-Refresh-Token 只允许出现在这里）。
// 实测（plugin 层 refresh）：Accept 宽松形态 + X-Request-ID（32 hex）+ X-User-Id +
// X-Domain + X-Product: SaaS + X-Auth-Refresh-Source: plugin。
func (c *Client) RefreshHeaders(req *http.Request, a *auth.Auth) {
	c.CommonHeaders(req, a)
	req.Header.Set("Accept", "application/json, text/plain, */*")
	req.Header.Set("X-Refresh-Token", a.RefreshToken)
	if a.UID != "" {
		req.Header.Set("X-User-Id", a.UID)
	}
	req.Header.Set("X-Request-ID", session.NewMessageID())
	if a.EnterpriseID != "" {
		req.Header.Set("X-Enterprise-Id", a.EnterpriseID)
	}
	// X-Auth-Refresh-Source 对齐官方客户端 refresh 渠道标识 "plugin"（D3）。
	req.Header.Set("X-Auth-Refresh-Source", "plugin")
}
