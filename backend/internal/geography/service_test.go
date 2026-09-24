package geography

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"testing"
	"time"
)

type repositoryStub struct{ tileCalls, mapCalls int }

func (r *repositoryStub) Datasets(context.Context) ([]Dataset, error) { return nil, nil }
func (r *repositoryStub) GeoJSON(context.Context, float64, float64, float64, float64, string) (json.RawMessage, error) {
	r.mapCalls++
	return json.RawMessage(`{"type":"FeatureCollection","features":[]}`), nil
}
func (r *repositoryStub) Tile(context.Context, int, int, int, string) ([]byte, error) {
	r.tileCalls++
	return []byte("tile"), nil
}

type cacheStub struct {
	value    []byte
	getError error
	sets     int
	ttl      time.Duration
}

func (c *cacheStub) Get(context.Context, string) ([]byte, error) { return c.value, c.getError }
func (c *cacheStub) Set(_ context.Context, _ string, value []byte, ttl time.Duration) error {
	c.sets++
	c.value, c.ttl = value, ttl
	return nil
}

func TestInvalidMapRequestsNeverReachRepository(t *testing.T) {
	repo := &repositoryStub{}
	service := Service{Repository: repo}
	for _, bounds := range [][4]float64{{math.NaN(), 0, 1, 1}, {0, 0, 0, 1}, {0, 0, 181, 1}} {
		if _, err := service.GeoJSON(context.Background(), bounds[0], bounds[1], bounds[2], bounds[3], ""); !errors.Is(err, ErrInvalidBounds) {
			t.Fatalf("invalid bounds accepted: %v", err)
		}
	}
	for _, coords := range [][3]int{{-1, 0, 0}, {23, 0, 0}, {2, 4, 0}} {
		if _, err := service.Tile(context.Background(), coords[0], coords[1], coords[2], ""); !errors.Is(err, ErrInvalidTile) {
			t.Fatalf("invalid tile accepted: %v", err)
		}
	}
	if repo.mapCalls != 0 || repo.tileCalls != 0 {
		t.Fatal("invalid request reached repository")
	}
}

func TestTileCacheHitAndRedisFailureFallback(t *testing.T) {
	repo := &repositoryStub{}
	cache := &cacheStub{value: []byte("cached")}
	service := Service{Repository: repo, Cache: cache}
	data, err := service.Tile(context.Background(), 2, 1, 1, "station")
	if err != nil || string(data) != "cached" || repo.tileCalls != 0 {
		t.Fatalf("cache hit: %q, %v, calls=%d", data, err, repo.tileCalls)
	}
	cache.getError = errors.New("redis unavailable")
	data, err = service.Tile(context.Background(), 2, 1, 1, "station")
	if err != nil || string(data) != "tile" || repo.tileCalls != 1 || cache.sets != 1 || cache.ttl != 30*time.Second {
		t.Fatalf("cache fallback: %q, %v, calls=%d", data, err, repo.tileCalls)
	}
}
