package upstream

import (
	"net/http"
	"regexp"
	"testing"

	"github.com/enticingns/workbuddy-gateway/internal/auth"
)

// TestChatHeadersAlwaysSendConversationTrio 回归 issue #190：国际端点收紧通道
// 校验后，缺 X-Conversation-ID 的聊天请求会 400 / 11128（conversation id
// missing）。即使调用方没给会话 ID（零值 ChatMeta），三元组也必须齐全：
// X-Conversation-ID 为官方形态的带横线 UUIDv7（36 字符），
// request/message ID 为 32 位 hex（UUIDv7 去横线）。
func TestChatHeadersAlwaysSendConversationTrio(t *testing.T) {
	c := &Client{}
	req, err := http.NewRequest(http.MethodPost, "https://example.com/v2/chat/completions", nil)
	if err != nil {
		t.Fatal(err)
	}
	c.ChatHeaders(req, testAuth(), "", ChatMeta{})

	uuidv7 := regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	if v := req.Header.Get("X-Conversation-ID"); !uuidv7.MatchString(v) {
		t.Errorf("X-Conversation-ID = %q, want 带横线 UUIDv7", v)
	}
	hex32 := regexp.MustCompile(`^[0-9a-f]{32}$`)
	for _, h := range []string{
		"X-Conversation-Request-ID",
		"X-Conversation-Message-ID",
	} {
		v := req.Header.Get(h)
		if v == "" {
			t.Fatalf("%s missing (通道校验会拒绝缺少会话三元组的请求)", h)
		}
		if !hex32.MatchString(v) {
			t.Errorf("%s = %q, want 32 hex", h, v)
		}
	}

	// 兜底会话 ID 每次请求新生成（不是常量），且与 request/message ID 不冲突。
	req2, _ := http.NewRequest(http.MethodPost, "https://example.com/v2/chat/completions", nil)
	c.ChatHeaders(req2, testAuth(), "", ChatMeta{})
	if req.Header.Get("X-Conversation-ID") == req2.Header.Get("X-Conversation-ID") {
		t.Error("fallback X-Conversation-ID should be fresh per request")
	}
}

// TestChatHeadersPreservesConversationID 入站带来的会话 ID 优先透传，不被兜底覆盖。
func TestChatHeadersPreservesConversationID(t *testing.T) {
	c := &Client{}
	req, _ := http.NewRequest(http.MethodPost, "https://example.com/v2/chat/completions", nil)
	const conv = "0123456789abcdef0123456789abcdef"
	c.ChatHeaders(req, testAuth(), "", ChatMeta{ConversationID: conv})
	if got := req.Header.Get("X-Conversation-ID"); got != conv {
		t.Errorf("X-Conversation-ID = %q, want supplied %q", got, conv)
	}
}

// testAuth 返回最小的 CN 账号（ChatHeaders 会读 UID/凭证，nil 会解引用）。
func testAuth() *auth.Auth {
	return &auth.Auth{UID: "u1", AccessToken: "at"}
}

// chatHeaderNames 返回 ChatHeaders 产出的全部头（凭证值不参与断言）。
func chatHeaderNames(t *testing.T, a *auth.Auth) http.Header {
	t.Helper()
	c := &Client{}
	req, err := http.NewRequest(http.MethodPost, "https://example.com/v2/chat/completions", nil)
	if err != nil {
		t.Fatal(err)
	}
	c.ChatHeaders(req, a, "203.0.113.7", ChatMeta{})
	return req.Header
}

