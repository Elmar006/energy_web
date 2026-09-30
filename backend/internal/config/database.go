package config

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Production runtime credentials must not be migration/owner credentials.
func ValidateRuntimeDatabase(ctx context.Context, db *pgxpool.Pool, environment string) error {
	if environment != "production" {
		return nil
	}
	var privileged bool
	err := db.QueryRow(ctx, `SELECT r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
 OR has_schema_privilege(current_user, 'public', 'CREATE')
 OR EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner=current_user)
 OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
 FROM pg_roles r WHERE r.rolname=current_user`).Scan(&privileged)
	if err != nil {
		return errors.New("could not verify production database privileges")
	}
	if privileged {
		return errors.New("production API/worker must use a non-owner role without administrative or schema creation privileges")
	}
	return nil
}
