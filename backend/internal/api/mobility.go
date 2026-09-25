package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

func (s Server) previewMobilityScenario(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<20)
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			fail(w, 413, "request_too_large", "mobility preview request exceeds 4 MiB")
		} else {
			fail(w, 400, "invalid_json", "unable to read mobility preview request")
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
	seen := make(map[string]bool, 2)
	for decoder.More() {
		name, err := decoder.Token()
		key, ok := name.(string)
		if err != nil || !ok || seen[key] {
			fail(w, 400, "invalid_json", "unknown or repeated field")
			return
		}
		seen[key] = true
		switch key {
		case "input":
			err = decoder.Decode(&input.Input)
		case "mobility":
			err = decoder.Decode(&input.Mobility)
		default:
			fail(w, 400, "invalid_json", "unknown or repeated field")
			return
		}
		if err != nil {
			fail(w, 400, "invalid_json", "invalid input or mobility JSON")
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
	service := planning.MobilityPreviewService{
		Compiler:  planning.HTTPMobilityCompiler{URL: s.EngineURL},
		Validator: planning.HTTPValidator{URL: s.EngineURL},
	}
	result, err := service.Preview(r.Context(), input)
	switch {
	case errors.Is(err, planning.ErrInvalidScenario):
		fail(w, 422, "invalid_mobility", err.Error())
	case errors.Is(err, planning.ErrMobilityInvalidResponse):
		fail(w, 502, "invalid_engine_response", "mobility compiler returned an invalid planning input")
	case errors.Is(err, planning.ErrMobilityCompilerUnavailable), errors.Is(err, planning.ErrValidatorUnavailable):
		fail(w, 503, "engine_unavailable", "mobility compiler is unavailable")
	case err != nil:
		fail(w, 500, "mobility_error", "unable to prepare mobility scenario")
	default:
		writeJSON(w, 200, result)
	}
}
