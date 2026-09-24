package api

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

func (s Server) datasetBuilder() planning.DatasetBuilder {
	return planning.DatasetBuilder{Repository: s.Store,
		Validator: planning.HTTPValidator{URL: s.EngineURL}}
}

func (s Server) previewDatasetScenario(w http.ResponseWriter, r *http.Request) {
	s.handleDatasetScenario(w, r, false)
}

func (s Server) createDatasetScenario(w http.ResponseWriter, r *http.Request) {
	s.handleDatasetScenario(w, r, true)
}

func (s Server) handleDatasetScenario(w http.ResponseWriter, r *http.Request, create bool) {
	r.Body = http.MaxBytesReader(w, r.Body, 4<<20)
	var input planning.DatasetBuildRequest
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&input); err != nil {
		fail(w, 400, "invalid_json", err.Error())
		return
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		fail(w, 400, "invalid_json", "one object required")
		return
	}
	builder := s.datasetBuilder()
	if !create {
		prepared, err := builder.Prepare(r.Context(), input)
		if err != nil {
			datasetBuildError(w, err)
			return
		}
		writeJSON(w, 200, prepared)
		return
	}
	saved, quality, err := builder.Create(r.Context(), input)
	if err != nil {
		datasetBuildError(w, err)
		return
	}
	writeJSON(w, 201, map[string]any{"scenario": saved, "data_quality": quality})
}

func datasetBuildError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, planning.ErrInvalidScenario):
		fail(w, 422, "invalid_dataset_scenario", err.Error())
	case errors.Is(err, planning.ErrDatasetNotFound):
		fail(w, 404, "dataset_not_found", "selected dataset version does not exist")
	case errors.Is(err, planning.ErrValidatorUnavailable):
		fail(w, 503, "engine_unavailable", "input validator is unavailable")
	default:
		fail(w, 500, "database_error", "unable to build scenario from datasets")
	}
}
