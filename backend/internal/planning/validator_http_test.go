package planning

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHTTPValidatorRequiresExplicitValidResponse(t *testing.T) {
	for _, tc := range []struct {
		name, response string
		wantErr        bool
	}{
		{"valid", `{"valid":true}`, false},
		{"false", `{"valid":false}`, true},
		{"missing", `{"id":"scenario"}`, true},
		{"malformed", `{`, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/v1/validate" || r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/json" {
					t.Errorf("unexpected validation request: %s %s", r.Method, r.URL.Path)
				}
				_, _ = w.Write([]byte(tc.response))
			}))
			defer server.Close()
			err := (HTTPValidator{URL: server.URL}).Validate(context.Background(), json.RawMessage(`{}`))
			if tc.wantErr != errors.Is(err, ErrValidatorUnavailable) {
				t.Fatalf("validator error = %v", err)
			}
		})
	}
}
