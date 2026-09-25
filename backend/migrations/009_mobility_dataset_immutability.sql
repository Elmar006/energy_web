-- The source bytes are immutable in scenario_mobility_sources. Keep their
-- catalog metadata equally stable after a scenario binds the dataset version.
CREATE FUNCTION protect_linked_mobility_dataset() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM scenario_mobility_sources
             WHERE dataset_version_id=OLD.id) THEN
    RAISE EXCEPTION 'mobility dataset versions are immutable; create a new version'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER mobility_dataset_immutable BEFORE UPDATE ON dataset_versions
  FOR EACH ROW EXECUTE FUNCTION protect_linked_mobility_dataset();
