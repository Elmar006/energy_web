package main

import (
	"context"
	"flag"
	"log/slog"
	"os"
	"os/signal"

	"github.com/Elmar006/energy_web/backend/internal/migrate"
	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	dir := flag.String("dir", "/migrations", "directory containing numbered SQL migrations")
	flag.Parse()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	pool, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("database connection", "error", err)
		os.Exit(1)
	}
	defer pool.Close()
	if err := migrate.Apply(ctx, pool, os.DirFS(*dir)); err != nil {
		slog.Error("migration failed", "error", err)
		os.Exit(1)
	}
	slog.Info("schema migrations applied")
}
