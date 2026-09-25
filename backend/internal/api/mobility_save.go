package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

func (s Server) mobilitySaver() planning.MobilitySaveService {
	return planning.MobilitySaveService{
		PreviewService: planning.MobilityPreviewService{
			Compiler:  planning.HTTPMobilityCompiler{URL: s.EngineURL},
			Validator: planning.HTTPValidator{URL: s.EngineURL}},
		Repository: s.Store,
	}
}

func (s Server) createMobilityScenario(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<20)
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			fail(w, 413, "request_too_large", "mobility creation request exceeds 4 MiB")
		} else {
			fail(w, 400, "invalid_json", "unable to read mobility creation request")
		}
		return
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	opening, err := decoder.Token()
	if err != nil || opening != json.Delim('{') {
		fail(w, 400, "invalid_json", "one object required")
		return
	}
	var input planning.MobilityPreviewRequest
	var name string
	seen := make(map[string]bool, 3)
	for decoder.More() {
		field, tokenErr := decoder.Token()
		key, ok := field.(string)
		if tokenErr != nil || !ok || seen[key] {
			fail(w, 400, "invalid_json", "unknown or repeated field")
			return
		}
		seen[key] = true
		switch key {
		case "name":
			err = decoder.Decode(&name)
		case "input":
			err = decoder.Decode(&input.Input)
		case "mobility":
			err = decoder.Decode(&input.Mobility)
		default:
			fail(w, 400, "invalid_json", "unknown or repeated field")
			return
		}
		if err != nil {
			fail(w, 400, "invalid_json", "invalid name, input or mobility JSON")
			return
		}
	}
	closing, err := decoder.Token()
	if err != nil || closing != json.Delim('}') {
		fail(w, 400, "invalid_json", "invalid object ending")
		return
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		fail(w, 400, "invalid_json", "one object required")
		return
	}
	result, err := s.mobilitySaver().Save(r.Context(), name, input)
	switch {
	case errors.Is(err, planning.ErrInvalidScenario):
		fail(w, 422, "invalid_mobility", err.Error())
	case errors.Is(err, planning.ErrMobilityInvalidResponse):
		fail(w, 502, "invalid_engine_response", "mobility compiler returned inconsistent source or scenario data")
	case errors.Is(err, planning.ErrMobilityCompilerUnavailable), errors.Is(err, planning.ErrValidatorUnavailable):
		fail(w, 503, "engine_unavailable", "mobility compiler is unavailable")
	case err != nil:
		fail(w, 500, "database_error", "unable to save mobility scenario")
	default:
		writeJSON(w, 201, result)
	}
}

func (s Server) getMobilityOrigin(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	origin, err := s.mobilitySaver().Origin(
		r.Context(), r.PathValue("id"), r.Header.Get("X-Mobility-Source-Token"))
	switch {
	case errors.Is(err, planning.ErrNotFound):
		// Hide whether the scenario has an origin or the capability was wrong.
		fail(w, 404, "not_found", "mobility origin not found")
	case err != nil:
		fail(w, 500, "database_error", "unable to load mobility origin")
	default:
		writeJSON(w, 200, origin)
	}
}
