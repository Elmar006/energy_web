package migrate

import (
	"context"
	"os"
	"strings"
	"testing"
	"testing/fstest"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestApplyIsIdempotentAndRejectsEditedMigration(t *testing.T) {
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is not configured")
	}
	ctx := context.Background()
	admin, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close()
	schema := "migrate_test_" + strings.ReplaceAll(time.Now().UTC().Format("150405.000000000"), ".", "")
	if _, err := admin.Exec(ctx, `CREATE SCHEMA `+schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.Exec(context.Background(), `DROP SCHEMA `+schema+` CASCADE`) })
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		t.Fatal(err)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = schema + ",public"
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	source := fstest.MapFS{
		"001_create.sql": {Data: []byte(`CREATE TABLE migration_example (id integer PRIMARY KEY);`)},
		"002_index.sql":  {Data: []byte(`CREATE INDEX migration_example_idx ON migration_example(id);`)},
	}
	if err := Apply(ctx, pool, source); err != nil {
		t.Fatal(err)
	}
	if err := Apply(ctx, pool, source); err != nil {
		t.Fatalf("second application: %v", err)
	}
	var count int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM schema_migrations`).Scan(&count); err != nil || count != 2 {
		t.Fatalf("migration count = %d, error = %v", count, err)
	}
	source["001_create.sql"] = &fstest.MapFile{Data: []byte(`CREATE TABLE migration_example (id bigint PRIMARY KEY);`)}
	if err := Apply(ctx, pool, source); err == nil || !strings.Contains(err.Error(), "checksum changed") {
		t.Fatalf("modified migration accepted: %v", err)
	}
}
