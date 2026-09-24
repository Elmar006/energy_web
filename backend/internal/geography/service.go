package geography

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"time"
)

type Dataset struct {
	ID         string     `json:"id"`
	Name       string     `json:"name"`
	Kind       string     `json:"kind"`
	Source     string     `json:"source"`
	License    *string    `json:"license,omitempty"`
	Checksum   string     `json:"checksum"`
	CapturedAt *time.Time `json:"captured_at,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
}

type Repository interface {
	Datasets(context.Context) ([]Dataset, error)
	GeoJSON(context.Context, float64, float64, float64, float64, string) (json.RawMessage, error)
	Tile(context.Context, int, int, int, string) ([]byte, error)
}

type TileCache interface {
	Get(context.Context, string) ([]byte, error)
	Set(context.Context, string, []byte, time.Duration) error
}

type Service struct {
	Repository Repository
	Cache      TileCache
}

var ErrInvalidBounds = errors.New("invalid geographic bounds")
var ErrInvalidTile = errors.New("invalid tile coordinates")

func (s Service) Datasets(ctx context.Context) ([]Dataset, error) {
	return s.Repository.Datasets(ctx)
}

func (s Service) GeoJSON(ctx context.Context, west, south, east, north float64, kind string) (json.RawMessage, error) {
	for _, v := range []float64{west, south, east, north} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return nil, ErrInvalidBounds
		}
	}
	if west < -180 || east > 180 || south < -90 || north > 90 || west >= east || south >= north {
		return nil, ErrInvalidBounds
	}
	return s.Repository.GeoJSON(ctx, west, south, east, north, kind)
}

func (s Service) Tile(ctx context.Context, z, x, y int, kind string) ([]byte, error) {
	if z < 0 || z > 22 || x < 0 || y < 0 || int64(x) >= 1<<z || int64(y) >= 1<<z {
		return nil, ErrInvalidTile
	}
	key := fmt.Sprintf("tile:v1:%d:%d:%d:%s", z, x, y, kind)
	if s.Cache != nil {
		if cached, err := s.Cache.Get(ctx, key); err == nil {
			return cached, nil
		}
	}
	data, err := s.Repository.Tile(ctx, z, x, y, kind)
	if err != nil {
		return nil, err
	}
	if s.Cache != nil {
		_ = s.Cache.Set(ctx, key, data, 30*time.Second)
	}
	return data, nil
}
