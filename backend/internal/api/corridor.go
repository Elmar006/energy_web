package api

import (
	"bytes"
	"io"
	"net/http"
	"strings"
	"time"
)

func (s Server) checkCorridor(w http.ResponseWriter, r *http.Request) {
	s.postEngine(w, r, "/v1/corridor/check")
}

func (s Server) scheduleFleet(w http.ResponseWriter, r *http.Request) {
	s.postEngine(w, r, "/v1/fleet/schedule")
}

func (s Server) postEngine(w http.ResponseWriter, r *http.Request, path string) {
	if s.EngineURL == "" {
		fail(w, http.StatusServiceUnavailable, "engine_unavailable", "corridor engine is not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	input, err := io.ReadAll(r.Body)
	if err != nil {
		fail(w, http.StatusRequestEntityTooLarge, "invalid_body", "request exceeds 1 MiB")
		return
	}
	request, err := http.NewRequestWithContext(r.Context(), http.MethodPost,
		strings.TrimRight(s.EngineURL, "/")+path, bytes.NewReader(input))
	if err != nil {
		fail(w, 500, "engine_error", "unable to prepare corridor calculation")
		return
	}
	request.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 15 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		fail(w, 503, "engine_unavailable", "corridor engine is unavailable")
		return
	}
	defer response.Body.Close()
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(response.StatusCode)
	_, _ = io.Copy(w, io.LimitReader(response.Body, 1<<20))
}
