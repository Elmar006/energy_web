package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/Elmar006/energy_web/backend/internal/geoimport"
	"github.com/Elmar006/energy_web/backend/internal/store"
)

func main() {
	path := flag.String("file", "", "GeoJSON FeatureCollection")
	name := flag.String("name", "", "dataset name")
	kind := flag.String("kind", "assumed", "observed, derived or assumed; default is assumed")
	source := flag.String("source", "", "source URL or description")
	license := flag.String("license", "", "license")
	capturedAt := flag.String("captured-at", "", "source observation time in RFC3339, required by the scenario builder for observed versions")
	flag.Parse()
	if *path == "" {
		slog.Error("-file is required")
		os.Exit(2)
	}
	input, err := os.Open(*path)
	if err != nil {
		slog.Error("open file", "error", err)
		os.Exit(1)
	}
	defer input.Close()
	var captured *time.Time
	if *capturedAt != "" {
		value, err := time.Parse(time.RFC3339Nano, *capturedAt)
		if err != nil {
			slog.Error("invalid -captured-at", "error", err)
			os.Exit(2)
		}
		captured = &value
	}
	ctx := context.Background()
	db, err := store.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("database", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	result, err := geoimport.Import(ctx, db.DB, input, geoimport.Metadata{Name: *name, Kind: *kind,
		Source: *source, License: *license, CapturedAt: captured})
	if err != nil {
		slog.Error("import failed", "error", err)
		os.Exit(1)
	}
	fmt.Printf("dataset=%s features=%d sha256=%s\n", result.DatasetID, result.Features, result.SHA256)
}
