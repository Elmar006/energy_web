package migrate

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"regexp"
	"sort"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var migrationName = regexp.MustCompile(`^[0-9]{3}_[a-z0-9_]+\.sql$`)

// Apply serializes migrations across processes and rejects edited versions.
// SQL files must be transactional; CREATE INDEX CONCURRENTLY belongs in a
// dedicated maintenance procedure, not in these short bootstrap migrations.
func Apply(ctx context.Context, db *pgxpool.Pool, source fs.FS) error {
	entries, err := fs.ReadDir(source, ".")
	if err != nil {
		return err
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !migrationName.MatchString(entry.Name()) {
			continue
		}
		names = append(names, entry.Name())
	}
	sort.Strings(names)
	if len(names) == 0 {
		return errors.New("no numbered SQL migrations found")
	}
	tx, err := db.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(506598209140)`); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `CREATE TABLE IF NOT EXISTS schema_migrations (
		name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
	)`); err != nil {
		return err
	}
	for _, name := range names {
		body, readErr := fs.ReadFile(source, name)
		if readErr != nil {
			return readErr
		}
		// Git can check out SQL with CRLF on Windows. A platform-specific
		// newline must not make an otherwise identical migration appear edited.
		sum := sha256.Sum256(bytes.ReplaceAll(body, []byte("\r\n"), []byte("\n")))
		checksum := hex.EncodeToString(sum[:])
		var previous string
		err = tx.QueryRow(ctx, `SELECT sha256 FROM schema_migrations WHERE name=$1`, name).Scan(&previous)
		if err == nil {
			if previous != checksum {
				return fmt.Errorf("migration %s checksum changed", name)
			}
			continue
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if _, err = tx.Exec(ctx, string(body)); err != nil {
			return fmt.Errorf("migration %s: %w", name, err)
		}
		if _, err = tx.Exec(ctx, `INSERT INTO schema_migrations(name,sha256) VALUES($1,$2)`, name, checksum); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}
