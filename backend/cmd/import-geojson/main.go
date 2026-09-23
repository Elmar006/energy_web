package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"

	"github.com/Elmar006/energy_web/backend/internal/geoimport"
	"github.com/Elmar006/energy_web/backend/internal/store"
)

func main() {
	path := flag.String("file", "", "GeoJSON FeatureCollection")
	name := flag.String("name", "", "dataset name")
	kind := flag.String("kind", "observed", "observed, derived or assumed")
	source := flag.String("source", "", "source URL or description")
	license := flag.String("license", "", "license")
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
	ctx := context.Background()
	db, err := store.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		slog.Error("database", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	result, err := geoimport.Import(ctx, db.DB, input, geoimport.Metadata{Name: *name, Kind: *kind, Source: *source, License: *license})
	if err != nil {
		slog.Error("import failed", "error", err)
		os.Exit(1)
	}
	fmt.Printf("dataset=%s features=%d sha256=%s\n", result.DatasetID, result.Features, result.SHA256)
}
