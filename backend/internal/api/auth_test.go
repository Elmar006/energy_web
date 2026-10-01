package api

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestProtectedRoutesRequireNonemptyBearerCredential(t *testing.T) {
	for _, tc := range []struct{ token, header string }{
		{"", ""}, {"", "Bearer "}, {"secret", "secret"}, {"secret", "Basic secret"}, {"secret", "Bearer wrong"},
	} {
		response := httptest.NewRecorder()
		request := httptest.NewRequest("GET", "/api/v1/datasets", nil)
		request.Header.Set("Authorization", tc.header)
		(Server{Token: tc.token}).Handler().ServeHTTP(response, request)
		if response.Code != http.StatusUnauthorized {
			t.Fatalf("invalid credential accepted: %d", response.Code)
		}
	}
}
