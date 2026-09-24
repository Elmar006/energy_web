package api

import (
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/cache"
	"github.com/Elmar006/energy_web/backend/internal/geography"
)

func (s Server) importDataset(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 52<<20)
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			fail(w, 413, "upload_too_large", "multipart upload exceeds 52 MiB")
		} else {
			fail(w, 400, "invalid_multipart", "multipart/form-data with a GeoJSON file is required")
		}
		return
	}
	defer r.MultipartForm.RemoveAll()
	allowedFields := map[string]bool{"name": true, "kind": true, "source": true,
		"license": true, "captured_at": true}
	for field, values := range r.MultipartForm.Value {
		if !allowedFields[field] || len(values) != 1 {
			fail(w, 422, "invalid_dataset", "unexpected or repeated metadata field")
			return
		}
	}
	if len(r.MultipartForm.File) != 1 {
		fail(w, 422, "invalid_dataset", "unexpected file field")
		return
	}
	if len(r.MultipartForm.File["file"]) != 1 {
		fail(w, 422, "invalid_dataset", "exactly one GeoJSON file is required")
		return
	}
	input, _, err := r.FormFile("file")
	if err != nil {
		fail(w, 422, "invalid_dataset", "GeoJSON file is required")
		return
	}
	defer input.Close()
	meta := geography.ImportMetadata{
		Name: r.FormValue("name"), Kind: r.FormValue("kind"),
		Source: r.FormValue("source"), License: r.FormValue("license"),
	}
	if stamp := r.FormValue("captured_at"); stamp != "" {
		instant, err := time.Parse(time.RFC3339Nano, stamp)
		if err != nil {
			fail(w, 422, "invalid_dataset", "captured_at must be RFC3339")
			return
		}
		meta.CapturedAt = &instant
	}
	result, err := (geography.ImportService{Repository: s.Store}).Import(r.Context(), input, meta)
	if errors.Is(err, geography.ErrInvalidImport) {
		fail(w, 422, "invalid_dataset", err.Error())
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to import dataset")
		return
	}
	writeJSON(w, 201, result)
}

func (s Server) geography() geography.Service {
	service := geography.Service{Repository: s.Store}
	if s.Cache != nil {
		service.Cache = cache.RedisTiles{Client: s.Cache}
	}
	return service
}

func (s Server) datasets(w http.ResponseWriter, r *http.Request) {
	out, err := s.geography().Datasets(r.Context())
	if err != nil {
		fail(w, 500, "database_error", "unable to load datasets")
		return
	}
	writeJSON(w, 200, out)
}

func (s Server) mapGeoJSON(w http.ResponseWriter, r *http.Request) {
	parts := strings.Split(r.URL.Query().Get("bbox"), ",")
	if len(parts) != 4 {
		fail(w, 422, "invalid_bbox", "bbox must be west,south,east,north")
		return
	}
	values := make([]float64, 4)
	for i, part := range parts {
		v, err := strconv.ParseFloat(part, 64)
		if err != nil {
			fail(w, 422, "invalid_bbox", "bbox must contain numbers")
			return
		}
		values[i] = v
	}
	body, err := s.geography().GeoJSON(r.Context(), values[0], values[1], values[2], values[3], r.URL.Query().Get("type"))
	if errors.Is(err, geography.ErrInvalidBounds) {
		fail(w, 422, "invalid_bbox", "bbox outside valid range")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to load map")
		return
	}
	w.Header().Set("Content-Type", "application/geo+json")
	_, _ = w.Write(body)
}

func (s Server) tile(w http.ResponseWriter, r *http.Request) {
	z, zerr := strconv.Atoi(r.PathValue("z"))
	x, xerr := strconv.Atoi(r.PathValue("x"))
	y, yerr := strconv.Atoi(r.PathValue("y"))
	if zerr != nil || xerr != nil || yerr != nil {
		fail(w, 422, "invalid_tile", "invalid tile coordinates")
		return
	}
	data, err := s.geography().Tile(r.Context(), z, x, y, r.URL.Query().Get("type"))
	if errors.Is(err, geography.ErrInvalidTile) {
		fail(w, 422, "invalid_tile", "invalid tile coordinates")
		return
	}
	if err != nil {
		fail(w, 500, "database_error", "unable to render tile")
		return
	}
	w.Header().Set("Content-Type", "application/vnd.mapbox-vector-tile")
	_, _ = w.Write(data)
}
