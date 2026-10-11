import copy
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-not-for-production")

import app as tecman


class PersistenceFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tickets_file = Path(self.tmp.name) / "tickets.json"

    def test_configured_postgresql_initialization_error_aborts_startup(self):
        with self.assertRaisesRegex(
            tecman.PersistenceUnavailableError,
            "se rechaza el fallback a JSON",
        ):
            tecman._abort_configured_database_startup()

    def test_connection_error_during_real_app_import_never_enables_json_backend(self):
        model_names = (
            "TicketDB MatafuegoDB MatafuegoVisitaDB GrupoElectrogenoDB FumigacionDB "
            "HabilitacionDB ComprobanteDB StockMovimientoDB NotifAdminDB AlertaSyhDB "
            "SyhGestionDB VehiculoDB PermisoDB PresupuestoDB CeyhRetiroDB CeyhJornadaDB "
            "LoteFifoDB TransferDB ConfigDB LogisticsStateDB UserDB AuthIdentityDB "
            "LocalCredentialDB PasswordResetTokenDB AuthAuditEventDB"
        ).split()
        script = textwrap.dedent(
            f"""
            import sys
            import types

            models = types.ModuleType("models")

            class BrokenDB:
                def init_app(self, app):
                    return None

                def create_all(self):
                    raise ConnectionError("simulated connection refusal")

            models.db = BrokenDB()
            for name in {model_names!r}:
                setattr(models, name, object())
            sys.modules["models"] = models

            try:
                import app
            except Exception as exc:
                expected = (
                    type(exc).__name__ == "PersistenceUnavailableError"
                    and "se rechaza el fallback a JSON" in str(exc)
                )
                raise SystemExit(0 if expected else 2)
            raise SystemExit(3)
            """
        )
        env = os.environ.copy()
        env["DATABASE_URL"] = "postgresql://configured-for-test"
        env["TECMAN_DATA_DIR"] = str(Path(self.tmp.name) / "data")
        env["TECMAN_UPLOADS_DIR"] = str(Path(self.tmp.name) / "uploads")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(tecman.__file__).parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertFalse((Path(self.tmp.name) / "data" / "tickets.json").exists())

    def test_postgresql_read_error_does_not_fall_back_to_json(self):
        local_snapshot = [{"id": "json-ephemeral", "estado": "Nuevo"}]
        self.tickets_file.write_text(json.dumps(local_snapshot), encoding="utf-8")
        before = self.tickets_file.read_bytes()

        with (
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "TicketDB", object(), create=True),
            patch.object(tecman, "TICKETS_FILE", self.tickets_file),
            patch.object(tecman, "_db_list", side_effect=RuntimeError("db caída")),
        ):
            with self.assertRaisesRegex(RuntimeError, "db caída"):
                tecman.load_tickets(readonly=True)

        self.assertEqual(self.tickets_file.read_bytes(), before)

    def test_postgresql_write_error_does_not_mutate_json(self):
        original = [{"id": "json-original", "estado": "Nuevo"}]
        replacement = [{"id": "db-replacement", "estado": "Resuelto"}]
        self.tickets_file.write_text(json.dumps(original), encoding="utf-8")
        before = self.tickets_file.read_bytes()

        with (
            patch.object(tecman, "USE_DB", True),
            patch.object(tecman, "TicketDB", object(), create=True),
            patch.object(tecman, "TICKETS_FILE", self.tickets_file),
            patch.object(tecman, "_db_replace", side_effect=RuntimeError("db caída")),
            patch.object(tecman, "_atomic_write", wraps=tecman._atomic_write) as atomic_write,
        ):
            with self.assertRaisesRegex(RuntimeError, "db caída"):
                tecman.save_tickets(copy.deepcopy(replacement))

        atomic_write.assert_not_called()
        self.assertEqual(self.tickets_file.read_bytes(), before)

    def test_local_json_remains_available_without_postgresql_configuration(self):
        initial = [{"id": "local-1", "estado": "Nuevo"}]
        replacement = [{"id": "local-1", "estado": "Resuelto"}]
        self.tickets_file.write_text(json.dumps(initial), encoding="utf-8")

        with (
            patch.object(tecman, "USE_DB", False),
            patch.object(tecman, "TICKETS_FILE", self.tickets_file),
        ):
            self.assertEqual(tecman.load_tickets(readonly=True), initial)
            tecman.save_tickets(copy.deepcopy(replacement))
            self.assertEqual(tecman.load_tickets(readonly=True), replacement)


if __name__ == "__main__":
    unittest.main()
