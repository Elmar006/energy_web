package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/redis/go-redis/v9"
)

type Server struct {
	Store     *store.Store
	Token     string
	Cache     *redis.Client
	EngineURL string
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
	mux.HandleFunc("GET /api/v1/scenarios/{id}", s.getScenario)
	mux.HandleFunc("POST /api/v1/scenarios/{id}/runs", s.createRun)
	mux.HandleFunc("GET /api/v1/runs/{id}", s.getRun)
	mux.HandleFunc("POST /api/v1/runs/{id}/cancel", s.cancelRun)
	mux.HandleFunc("GET /api/v1/runs/{id}/results", s.getResult)
	mux.HandleFunc("GET /api/v1/runs/{id}/events", s.events)
	mux.HandleFunc("GET /api/v1/datasets", s.datasets)
	mux.HandleFunc("GET /api/v1/map", s.mapGeoJSON)
	mux.HandleFunc("GET /api/v1/tiles/{z}/{x}/{y}", s.tile)
	mux.HandleFunc("POST /api/v1/corridors/check", s.checkCorridor)
	mux.HandleFunc("POST /api/v1/fleets/schedule", s.scheduleFleet)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		if r.URL.Path != "/healthz" && r.URL.Path != "/readyz" {
			supplied := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
			if len(supplied) != len(s.Token) || subtle.ConstantTimeCompare([]byte(supplied), []byte(s.Token)) != 1 {
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
	if strings.TrimSpace(in.Name) == "" || len(in.Name) > 120 || !json.Valid(in.Spec) || string(in.Spec) == "null" {
		fail(w, 422, "invalid_scenario", "name and JSON spec are required")
		return
	}
	saved, err := s.Store.CreateScenario(r.Context(), in.Name, in.Spec)
	if err != nil {
		fail(w, 500, "database_error", "unable to create scenario")
		return
	}
	writeJSON(w, 201, saved)
}

func (s Server) getScenario(w http.ResponseWriter, r *http.Request) {
	out, err := s.Store.GetScenario(r.Context(), r.PathValue("id"))
	if errors.Is(err, store.ErrNotFound) {
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
	key := r.Header.Get("Idempotency-Key")
	if len(key) < 8 || len(key) > 128 {
		fail(w, 422, "invalid_key", "Idempotency-Key must be 8..128 characters")
		return
	}
	id := r.PathValue("id")
	if _, err := s.Store.GetScenario(r.Context(), id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			fail(w, 404, "not_found", "scenario not found")
		} else {
			fail(w, 500, "database_error", "unable to load scenario")
		}
		return
	}
	out, err := s.Store.CreateRun(r.Context(), id, key)
	if err != nil {
		fail(w, 500, "database_error", "unable to create run")
		return
	}
	writeJSON(w, 202, out)
}

func (s Server) getRun(w http.ResponseWriter, r *http.Request) {
	out, err := s.Store.GetRun(r.Context(), r.PathValue("id"))
	if errors.Is(err, store.ErrNotFound) {
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
	ok, err := s.Store.Cancel(r.Context(), r.PathValue("id"))
	if err != nil {
		fail(w, 500, "database_error", "unable to cancel run")
		return
	}
	if !ok {
		fail(w, 409, "not_cancellable", "run was already completed or does not exist")
		return
	}
	writeJSON(w, 200, map[string]string{"state": "cancelled"})
}

func (s Server) getResult(w http.ResponseWriter, r *http.Request) {
	out, err := s.Store.Result(r.Context(), r.PathValue("id"))
	if errors.Is(err, store.ErrNotFound) {
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
	if _, err := s.Store.GetRun(r.Context(), r.PathValue("id")); err != nil {
		if errors.Is(err, store.ErrNotFound) {
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
		events, err := s.Store.Events(r.Context(), r.PathValue("id"), cursor)
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
