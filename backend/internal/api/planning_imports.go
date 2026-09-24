package api

import (
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"path"
	"strconv"
	"strings"

	"github.com/Elmar006/energy_web/backend/internal/planning"
)

func (s Server) importSessions(w http.ResponseWriter, r *http.Request) {
	s.importPlanningCSV(w, r, "demand_sessions")
}

func (s Server) importGridHeadroom(w http.ResponseWriter, r *http.Request) {
	s.importPlanningCSV(w, r, "grid_headroom")
}

func (s Server) importPlanningCSV(w http.ResponseWriter, r *http.Request, role string) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	maxFile := planning.MaxSessionCSV
	if role == "grid_headroom" {
		maxFile = planning.MaxGridCSV
	}
	r.Body = http.MaxBytesReader(w, r.Body, int64(maxFile+(2<<20)))
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			fail(w, 413, "upload_too_large", "multipart upload exceeds limit")
		} else {
			fail(w, 400, "invalid_multipart", "multipart/form-data with one CSV file is required")
		}
		return
	}
	defer r.MultipartForm.RemoveAll()
	allowed := map[string]bool{"scenario_name": true, "dataset_name": true,
		"kind": true, "source": true, "license": true, "time_zone": true,
		"start_date": true, "end_date": true, "profile_date": true,
		"coverage_complete": true}
	for key, values := range r.MultipartForm.Value {
		if !allowed[key] || len(values) != 1 {
			fail(w, 422, "invalid_import", "unexpected or repeated metadata field")
			return
		}
	}
	if len(r.MultipartForm.File) != 1 || len(r.MultipartForm.File["file"]) != 1 {
		fail(w, 422, "invalid_import", "exactly one CSV file field is required")
		return
	}
	fileHeader := r.MultipartForm.File["file"][0]
	if fileHeader.Size > int64(maxFile) {
		fail(w, 413, "upload_too_large", "CSV exceeds role-specific limit")
		return
	}
	file, err := fileHeader.Open()
	if err != nil {
		fail(w, 400, "invalid_import", "cannot read CSV file")
		return
	}
	defer file.Close()
	raw, err := io.ReadAll(io.LimitReader(file, int64(maxFile)+1))
	if err != nil {
		fail(w, 400, "invalid_import", "cannot read CSV file")
		return
	}
	if len(raw) > maxFile {
		fail(w, 413, "upload_too_large", "CSV exceeds role-specific limit")
		return
	}
	name := path.Base(strings.ReplaceAll(fileHeader.Filename, "\\", "/"))
	if name == "." || name == "/" || name == "" {
		name = "data.csv"
	}
	coverageComplete := false
	if values, present := r.MultipartForm.Value["coverage_complete"]; present {
		if role != "demand_sessions" || (values[0] != "true" && values[0] != "false") {
			fail(w, 422, "invalid_import", "coverage_complete must be true or false for sessions only")
			return
		}
		coverageComplete, _ = strconv.ParseBool(values[0])
	}
	input := planning.ImportInput{
		ParentScenarioID: r.PathValue("id"), Role: role,
		ScenarioName: r.FormValue("scenario_name"), DatasetName: r.FormValue("dataset_name"),
		FileName: name, Source: r.FormValue("source"), License: r.FormValue("license"),
		Kind: r.FormValue("kind"), TimeZone: r.FormValue("time_zone"),
		StartDate: r.FormValue("start_date"), EndDate: r.FormValue("end_date"),
		ProfileDate: r.FormValue("profile_date"), CoverageComplete: coverageComplete, CSV: raw,
	}
	service := planning.ImportService{Repository: s.Store,
		Deriver:   planning.HTTPDeriver{URL: s.EngineURL},
		Validator: planning.HTTPValidator{URL: s.EngineURL}}
	result, err := service.Import(r.Context(), input)
	switch {
	case errors.Is(err, planning.ErrInvalidImport), errors.Is(err, planning.ErrInvalidScenario):
		fail(w, 422, "invalid_import", err.Error())
	case errors.Is(err, planning.ErrImportTooLarge):
		fail(w, 413, "upload_too_large", "CSV exceeds role-specific limit")
	case errors.Is(err, planning.ErrNotFound):
		fail(w, 404, "not_found", "parent scenario not found")
	case errors.Is(err, planning.ErrDeriverUnavailable), errors.Is(err, planning.ErrValidatorUnavailable):
		fail(w, 503, "engine_unavailable", "data derivation engine is unavailable")
	case err != nil:
		fail(w, 500, "database_error", "unable to save imported planning data")
	default:
		writeJSON(w, 201, result)
	}
}

func (s Server) downloadUploadedFile(w http.ResponseWriter, r *http.Request) {
	if !validRunOrScenarioID(w, r.PathValue("id")) {
		return
	}
	file, err := (planning.UploadQueries{Repository: s.Store}).Download(r.Context(), r.PathValue("id"))
	if errors.Is(err, planning.ErrNotFound) {
		fail(w, 404, "not_found", "uploaded CSV not found")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to load uploaded CSV")
		return
	}
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{
		"filename": file.FileName}))
	w.Header().Set("Content-Length", fmt.Sprint(len(file.Content)))
	w.Header().Set("X-Content-SHA256", file.SHA256)
	_, _ = w.Write(file.Content)
}
