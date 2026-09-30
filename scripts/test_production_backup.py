import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from production_backup import Deployment, FILES, sha256, verify_backup


class BackupTests(unittest.TestCase):
    def make_backup(self, root, name="./" + "a" * 64, kind=tarfile.REGTYPE):
        (root / FILES[0]).write_bytes(b"fixture-dump")
        with tarfile.open(root / FILES[1], "w:gz") as archive:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = 3 if kind == tarfile.REGTYPE else 0
            entry.linkname = "../../escape"
            archive.addfile(entry, io.BytesIO(b"123") if entry.size else None)
        manifest = {"version": "energy-backup-v1", "files": {
            name: {"sha256": sha256(root / name), "bytes": (root / name).stat().st_size} for name in FILES}}
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_corruption_detected_before_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_backup(root)
            verify_backup(root)
            (root / FILES[0]).write_bytes(b"corrupt-dump")
            with self.assertRaisesRegex(ValueError, "integrity"):
                verify_backup(root)

    def test_archive_cannot_escape_destination(self):
        for name, kind in [("../../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("./link", tarfile.SYMTYPE), ("..\\escape", tarfile.REGTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                self.make_backup(Path(temp), name, kind)
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    verify_backup(Path(temp))

    def test_application_database_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_backup(root)
            deployment = Deployment(root / "config", "energy-qa")
            with patch.object(deployment, "run") as command:
                with self.assertRaisesRegex(ValueError, "scratch"):
                    deployment.recover_check(root, "energy", root / "restore")
                command.assert_not_called()

    def test_backup_requires_stopped_writers(self):
        with tempfile.TemporaryDirectory() as temp:
            deployment = Deployment(Path(temp) / "config", "energy-qa")
            with patch.object(deployment, "run") as command:
                command.return_value.stdout = b"running-api-id\n"
                with self.assertRaisesRegex(ValueError, "stop"):
                    deployment.backup(Path(temp) / "backup")
                self.assertFalse((Path(temp) / "backup").exists())


if __name__ == "__main__":
    unittest.main()
