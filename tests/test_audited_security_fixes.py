import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ["SECRET_KEY"] = "audited-security-test"
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402
import migrate_json_to_db as migration  # noqa: E402


class MigrationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for spec in migration.LIST_SOURCES:
            if spec.root_key:
                value = {spec.root_key: []}
            else:
                value = []
            (self.source / spec.filename).write_text(json.dumps(value), encoding="utf-8")
        for filename, _key, _type in migration.CONFIG_SOURCES:
            (self.source / filename).write_text("{}", encoding="utf-8")
        self.backup = self.root / "before.zip"
        self.backup.write_bytes(b"verified-backup")
        self.digest = hashlib.sha256(self.backup.read_bytes()).hexdigest()

    def test_complete_preflight_accepts_explicit_source_and_verified_backup(self):
        snapshot = migration.preflight(self.source, self.backup, self.digest)
        self.assertEqual(snapshot["source"], self.source.resolve())
        self.assertEqual(snapshot["backup_sha256"], self.digest)
        self.assertEqual(set(snapshot["lists"]), {spec.label for spec in migration.LIST_SOURCES})

    def test_preflight_rejects_missing_document_before_migrate_is_called(self):
        (self.source / "tickets.json").unlink()
        with patch.object(migration, "migrate") as migrate:
            result = migration.main([
                "--source-dir", str(self.source),
                "--backup", str(self.backup),
                "--backup-sha256", self.digest,
            ])
        self.assertEqual(result, 2)
        migrate.assert_not_called()

    def test_preflight_rejects_bad_backup_checksum(self):
        with self.assertRaisesRegex(migration.PreflightError, "no coincide"):
            migration.preflight(self.source, self.backup, "0" * 64)

    def test_preflight_rejects_missing_or_duplicate_record_ids(self):
        tickets = self.source / "tickets.json"
        tickets.write_text(json.dumps([{"estado": "Nuevo"}]), encoding="utf-8")
        with self.assertRaisesRegex(migration.PreflightError, "sin id explícito"):
            migration.preflight(self.source, self.backup, self.digest)
        tickets.write_text(json.dumps([{"id": 1}, {"id": "1"}]), encoding="utf-8")
        with self.assertRaisesRegex(migration.PreflightError, "ids duplicados"):
            migration.preflight(self.source, self.backup, self.digest)

    def test_migration_has_one_commit_no_schema_mutation_and_rollback(self):
        source = Path(migration.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("db.session.commit()"), 1)
        self.assertEqual(source.count("db.session.rollback()"), 1)
        self.assertNotIn("db.create_all", source)


class CredentialSafetyTests(unittest.TestCase):
    def test_empty_legacy_credential_never_authenticates(self):
        self.assertFalse(tecman._legacy_password_matches({"password": ""}, ""))
        self.assertFalse(tecman._legacy_password_matches({}, "anything"))
        self.assertTrue(tecman._legacy_password_matches({"password": "configured"}, "configured"))

    def test_production_without_secret_key_aborts_import(self):
        env = os.environ.copy()
        env.pop("SECRET_KEY", None)
        env["RENDER"] = "true"
        env["TECMAN_DATA_DIR"] = str(self.root_path("prod-data"))
        env["TECMAN_UPLOADS_DIR"] = str(self.root_path("prod-uploads"))
        result = subprocess.run(
            [sys.executable, "-c", "import app"],
            cwd=Path(tecman.__file__).parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY debe configurarse explícitamente", result.stderr)

    @staticmethod
    def root_path(name):
        return Path(_TEST_ROOT.name) / name


class BackupDataTests(unittest.TestCase):
    def setUp(self):
        tecman.app.config.update(TESTING=True, SECRET_KEY="backup-test")
        self.client = tecman.app.test_client()

    def test_local_json_mode_keeps_json_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "tickets.json").write_text('[{"id":"local"}]', encoding="utf-8")
            with patch.dict(os.environ, {"BACKUP_SECRET": "backup-token"}), \
                 patch.object(tecman, "USE_DB", False), \
                 patch.object(tecman, "DATA_DIR", data_dir):
                response = self.client.get("/api/backup-data?token=backup-token")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["tickets.json"])

    def test_postgresql_mode_uses_database_export_not_stale_json(self):
        documents = {
            "database/tickets.json": [{"id": "db"}],
            "manifest.json": {"backend": "postgresql", "tables": {"tickets": 1}},
        }
        with patch.dict(os.environ, {"BACKUP_SECRET": "backup-token"}), \
             patch.object(tecman, "USE_DB", True), \
             patch.object(tecman, "_postgresql_backup_documents", return_value=documents) as export:
            response = self.client.get("/api/backup-data?token=backup-token")
        self.assertEqual(response.status_code, 200)
        export.assert_called_once_with()
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(set(archive.namelist()), set(documents))
            self.assertEqual(json.loads(archive.read("database/tickets.json")), [{"id": "db"}])

    def test_postgresql_export_failure_returns_no_partial_success(self):
        with patch.dict(os.environ, {"BACKUP_SECRET": "backup-token"}), \
             patch.object(tecman, "USE_DB", True), \
             patch.object(tecman, "_postgresql_backup_documents", side_effect=RuntimeError("db unavailable")):
            with self.assertRaisesRegex(RuntimeError, "db unavailable"):
                self.client.get("/api/backup-data?token=backup-token")


if __name__ == "__main__":
    unittest.main()
