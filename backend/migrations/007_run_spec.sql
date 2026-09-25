-- A run owns its execution controls. Historical controls were not persisted:
-- infer only the former worker defaults and explicitly retain that distinction.
-- Existing results are never rewritten or promoted to verified evidence.
ALTER TABLE runs
  ADD COLUMN run_spec jsonb,
  ADD COLUMN scenario_sha256 text,
  ADD COLUMN run_spec_sha256 text,
  ADD COLUMN execution_sha256 text,
  ADD COLUMN run_spec_origin text;

WITH prior AS (
  SELECT r.id, sc.spec_sha256,
    CASE WHEN sc.spec #> '{parameters,solver_seconds}' = 'true'::jsonb THEN 1
      WHEN sc.spec #>> '{parameters,solver_seconds}' ~ '^[0-9]{1,4}([.]0+)?$'
      THEN (sc.spec #>> '{parameters,solver_seconds}')::numeric::integer END AS solver_seconds,
    CASE WHEN sc.spec #> '{parameters,simulation_days}' = 'true'::jsonb THEN 1
      WHEN sc.spec #>> '{parameters,simulation_days}' ~ '^[0-9]{1,2}([.]0+)?$'
      THEN (sc.spec #>> '{parameters,simulation_days}')::numeric::integer END AS simulation_days
  FROM runs r JOIN scenarios sc ON sc.id=r.scenario_id
)
UPDATE runs r SET scenario_sha256=prior.spec_sha256, run_spec_origin='legacy_inferred',
  run_spec=jsonb_build_object(
    'schema_version','run-spec-v1',
    'model_version','planner-mip-v3',
    'simulation_version','simpy-multiday-v1',
    'mode','exploratory',
    'simulation_seeds',jsonb_build_array(1,2,3),
    'explain_top_n',3,
    'alternative_service_fractions',jsonb_build_array(0,0.5,1),
    'alternative_solver_seconds',20,
    'solver_seconds',CASE WHEN prior.solver_seconds BETWEEN 1 AND 3600 THEN prior.solver_seconds ELSE 60 END,
    'simulation_days',CASE WHEN prior.simulation_days BETWEEN 1 AND 14 THEN prior.simulation_days ELSE 3 END
  )
FROM prior WHERE prior.id=r.id;

UPDATE runs SET run_spec_sha256=encode(sha256(convert_to(run_spec::text,'UTF8')),'hex');
UPDATE runs SET execution_sha256=encode(sha256(convert_to(scenario_sha256 || E'\n' || run_spec_sha256,'UTF8')),'hex');

ALTER TABLE runs
  ALTER COLUMN run_spec SET NOT NULL,
  ALTER COLUMN scenario_sha256 SET NOT NULL,
  ALTER COLUMN run_spec_sha256 SET NOT NULL,
  ALTER COLUMN execution_sha256 SET NOT NULL,
  ALTER COLUMN run_spec_origin SET NOT NULL,
  ADD CONSTRAINT runs_spec_object CHECK (jsonb_typeof(run_spec)='object'),
  ADD CONSTRAINT runs_scenario_sha_format CHECK (scenario_sha256 ~ '^[0-9a-f]{64}$'),
  ADD CONSTRAINT runs_spec_sha_valid CHECK (run_spec_sha256=encode(sha256(convert_to(run_spec::text,'UTF8')),'hex')),
  ADD CONSTRAINT runs_execution_sha_valid CHECK (execution_sha256=encode(sha256(convert_to(scenario_sha256 || E'\n' || run_spec_sha256,'UTF8')),'hex')),
  ADD CONSTRAINT runs_spec_origin_valid CHECK (run_spec_origin IN ('resolved','legacy_inferred'));

-- Application methods already create new scenario versions. Enforce that
-- contract in the database so a stored run cannot silently execute new inputs.
ALTER TABLE scenarios ADD CONSTRAINT scenarios_snapshot_sha_valid
  CHECK (spec_sha256=encode(sha256(convert_to(spec::text,'UTF8')),'hex'));

CREATE FUNCTION protect_scenario_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- jsonb equates 1 and 1.0, while their serialized bytes differ. Immutable
  -- evidence must preserve the representation used to calculate its digest.
  IF NEW.spec::text IS DISTINCT FROM OLD.spec::text OR NEW.spec_sha256 IS DISTINCT FROM OLD.spec_sha256 THEN
    RAISE EXCEPTION 'scenario snapshots are immutable; create a new scenario'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER scenarios_immutable_snapshot BEFORE UPDATE OF spec,spec_sha256 ON scenarios
  FOR EACH ROW EXECUTE FUNCTION protect_scenario_snapshot();

CREATE FUNCTION protect_run_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.scenario_sha256 IS DISTINCT FROM (SELECT spec_sha256 FROM scenarios WHERE id=NEW.scenario_id) THEN
      RAISE EXCEPTION 'run scenario checksum does not match the immutable scenario'
        USING ERRCODE='23514';
    END IF;
  ELSIF ROW(NEW.scenario_id,NEW.idempotency_key,NEW.run_spec,NEW.scenario_sha256,NEW.run_spec_sha256,NEW.execution_sha256,NEW.run_spec_origin)
    IS DISTINCT FROM ROW(OLD.scenario_id,OLD.idempotency_key,OLD.run_spec,OLD.scenario_sha256,OLD.run_spec_sha256,OLD.execution_sha256,OLD.run_spec_origin) THEN
    RAISE EXCEPTION 'run snapshots and fingerprints are immutable; create a new run'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER runs_immutable_snapshot BEFORE INSERT OR UPDATE OF scenario_id,idempotency_key,run_spec,scenario_sha256,run_spec_sha256,execution_sha256,run_spec_origin ON runs
  FOR EACH ROW EXECUTE FUNCTION protect_run_snapshot();
