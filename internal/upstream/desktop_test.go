package upstream

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/enticingns/workbuddy-gateway/internal/auth"
)

// TestReportDesktopEventFingerprint 断言桌面指纹上报：走 chatBase、UA 为桌面形状、
// 事件数组自动注入 workbuddy-desktop 公共指纹（覆盖同名业务键）。
func TestReportDesktopEventFingerprint(t *testing.T) {
	var got []map[string]any
	var gotUA string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v2/report" {
			t.Errorf("path=%s want /v2/report", r.URL.Path)
		}
		gotUA = r.Header.Get("User-Agent")
		if r.Header.Get("X-User-Id") != "u-dt" {
			t.Errorf("X-User-Id=%q want u-dt", r.Header.Get("X-User-Id"))
		}
		if r.Header.Get("X-Product") != "SaaS" {
			t.Errorf("X-Product=%q want SaaS", r.Header.Get("X-Product"))
		}
		raw, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatalf("body must be array: %v", err)
		}
		w.Write([]byte(`{"code":0,"msg":"OK"}`))
	}))
	defer srv.Close()

	c := &Client{HTTP: srv.Client(), ChatBaseCN: srv.URL}
	acc := &auth.Auth{AccessToken: "at", UID: "u-dt", Nickname: "RenJie"}
	err := c.ReportDesktopEvent(acc,
		DesktopEvent{"eventCode": "agent_task_created", "mode": "craft"})
	if err != nil {
		t.Fatalf("report desktop: %v", err)
	}
	if want := "WorkBuddy/5.9.3 WorkBuddy/5.9.3 CLI/2.165.0"; gotUA != want {
		t.Errorf("UA=%q want %q（CN 真机 5.9.3 形态）", gotUA, want)
	}
	if len(got) != 1 {
		t.Fatalf("events=%d want 1", len(got))
	}
	ev := got[0]
	// 指纹版本必须与出站 UA 同源（曾出现 UA 5.9.2 而真机已 5.9.3/5.9.4 的漂移）。
	if ev["ideVersion"] != "5.9.3" || ev["extVersion"] != "5.9.3" {
		t.Errorf("ideVersion/extVersion=%v/%v want 5.9.3/5.9.3", ev["ideVersion"], ev["extVersion"])
	}
	if ev["commit"] != "d46924219e79332f49c37ccebf27292f87001b19" {
		t.Errorf("commit=%v want CN 5.9.3 commit", ev["commit"])
	}
	if ev["releaseDate"] != float64(1793093050922) {
		t.Errorf("releaseDate=%v want 1793093050922", ev["releaseDate"])
	}
	if ev["extName"] != "workbuddy-desktop" {
		t.Errorf("extName=%v want workbuddy-desktop", ev["extName"])
	}
	if ev["ideType"] != "WorkBuddy" || ev["ideName"] != "WorkBuddy" {
		t.Errorf("ideType/ideName=%v/%v want WorkBuddy", ev["ideType"], ev["ideName"])
	}
	if ev["userId"] != "u-dt" {
		t.Errorf("userId=%v want u-dt", ev["userId"])
	}
	if ev["userNickname"] != "RenJie" {
		t.Errorf("userNickname=%v want RenJie", ev["userNickname"])
	}
	if ev["mode"] != "craft" {
		t.Errorf("业务字段 mode=%v 被指纹覆盖或缺失", ev["mode"])
	}
	// machineId 应为 uid 稳定派生（36 hex）。
	if len(ev["machineId"].(string)) != 36 {
		t.Errorf("machineId 长度=%d want 36", len(ev["machineId"].(string)))
	}
}

