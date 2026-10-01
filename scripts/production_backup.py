"""Offline backup and recovery verification for compose.production.yaml.

Never restores over the application database. Recovery creates a new scratch
database and a new directory. Stop frontend/api/worker before backup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FILES = ("database.dump", "artifacts.tar.gz")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "energy-backup-v1" or set(manifest.get("files", {})) != set(FILES):
        raise ValueError("invalid backup manifest")
    for name in FILES:
        entry = manifest["files"][name]
        path = directory / name
        if path.is_symlink() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"backup integrity mismatch: {name}")
    # Reject link traversal, device files and absolute names before extraction.
    with tarfile.open(directory / "artifacts.tar.gz", "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe artifact archive")
    return manifest


class Deployment:
    def __init__(self, env_file: Path, project: str):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,62}", project):
            raise ValueError("invalid compose project")
        self.prefix = ["docker", "compose", "--env-file", str(env_file.resolve()),
                       "-f", str(ROOT / "compose.production.yaml"), "-p", project]

    def run(self, *args: str, **kwargs):
        # Do not propagate container logs (which may contain confidential input).
        result = subprocess.run([*self.prefix, *args], stderr=subprocess.PIPE, **kwargs)
        if result.returncode:
            raise RuntimeError("deployment command failed; inspect controlled service logs")
        return result

    def inventory(self, database: str) -> dict:
        query = """SELECT json_build_object(
          'migrations', (SELECT count(*) FROM schema_migrations),
          'scenarios', (SELECT count(*) FROM scenarios),
          'runs', (SELECT count(*) FROM runs))"""
        result = self.run("exec", "-T", "db", "psql", "-U", "energy_owner", "-d", database,
                          "-Atc", query, stdout=subprocess.PIPE)
        return json.loads(result.stdout)

    def backup(self, directory: Path):
        for service in ("frontend", "api", "worker"):
            running = self.run("ps", "--status", "running", "-q", service, stdout=subprocess.PIPE).stdout
            if running.strip():
                raise ValueError("stop frontend/api/worker before a consistent backup")
        container = self.run("ps", "--all", "-q", "api", stdout=subprocess.PIPE).stdout.decode().strip()
        if not re.fullmatch(r"[0-9a-f]{12,64}", container):
            raise ValueError("exactly one existing API container is required")
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        with (directory / FILES[0]).open("xb") as stream:
            self.run("exec", "-T", "db", "pg_dump", "-U", "energy_owner", "-d", "energy",
                     "--format=custom", stdout=stream)
        with (directory / FILES[1]).open("xb") as stream:
            result = subprocess.run(["docker", "run", "--rm", "--network", "none", "--volumes-from",
                                     container + ":ro", "alpine:3.22", "tar", "-C", "/data/artifacts", "-czf", "-", "."],
                                    stdout=stream, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError("artifact backup failed")
        manifest = {"version": "energy-backup-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                    "inventory": self.inventory("energy"),
                    "files": {name: {"bytes": (directory / name).stat().st_size,
                                      "sha256": sha256(directory / name)} for name in FILES}}
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        verify_backup(directory)

    def recover_check(self, directory: Path, database: str, artifact_output: Path):
        manifest = verify_backup(directory)
        if not re.fullmatch(r"energy_restore_[a-z0-9_]{1,40}", database):
            raise ValueError("recovery database must be a NEW energy_restore_* scratch database")
        artifact_output.mkdir(mode=0o700, parents=True, exist_ok=False)
        # createdb fails if it exists. No DROP, --clean or writes to 'energy'.
        self.run("exec", "-T", "db", "createdb", "-U", "energy_owner", "--", database, stdout=subprocess.PIPE)
        with (directory / FILES[0]).open("rb") as stream:
            self.run("exec", "-T", "db", "pg_restore", "-U", "energy_owner", "-d", database,
                     "--exit-on-error", "--no-owner", "--no-acl", stdin=stream, stdout=subprocess.PIPE)
        with tarfile.open(directory / FILES[1], "r:gz") as archive:
            archive.extractall(artifact_output, filter="data")
        if self.inventory(database) != manifest["inventory"]:
            raise ValueError("restored database inventory mismatch")
        # Local store file names are their content address; validate every file.
        count = 0
        for path in artifact_output.rglob("*"):
            if path.is_file():
                if path.name.startswith(".upload-"):
                    continue  # Unpublished upload remnants are not referenced by manifests.
                if (not re.fullmatch(r"[0-9a-f]{64}\.json", path.name)
                        or path.parent.name != path.stem[:2] or sha256(path) != path.stem):
                    raise ValueError("restored artifact content address mismatch")
                count += 1
        print(json.dumps({"status": "recovery_verified", "database": database,
                          "inventory": manifest["inventory"], "artifacts": count}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--project", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "recover-check"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
        if name == "recover-check":
            command.add_argument("--database", required=True)
            command.add_argument("--artifact-output", type=Path, required=True)
    args = parser.parse_args()
    deployment = Deployment(args.env_file, args.project)
    if args.command == "backup":
        deployment.backup(args.directory)
        print("Backup created and checksums verified. Store it encrypted outside this host.")
    else:
        deployment.recover_check(args.directory, args.database, args.artifact_output)


if __name__ == "__main__":
    main()
