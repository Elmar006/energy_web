package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/api"
	"github.com/Elmar006/energy_web/backend/internal/artifact"
	"github.com/Elmar006/energy_web/backend/internal/config"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/redis/go-redis/v9"
)

func main() {
	token := os.Getenv("API_TOKEN")
	if err := config.ValidateAPIToken(token, os.Getenv("APP_ENV"), os.Getenv("ALLOW_INSECURE_DEMO_TOKEN")); err != nil {
		slog.Error("API_TOKEN configuration", "error", err)
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	db, err := store.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("database", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	if err := config.ValidateRuntimeDatabase(ctx, db.DB, os.Getenv("APP_ENV")); err != nil {
		slog.Error("runtime database configuration", "error", err)
		os.Exit(1)
	}
	addr := os.Getenv("API_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	var cache *redis.Client
	if redisAddr := os.Getenv("REDIS_ADDR"); redisAddr != "" {
		cache = redis.NewClient(&redis.Options{Addr: redisAddr})
		defer cache.Close()
	}
	var artifacts artifact.Store
	if root := os.Getenv("ARTIFACT_DIR"); root != "" {
		artifacts = artifact.Local{Root: root}
	}
	server := &http.Server{Addr: addr, Handler: (api.Server{Store: db, Token: token, Cache: cache, EngineURL: os.Getenv("ENGINE_URL"), Artifacts: artifacts}).Handler(), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
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