// TestChatHeadersMatchCapturedBaseline chat 出站头族与真机抓包基线逐项对齐。
//
// 基线（2026-10-28 双域真实抓包，/v2/chat/completions）：
//   - 必带：Accept=application/json、X-Requested-With、x-stainless-*（7）、
//     X-Conversation-*、X-Root-Request-ID、X-Agent-Intent/Purpose/Type、
//     X-IDE-Name/Type/Version、X-Product=SaaS、X-Private-Data、acp-connection-id、
//     traceparent / b3 / X-B3-*（三套链路格式）、X-Domain。
//   - 绝不带：Origin、Referer、Accept-Language、X-Machine-ID、X-Session-ID、
//     X-Forwarded-For、X-Real-IP、X-Client-IP（官方 Electron/Node 层一个都不发）。
//   - 分档：baggage / X-Agent-Runtime 仅 CN；X-Private-Data 值 intl=true / CN=false。
func TestChatHeadersMatchCapturedBaseline(t *testing.T) {
	mustHave := []string{
		"Accept", "Content-Type", "X-Requested-With", "User-Agent",
		"X-CodeBuddy-Request", "X-Product", "X-Domain", "X-User-Id",
		"x-stainless-arch", "x-stainless-lang", "x-stainless-os",
		"x-stainless-package-version", "x-stainless-retry-count",
		"x-stainless-runtime", "x-stainless-runtime-version",
		"X-Conversation-ID", "X-Conversation-Request-ID", "X-Conversation-Message-ID",
		"X-Request-ID", "X-Root-Request-ID", "X-Trace-ID",
		"traceparent", "b3", "X-B3-TraceId", "X-B3-SpanId", "X-B3-Sampled",
		"acp-connection-id",
		"X-Agent-Intent", "X-Agent-Purpose", "X-Agent-Type",
		"X-IDE-Name", "X-IDE-Type", "X-IDE-Version", "X-Private-Data",
	}
	mustNotHave := []string{
		"Origin", "Referer", "Accept-Language",
		"X-Machine-ID", "X-Session-ID",
		"X-Forwarded-For", "X-Real-IP", "X-Client-IP",
	}
	cn := chatHeaderNames(t, testAuth())
	for _, h := range mustHave {
		if cn.Get(h) == "" {
			t.Errorf("CN chat 缺头 %s（真机基线必带）", h)
		}
	}
	for _, h := range mustNotHave {
		if v := cn.Get(h); v != "" {
			t.Errorf("CN chat 不应带 %s=%q（官方实测不发）", h, v)
		}
	}
	if got := cn.Get("Accept"); got != "application/json" {
		t.Errorf("Accept = %q, want application/json（官方 chat 实测值）", got)
	}
	if got := cn.Get("X-Private-Data"); got != "false" {
		t.Errorf("CN X-Private-Data = %q, want false（5.9.3 实测）", got)
	}
	if cn.Get("baggage") == "" || cn.Get("X-Agent-Runtime") != "local-agent" {
		t.Errorf("CN 应带 baggage + X-Agent-Runtime: local-agent（5.9.3 实测），got baggage=%q runtime=%q",
			cn.Get("baggage"), cn.Get("X-Agent-Runtime"))
	}
	// 链路三套格式同源：traceparent/b3 必须复用 X-B3-TraceId/SpanId。
	traceID, spanID := cn.Get("X-B3-TraceId"), cn.Get("X-B3-SpanId")
	if want := "00-" + traceID + "-" + spanID + "-01"; cn.Get("traceparent") != want {
		t.Errorf("traceparent = %q, want %q", cn.Get("traceparent"), want)
	}
	if want := traceID + "-" + spanID + "-1"; cn.Get("b3") != want {
		t.Errorf("b3 = %q, want %q", cn.Get("b3"), want)
	}

	gl := chatHeaderNames(t, &auth.Auth{UID: "u2", AccessToken: "at", Domain: "www.workbuddy.ai"})
	if got := gl.Get("X-Private-Data"); got != "true" {
		t.Errorf("intl X-Private-Data = %q, want true（5.8.4 实测）", got)
	}
	if gl.Get("baggage") != "" || gl.Get("X-Agent-Runtime") != "" {
		t.Errorf("intl 不应带 baggage/X-Agent-Runtime（5.8.4 实测），got %q/%q",
			gl.Get("baggage"), gl.Get("X-Agent-Runtime"))
	}
	if got := gl.Get("X-Domain"); got != domainGlobal {
		t.Errorf("intl X-Domain = %q, want %q", got, domainGlobal)
	}
	if got := cn.Get("X-Domain"); got != domainCN {
		t.Errorf("CN X-Domain = %q, want %q", got, domainCN)
	}
	// acp-connection-id 进程内恒定（一个连接一个 ID），不是逐请求新值。
	if a, b := cn.Get("acp-connection-id"), gl.Get("acp-connection-id"); a != b {
		t.Errorf("acp-connection-id 应进程级恒定，got %q vs %q", a, b)
	}
}
