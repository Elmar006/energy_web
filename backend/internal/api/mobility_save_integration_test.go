package api

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/migrate"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestMobilitySaveAndCapabilityGatedOriginIntegration(t *testing.T) {
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	ctx := context.Background()
	db, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := migrate.Apply(ctx, db, os.DirFS("../../migrations")); err != nil {
		t.Fatal(err)
	}
	source := `{"license":null,"schema_version":"mobility-v1","source":"representative survey","source_kind":"assumed"}`
	sourceSum := sha256.Sum256([]byte(source))
	sourceSHA := hex.EncodeToString(sourceSum[:])
	var badHash bool
	engine := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v1/mobility/compile":
			var input struct {
				Input    map[string]any `json:"input"`
				Mobility map[string]any `json:"mobility"`
			}
			if json.NewDecoder(r.Body).Decode(&input) != nil || input.Input["id"] != "original" ||
				input.Mobility["schema_version"] != "mobility-v1" {
				t.Error("unexpected source passed to compiler")
			}
			sha := sourceSHA
			if badHash {
				sha = strings.Repeat("0", 64)
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"spec": map[string]any{"id": "compiled", "datasets": []any{map[string]any{
					"name": "mobility-v1 potential public requests", "role": "planning_assumptions",
					"kind": "derived", "source_kind": "assumed", "source": "representative survey",
					"sha256": sha, "transform_version": "mobility-v1"}}},
				"requests": []any{}, "calendar_profiles": []any{}, "audit": map[string]any{},
				"source_sha256": sha, "source_canonical_json": source,
				"compiler_source_sha256":    strings.Repeat("a", 64),
				"compiler_pydantic_version": "2.12.0",
			})
		case "/v1/validate":
			_, _ = w.Write([]byte(`{"valid":true}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer engine.Close()
	handler := (Server{Store: &store.Store{DB: db}, EngineURL: engine.URL, Token: "mobility-test-token"}).Handler()
	name := fmt.Sprintf("mobility-integration-%d", time.Now().UnixNano())
	body := fmt.Sprintf(`{"name":%q,"input":{"id":"original"},"mobility":{"schema_version":"mobility-v1"}}`, name)
	request := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/from-mobility", strings.NewReader(body))
	request.Header.Set("Authorization", "Bearer mobility-test-token")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 201 {
		t.Fatalf("save returned %d: %s", response.Code, response.Body.String())
	}
	var saved struct {
		Scenario struct {
			ID     string          `json:"id"`
			Spec   json.RawMessage `json:"spec"`
			SHA256 string          `json:"sha256"`
		} `json:"scenario"`
		DatasetVersionID  string `json:"dataset_version_id"`
		SourceSHA256      string `json:"source_sha256"`
		BaseSHA256        string `json:"base_sha256"`
		SourceAccessToken string `json:"source_access_token"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &saved); err != nil {
		t.Fatal(err)
	}
	if saved.Scenario.ID == "" || saved.DatasetVersionID == "" || saved.SourceSHA256 != sourceSHA ||
		len(saved.SourceAccessToken) != 64 || len(saved.BaseSHA256) != 64 {
		t.Fatalf("incomplete save response: %s", response.Body.String())
	}
	t.Cleanup(func() {
		_, _ = db.Exec(context.Background(), `DELETE FROM scenarios WHERE id=$1::uuid`, saved.Scenario.ID)
		_, _ = db.Exec(context.Background(), `DELETE FROM dataset_versions WHERE id=$1::uuid`, saved.DatasetVersionID)
	})
	var bound struct {
		Datasets []struct {
			VersionID string `json:"version_id"`
			SHA256    string `json:"sha256"`
		} `json:"datasets"`
	}
	if json.Unmarshal(saved.Scenario.Spec, &bound) != nil || len(bound.Datasets) != 1 ||
		bound.Datasets[0].VersionID != saved.DatasetVersionID || bound.Datasets[0].SHA256 != sourceSHA {
		t.Fatalf("scenario does not bind source dataset: %s", saved.Scenario.Spec)
	}
	var storedSourceSHA, storedBaseSHA, datasetSHA, sourceKind string
	var sourceBytes []byte
	err = db.QueryRow(ctx, `SELECT m.content,m.source_sha256,m.base_sha256,d.checksum,d.kind
		FROM scenario_mobility_sources m JOIN dataset_versions d ON d.id=m.dataset_version_id
		WHERE m.scenario_id=$1::uuid`, saved.Scenario.ID).Scan(
		&sourceBytes, &storedSourceSHA, &storedBaseSHA, &datasetSHA, &sourceKind)
	if err != nil || string(sourceBytes) != source || storedSourceSHA != sourceSHA ||
		storedBaseSHA != saved.BaseSHA256 || datasetSHA != sourceSHA || sourceKind != "assumed" {
		t.Fatalf("atomic source save failed: %v", err)
	}
	datasets, err := (&store.Store{DB: db}).Datasets(ctx)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, dataset := range datasets {
		if dataset.ID == saved.DatasetVersionID {
			found = dataset.Format == "mobility" && dataset.Role != nil &&
				*dataset.Role == "mobility_source" && dataset.Checksum == sourceSHA
			break
		}
	}
	if !found {
		t.Fatal("mobility dataset was missing or mislabeled in dataset listing")
	}
	if _, err := db.Exec(ctx, `UPDATE scenario_mobility_sources SET content=content
		WHERE scenario_id=$1::uuid`, saved.Scenario.ID); err == nil {
		t.Fatal("immutable mobility source was updated")
	}
	if _, err := db.Exec(ctx, `UPDATE dataset_versions SET source='changed'
		WHERE id=$1::uuid`, saved.DatasetVersionID); err == nil {
		t.Fatal("mobility dataset provenance was updated after scenario binding")
	}
	if _, err := db.Exec(ctx, `DELETE FROM scenario_mobility_sources
		WHERE scenario_id=$1::uuid`, saved.Scenario.ID); err == nil {
		t.Fatal("mobility source was removed while its scenario still exists")
	}
	if _, err := db.Exec(ctx, `DELETE FROM dataset_versions
		WHERE id=$1::uuid`, saved.DatasetVersionID); err == nil {
		t.Fatal("mobility dataset was removed while its scenario is bound")
	}
	get := func(bearer, capability string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/scenarios/"+saved.Scenario.ID+"/mobility-origin", nil)
		if bearer != "" {
			req.Header.Set("Authorization", "Bearer "+bearer)
		}
		if capability != "" {
			req.Header.Set("X-Mobility-Source-Token", capability)
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec
	}
	if got := get("", saved.SourceAccessToken); got.Code != 401 {
		t.Fatalf("bearerless retrieval returned %d", got.Code)
	}
	if got := get("mobility-test-token", ""); got.Code != 404 {
		t.Fatalf("capability-free retrieval returned %d", got.Code)
	}
	if got := get("mobility-test-token", strings.Repeat("0", 64)); got.Code != 404 {
		t.Fatalf("wrong capability retrieval returned %d", got.Code)
	}
	got := get("mobility-test-token", saved.SourceAccessToken)
	if got.Code != 200 || got.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("authorized retrieval returned %d: %s", got.Code, got.Body.String())
	}
	var origin struct {
		SourceCanonicalJSON  string          `json:"source_canonical_json"`
		BaseInput            json.RawMessage `json:"base_input"`
		CompilerSourceSHA256 string          `json:"compiler_source_sha256"`
	}
	originErr := json.Unmarshal(got.Body.Bytes(), &origin)
	var base struct {
		ID string `json:"id"`
	}
	baseErr := json.Unmarshal(origin.BaseInput, &base)
	if originErr != nil || origin.SourceCanonicalJSON != source ||
		baseErr != nil || base.ID != "original" || len(origin.CompilerSourceSHA256) != 64 {
		t.Fatalf("retrieved origin is not reproducible: %s", got.Body.String())
	}
	badHash = true
	badName := name + "-bad"
	badBody := fmt.Sprintf(`{"name":%q,"input":{"id":"original"},"mobility":{"schema_version":"mobility-v1"}}`, badName)
	badRequest := httptest.NewRequest(http.MethodPost, "/api/v1/scenarios/from-mobility", strings.NewReader(badBody))
	badRequest.Header.Set("Authorization", "Bearer mobility-test-token")
	badResponse := httptest.NewRecorder()
	handler.ServeHTTP(badResponse, badRequest)
	if badResponse.Code != 502 {
		t.Fatalf("tampered engine source returned %d: %s", badResponse.Code, badResponse.Body.String())
	}
	var count int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM scenarios WHERE name=$1`, badName).Scan(&count); err != nil || count != 0 {
		t.Fatalf("tampered engine response wrote a scenario: %d %v", count, err)
	}
	if _, err := db.Exec(ctx, `DELETE FROM scenarios WHERE id=$1::uuid`, saved.Scenario.ID); err != nil {
		t.Fatalf("scenario retention cleanup failed: %v", err)
	}
	if err := db.QueryRow(ctx, `SELECT count(*) FROM scenario_mobility_sources
		WHERE scenario_id=$1::uuid`, saved.Scenario.ID).Scan(&count); err != nil || count != 0 {
		t.Fatalf("scenario deletion did not remove source snapshot: count=%d err=%v", count, err)
	}
	if _, err := db.Exec(ctx, `DELETE FROM dataset_versions WHERE id=$1::uuid`, saved.DatasetVersionID); err != nil {
		t.Fatalf("dataset retention cleanup failed after scenario deletion: %v", err)
	}
}
