package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestScenarioValidationRejectsBrokenPlanningInputBeforeDatabase(t *testing.T) {
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/validate" || r.Method != http.MethodPost {
			t.Errorf("unexpected validation request: %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"detail":[{"loc":["body","sites",0,"grid_node_id"],"msg":"unknown node"}]}`))
	}))
	defer engine.Close()
	handler := (Server{Token: "test-secret-token", EngineURL: engine.URL}).Handler()
	request := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios", strings.NewReader(`{"name":"broken","spec":{"sites":[]}}`))
	request.Header.Set("Authorization", "Bearer test-secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusUnprocessableEntity {
		t.Fatalf("unexpected status: %d %s", response.Code, response.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil || !strings.Contains(body["detail"], "sites.0.grid_node_id") {
		t.Fatalf("missing field detail: %s, error: %v", response.Body.String(), err)
	}
}

func TestAuthAndRequestValidation(t *testing.T) {
	handler := (Server{Token: "test-secret-token"}).Handler()
	for _, tc := range []struct {
		name, path, token string
		want              int
	}{
		{"no token", "/api/v1/map?bbox=37,55,38,56", "", 401},
		{"wrong token", "/api/v1/map?bbox=37,55,38,56", "other-secret-token", 401},
		{"bad bbox", "/api/v1/map?bbox=37,55,36,56", "test-secret-token", 422},
		{"nonfinite bbox", "/api/v1/map?bbox=NaN,55,38,56", "test-secret-token", 422},
		{"bad tile", "/api/v1/tiles/9/999/160", "test-secret-token", 422},
		{"bad scenario UUID", "/api/v1/scenarios/not-a-uuid", "test-secret-token", 422},
		{"bad run UUID", "/api/v1/runs/not-a-uuid", "test-secret-token", 422},
		{"bad result UUID", "/api/v1/runs/not-a-uuid/results", "test-secret-token", 422},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, tc.path, nil)
			if tc.token != "" {
				req.Header.Set("Authorization", "Bearer "+tc.token)
			}
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, req)
			if response.Code != tc.want || !strings.Contains(response.Header().Get("Content-Type"), "json") {
				t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
			}
		})
	}
}

func TestCorridorProxyPreservesEngineResponse(t *testing.T) {
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/corridor/check" || r.Method != http.MethodPost {
			t.Errorf("unexpected engine request: %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"reachable":true,"stops":["a"]}`))
	}))
	defer engine.Close()
	handler := (Server{Token: "test-secret-token", EngineURL: engine.URL}).Handler()
	request := httptest.NewRequest(http.MethodPost, "/api/v1/corridors/check", strings.NewReader(`{"route_km":300}`))
	request.Header.Set("Authorization", "Bearer test-secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 200 || !strings.Contains(response.Body.String(), `"reachable":true`) {
		t.Fatalf("unexpected proxy response: %d %s", response.Code, response.Body.String())
	}
}
