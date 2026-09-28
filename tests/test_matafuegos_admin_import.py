import json
import os
import tempfile
import unittest
from pathlib import Path


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class MatafuegosAdminImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (
            tecman.MATAFUEGOS_FILE,
            tecman.ALERTAS_SYH_FILE,
            tecman.DATA_DIR,
            tecman.USE_DB,
        )
        tecman.DATA_DIR = root / "data"
        tecman.MATAFUEGOS_FILE = tecman.DATA_DIR / "matafuegos.json"
        tecman.ALERTAS_SYH_FILE = tecman.DATA_DIR / "alertas_syh.json"
        tecman.DATA_DIR.mkdir(parents=True)
        tecman.USE_DB = False
        tecman.app.config.update(TESTING=True, SECRET_KEY="matafuegos-admin-import-test")
        self.client = tecman.app.test_client()
        self.before = {
            "matafuegos": [
                {
                    "id": "m1",
                    "sucursal": "Sucursal 036",
                    "sucursal_num": "036",
                    "tipo": "ABC",
                    "capacidad": "5 KG",
                    "historial": [{"accion": "manual"}],
                }
            ]
        }
        tecman.save_matafuegos(self.before)

    def tearDown(self):
        (
            tecman.MATAFUEGOS_FILE,
            tecman.ALERTAS_SYH_FILE,
            tecman.DATA_DIR,
            tecman.USE_DB,
        ) = self.original
        self.temp.cleanup()

    def _admin(self):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user="admin-test", rol="admin", nombre="Admin Test", _csrf_token="csrf-test")

    def test_export_requires_admin_and_reports_current_hash(self):
        self.assertEqual(self.client.get("/admin/syh/matafuegos/export.json").status_code, 302)
        self._admin()
        response = self.client.get("/admin/syh/matafuegos/export.json")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["schema"], "tecman.matafuegos-export/v1")
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["sha256"], tecman._canonical_json_sha256(self.before))
        self.assertEqual(body["data"], self.before)

    def test_import_rejects_csrf_divergence_and_duplicates_without_mutation(self):
        self._admin()
        exported = self.client.get("/admin/syh/matafuegos/export.json").get_json()
        changed = {"matafuegos": [dict(self.before["matafuegos"][0], tipo="CO2")]}

        response = self.client.post(
            "/admin/syh/matafuegos/import.json",
            data={"expected_current_sha256": exported["sha256"], "data": json.dumps(changed)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_matafuegos(), self.before)

        response = self.client.post(
            "/admin/syh/matafuegos/import.json",
            data={
                "_csrf_token": "csrf-test",
                "expected_current_sha256": "bad",
                "data": json.dumps(changed),
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(tecman.load_matafuegos(), self.before)

        duplicated = {"matafuegos": [self.before["matafuegos"][0], self.before["matafuegos"][0]]}
        response = self.client.post(
            "/admin/syh/matafuegos/import.json",
            data={
                "_csrf_token": "csrf-test",
                "expected_current_sha256": exported["sha256"],
                "data": json.dumps(duplicated),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_matafuegos(), self.before)

    def test_import_writes_backup_and_requires_expected_payload_hash(self):
        self._admin()
        exported = self.client.get("/admin/syh/matafuegos/export.json").get_json()
        changed = {"matafuegos": [dict(self.before["matafuegos"][0], tipo="CO2")]}
        changed_sha = tecman._canonical_json_sha256(changed)

        response = self.client.post(
            "/admin/syh/matafuegos/import.json",
            data={
                "_csrf_token": "csrf-test",
                "expected_current_sha256": exported["sha256"],
                "expected_new_sha256": "bad",
                "data": json.dumps(changed),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tecman.load_matafuegos(), self.before)

        response = self.client.post(
            "/admin/syh/matafuegos/import.json",
            data={
                "_csrf_token": "csrf-test",
                "expected_current_sha256": exported["sha256"],
                "expected_new_sha256": changed_sha,
                "data": json.dumps(changed),
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["before_count"], 1)
        self.assertEqual(body["after_count"], 1)
        self.assertEqual(body["after_sha256"], changed_sha)
        self.assertEqual(tecman.load_matafuegos(), changed)
        self.assertEqual(json.loads(Path(body["backup"]).read_text(encoding="utf-8")), self.before)


if __name__ == "__main__":
    unittest.main()