// TestDesktopChatSequenceShape 断言完整对话事件链的事件码顺序与关键字段。
func TestDesktopChatSequenceShape(t *testing.T) {
	events := DesktopChatSequence("conv-1", "req-1", "msg-1", "fast-model", "fast-model")
	wantCodes := []string{
		"agent_task_created", "chat_message_send", "chat_request_send",
		"chat_message_response", "chat_message_status", "chat_request_response",
	}
	if len(events) != len(wantCodes) {
		t.Fatalf("events=%d want %d", len(events), len(wantCodes))
	}
	for i, want := range wantCodes {
		if events[i]["eventCode"] != want {
			t.Errorf("events[%d].eventCode=%v want %v", i, events[i]["eventCode"], want)
		}
	}
	resp := events[3]
	if resp["isSuccessful"] != true {
		t.Errorf("chat_message_response.isSuccessful=%v want true（RichMeow 判据）", resp["isSuccessful"])
	}
	if resp["finishReason"] != "stop" {
		t.Errorf("finishReason=%v want stop", resp["finishReason"])
	}
	if resp["conversationId"] != "conv-1" {
		t.Errorf("conversationId=%v want conv-1", resp["conversationId"])
	}
}

// TestSetAppearanceTheme 断言主题设置端点形状（点亮 Hp_Appearance 的 API）。
func TestSetAppearanceTheme(t *testing.T) {
	var got map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v2/user-asset/appearance/set" {
			t.Errorf("path=%s want /v2/user-asset/appearance/set", r.URL.Path)
		}
		if want := "WorkBuddy/5.9.3 WorkBuddy/5.9.3 CLI/2.165.0"; r.Header.Get("User-Agent") != want {
			t.Errorf("UA=%q want %q", r.Header.Get("User-Agent"), want)
		}
		raw, _ := io.ReadAll(r.Body)
		json.Unmarshal(raw, &got)
		w.Write([]byte(`{"code":0,"msg":"OK"}`))
	}))
	defer srv.Close()

	c := &Client{HTTP: srv.Client(), ChatBaseCN: srv.URL}
	if err := c.SetAppearanceTheme(&auth.Auth{AccessToken: "at", UID: "u1"}, "theme-tkmw7j"); err != nil {
		t.Fatalf("set theme: %v", err)
	}
	if got["kind"] != "theme" || got["resource_key"] != "theme-tkmw7j" {
		t.Errorf("body=%v want kind=theme resource_key=theme-tkmw7j", got)
	}
}

// TestDesktopFingerprintRealm 断言桌面指纹按 realm 分档：global 账号的 UA /
// ideVersion / commit / releaseDate 必须取国际版真机值，不能沿用 CN 或旧值。
func TestDesktopFingerprintRealm(t *testing.T) {
	c := &Client{}
	cn := &auth.Auth{AccessToken: "at", UID: "u-cn", Domain: "copilot.tencent.com"}
	global := &auth.Auth{AccessToken: "at", UID: "u-gl", Domain: "www.workbuddy.ai"}
	global.BackfillRealm()

	if got, want := c.userAgent(cn), "WorkBuddy/5.9.3 WorkBuddy/5.9.3 CLI/2.165.0"; got != want {
		t.Errorf("CN UA=%q want %q", got, want)
	}
	if got, want := c.userAgent(global), "WorkBuddy/5.9.4 workbuddy-ai/5.9.4 CLI/2.165.0"; got != want {
		t.Errorf("global UA=%q want %q", got, want)
	}

	fpCN, fpGL := c.desktopFingerprint(cn), c.desktopFingerprint(global)
	if fpCN["ideVersion"] != "5.9.3" || fpCN["commit"] != desktopCommitCN ||
		fpCN["releaseDate"] != desktopReleaseDateCN {
		t.Errorf("CN 指纹=%v/%v/%v want 5.9.3/%s/%d",
			fpCN["ideVersion"], fpCN["commit"], fpCN["releaseDate"],
			desktopCommitCN, desktopReleaseDateCN)
	}
	if fpGL["ideVersion"] != "5.9.4" || fpGL["commit"] != desktopCommitGlobal ||
		fpGL["releaseDate"] != desktopReleaseDateGlobal {
		t.Errorf("global 指纹=%v/%v/%v want 5.9.4/%s/%d",
			fpGL["ideVersion"], fpGL["commit"], fpGL["releaseDate"],
			desktopCommitGlobal, desktopReleaseDateGlobal)
	}
}
