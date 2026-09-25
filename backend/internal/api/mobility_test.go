package api

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const mobilityPreviewBody = `{"input":{"id":"base"},"mobility":{"schema_version":"mobility-v1"}}`

func mobilityCompileResponse(spec json.RawMessage) []byte {
	source := `{"schema_version":"mobility-v1","source":"survey","source_kind":"assumed"}`
	sum := sha256.Sum256([]byte(source))
	result, _ := json.Marshal(map[string]any{
		"spec": spec, "requests": []any{}, "calendar_profiles": []any{},
		"audit":         map[string]any{"request_count": 0},
		"source_sha256": hex.EncodeToString(sum[:]), "source_canonical_json": source,
		"compiler_source_sha256": strings.Repeat("a", 64), "compiler_pydantic_version": "2.12.0",
	})
	return result
}

func TestMobilityPreviewRouteCompilesAndRevalidatesWithoutDatabase(t *testing.T) {
	compileCalls, validateCalls := 0, 0
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/mobility/compile":
			compileCalls++
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(mobilityCompileResponse(json.RawMessage(`{"id":"compiled"}`)))
		case "/v1/validate":
			validateCalls++
			var spec struct {
				ID string `json:"id"`
			}
			if err := json.NewDecoder(r.Body).Decode(&spec); err != nil || spec.ID != "compiled" {
				t.Errorf("compiled planning input was not validated: %+v %v", spec, err)
			}
			_, _ = w.Write([]byte(`{"valid":true}`))
		default:
			t.Errorf("unexpected engine path: %s", r.URL.Path)
			http.NotFound(w, r)
		}
	}))
	defer engine.Close()
	handler := (Server{Token: "test-secret-token", EngineURL: engine.URL}).Handler()
	request := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/from-mobility/preview", strings.NewReader(mobilityPreviewBody))
	request.Header.Set("Authorization", "Bearer test-secret-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 200 || compileCalls != 1 || validateCalls != 1 ||
		!strings.Contains(response.Body.String(), `"source_sha256"`) ||
		!strings.Contains(response.Body.String(), `"id":"compiled"`) {
		t.Fatalf("preview failed: status=%d compiler=%d validator=%d body=%s", response.Code, compileCalls, validateCalls, response.Body.String())
	}
}

func TestMobilityPreviewRouteInputAndEngineErrors(t *testing.T) {
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/mobility/compile":
			w.WriteHeader(422)
			_, _ = w.Write([]byte(`{"detail":"unknown destination zone"}`))
		default:
			t.Fatal("invalid itinerary should not reach validation")
		}
	}))
	defer engine.Close()
	for _, tc := range []struct {
		name, body, token string
		engineURL         string
		want              int
	}{
		{"auth", mobilityPreviewBody, "", engine.URL, 401},
		{"unknown field", `{"input":{},"mobility":{},"other":1}`, "test-secret-token", engine.URL, 400},
		{"repeated field", `{"input":{},"input":{"id":"ambiguous"},"mobility":{}}`, "test-secret-token", engine.URL, 400},
		{"multiple objects", `{} {}`, "test-secret-token", engine.URL, 400},
		{"missing mobility", `{"input":{}}`, "test-secret-token", engine.URL, 422},
		{"invalid itinerary", mobilityPreviewBody, "test-secret-token", engine.URL, 422},
		{"engine unavailable", mobilityPreviewBody, "test-secret-token", "", 503},
		{"oversized request", strings.Repeat(" ", 4<<20) + mobilityPreviewBody, "test-secret-token", engine.URL, 413},
	} {
		t.Run(tc.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/from-mobility/preview", strings.NewReader(tc.body))
			if tc.token != "" {
				request.Header.Set("Authorization", "Bearer "+tc.token)
			}
			response := httptest.NewRecorder()
			(Server{Token: "test-secret-token", EngineURL: tc.engineURL}).Handler().ServeHTTP(response, request)
			if response.Code != tc.want {
				t.Fatalf("status=%d want=%d body=%s", response.Code, tc.want, response.Body.String())
			}
		})
	}
}

func TestMobilityPreviewRouteDoesNotPublishInvalidCompiledInput(t *testing.T) {
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/mobility/compile":
			_, _ = w.Write(mobilityCompileResponse(json.RawMessage(`{"id":"invalid"}`)))
		case "/v1/validate":
			w.WriteHeader(422)
			_, _ = w.Write([]byte(`{"detail":[{"loc":["body","zones"],"msg":"zone missing"}]}`))
		default:
			t.Errorf("unexpected engine path: %s", r.URL.Path)
			http.NotFound(w, r)
		}
	}))
	defer engine.Close()
	request := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/from-mobility/preview", strings.NewReader(mobilityPreviewBody))
	request.Header.Set("Authorization", "Bearer test-secret-token")
	response := httptest.NewRecorder()
	(Server{Token: "test-secret-token", EngineURL: engine.URL}).Handler().ServeHTTP(response, request)
	if response.Code != 502 || strings.Contains(response.Body.String(), `"spec"`) {
		t.Fatalf("invalid compiled scenario escaped validation: %d %s", response.Code, response.Body.String())
	}
}
