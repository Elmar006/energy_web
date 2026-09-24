package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestPlanningCSVUploadStoresSourceAndImmutableScenario(t *testing.T) {
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
	st := &store.Store{DB: db}
	parent, err := st.CreateScenario(ctx, "base", json.RawMessage(`{"id":"base","datasets":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	datasetName := "April sessions " + parent.ID
	var createdID, datasetID string
	t.Cleanup(func() {
		if createdID != "" {
			_, _ = db.Exec(context.Background(), `DELETE FROM scenario_imports WHERE scenario_id=$1::uuid`, createdID)
			_, _ = db.Exec(context.Background(), `DELETE FROM scenarios WHERE id=$1::uuid`, createdID)
		}
		if datasetID != "" {
			_, _ = db.Exec(context.Background(), `DELETE FROM uploaded_csv WHERE dataset_version_id=$1::uuid`, datasetID)
			_, _ = db.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, datasetID)
		}
		_, _ = db.Exec(context.Background(), `DELETE FROM scenarios WHERE id=$1::uuid`, parent.ID)
	})
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/validate" {
			_, _ = w.Write([]byte(`{"valid":true}`))
			return
		}
		if r.URL.Path != "/v1/derive" {
			t.Errorf("unexpected engine path: %s", r.URL.Path)
			w.WriteHeader(500)
			return
		}
		var req struct {
			Input            map[string]any `json:"input"`
			DatasetVersionID string         `json:"dataset_version_id"`
			CSVBase64        string         `json:"csv_base64"`
			Role             string         `json:"role"`
			Kind             string         `json:"kind"`
			DatasetName      string         `json:"dataset_name"`
		}
		if json.NewDecoder(r.Body).Decode(&req) != nil {
			w.WriteHeader(500)
			return
		}
		file, err := base64.StdEncoding.DecodeString(req.CSVBase64)
		if err != nil {
			w.WriteHeader(500)
			return
		}
		if strings.Contains(string(file), "bad") {
			w.WriteHeader(422)
			_, _ = w.Write([]byte(`{"detail":"row 2: unknown zone_id"}`))
			return
		}
		fileHash := sha256.Sum256(file)
		sha := hex.EncodeToString(fileHash[:])
		references, _ := req.Input["datasets"].([]any)
		req.Input["datasets"] = append(references, map[string]any{
			"version_id": req.DatasetVersionID, "sha256": sha,
			"role": req.Role, "kind": req.Kind, "source": "operator export",
			"name": req.DatasetName, "transform_version": "test-transform-v1",
		})
		_ = json.NewEncoder(w).Encode(map[string]any{"spec": req.Input, "sha256": sha,
			"transform_version": "test-transform-v1"})
	}))
	defer engine.Close()
	handler := (Server{Store: st, EngineURL: engine.URL, Token: "test-token"}).Handler()
	csv := []byte("session_id,zone_id,started_at,ended_at,energy_kwh\n1,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n")
	request := func(data []byte) *httptest.ResponseRecorder {
		t.Helper()
		var body bytes.Buffer
		writer := multipart.NewWriter(&body)
		for key, value := range map[string]string{
			"scenario_name": "From operator", "dataset_name": datasetName,
			"source": "operator export", "kind": "observed", "time_zone": "Europe/Moscow",
			"start_date": "2027-04-01", "end_date": "2027-04-01",
		} {
			_ = writer.WriteField(key, value)
		}
		file, createErr := writer.CreateFormFile("file", `C:\supplier\sessions.csv`)
		if createErr != nil {
			t.Fatal(createErr)
		}
		_, _ = file.Write(data)
		_ = writer.Close()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/"+parent.ID+"/imports/sessions", &body)
		req.Header.Set("Content-Type", writer.FormDataContentType())
		req.Header.Set("Authorization", "Bearer test-token")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, req)
		return response
	}
	bad := request([]byte("bad"))
	if bad.Code != 422 {
		t.Fatalf("bad CSV accepted: %d %s", bad.Code, bad.Body.String())
	}
	var orphan int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM dataset_versions WHERE name=$1`, datasetName).Scan(&orphan); err != nil || orphan != 0 {
		t.Fatalf("invalid import persisted: %d %v", orphan, err)
	}
	first := request(csv)
	if first.Code != 201 {
		t.Fatalf("upload failed: %d %s", first.Code, first.Body.String())
	}
	var imported struct {
		Scenario struct {
			ID     string          `json:"id"`
			Spec   json.RawMessage `json:"spec"`
			SHA256 string          `json:"sha256"`
		} `json:"scenario"`
		DatasetID string `json:"dataset_id"`
		SHA256    string `json:"sha256"`
		Reused    bool   `json:"reused"`
	}
	if err := json.Unmarshal(first.Body.Bytes(), &imported); err != nil {
		t.Fatal(err)
	}
	createdID, datasetID = imported.Scenario.ID, imported.DatasetID
	if createdID == "" || datasetID == "" || imported.Reused || imported.Scenario.SHA256 == "" {
		t.Fatalf("missing import metadata: %s", first.Body.String())
	}
	var snapshot map[string]any
	if json.Unmarshal(imported.Scenario.Spec, &snapshot) != nil ||
		snapshot["id"] != "base" || len(snapshot["datasets"].([]any)) != 1 {
		t.Fatalf("derived snapshot missing uploaded dataset: %s", imported.Scenario.Spec)
	}
	read := httptest.NewRequest(http.MethodGet, "/api/v1/datasets/"+datasetID+"/file", nil)
	read.Header.Set("Authorization", "Bearer test-token")
	down := httptest.NewRecorder()
	handler.ServeHTTP(down, read)
	if down.Code != 200 || !bytes.Equal(down.Body.Bytes(), csv) ||
		!strings.Contains(down.Header().Get("Content-Disposition"), "sessions.csv") ||
		down.Header().Get("X-Content-SHA256") != imported.SHA256 {
		t.Fatalf("source file was not reproducible: %d %s", down.Code, down.Body.String())
	}
	list := httptest.NewRequest(http.MethodGet, "/api/v1/datasets", nil)
	list.Header.Set("Authorization", "Bearer test-token")
	listed := httptest.NewRecorder()
	handler.ServeHTTP(listed, list)
	var datasets []struct {
		ID     string `json:"id"`
		Format string `json:"format"`
		Role   string `json:"role"`
	}
	if listed.Code != 200 || json.Unmarshal(listed.Body.Bytes(), &datasets) != nil {
		t.Fatalf("dataset manifest unavailable: %d %s", listed.Code, listed.Body.String())
	}
	found := false
	for _, item := range datasets {
		if item.ID == datasetID {
			found = item.Format == "csv" && item.Role == "demand_sessions"
		}
	}
	if !found {
		t.Fatalf("uploaded dataset is not typed in history: %s", listed.Body.String())
	}
	var wg sync.WaitGroup
	errorsFromRetries := make(chan string, 6)
	for range 6 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			retry := request(csv)
			var got struct {
				Scenario struct {
					ID string `json:"id"`
				} `json:"scenario"`
				DatasetID string `json:"dataset_id"`
				Reused    bool   `json:"reused"`
			}
			if retry.Code != 201 || json.Unmarshal(retry.Body.Bytes(), &got) != nil ||
				got.Scenario.ID != createdID || got.DatasetID != datasetID || !got.Reused {
				errorsFromRetries <- fmt.Sprintf("%d %s", retry.Code, retry.Body.String())
			}
		}()
	}
	wg.Wait()
	close(errorsFromRetries)
	for failure := range errorsFromRetries {
		t.Errorf("duplicate import created another version: %s", failure)
	}
	var count int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM scenario_imports WHERE parent_scenario_id=$1::uuid`, parent.ID).Scan(&count); err != nil || count != 1 {
		t.Fatalf("duplicate scenario imports: %d %v", count, err)
	}
	get := httptest.NewRequest(http.MethodGet, "/api/v1/scenarios/"+createdID, nil)
	get.Header.Set("Authorization", "Bearer test-token")
	stored := httptest.NewRecorder()
	handler.ServeHTTP(stored, get)
	if stored.Code != 200 || !strings.Contains(stored.Body.String(), datasetID) {
		t.Fatalf("saved scenario cannot be retrieved: %d %s", stored.Code, stored.Body.String())
	}
}
