package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/artifact"
	"github.com/Elmar006/energy_web/backend/internal/planning"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/redis/go-redis/v9"
)

type Server struct {
	Store     *store.Store
	Token     string
	Cache     *redis.Client
	EngineURL string
	Artifacts artifact.Store
}

func (s Server) scenarioQueries() planning.Queries { return planning.Queries{Repository: s.Store} }
func (s Server) runs() planning.Runs               { return planning.Runs{Repository: s.Store} }

var uuidPath = regexp.MustCompile(`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

func validRunOrScenarioID(w http.ResponseWriter, id string) bool {
	if uuidPath.MatchString(id) {
		return true
	}
	fail(w, 422, "invalid_id", "id must be a UUID")
	return false
}

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}

func fail(w http.ResponseWriter, status int, code, detail string) {
	writeJSON(w, status, map[string]string{"code": code, "detail": detail})
}

func (s Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, map[string]string{"status": "ok"}) })
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if err := s.Store.DB.Ping(r.Context()); err != nil {
			fail(w, 503, "database_unavailable", "database is unavailable")
			return
		}
		writeJSON(w, 200, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("POST /api/v1/scenarios", s.createScenario)
	mux.HandleFunc("POST /api/v1/artifacts/demand", s.uploadDemandArtifact)
	mux.HandleFunc("POST /api/v1/scenarios/from-datasets/preview", s.previewDatasetScenario)
	mux.HandleFunc("POST /api/v1/scenarios/from-mobility/preview", s.previewMobilityScenario)
	mux.HandleFunc("POST /api/v1/scenarios/from-mobility", s.createMobilityScenario)
	mux.HandleFunc("POST /api/v1/scenarios/from-datasets", s.createDatasetScenario)
	mux.HandleFunc("GET /api/v1/scenarios", s.listScenarios)
	mux.HandleFunc("GET /api/v1/scenarios/{id}", s.getScenario)
	mux.HandleFunc("GET /api/v1/scenarios/{id}/mobility-origin", s.getMobilityOrigin)
	mux.HandleFunc("POST /api/v1/scenarios/{id}/imports/sessions", s.importSessions)
	mux.HandleFunc("POST /api/v1/scenarios/{id}/imports/grid-headroom", s.importGridHeadroom)
	mux.HandleFunc("POST /api/v1/scenarios/{id}/runs", s.createRun)
	mux.HandleFunc("GET /api/v1/runs/{id}", s.getRun)
	mux.HandleFunc("POST /api/v1/runs/{id}/cancel", s.cancelRun)
	mux.HandleFunc("GET /api/v1/runs/{id}/results", s.getResult)
	mux.HandleFunc("GET /api/v1/runs/{id}/events", s.events)
	mux.HandleFunc("GET /api/v1/datasets", s.datasets)
	mux.HandleFunc("POST /api/v1/datasets/import", s.importDataset)
	mux.HandleFunc("GET /api/v1/datasets/{id}/file", s.downloadUploadedFile)
	mux.HandleFunc("GET /api/v1/map", s.mapGeoJSON)
	mux.HandleFunc("GET /api/v1/tiles/{z}/{x}/{y}", s.tile)
	mux.HandleFunc("POST /api/v1/corridors/check", s.checkCorridor)
	mux.HandleFunc("POST /api/v1/fleets/schedule", s.scheduleFleet)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		if r.URL.Path != "/healthz" && r.URL.Path != "/readyz" {
			supplied := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if s.Token == "" || !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || len(supplied) != len(s.Token) || subtle.ConstantTimeCompare([]byte(supplied), []byte(s.Token)) != 1 {
				fail(w, 401, "unauthorized", "valid bearer token required")
				return
			}
		}
		mux.ServeHTTP(w, r)
	})
}

func (s Server) createScenario(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<20)
	var in struct {
		Name string          `json:"name"`
		Spec json.RawMessage `json:"spec"`
	}
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&in); err != nil {
		fail(w, 400, "invalid_json", err.Error())
		return
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		fail(w, 400, "invalid_json", "one object required")
		return
	}
	saved, err := (planning.Service{
		Repository: s.Store,
		Validator:  planning.ArtifactValidator{Next: planning.HTTPValidator{URL: s.EngineURL}, Reader: s.Artifacts},
	}).CreateScenario(r.Context(), in.Name, in.Spec)
	if errors.Is(err, planning.ErrInvalidScenario) {
		fail(w, 422, "invalid_scenario", err.Error())
		return
	}
	if errors.Is(err, planning.ErrValidatorUnavailable) {
		fail(w, 503, "engine_unavailable", "input validator is unavailable")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to create scenario")
		return
	}
	writeJSON(w, 201, saved)
}

func (s Server) uploadDemandArtifact(w http.ResponseWriter, r *http.Request) {
	if s.Artifacts == nil {
		fail(w, 503, "artifact_store_unavailable", "artifact storage is not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, artifact.MaxBytes)
	content, err := io.ReadAll(r.Body)
	if err != nil {
		fail(w, 413, "artifact_too_large", "demand artifact exceeds 64 MiB or cannot be read")
		return
	}
	if _, err := artifact.ParseDemandDocument(content); err != nil {
		fail(w, 422, "invalid_demand_artifact", "expected demand-dataset-v1 with service_calendar and charging_requests")
		return
	}
	manifest, err := s.Artifacts.Put(r.Context(), content)
	if err != nil {
		fail(w, 500, "artifact_store_error", "unable to store demand artifact")
		return
	}
	writeJSON(w, 201, manifest)
}

func (s Server) listScenarios(w http.ResponseWriter, r *http.Request) {
	items, err := s.scenarioQueries().ListScenarios(r.Context())
	if err != nil {
		fail(w, 500, "database_error", "unable to list scenarios")
		return
	}
	writeJSON(w, 200, items)
}

func (s Server) getScenario(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	out, err := s.scenarioQueries().GetScenario(r.Context(), r.PathValue("id"))
	if errors.Is(err, planning.ErrNotFound) {
		fail(w, 404, "not_found", "scenario not found")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to load scenario")
		return
	}
	writeJSON(w, 200, out)
}

func (s Server) createRun(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 16<<10)
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		fail(w, http.StatusRequestEntityTooLarge, "invalid_run_request", "run request exceeds 16 KiB or cannot be read")
		return
	}
	var in struct {
		RunSpec json.RawMessage `json:"run_spec"`
	}
	if len(strings.TrimSpace(string(raw))) > 0 {
		if strings.TrimSpace(string(raw))[0] != '{' {
			fail(w, 400, "invalid_json", "run request must be an object")
			return
		}
		decoder := json.NewDecoder(strings.NewReader(string(raw)))
		_, _ = decoder.Token() // Opening object was checked above.
		seen := false
		for decoder.More() {
			name, err := decoder.Token()
			if err != nil || name != "run_spec" || seen {
				fail(w, 400, "invalid_json", "unknown or repeated field")
				return
			}
			seen = true
			if err := decoder.Decode(&in.RunSpec); err != nil {
				fail(w, 400, "invalid_json", "invalid run_spec JSON")
				return
			}
		}
		if _, err := decoder.Token(); err != nil {
			fail(w, 400, "invalid_json", "invalid object ending")
			return
		}
		if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
			fail(w, 400, "invalid_json", "one object required")
			return
		}
	}
	out, err := s.runs().Start(r.Context(), r.PathValue("id"), r.Header.Get("Idempotency-Key"), in.RunSpec)
	if errors.Is(err, planning.ErrInvalidKey) {
		fail(w, 422, "invalid_key", "Idempotency-Key must be 8..128 characters")
		return
	}
	if errors.Is(err, planning.ErrInvalidRunSpec) {
		fail(w, 422, "invalid_run_spec", err.Error())
		return
	}
	if errors.Is(err, planning.ErrRunSpecConflict) {
		fail(w, 409, "idempotency_conflict", "Idempotency-Key already identifies a run with different parameters")
		return
	}
	if errors.Is(err, planning.ErrNotFound) {
		fail(w, 404, "not_found", "scenario not found")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to create run")
		return
	}
	writeJSON(w, 202, out)
}

func (s Server) getRun(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	out, err := s.runs().Get(r.Context(), r.PathValue("id"))
	if errors.Is(err, planning.ErrNotFound) {
		fail(w, 404, "not_found", "run not found")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to load run")
		return
	}
	writeJSON(w, 200, out)
}

func (s Server) cancelRun(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	err := s.runs().Cancel(r.Context(), r.PathValue("id"))
	if errors.Is(err, planning.ErrNotCancellable) {
		fail(w, 409, "not_cancellable", "run was already completed or does not exist")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to cancel run")
		return
	}
	writeJSON(w, 200, map[string]string{"state": "cancelled"})
}

func (s Server) getResult(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	out, err := s.runs().Result(r.Context(), r.PathValue("id"))
	if errors.Is(err, planning.ErrNotFound) {
		fail(w, 404, "not_found", "completed result not found")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to load result")
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_, _ = w.Write(out)
}

func (s Server) events(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	if _, err := s.runs().Get(r.Context(), r.PathValue("id")); err != nil {
		if errors.Is(err, planning.ErrNotFound) {
			fail(w, 404, "not_found", "run not found")
		} else {
			fail(w, 500, "database_error", "unable to load run")
		}
		return
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		fail(w, 500, "stream_error", "stream unsupported")
		return
	}
	cursor, _ := strconv.ParseInt(r.Header.Get("Last-Event-ID"), 10, 64)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		events, err := s.runs().Events(r.Context(), r.PathValue("id"), cursor)
		if err != nil {
			return
		}
		for _, event := range events {
			payload, _ := json.Marshal(event)
			_, _ = fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", event.ID, event.Kind, payload)
			cursor = event.ID
		}
		flusher.Flush()
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
		}
	}
}
