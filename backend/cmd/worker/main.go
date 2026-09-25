package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"

	"github.com/Elmar006/energy_web/backend/internal/artifact"
	"github.com/Elmar006/energy_web/backend/internal/store"
	"github.com/Elmar006/energy_web/backend/internal/worker"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	db, err := store.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("database", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	url := os.Getenv("ENGINE_URL")
	if url == "" {
		url = "http://engine:8090"
	}
	var artifacts artifact.Reader
	if root := os.Getenv("ARTIFACT_DIR"); root != "" {
		artifacts = artifact.Local{Root: root}
	}
	w := worker.Worker{Store: db, Artifacts: artifacts, EngineURL: url}
	slog.Info("worker ready")
	if err := w.Run(ctx); err != nil && err != context.Canceled {
		slog.Error("worker stopped", "error", err)
		os.Exit(1)
	}
}
