import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def _diprogom_source(self, payload):
        digest = hashlib.sha256(payload).hexdigest()
        row = {
            "row": 4,
            "sucursal_num": "036",
            "branch_source": "nombre_suc",
            "pending": False,
            "nro_extintor": "D-001",
            "fecha_vencimiento_proveedor": "2027-06-01",
            "tipo": "ABC",
            "capacidad": "5 KG",
            "green_marker": False,
            "inactive_green": False,
        }
        return {
            "schema": "tecman.diprogom-source/v1",
            "xls": "Planilla_Diprogom.xls",
            "xls_sha256": digest,
            "rows": [row],
            "active_branch_numbers": ["036"],
            "inactive_green_branch_numbers": [],
            "summary": {
                "rows": 1,
                "unique_extinguisher_ids": 1,
                "numbered_rows": 1,
                "numbered_branches": 1,
                "active_rows": 1,
                "active_branches": 1,
                "inactive_green_rows": 0,
                "inactive_green_branches": {},
                "green_fill_index": 49,
                "green_fill_rgb": [51, 204, 204],
                "green_marker_rows": [],
                "conflict_rows": 0,
                "conflict_branches": {"051": 13, "156": 23},
                "pending_rows": 14,
                "pending_label": "PARQUE INDUSTRIAL MORZAT",
                "fallback_214_rows": 9,
                "count_validation": "ok",
            },
        }

    def _preview(self, payload=b"official-diprogom-fixture"):
        dip = tecman._diprogom_reconciler()
        source = self._diprogom_source(payload)
        with mock.patch.object(dip, "EXPECTED_XLS_SHA256", hashlib.sha256(payload).hexdigest()), mock.patch.object(
            dip, "parse_xls", return_value=source
        ):
            return self.client.post(
                "/admin/syh/matafuegos/diprogom/preview",
                data={"_csrf_token": "csrf-test", "xls": (io.BytesIO(payload), "Planilla_Diprogom.xls")},
                content_type="multipart/form-data",
            )

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

    def test_diprogom_preview_requires_admin_csrf_name_sha_and_never_mutates(self):
        before_bytes = tecman.MATAFUEGOS_FILE.read_bytes()
        payload = b"official-diprogom-fixture"
        self.assertEqual(
            self.client.post("/admin/syh/matafuegos/diprogom/preview").status_code,
            302,
        )
        with self.client.session_transaction() as session:
            session.update(user="tech", rol="tecnico", nombre="Tech")
        self.assertEqual(
            self.client.post("/admin/syh/matafuegos/diprogom/preview").status_code,
            403,
        )
        self._admin()
        response = self.client.post(
            "/admin/syh/matafuegos/diprogom/preview",
            data={"xls": (io.BytesIO(payload), "Planilla_Diprogom.xls")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_csrf")
        tecman.USE_DB = True
        response = self.client.post(
            "/admin/syh/matafuegos/diprogom/preview",
            data={"_csrf_token": "csrf-test", "xls": (io.BytesIO(payload), "Planilla_Diprogom.xls")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "unsupported_inventory_backend")
        tecman.USE_DB = False
        self.assertEqual(tecman.MATAFUEGOS_FILE.read_bytes(), before_bytes)
        response = self.client.post(
            "/admin/syh/matafuegos/diprogom/preview",
            data={"_csrf_token": "csrf-test", "xls": (io.BytesIO(payload), "other.xls")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.get_json()["error"], "invalid_filename")
        response = self.client.post(
            "/admin/syh/matafuegos/diprogom/preview",
            data={"_csrf_token": "csrf-test", "xls": (io.BytesIO(payload), "Planilla_Diprogom.xls")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.get_json()["error"], "invalid_xls_sha256")
        oversized = b"x" * (tecman.DIPROGOM_XLS_MAX_BYTES + 1)
        dip = tecman._diprogom_reconciler()
        with mock.patch.object(dip, "EXPECTED_XLS_SHA256", hashlib.sha256(oversized).hexdigest()):
            response = self.client.post(
                "/admin/syh/matafuegos/diprogom/preview",
                data={"_csrf_token": "csrf-test", "xls": (io.BytesIO(oversized), "Planilla_Diprogom.xls")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.get_json()["error"], "invalid_size")
        self.assertEqual(self.client.get("/admin/syh/matafuegos/diprogom/preview").status_code, 405)
        valid = self._preview(payload)
        self.assertEqual(valid.status_code, 200)
        body = valid.get_json()
        self.assertEqual(body["schema"], "tecman.diprogom-admin-preview/v1")
        self.assertEqual(body["report"]["version"], "diprogom-import-v3")
        self.assertNotIn("operations", body["report"])
        self.assertNotIn("input", body["report"])
        self.assertEqual(tecman.MATAFUEGOS_FILE.read_bytes(), before_bytes)

    def test_diprogom_apply_requires_exact_hashes_is_idempotent_and_exports_artifacts(self):
        self._admin()
        payload = b"official-diprogom-fixture"
        preview = self._preview(payload).get_json()
        before_bytes = tecman.MATAFUEGOS_FILE.read_bytes()
        dip = tecman._diprogom_reconciler()
        source = self._diprogom_source(payload)

        def apply(inventory_sha, plan_sha):
            with mock.patch.object(dip, "EXPECTED_XLS_SHA256", hashlib.sha256(payload).hexdigest()), mock.patch.object(
                dip, "parse_xls", return_value=source
            ):
                return self.client.post(
                    "/admin/syh/matafuegos/diprogom/apply",
                    data={
                        "_csrf_token": "csrf-test",
                        "inventory_sha256": inventory_sha,
                        "plan_sha256": plan_sha,
                        "xls": (io.BytesIO(payload), "Planilla_Diprogom.xls"),
                    },
                    content_type="multipart/form-data",
                )

        no_csrf = self.client.post(
            "/admin/syh/matafuegos/diprogom/apply",
            data={
                "inventory_sha256": preview["inventory_sha256"],
                "plan_sha256": preview["plan_sha256"],
                "xls": (io.BytesIO(payload), "Planilla_Diprogom.xls"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(no_csrf.status_code, 400)
        self.assertEqual(no_csrf.get_json()["error"], "invalid_csrf")
        self.assertEqual(tecman.MATAFUEGOS_FILE.read_bytes(), before_bytes)

        mismatch = apply("0" * 64, preview["plan_sha256"])
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.get_json()["error"], "inventory_changed")
        self.assertEqual(tecman.MATAFUEGOS_FILE.read_bytes(), before_bytes)
        mismatch = apply(preview["inventory_sha256"], "0" * 64)
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.get_json()["error"], "plan_changed")
        self.assertEqual(tecman.MATAFUEGOS_FILE.read_bytes(), before_bytes)

        response = apply(preview["inventory_sha256"], preview["plan_sha256"])
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["schema"], "tecman.diprogom-admin-apply/v1")
        self.assertEqual(body["applied"], 1)
        backup = tecman.DATA_DIR / "backups" / body["backup_id"]
        journal = tecman.DATA_DIR / "backups" / body["journal_id"]
        self.assertEqual(backup.read_bytes(), before_bytes)
        self.assertTrue(journal.is_file())
        self.assertNotIn(str(tecman.DATA_DIR), json.dumps(body))

        download = self.client.post(
            "/admin/syh/matafuegos/diprogom/artifact",
            data={"_csrf_token": "csrf-test", "artifact_id": body["backup_id"]},
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, before_bytes)
        download.close()
        journal_download = self.client.post(
            "/admin/syh/matafuegos/diprogom/artifact",
            data={"_csrf_token": "csrf-test", "artifact_id": body["journal_id"]},
        )
        self.assertEqual(journal_download.status_code, 200)
        self.assertEqual(json.loads(journal_download.data)["schema"], "tecman.diprogom-journal/v2")
        journal_download.close()
        traversal = self.client.post(
            "/admin/syh/matafuegos/diprogom/artifact",
            data={"_csrf_token": "csrf-test", "artifact_id": "../matafuegos.json"},
        )
        self.assertEqual(traversal.status_code, 400)

        repeated = self._preview(payload).get_json()
        self.assertEqual(repeated["report"]["summary"]["operations"], 0)
        self.assertEqual(repeated["report"]["summary"]["conflicts"], 0)

    def test_diprogom_apply_rejects_old_delete_and_conflict_plans_without_mutation(self):
        self._admin()
        payload = b"official-diprogom-fixture"
        dip = tecman._diprogom_reconciler()
        source = self._diprogom_source(payload)
        inventory_sha = hashlib.sha256(tecman.MATAFUEGOS_FILE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            dip, "EXPECTED_XLS_SHA256", hashlib.sha256(payload).hexdigest()
        ), mock.patch.object(dip, "parse_xls", return_value=source):
            xls = Path(directory) / "source.xls"
            xls.write_bytes(payload)
            safe_plan = dip.make_plan(tecman.MATAFUEGOS_FILE, xls, inventory_sha)
        before_bytes = tecman.MATAFUEGOS_FILE.read_bytes()
        for mutation in ("old", "delete", "conflict"):
            unsafe = json.loads(json.dumps(safe_plan))
            if mutation == "old":
                unsafe["version"] = "diprogom-import-v2"
            elif mutation == "delete":
                unsafe["summary"]["safe_deletes"] = 1
                unsafe["operations"][0]["kind"] = "delete_safe"
            else:
                unsafe["summary"]["conflicts"] = 1
                unsafe["conflicts"] = [{"reason": "fixture"}]
            with mock.patch.object(dip, "EXPECTED_XLS_SHA256", hashlib.sha256(payload).hexdigest()), mock.patch.object(
                dip, "make_plan", return_value=unsafe
            ):
                response = self.client.post(
                    "/admin/syh/matafuegos/diprogom/apply",
                    data={
                        "_csrf_token": "csrf-test",
                        "inventory_sha256": inventory_sha,
                        "plan_sha256": dip.object_hash(unsafe),
                        "xls": (io.BytesIO(payload), "Planilla_Diprogom.xls"),
                    },
                    content_type="multipart/form-data",
                )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"], "unsafe_plan")
            self.assertEqual(tecman.MATAFUEGOS_FILE.read_bytes(), before_bytes)


if __name__ == "__main__":
    unittest.main()
