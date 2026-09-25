package api

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/Elmar006/energy_web/backend/internal/artifact"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDemandArtifactUploadScenarioPersistenceAndEngineValidation(t *testing.T) {
	dbURL := os.Getenv("TEST_DATABASE_URL")
	if dbURL == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	ctx := context.Background()
	db, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	local := artifact.Local{Root: t.TempDir()}
	validated := false
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/validate" {
			t.Errorf("unexpected engine path: %s", r.URL.Path)
		}
		content, _ := io.ReadAll(r.Body)
		var input map[string]json.RawMessage
		if json.Unmarshal(content, &input) != nil || len(input["service_calendar"]) == 0 ||
			string(input["charging_requests"]) != "[]" || len(input["demand_dataset"]) == 0 {
			t.Errorf("engine did not receive fully hydrated input: %s", content)
		}
		validated = true
		_, _ = w.Write([]byte(`{"valid":true}`))
	}))
	defer engine.Close()
	handler := (Server{Store: &store.Store{DB: db}, Token: "artifact-integration-token",
		EngineURL: engine.URL, Artifacts: local}).Handler()
	const data = `{"schema_version":"demand-dataset-v1","service_calendar":{"schema_version":"service-calendar-v1","time_zone":"Europe/Moscow","covered_dates":["2027-05-03"],"request_zone_ids":["z1"],"legacy_profile_zone_ids":[],"annualization_factor":365,"annualization_basis":"assumed_repeat","days":[{"date":"2027-05-03","day_type":"weekday","season":"spring"}]},"charging_requests":[]}`
	upload := httptest.NewRequest(http.MethodPost, "/api/v1/artifacts/demand", bytes.NewBufferString(data))
	upload.Header.Set("Authorization", "Bearer artifact-integration-token")
	uploadResult := httptest.NewRecorder()
	handler.ServeHTTP(uploadResult, upload)
	var m artifact.Manifest
	if uploadResult.Code != 201 || json.Unmarshal(uploadResult.Body.Bytes(), &m) != nil {
		t.Fatalf("upload failed: %d %s", uploadResult.Code, uploadResult.Body.String())
	}
	scenarioSpec, _ := json.Marshal(map[string]any{"id": "artifact-test", "demand_dataset": m})
	createBody, _ := json.Marshal(map[string]any{"name": "artifact-test", "spec": json.RawMessage(scenarioSpec)})
	create := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios", bytes.NewReader(createBody))
	create.Header.Set("Authorization", "Bearer artifact-integration-token")
	created := httptest.NewRecorder()
	handler.ServeHTTP(created, create)
	var saved struct {
		ID   string                     `json:"id"`
		Spec map[string]json.RawMessage `json:"spec"`
	}
	if created.Code != 201 || !validated || json.Unmarshal(created.Body.Bytes(), &saved) != nil {
		t.Fatalf("scenario was not validated and saved: %d %s", created.Code, created.Body.String())
	}
	t.Cleanup(func() {
		_, _ = db.Exec(context.Background(), `DELETE FROM scenarios WHERE id=$1::uuid`, saved.ID)
	})
	if len(saved.Spec["demand_dataset"]) == 0 || len(saved.Spec["charging_requests"]) != 0 ||
		len(saved.Spec["service_calendar"]) != 0 {
		t.Fatalf("large requests were inlined in persisted snapshot: %s", created.Body.String())
	}
	var stored json.RawMessage
	if err := db.QueryRow(ctx, `SELECT spec FROM scenarios WHERE id=$1::uuid`, saved.ID).Scan(&stored); err != nil {
		t.Fatal(err)
	}
	var storedSpec map[string]json.RawMessage
	var storedManifest artifact.Manifest
	if json.Unmarshal(stored, &storedSpec) != nil ||
		json.Unmarshal(storedSpec["demand_dataset"], &storedManifest) != nil ||
		storedManifest != m || len(storedSpec["charging_requests"]) != 0 {
		t.Fatalf("persisted input lost immutable reference: %s", stored)
	}
	// A missing artifact is rejected before an apparently valid manifest can
	// enter the scenario table.
	bad := m
	bad.SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"
	bad.ArtifactID = "sha256:" + bad.SHA256
	badSpec, _ := json.Marshal(map[string]any{"id": "missing", "demand_dataset": bad})
	badBody, _ := json.Marshal(map[string]any{"name": "missing", "spec": json.RawMessage(badSpec)})
	request := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios", bytes.NewReader(badBody))
	request.Header.Set("Authorization", "Bearer artifact-integration-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 422 {
		t.Fatalf("missing artifact accepted: %d %s", response.Code, response.Body.String())
	}
}
