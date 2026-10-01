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


ASERVITA_EMAIL = "aservita@grupodexter.com.ar"


class AdminSucursalEntraAccessTest(unittest.TestCase):
    def setUp(self):
        tecman.app.config.update(TESTING=True, SECRET_KEY="admin-sucursal-entra-test")
        self.client = tecman.app.test_client()

    def _identity(self, email=ASERVITA_EMAIL, **overrides):
        identity = {
            "object_id": f"oid-{email.split('@', 1)[0]}",
            "tenant_id": "tenant-test",
            "email": email,
            "name": "Aservita",
            "claims": {
                "preferred_username": email.upper(),
            },
        }
        identity.update(overrides)
        return identity

    def _callback(self, portal, identity=None, groups=None):
        msal_app = Mock()
        msal_app.acquire_token_by_authorization_code.return_value = {
            "id_token": "token-test",
            "access_token": "access-test",
        }
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["entra_state"] = f"state-{portal}"
            sess["entra_nonce"] = f"nonce-{portal}"
            sess["entra_requested_portal"] = portal
        with patch.object(tecman, "_entra_is_configured", return_value=True), \
             patch.object(tecman, "_create_msal_app", return_value=msal_app), \
             patch.object(tecman, "_validate_entra_id_token", return_value=identity or self._identity()), \
             patch.object(tecman, "_entra_group_ids", return_value=set(groups or ())), \
             patch.object(tecman, "_audit_event"):
            return self.client.get(f"/auth/entra/callback?state=state-{portal}&code=code-test")

    def test_email_normalizado_y_seed_json_microsoft_only_sin_credencial_local(self):
        self.assertTrue(tecman._identity_has_admin_sucursal_access(self._identity(email="ASERVITA@GRUPODEXTER.COM.AR")))
        users = tecman._load_users_json()["users"]
        account = next(u for u in users if u.get("email") == ASERVITA_EMAIL)
        self.assertEqual(account["username"], "aservita")
        self.assertEqual(account["role"], "admin")
        self.assertEqual(account["status"], "active")
        self.assertNotIn("local_credentials", account)
        self.assertNotIn("password_hash", json.dumps(account))
        self.assertEqual([i["provider"] for i in account["auth_identities"]], ["entra"])

    def test_login_admin_proyecta_admin_y_decorators_no_crean_password_local(self):
        response = self._callback("admin")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["auth_provider"], "entra")
            self.assertEqual(sess["entra_role"], "admin")
            self.assertEqual(sess["rol"], "admin")
            self.assertEqual(sess["user"], "aservita")
            self.assertNotIn("suc_user", sess)
            self.assertNotIn("prov_user", sess)
            self.assertNotIn("compras_user", sess)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        account = next(u for u in tecman._load_users_json()["users"] if u.get("email") == ASERVITA_EMAIL)
        self.assertNotIn("local_credentials", account)
        self.assertNotIn("password_hash", json.dumps(account))

    def test_login_sucursal_proyecta_portal_general_con_selector_sin_admin(self):
        response = self._callback("sucursal")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/mi-panel"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["auth_provider"], "entra")
            self.assertEqual(sess["entra_role"], "sucursal")
            self.assertEqual(sess["suc_user"], "entra_sucursales")
            self.assertEqual(sess["suc_nombre"], "Portal Sucursales")
            self.assertTrue(sess["suc_general"])
            self.assertNotIn("user", sess)
            self.assertNotIn("rol", sess)
        self.assertEqual(self.client.get("/mi-panel").status_code, 200)
        new_ticket = self.client.get("/nuevo")
        self.assertEqual(new_ticket.status_code, 200)
        self.assertIn('name="sucursal"', new_ticket.get_data(as_text=True))
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_aservita_no_gana_proveedores_compras_oficina_supervisor_ni_logistica(self):
        for portal in ("proveedor", "compras", "oficina", "supervisor", "logistica"):
            with self.subTest(portal=portal):
                response = self._callback(portal)
                self.assertEqual(response.status_code, 403)
                with self.client.session_transaction() as sess:
                    self.assertNotIn("prov_user", sess)
                    self.assertNotIn("compras_user", sess)
                    self.assertNotIn("oficina_user", sess)
                    self.assertNotIn("logistica_role", sess)
                    self.assertNotIn("user", sess)
                    self.assertNotIn("suc_user", sess)

    def test_identidad_ajena_rechazada_en_admin_y_sucursal(self):
        other = self._identity(email="sinacceso@grupodexter.com.ar", name="Sin Acceso")
        for portal in ("admin", "sucursal"):
            with self.subTest(portal=portal):
                response = self._callback(portal, identity=other)
                self.assertEqual(response.status_code, 403)

    def test_full_portal_access_conserva_conducta_existente(self):
        full_identity = self._identity(email="full@example.com", name="Full Access")
        with patch.object(tecman, "FULL_PORTAL_ACCESS_EMAILS", {"full@example.com"}):
            response = self._callback("proveedor", identity=full_identity)
        self.assertEqual(response.status_code, 302)
        self.assertIn(response.headers["Location"], ("/proveedor", "/proveedores"))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["auth_provider"], "entra")
            self.assertEqual(sess["entra_role"], "proveedor")
            self.assertTrue(sess["prov_full_access"])

    def test_seed_db_retira_credencial_local_y_no_muta_segunda_pasada(self):
        existing = SimpleNamespace(
            id="aservita-id",
            username="aservita",
            email=ASERVITA_EMAIL,
            first_name="Aservita",
            last_name="",
            role="tecnico",
            status="disabled",
            must_change_password=True,
            session_version=3,
        )
        preparador = SimpleNamespace(
            id="prep-id",
            username=tecman.PREPARADOR_DABRA_USERNAME,
            email=tecman.PREPARADOR_DABRA_EMAIL,
            first_name="Preparador Dabra",
            last_name="Central",
            role=tecman.PREPARADOR_DABRA_ROLE,
            status="active",
            must_change_password=False,
            session_version=1,
        )
        users = {"aservita": existing, tecman.PREPARADOR_DABRA_USERNAME: preparador}
        credentials = {"aservita-id": object()}
        identities = set()

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

        class IdentityQuery:
            @staticmethod
            def filter_by(user_id=None, provider=None, **kwargs):
                return SimpleNamespace(first=lambda: object() if (user_id, provider) in identities else None)

        fake_credentials = SimpleNamespace(query=CredentialQuery())

        class FakeIdentityDB:
            query = IdentityQuery()

            def __init__(self, user_id=None, provider=None, provider_subject=None, tenant_id=None):
                self.user_id = user_id
                self.provider = provider
                self.provider_subject = provider_subject
                self.tenant_id = tenant_id

        fake_db = SimpleNamespace(session=SimpleNamespace(commit=Mock(), add=Mock(), flush=Mock()))

        def add_identity(identity):
            identities.add((identity.user_id, identity.provider))

        fake_db.session.add.side_effect = add_identity

        with patch.object(tecman, "USE_DB", True), \
             patch.object(tecman, "ADMINS", {}), \
             patch.object(tecman, "_supervisores_by_email", return_value={}), \
             patch.object(tecman, "_find_db_user", side_effect=find_user), \
             patch.object(tecman, "LocalCredentialDB", fake_credentials, create=True), \
             patch.object(tecman, "AuthIdentityDB", FakeIdentityDB, create=True), \
             patch.object(tecman, "db", fake_db, create=True):
            tecman._seed_auth_users()
            first = (existing.role, existing.status, existing.must_change_password, existing.session_version, dict(credentials), set(identities))
            tecman._seed_auth_users()
            second = (existing.role, existing.status, existing.must_change_password, existing.session_version, dict(credentials), set(identities))

        self.assertEqual(first, second)
        self.assertEqual(existing.role, "admin")
        self.assertEqual(existing.status, "active")
        self.assertFalse(existing.must_change_password)
        self.assertEqual(existing.session_version, 4)
        self.assertEqual(credentials, {})
        self.assertIn(("aservita-id", "entra"), identities)


if __name__ == "__main__":
    unittest.main()
