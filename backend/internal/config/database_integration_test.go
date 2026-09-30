//go:build integration

package config

import (
	"context"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestRuntimeDatabaseRejectsOwnerAndSchemaCreation(t *testing.T) {
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL required")
	}
	ctx := context.Background()
	owner, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer owner.Close()
	if err = ValidateRuntimeDatabase(ctx, owner, "production"); err == nil {
		t.Fatal("fixture owner accepted as runtime")
	}
	if err = ValidateRuntimeDatabase(ctx, owner, "test"); err != nil {
		t.Fatal(err)
	}
	role := fmt.Sprintf("runtime_guard_test_%d", time.Now().UnixNano())
	identifier := pgx.Identifier{role}.Sanitize()
	if _, err = owner.Exec(ctx, "CREATE ROLE "+identifier+" NOLOGIN"); err != nil {
		t.Fatal(err)
	}
	defer owner.Exec(ctx, "DROP ROLE "+identifier)
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		t.Fatal(err)
	}
	cfg.MaxConns = 1
	cfg.AfterConnect = func(ctx context.Context, connection *pgx.Conn) error {
		_, err := connection.Exec(ctx, "SET ROLE "+identifier)
		return err
	}
	runtime, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer runtime.Close()
	if err = ValidateRuntimeDatabase(ctx, runtime, "production"); err != nil {
		t.Fatalf("non-owner runtime rejected: %v", err)
	}
	if _, err = owner.Exec(ctx, "GRANT pg_read_all_data TO "+identifier); err != nil {
		t.Fatal(err)
	}
	if err = ValidateRuntimeDatabase(ctx, runtime, "production"); err == nil {
		t.Fatal("inherited database access accepted")
	}
	if _, err = owner.Exec(ctx, "REVOKE pg_read_all_data FROM "+identifier); err != nil {
		t.Fatal(err)
	}
	if _, err = owner.Exec(ctx, "GRANT CREATE ON SCHEMA public TO "+identifier); err != nil {
		t.Fatal(err)
	}
	defer owner.Exec(ctx, "REVOKE CREATE ON SCHEMA public FROM "+identifier)
	if err = ValidateRuntimeDatabase(ctx, runtime, "production"); err == nil {
		t.Fatal("schema creation privilege accepted")
	}
}
