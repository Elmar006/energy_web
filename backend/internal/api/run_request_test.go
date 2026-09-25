package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRunRequestRejectsMalformedBodyBeforeDatabase(t *testing.T) {
	for _, tc := range []struct {
		body   string
		status int
	}{
		{`null`, 400}, {`[]`, 400}, {`{"wrong":true}`, 400},
		{`{"run_spec":{},"run_spec":{}}`, 400}, {`{"Run_Spec":{}}`, 400},
		{`{} {}`, 400}, {`{"run_spec":`, 400},
		{strings.Repeat(" ", 16*1024+1), 413},
	} {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/11111111-1111-1111-1111-111111111111/runs", strings.NewReader(tc.body))
		req.Header.Set("Authorization", "Bearer test-token")
		req.Header.Set("Idempotency-Key", "test-request-key")
		rec := httptest.NewRecorder()
		(Server{Token: "test-token"}).Handler().ServeHTTP(rec, req)
		if rec.Code != tc.status {
			t.Fatalf("body %q: %d %s", tc.body[:min(50, len(tc.body))], rec.Code, rec.Body.String())
		}
	}
}
