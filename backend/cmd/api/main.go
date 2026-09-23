package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/api"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/redis/go-redis/v9"
)

func main() {
	token := os.Getenv("API_TOKEN")
	if len(token) < 24 {
		slog.Error("API_TOKEN must be at least 24 bytes")
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	db, err := store.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("database", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	addr := os.Getenv("API_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	var cache *redis.Client
	if redisAddr := os.Getenv("REDIS_ADDR"); redisAddr != "" {
		cache = redis.NewClient(&redis.Options{Addr: redisAddr})
		defer cache.Close()
	}
	server := &http.Server{Addr: addr, Handler: (api.Server{Store: db, Token: token, Cache: cache, EngineURL: os.Getenv("ENGINE_URL")}).Handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server", "error", err)
			stop()
		}
	}()
	slog.Info("api ready", "address", addr)
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdown)
}
