package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDatasetUploadPreviewAndPersistedScenario(t *testing.T) {
	ctx := context.Background()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	db, err := pgxpool.New(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var validations int
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/validate" {
			t.Errorf("unexpected engine request: %s", r.URL.Path)
		}
		var spec struct {
			TimeZone    string            `json:"time_zone"`
			Zones       []json.RawMessage `json:"zones"`
			Sites       []json.RawMessage `json:"sites"`
			GridNodes   []json.RawMessage `json:"grid_nodes"`
			TravelEdges []json.RawMessage `json:"travel_edges"`
		}
		if err := json.NewDecoder(r.Body).Decode(&spec); err != nil || spec.TimeZone != "Europe/Moscow" ||
			len(spec.Zones) != 1 || len(spec.Sites) != 1 || len(spec.GridNodes) != 1 || len(spec.TravelEdges) != 1 {
			t.Errorf("malformed assembled input: %+v %v", spec, err)
		}
		validations++
		_, _ = w.Write([]byte(`{"valid":true}`))
	}))
	defer engine.Close()
	handler := (Server{Store: &store.Store{DB: db}, EngineURL: engine.URL, Token: "test-token"}).Handler()
	name := fmt.Sprintf("dataset-e2e-%d", time.Now().UnixNano())
	ids := map[string]string{}
	var savedScenarioID string
	t.Cleanup(func() {
		if savedScenarioID != "" {
			_, _ = db.Exec(context.Background(), `DELETE FROM scenarios WHERE id=$1::uuid`, savedScenarioID)
		}
		for _, id := range ids {
			_, _ = db.Exec(context.Background(), `DELETE FROM geographic_features WHERE dataset_version_id=$1::uuid`, id)
			_, _ = db.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, id)
		}
	})
	energy := `[0,0,0,0,0,0,0,0,0,0,0,0,10,0,0,0,0,0,0,0,0,0,0,0]`
	grid := `[10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10]`
	collections := map[string]string{
		"demand_zones":    `{"type":"FeatureCollection","features":[{"type":"Feature","id":"z1","geometry":{"type":"Point","coordinates":[37.6,55.7]},"properties":{"feature_type":"demand_zone","name":"Zone","hourly_kwh":` + energy + `,"mean_session_kwh":10,"max_travel_minutes":20,"time_zone":"Europe/Moscow"}}]}`,
		"candidate_sites": `{"type":"FeatureCollection","features":[{"type":"Feature","id":"s1","geometry":{"type":"Point","coordinates":[37.6,55.7]},"properties":{"feature_type":"candidate_site","name":"Site","grid_node_id":"g1","option_ids":["dc"]}}]}`,
		"grid_nodes":      `{"type":"FeatureCollection","features":[{"type":"Feature","id":"g1","geometry":{"type":"Point","coordinates":[37.6,55.7]},"properties":{"feature_type":"grid_node","headroom_kw":` + grid + `,"time_zone":"Europe/Moscow"}}]}`,
		"travel_edges":    `{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"LineString","coordinates":[[37.6,55.7],[37.6001,55.7001]]},"properties":{"feature_type":"travel_edge","zone_id":"z1","site_id":"s1","minutes":5}}]}`,
	}
	stamp := "2026-09-24T12:00:00Z"
	for _, role := range []string{"demand_zones", "candidate_sites", "grid_nodes", "travel_edges"} {
		var multipartBody bytes.Buffer
		writer := multipart.NewWriter(&multipartBody)
		for key, value := range map[string]string{"name": name + "-" + role, "kind": "observed",
			"source": "integration supplier", "license": "test license", "captured_at": stamp} {
			if err := writer.WriteField(key, value); err != nil {
				t.Fatal(err)
			}
		}
		file, err := writer.CreateFormFile("file", role+".geojson")
		if err != nil {
			t.Fatal(err)
		}
		if _, err := file.Write([]byte(collections[role])); err != nil {
			t.Fatal(err)
		}
		if err := writer.Close(); err != nil {
			t.Fatal(err)
		}
		rawUpload := append([]byte(nil), multipartBody.Bytes()...)
		req := httptest.NewRequest(http.MethodPost, "/api/v1/datasets/import", bytes.NewReader(rawUpload))
		req.Header.Set("Authorization", "Bearer test-token")
		req.Header.Set("Content-Type", writer.FormDataContentType())
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		if response.Code != 201 {
			t.Fatalf("import %s: %d %s", role, response.Code, response.Body.String())
		}
		var imported struct {
			DatasetID string `json:"dataset_id"`
			Features  int    `json:"features"`
		}
		if err := json.Unmarshal(response.Body.Bytes(), &imported); err != nil || imported.Features != 1 || imported.DatasetID == "" {
			t.Fatalf("invalid import: %+v %v", imported, err)
		}
		ids[role] = imported.DatasetID
		if role == "demand_zones" {
			retry := httptest.NewRequest(http.MethodPost, "/api/v1/datasets/import", bytes.NewReader(rawUpload))
			retry.Header.Set("Authorization", "Bearer test-token")
			retry.Header.Set("Content-Type", writer.FormDataContentType())
			repeated := httptest.NewRecorder()
			handler.ServeHTTP(repeated, retry)
			var duplicate struct {
				DatasetID string `json:"dataset_id"`
			}
			if repeated.Code != 201 || json.Unmarshal(repeated.Body.Bytes(), &duplicate) != nil || duplicate.DatasetID != imported.DatasetID {
				t.Fatalf("identical upload was not idempotent: %d %s", repeated.Code, repeated.Body.String())
			}
		}
	}
	var invalidBody bytes.Buffer
	invalidWriter := multipart.NewWriter(&invalidBody)
	_ = invalidWriter.WriteField("name", name+"-malformed")
	_ = invalidWriter.WriteField("kind", "assumed")
	_ = invalidWriter.WriteField("source", "integration test")
	invalidFile, err := invalidWriter.CreateFormFile("file", "bad.geojson")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = invalidFile.Write([]byte(`{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":"bad"}}]}`))
	if err := invalidWriter.Close(); err != nil {
		t.Fatal(err)
	}
	invalidRequest := httptest.NewRequest(http.MethodPost, "/api/v1/datasets/import", &invalidBody)
	invalidRequest.Header.Set("Authorization", "Bearer test-token")
	invalidRequest.Header.Set("Content-Type", invalidWriter.FormDataContentType())
	invalidResponse := httptest.NewRecorder()
	handler.ServeHTTP(invalidResponse, invalidRequest)
	if invalidResponse.Code != 422 {
		t.Fatalf("malformed geometry was not rejected as input: %d %s", invalidResponse.Code, invalidResponse.Body.String())
	}
	var persistedBad int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM dataset_versions WHERE name=$1`, name+"-malformed").Scan(&persistedBad); err != nil || persistedBad != 0 {
		t.Fatalf("malformed import persisted partial data: %d %v", persistedBad, err)
	}
	body, err := json.Marshal(map[string]any{
		"name": name, "input_id": "dataset-input", "time_zone": "Europe/Moscow",
		"dataset_versions": ids,
		"options": []map[string]any{{"id": "dc", "ports": 1, "charger_kw": 10,
			"connection_kw": 10, "capex_rub": 1000, "annual_fixed_rub": 0}},
		"parameters": map[string]any{"mode": "city", "years": []int{2027},
			"annual_budgets_rub": []int{1000}, "total_budget_rub": 1000,
			"sale_rub_per_kwh": 20, "purchase_rub_per_kwh": 5,
			"discount_rate": 0.1, "pv_hourly_factor": make([]int, 24)},
		"scenarios": []map[string]any{{"id": "base", "demand_multiplier": []int{1}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	request := func(path string) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, path, bytes.NewReader(body))
		req.Header.Set("Authorization", "Bearer test-token")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		return response
	}
	preview := request("/api/v1/scenarios/from-datasets/preview")
	if preview.Code != 200 || !strings.Contains(preview.Body.String(), ids["demand_zones"]) {
		t.Fatalf("preview failed: %d %s", preview.Code, preview.Body.String())
	}
	var previewBody struct {
		Spec json.RawMessage `json:"spec"`
	}
	if err := json.Unmarshal(preview.Body.Bytes(), &previewBody); err != nil {
		t.Fatal(err)
	}
	created := request("/api/v1/scenarios/from-datasets")
	if created.Code != 201 {
		t.Fatalf("creation failed: %d %s", created.Code, created.Body.String())
	}
	var result struct {
		Scenario struct {
			ID     string          `json:"id"`
			Spec   json.RawMessage `json:"spec"`
			SHA256 string          `json:"sha256"`
		} `json:"scenario"`
		Quality struct {
			Datasets []json.RawMessage `json:"datasets"`
		} `json:"data_quality"`
	}
	if err := json.Unmarshal(created.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	savedScenarioID = result.Scenario.ID
	if savedScenarioID == "" || result.Scenario.SHA256 == "" || len(result.Quality.Datasets) != 4 ||
		!equalJSON(previewBody.Spec, result.Scenario.Spec) || validations != 2 {
		t.Fatalf("saved snapshot differs from validated preview: %s", created.Body.String())
	}
}

func equalJSON(first, second []byte) bool {
	var a, b any
	if json.Unmarshal(first, &a) != nil || json.Unmarshal(second, &b) != nil {
		return false
	}
	left, _ := json.Marshal(a)
	right, _ := json.Marshal(b)
	return bytes.Equal(left, right)
}
