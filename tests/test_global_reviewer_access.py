import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class GlobalReviewerAccessTests(unittest.TestCase):
    def setUp(self):
        tecman.app.config.update(TESTING=True, SECRET_KEY="global-reviewer-test")
        self.client = tecman.app.test_client()

    def _callback(self):
        identity = {
            "object_id": "oid-anabella",
            "tenant_id": "tenant-test",
            "email": tecman.GLOBAL_REVIEWER_EMAIL,
            "name": "Anabella Karaguezian",
            "claims": {"preferred_username": tecman.GLOBAL_REVIEWER_EMAIL.upper()},
        }
        msal_app = Mock()
        msal_app.acquire_token_by_authorization_code.return_value = {
            "id_token": "token-test",
            "access_token": "access-test",
        }
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["entra_state"] = "state-admin"
            sess["entra_nonce"] = "nonce-admin"
            sess["entra_requested_portal"] = "admin"
        with patch.object(tecman, "_entra_is_configured", return_value=True), \
             patch.object(tecman, "_create_msal_app", return_value=msal_app), \
             patch.object(tecman, "_validate_entra_id_token", return_value=identity), \
             patch.object(tecman, "_entra_group_ids", return_value=set()), \
             patch.object(tecman, "_audit_event"):
            return self.client.get("/auth/entra/callback?state=state-admin&code=code-test")

    @staticmethod
    def _sha(path):
        path = Path(path)
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    def test_seed_es_microsoft_only_e_idempotente(self):
        users = tecman._load_users_json()["users"]
        account = next(u for u in users if u.get("email") == tecman.GLOBAL_REVIEWER_EMAIL)
        self.assertEqual(account["username"], tecman.GLOBAL_REVIEWER_USERNAME)
        self.assertEqual(account["role"], tecman.GLOBAL_REVIEWER_ROLE)
        self.assertEqual(account["status"], "active")
        self.assertNotIn("local_credentials", account)
        self.assertNotIn("password_hash", json.dumps(account))
        self.assertEqual([i["provider"] for i in account["auth_identities"]], ["entra"])
        before = self._sha(tecman.USERS_FILE)
        tecman._seed_auth_users()
        self.assertEqual(self._sha(tecman.USERS_FILE), before)

    def test_login_entra_crea_sesion_revisora_y_lee_todas_las_colas(self):
        response = self._callback()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["auth_provider"], "entra")
            self.assertEqual(sess["entra_role"], tecman.GLOBAL_REVIEWER_ROLE)
            self.assertEqual(sess["auth_account_role"], tecman.GLOBAL_REVIEWER_ROLE)
            self.assertEqual(sess["rol"], tecman.GLOBAL_REVIEWER_ROLE)
            self.assertNotIn("prov_user", sess)
            self.assertNotIn("suc_user", sess)
        tickets = [
            {"id": 1, "servicio": "mantenimiento"},
            {"id": 2, "servicio": "marketing"},
            {"id": 3, "servicio": "it"},
        ]
        with tecman.app.test_request_context("/admin"):
            tecman.session["rol"] = tecman.GLOBAL_REVIEWER_ROLE
            scoped = tecman._tickets_in_session_scope(tickets)
        self.assertEqual([t["id"] for t in scoped], [1, 2, 3])

    def test_gets_admin_son_visibles_y_ui_oculta_acciones(self):
        self._callback()
        with patch.object(tecman, "sync_alertas_syh") as sync_alerts:
            response = self.client.get("/admin?vista=tabla")
        self.assertEqual(response.status_code, 200)
        sync_alerts.assert_not_called()
        html = response.get_data(as_text=True)
        self.assertIn('class="tecman-read-only"', html)
        self.assertIn("Modo revisión", html)
        self.assertIn('form[method="post" i]', html)
        self.assertEqual(self.client.get("/admin/usuarios").status_code, 200)
        self.assertEqual(self.client.get("/admin/resumen-ejecutivo").status_code, 200)
        with patch.object(tecman, "sync_alertas_syh") as sync_alerts:
            self.assertEqual(self.client.get("/admin/syh").status_code, 200)
        sync_alerts.assert_not_called()
        self.assertEqual(self.client.get("/admin/proveedores/matafuegos").status_code, 200)
        self.assertEqual(self.client.get("/admin/proveedores/fumigaciones").status_code, 200)

    def test_toda_escritura_se_rechaza_sin_mutar_archivos(self):
        self._callback()
        watched = [tecman.USERS_FILE, tecman.TICKETS_FILE]
        before = {str(path): self._sha(path) for path in watched}
        attempts = [
            ("/admin/ticket/999999", {"accion": "cerrar"}),
            ("/admin/usuarios", {"accion": "crear"}),
            ("/admin/stock/add", {"item": "x", "cantidad": "1"}),
            ("/admin/notif/leer-todas", {}),
            ("/api/import-tickets", {}),
        ]
        for path, payload in attempts:
            with self.subTest(path=path):
                response = self.client.post(path, data=payload)
                self.assertEqual(response.status_code, 403)
                self.assertIn("no puede modificar", response.get_data(as_text=True))
        for path in ("/admin/pedido/999999/guia", "/admin/crear-demo-fuga"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 403)
                self.assertIn("no puede modificar", response.get_data(as_text=True))
        after = {str(path): self._sha(path) for path in watched}
        self.assertEqual(after, before)

    def test_no_admite_login_local_ni_sesion_revisora_incompleta(self):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["_csrf_token"] = "csrf-test"
        response = self.client.post(
            "/admin/login",
            data={"_csrf_token": "csrf-test", "usuario": tecman.GLOBAL_REVIEWER_USERNAME, "password": "cualquiera"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Usuario o contraseña incorrectos", response.get_data(as_text=True))
        with self.client.session_transaction() as sess:
            sess.clear()
            sess.update(
                user="akaraguezian",
                rol=tecman.GLOBAL_REVIEWER_ROLE,
                auth_provider="entra",
                entra_role=tecman.GLOBAL_REVIEWER_ROLE,
                # auth_account_role ausente: no debe habilitar el modo revisor.
            )
        self.assertEqual(self.client.post("/admin/stock/add").status_code, 302)


if __name__ == "__main__":
    unittest.main()
