package cache

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisTiles is an optional adapter. The geography use case treats errors as
// cache misses because PostgreSQL remains the authoritative source.
type RedisTiles struct{ Client *redis.Client }

func (c RedisTiles) Get(ctx context.Context, key string) ([]byte, error) {
	return c.Client.Get(ctx, key).Bytes()
}

func (c RedisTiles) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	return c.Client.Set(ctx, key, value, ttl).Err()
}
