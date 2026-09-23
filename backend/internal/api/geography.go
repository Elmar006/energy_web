package api

import (
	"fmt"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func (s Server) datasets(w http.ResponseWriter, r *http.Request) {
	out, err := s.Store.Datasets(r.Context())
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
		if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
			fail(w, 422, "invalid_bbox", "bbox must contain numbers")
			return
		}
		values[i] = v
	}
	if values[0] < -180 || values[2] > 180 || values[1] < -90 || values[3] > 90 || values[0] >= values[2] || values[1] >= values[3] {
		fail(w, 422, "invalid_bbox", "bbox outside valid range")
		return
	}
	body, err := s.Store.GeoJSON(r.Context(), values[0], values[1], values[2], values[3], r.URL.Query().Get("type"))
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
	if zerr != nil || xerr != nil || yerr != nil || z < 0 || z > 22 || x < 0 || y < 0 || int64(x) >= 1<<z || int64(y) >= 1<<z {
		fail(w, 422, "invalid_tile", "invalid tile coordinates")
		return
	}
	kind := r.URL.Query().Get("type")
	key := fmt.Sprintf("tile:v1:%d:%d:%d:%s", z, x, y, kind)
	if s.Cache != nil {
		if cached, err := s.Cache.Get(r.Context(), key).Bytes(); err == nil {
			w.Header().Set("Content-Type", "application/vnd.mapbox-vector-tile")
			_, _ = w.Write(cached)
			return
		}
	}
	data, err := s.Store.Tile(r.Context(), z, x, y, kind)
	if err != nil {
		fail(w, 500, "database_error", "unable to render tile")
		return
	}
	if s.Cache != nil {
		_ = s.Cache.Set(r.Context(), key, data, 30*time.Second).Err()
	}
	w.Header().Set("Content-Type", "application/vnd.mapbox-vector-tile")
	_, _ = w.Write(data)
}
