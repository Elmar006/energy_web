import unittest
import tempfile
from pathlib import Path
from production_preflight import validate, deployment_values

class ProductionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.valid = {"POSTGRES_PASSWORD":"a"*40, "RUNTIME_DB_PASSWORD":"b"*40, "API_TOKEN":"c"*40,
                      "SESSION_SECRET":"d"*40, "APP_ACCESS_PASSWORD":"e"*40, "APP_PUBLIC_ORIGIN":"https://planner.test"}

    def test_valid_private_configuration(self):
        self.assertEqual(validate(self.valid), [])

    def test_shell_override_cannot_bypass_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.env"
            path.write_text("".join(f"{k}={v}\n" for k, v in self.valid.items()), encoding="utf-8")
            self.assertEqual(validate(deployment_values(path, {})), [])
            self.assertTrue(validate(deployment_values(path, {"POSTGRES_PASSWORD": "short"})))
            self.assertTrue(validate(deployment_values(path, {"SESSION_SECRET": ""})))

    def test_missing_reused_placeholder_and_url_unsafe_secrets(self):
        for patch in [{"API_TOKEN":""}, {"SESSION_SECRET":"c"*40}, {"RUNTIME_DB_PASSWORD":"replace-"+"x"*40},
                      {"POSTGRES_PASSWORD":"x"*40+"@"}, {"APP_PUBLIC_ORIGIN":"http://planner.test"},
                      {"APP_PUBLIC_ORIGIN":"https://user:password@planner.test"}, {"FRONTEND_PORT":"0"}]:
            self.assertTrue(validate(self.valid | patch), patch.keys())

if __name__ == "__main__":
    unittest.main()
