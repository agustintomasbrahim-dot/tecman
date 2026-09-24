import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


_TEST_ROOT = tempfile.TemporaryDirectory()
os.environ["TECMAN_DATA_DIR"] = str(Path(_TEST_ROOT.name) / "data")
os.environ["TECMAN_UPLOADS_DIR"] = str(Path(_TEST_ROOT.name) / "uploads")
os.environ.pop("DATABASE_URL", None)

import app as tecman  # noqa: E402


class PreparadorSeedTests(unittest.TestCase):
    def test_entra_admin_mapea_rol_logistico_a_pedidos_stock_y_movimientos(self):
        client = tecman.app.test_client()
        tecman.app.config.update(TESTING=True, SECRET_KEY="test-only")
        identity = {
            "object_id": "entra-hdiosque-admin",
            "tenant_id": "tenant-test",
            "email": tecman.PREPARADOR_DABRA_EMAIL,
            "name": "Héctor Diosque",
            "claims": {},
        }
        msal_app = Mock()
        msal_app.acquire_token_by_authorization_code.return_value = {
            "id_token": "token-test",
            "access_token": "access-test",
        }
        with client.session_transaction() as sess:
            sess["entra_state"] = "state-admin"
            sess["entra_nonce"] = "nonce-admin"
            sess["entra_requested_portal"] = "admin"
        with patch.object(tecman, "_entra_is_configured", return_value=True), \
             patch.object(tecman, "_create_msal_app", return_value=msal_app), \
             patch.object(tecman, "_validate_entra_id_token", return_value=identity), \
             patch.object(tecman, "_entra_group_ids", return_value=set()), \
             patch.object(tecman, "_audit_event"):
            response = client.get("/auth/entra/callback?state=state-admin&code=code-admin")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin"))
        with client.session_transaction() as sess:
            self.assertEqual(sess["auth_provider"], "entra")
            self.assertEqual(sess["auth_account_role"], tecman.PREPARADOR_DABRA_ROLE)
            self.assertEqual(sess["entra_role"], "tecnico")
            self.assertEqual(sess["rol"], "tecnico")
        self.assertEqual(client.get("/admin/pedidos").status_code, 200)
        self.assertEqual(client.get("/admin/stock").status_code, 200)
        self.assertEqual(client.get("/admin/stock/movimientos").status_code, 200)
        self.assertEqual(client.get("/admin/comprobantes").status_code, 403)

    def test_seed_json_es_idempotente_revoca_soria_y_no_crea_secreto_local(self):
        with tempfile.TemporaryDirectory() as temp:
            users_file = Path(temp) / "users.json"
            users_file.write_text(json.dumps({"users": [
                {"id": "old-1", "username": "esoria", "email": "esoria@grupodexter.com.ar",
                 "status": "active", "session_version": 4, "role": "tecnico",
                 "local_credentials": {"password_hash": "legacy"}, "auth_identities": []},
                {"id": "old-2", "username": "soria_demo", "email": "", "status": "active",
                 "session_version": 2, "role": "tecnico",
                 "local_credentials": {"password_hash": "legacy"}, "auth_identities": []},
            ]}), encoding="utf-8")
            with patch.object(tecman, "USE_DB", False), patch.object(tecman, "USERS_FILE", users_file), \
                 patch.object(tecman, "ADMINS", {}), patch.object(tecman, "_supervisores_by_email", return_value={}):
                tecman._seed_auth_users()
                first = users_file.read_bytes()
                tecman._seed_auth_users()
                second = users_file.read_bytes()

            self.assertEqual(first, second)
            users = json.loads(first)["users"]
            by_name = {u["username"]: u for u in users}
            for username, expected_version in (("esoria", 5), ("soria_demo", 3)):
                self.assertEqual(by_name[username]["status"], "disabled")
                self.assertEqual(by_name[username]["session_version"], expected_version)
                self.assertNotIn("local_credentials", by_name[username])
            preparador = by_name[tecman.PREPARADOR_DABRA_USERNAME]
            self.assertEqual(preparador["email"], tecman.PREPARADOR_DABRA_EMAIL)
            self.assertEqual(preparador["role"], tecman.PREPARADOR_DABRA_ROLE)
            self.assertEqual(preparador["status"], "active")
            self.assertNotIn("local_credentials", preparador)
            self.assertEqual([i["provider"] for i in preparador["auth_identities"]], ["entra"])

    def test_seed_db_es_idempotente_revoca_sesiones_y_credenciales(self):
        users = {
            "esoria": SimpleNamespace(id="old-1", username="esoria", email="esoria@grupodexter.com.ar",
                                      status="active", session_version=7, role="tecnico"),
            "soria_demo": SimpleNamespace(id="old-2", username="soria_demo", email=None,
                                          status="active", session_version=3, role="tecnico"),
            "hdiosque": SimpleNamespace(id="new-1", username="hdiosque", email=tecman.PREPARADOR_DABRA_EMAIL,
                                        first_name="Héctor", last_name="Diosque", status="active",
                                        session_version=1, role="tecnico", must_change_password=False),
        }
        credentials = {"old-1": object(), "old-2": object(), "new-1": object()}

        def find_user(identifier=None, entra_object_id=None, email=None):
            if email:
                return next((u for u in users.values() if (u.email or "").lower() == email.lower()), None)
            return users.get((identifier or "").lower())

        class CredentialQuery:
            @staticmethod
            def get(user_id):
                return credentials.get(user_id)

            @staticmethod
            def filter_by(user_id=None):
                return SimpleNamespace(delete=lambda: credentials.pop(user_id, None))

        identity = SimpleNamespace(provider="entra", provider_subject=tecman.PREPARADOR_DABRA_EMAIL)
        identity_query = SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: identity))
        fake_credentials = SimpleNamespace(query=CredentialQuery())
        fake_identities = SimpleNamespace(query=identity_query)
        fake_db = SimpleNamespace(session=SimpleNamespace(commit=Mock(), add=Mock(), flush=Mock()))

        with patch.object(tecman, "USE_DB", True), patch.object(tecman, "ADMINS", {}), \
             patch.object(tecman, "_supervisores_by_email", return_value={}), \
             patch.object(tecman, "_find_db_user", side_effect=find_user), \
             patch.object(tecman, "LocalCredentialDB", fake_credentials, create=True), \
             patch.object(tecman, "AuthIdentityDB", fake_identities, create=True), \
             patch.object(tecman, "db", fake_db, create=True):
            tecman._seed_auth_users()
            versions = (users["esoria"].session_version, users["soria_demo"].session_version)
            tecman._seed_auth_users()

        self.assertEqual(versions, (8, 4))
        self.assertEqual((users["esoria"].session_version, users["soria_demo"].session_version), versions)
        self.assertEqual(users["esoria"].status, "disabled")
        self.assertEqual(users["soria_demo"].status, "disabled")
        self.assertEqual(credentials, {})
        preparador = users["hdiosque"]
        self.assertEqual(preparador.role, tecman.PREPARADOR_DABRA_ROLE)
        self.assertEqual(preparador.first_name, "Preparador Dabra")
        self.assertEqual(preparador.last_name, "Central")


if __name__ == "__main__":
    unittest.main()
