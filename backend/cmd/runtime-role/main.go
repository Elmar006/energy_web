// runtime-role is an owner-only deployment step, never part of API startup.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

func main() {
	if err := provision(); err != nil {
		slog.Error("runtime role provisioning failed", "error", err)
		os.Exit(1)
	}
}

func provision() error {
	password := os.Getenv("RUNTIME_DB_PASSWORD")
	if len(password) < 32 || strings.Contains(strings.ToLower(password), "replace") {
		return fmt.Errorf("RUNTIME_DB_PASSWORD must be a strong independent secret")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	db, err := pgx.Connect(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		return fmt.Errorf("owner database connection failed")
	}
	defer db.Close(ctx)
	tx, err := db.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(506598209141)`); err != nil {
		return err
	}
	var exists bool
	if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='energy_runtime')`).Scan(&exists); err != nil {
		return err
	}
	if !exists {
		if _, err = tx.Exec(ctx, `CREATE ROLE energy_runtime LOGIN`); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(ctx, `ALTER ROLE energy_runtime NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`); err != nil {
		return err
	}
	var statement string
	if err = tx.QueryRow(ctx, `SELECT format('ALTER ROLE energy_runtime PASSWORD %L', $1::text)`, password).Scan(&statement); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, statement); err != nil {
		return fmt.Errorf("runtime password update failed")
	}
	if _, err = tx.Exec(ctx, `REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO energy_runtime`); err != nil {
		return err
	}
	rows, err := tx.Query(ctx, `SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('schema_migrations','spatial_ref_sys')`)
	if err != nil {
		return err
	}
	var tables []string
	for rows.Next() {
		var name string
		if err = rows.Scan(&name); err != nil {
			rows.Close()
			return err
		}
		tables = append(tables, name)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	for _, name := range tables {
		if _, err = tx.Exec(ctx, `GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE `+pgx.Identifier{"public", name}.Sanitize()+` TO energy_runtime`); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(ctx, `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO energy_runtime`); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `REVOKE ALL ON TABLE schema_migrations FROM energy_runtime`); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
