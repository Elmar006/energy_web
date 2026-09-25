-- A mobility source is part of its scenario's immutable snapshot. Deleting the
-- child first would leave a scenario whose manifest names an unavailable input.
-- Deleting the scenario itself remains the deliberate retention-cleanup path.
ALTER TABLE scenario_mobility_sources
  DROP CONSTRAINT scenario_mobility_sources_scenario_id_fkey;
ALTER TABLE scenario_mobility_sources
  ADD CONSTRAINT scenario_mobility_sources_scenario_id_fkey
  FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE;

CREATE FUNCTION protect_linked_mobility_source_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM scenarios WHERE id=OLD.scenario_id) THEN
    RAISE EXCEPTION 'delete the mobility scenario to remove its source snapshot'
      USING ERRCODE='23514';
  END IF;
  RETURN OLD;
END;
$$;

CREATE TRIGGER mobility_source_delete_with_scenario
  BEFORE DELETE ON scenario_mobility_sources
  FOR EACH ROW EXECUTE FUNCTION protect_linked_mobility_source_delete();
